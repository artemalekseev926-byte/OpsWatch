from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from opswatch.backup.archive import BackupError, make_archive, sha256_file, verify_archive
from opswatch.backup.delivery import copy_to_folder, send_to_telegram, upload_s3
from opswatch.backup.engines import ENGINES
from opswatch.connectors import get_connector_class
from opswatch.core.events import EventIn, make_fingerprint
from opswatch.core.render import esc
from opswatch.db import utcnow
from opswatch.i18n import ts
from opswatch.models import BackupJob, BackupRecord, Source, User
from opswatch.permissions import has_perm, role_name
from opswatch.sizes import human_size

log = logging.getLogger(__name__)


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:60] or "backup"


def unique_path(path: Path) -> Path:
    candidate = path
    index = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        index += 1
    return candidate


class BackupManager:
    def __init__(self, db, crypto, settings, sources, pipeline, bot_provider, config) -> None:
        self.db = db
        self.crypto = crypto
        self.settings = settings
        self.sources = sources
        self.pipeline = pipeline
        self.bot_provider = bot_provider
        self.config = config
        self._running: set[int] = set()

    def root(self) -> Path:
        custom = self.settings.get("backup_dir")
        return Path(custom) if custom else Path(self.config.backups_dir)

    def is_running(self, job_id: int) -> bool:
        return job_id in self._running

    async def recipients(self, session, job: BackupJob) -> list[User]:
        destinations = job.destinations or {}
        roles = destinations.get("telegram_roles") or []
        user_ids = set(destinations.get("telegram_users") or [])
        users = (await session.execute(select(User).where(User.status == "active"))).scalars().unique().all()
        result = []
        for user in users:
            if not has_perm(user, "backups.view"):
                continue
            if roles or user_ids:
                if user.id in user_ids or role_name(user) in roles:
                    result.append(user)
            elif has_perm(user, "backups.manage"):
                result.append(user)
        return result

    async def run(self, job_id: int, manual: bool = False) -> BackupRecord | None:
        if job_id in self._running:
            return None
        self._running.add(job_id)
        try:
            return await self._run(job_id, manual)
        finally:
            self._running.discard(job_id)

    async def _run(self, job_id: int, manual: bool) -> BackupRecord | None:
        started = time.monotonic()
        async with self.db.session() as session:
            job = await session.get(BackupJob, job_id)
            if job is None:
                return None
            source = await session.get(Source, job.source_id) if job.source_id else None
            record = BackupRecord(job_id=job.id, manual=manual, status="running", started_at=utcnow())
            session.add(record)
            job.last_status = "running"
            await session.commit()
            record_id = record.id
            job_name = job.name
            source_name = source.name if source else ""
            source_id = source.id if source else None
            options = dict(job.options or {})
            encrypted = bool(job.encrypt)
            password = self.crypto.decrypt(job.password) if encrypted else ""
            keep_last = job.keep_last
            connector = self.sources.build(source) if source else None
            source_type = source.type if source else ""

        workdir = Path(self.config.tmp_dir) / f"backup_{job_id}_{int(time.time())}"
        fail_fp = make_fingerprint("backup", job_id, "failed")
        archive: Path | None = None
        delivery: dict[str, Any] = {}
        error = ""
        try:
            if connector is None:
                raise BackupError(ts("Источник для бэкапа не найден"))
            engine_cls = ENGINES.get(source_type)
            if engine_cls is None or not get_connector_class(source_type).supports_backup:
                raise BackupError(ts("Тип источника {source_type} не поддерживает резервное копирование", source_type=source_type))
            if encrypted and not password:
                raise BackupError(ts("Включено шифрование, но не задан пароль архива"))
            workdir.mkdir(parents=True, exist_ok=True)
            files = await engine_cls(connector, options, self.settings).dump(workdir)
            job_dir = self.root() / f"{job_id}_{safe_name(job_name)}"
            archive = unique_path(job_dir / f"{safe_name(job_name)}_{datetime.now():%Y%m%d_%H%M%S}.zip")
            await asyncio.to_thread(make_archive, files, archive, password, workdir)
            count = await asyncio.to_thread(verify_archive, archive, password)
            digest = await asyncio.to_thread(sha256_file, archive)
            size = archive.stat().st_size
            async with self.db.session() as session:
                record = await session.get(BackupRecord, record_id)
                record.file_path = str(archive)
                record.size = size
                record.sha256 = digest
                record.verified = True
                await session.commit()
            delivery = await self.deliver(job_id, archive, size, count, encrypted)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            log.warning(ts("Бэкап %s завершился ошибкой: %s"), job_name, error)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        duration = time.monotonic() - started
        async with self.db.session() as session:
            record = await session.get(BackupRecord, record_id)
            job = await session.get(BackupJob, job_id)
            record.finished_at = utcnow()
            record.delivery = delivery
            if error:
                record.status = "failed"
                record.error = error[:4000]
                if archive is not None and archive.exists():
                    archive.unlink(missing_ok=True)
                    record.file_path = ""
            else:
                record.status = "ok"
            if job is not None:
                job.last_run_at = record.finished_at
                job.last_status = record.status
                job.last_error = record.error
            await session.commit()
            await session.refresh(record)

        if error:
            await self.pipeline.ingest(
                EventIn(
                    title=ts("Бэкап «{job_name}» не выполнен", job_name=job_name),
                    message=error,
                    severity="critical",
                    category="backup",
                    type="backup.failed",
                    source_id=source_id,
                    source_name=source_name,
                    fingerprint=fail_fp,
                    details={"job_id": job_id, "record_id": record_id},
                )
            )
        else:
            await self.pipeline.ingest(
                EventIn(title="ok", category="backup", source_id=source_id, fingerprint=fail_fp, resolve=True,
                        message=ts("Бэкап «{job_name}» снова выполняется успешно", job_name=job_name))
            )
            problems = [name for name, value in delivery.items() if isinstance(value, dict) and value.get("error")]
            telegram = delivery.get("telegram") or {}
            if telegram.get("failed"):
                problems.append("telegram")
            lines = [
                ts("Размер: {human_size}, время: {duration:.0f} сек", human_size=human_size(record.size), duration=duration),
                ts("Архив проверен: целостность в порядке"),
                f"SHA-256: {record.sha256[:16]}…",
            ]
            if telegram:
                lines.append(ts("Telegram: отправлено {sent}, ошибок {failed}", sent=telegram.get("sent", 0), failed=telegram.get("failed", 0)))
            for name in ("folder", "s3"):
                if name in delivery:
                    item = delivery[name]
                    if item.get("error"):
                        lines.append(ts("{name}: ошибка — {error}", name=name, error=item["error"]))
                    else:
                        lines.append(ts("{name}: выгружено", name=name))
            await self.pipeline.ingest(
                EventIn(
                    title=ts("Бэкап «{job_name}» выполнен с ошибками доставки", job_name=job_name) if problems else ts("Бэкап «{job_name}» выполнен", job_name=job_name),
                    message="\n".join(lines),
                    severity="warning" if problems else "info",
                    category="backup",
                    type="backup.delivery_failed" if problems else "backup.ok",
                    source_id=source_id,
                    source_name=source_name,
                    fingerprint=make_fingerprint("backup", job_id, "ok", record_id),
                    details={"job_id": job_id, "record_id": record_id, "size": record.size},
                )
            )
            await self.rotate(job_id, keep_last)
        return record

    async def deliver(self, job_id: int, archive: Path, size: int, files_count: int, encrypted: bool) -> dict[str, Any]:
        result: dict[str, Any] = {}
        async with self.db.session() as session:
            job = await session.get(BackupJob, job_id)
            destinations = dict(job.destinations or {})
            users = await self.recipients(session, job) if destinations.get("telegram", True) else []
            job_name = job.name
        links: list[str] = []
        folder = str(destinations.get("folder") or "").strip()
        if folder:
            try:
                result["folder"] = {"path": await asyncio.to_thread(copy_to_folder, archive, folder)}
            except Exception as exc:
                result["folder"] = {"error": str(exc)}
        if destinations.get("s3"):
            try:
                url = await asyncio.to_thread(upload_s3, archive, self.settings)
                result["s3"] = {"url": url}
                links.append(url)
            except Exception as exc:
                result["s3"] = {"error": str(exc)}
        if destinations.get("telegram", True):
            caption = (
                ts("💾 <b>Бэкап «{job}»</b>\n{file} · {size} · файлов: {files_count}", job=esc(job_name), file=esc(archive.name), size=human_size(size), files_count=files_count)
                + ("\n" + ts("🔒 Зашифрован AES-256") if encrypted else "")
            ).strip()
            result["telegram"] = await send_to_telegram(
                self.bot_provider(),
                self.crypto,
                users,
                archive,
                caption,
                self.settings,
                Path(self.config.tmp_dir),
                links,
                allow_split=destinations.get("split", True),
            )
        return result

    async def rotate(self, job_id: int, keep_last: int) -> int:
        if keep_last <= 0:
            return 0
        removed = 0
        async with self.db.session() as session:
            records = (
                await session.execute(
                    select(BackupRecord)
                    .where(BackupRecord.job_id == job_id, BackupRecord.status == "ok", BackupRecord.deleted.is_(False))
                    .order_by(BackupRecord.started_at.desc(), BackupRecord.id.desc())
                )
            ).scalars().all()
            for record in records[keep_last:]:
                if record.file_path:
                    try:
                        Path(record.file_path).unlink(missing_ok=True)
                    except OSError as exc:
                        log.warning(ts("Не удалось удалить старый бэкап %s: %s"), record.file_path, exc)
                        continue
                record.deleted = True
                removed += 1
            await session.commit()
        return removed
