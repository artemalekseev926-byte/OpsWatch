from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select
from tzlocal import get_localzone

from opswatch.connectors import get_connector_class
from opswatch.db import utcnow
from opswatch.i18n import ts
from opswatch.models import AuthSession, BackupJob, Event, Notification, Source

log = logging.getLogger(__name__)

MIN_INTERVAL = 15


def validate_cron(expression: str) -> CronTrigger:
    expression = (expression or "").strip()
    if len(expression.split()) != 5:
        raise ValueError(ts("Ожидается 5 полей: минута час день месяц день_недели"))
    return CronTrigger.from_crontab(expression, timezone=get_localzone())


def next_cron_run(expression: str) -> datetime | None:
    try:
        trigger = validate_cron(expression)
    except ValueError:
        return None
    now = datetime.now(get_localzone())
    return trigger.get_next_fire_time(None, now)


class Scheduler:
    def __init__(self, runtime) -> None:
        self.rt = runtime
        self.aps = AsyncIOScheduler(timezone=get_localzone())
        self._signatures: dict[str, tuple] = {}
        self.running = False

    async def start(self) -> None:
        self.aps.start()
        self.running = True
        self.aps.add_job(
            self.rt.pipeline.run_escalations,
            IntervalTrigger(seconds=30),
            id="escalation",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self.aps.add_job(
            self.cleanup,
            IntervalTrigger(hours=6),
            id="cleanup",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            next_run_time=datetime.now(get_localzone()) + timedelta(minutes=2),
        )
        await self.sync()

    async def stop(self) -> None:
        if self.running:
            self.aps.shutdown(wait=False)
            self.running = False

    async def sync(self) -> None:
        if not self.running:
            return
        desired: dict[str, tuple] = {}
        async with self.rt.db.session() as session:
            sources = (await session.execute(select(Source).where(Source.enabled.is_(True)))).scalars().all()
            jobs = (await session.execute(select(BackupJob).where(BackupJob.enabled.is_(True)))).scalars().all()
        for source in sources:
            try:
                cls = get_connector_class(source.type)
            except Exception:
                continue
            if not cls.passive:
                desired[f"source:{source.id}"] = ("interval", max(MIN_INTERVAL, int(source.poll_interval or cls.default_interval or 60)), source.id)
            if cls.supports_maintenance:
                cron = self.rt.sources.build(source).maintenance_cron()
                if cron:
                    desired[f"maint:{source.id}"] = ("cron", cron, source.id)
        for job in jobs:
            desired[f"backup:{job.id}"] = ("cron", job.schedule, job.id)

        for job in self.aps.get_jobs():
            if job.id.split(":")[0] in {"source", "maint", "backup"} and job.id not in desired:
                job.remove()
                self._signatures.pop(job.id, None)

        delay = 3
        for job_id, signature in desired.items():
            if self._signatures.get(job_id) == signature and self.aps.get_job(job_id):
                continue
            kind, value, target = signature
            prefix = job_id.split(":")[0]
            try:
                if kind == "interval":
                    trigger = IntervalTrigger(seconds=value)
                    first = datetime.now(get_localzone()) + timedelta(seconds=delay)
                    delay += 2
                else:
                    trigger = validate_cron(value)
                    first = None
            except ValueError as exc:
                log.warning(ts("Неверное расписание %s: %s"), job_id, exc)
                continue
            func = {
                "source": self.rt.sources.poll,
                "maint": self.rt.sources.maintenance,
                "backup": self.rt.backups.run,
            }[prefix]
            kwargs = {
                "id": job_id,
                "args": [target],
                "max_instances": 1,
                "coalesce": True,
                "replace_existing": True,
                "misfire_grace_time": 3600,
            }
            if first is not None:
                kwargs["next_run_time"] = first
            self.aps.add_job(func, trigger, **kwargs)
            self._signatures[job_id] = signature

    def next_run(self, job_id: str) -> datetime | None:
        if not self.running:
            return None
        job = self.aps.get_job(job_id)
        return job.next_run_time if job else None

    async def cleanup(self) -> None:
        days = int(self.rt.settings.get("event_retention_days") or 90)
        threshold = utcnow() - timedelta(days=days)
        async with self.rt.db.session() as session:
            await session.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
            await session.execute(delete(Notification).where(Notification.created_at < threshold))
            old = (
                await session.execute(
                    select(Event).where(Event.status == "resolved", Event.last_seen_at < threshold)
                )
            ).scalars().all()
            for event in old:
                for attachment in event.attachments:
                    (self.rt.config.attachments_dir / attachment.stored_name).unlink(missing_ok=True)
                await session.delete(event)
            await session.commit()
        await self.rt.metrics.cleanup(int(self.rt.settings.get("metric_retention_days") or 30))
