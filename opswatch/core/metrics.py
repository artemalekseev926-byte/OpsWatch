from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from opswatch.db import Database, utcnow
from opswatch.i18n import tr
from opswatch.models import MetricPoint

METRIC_INFO: dict[str, dict[str, str]] = {
    "size": {"title": "Размер базы", "unit": "bytes"},
    "latency_ms": {"title": "Время отклика", "unit": "ms"},
    "problems": {"title": "Активные проблемы", "unit": "count"},
    "log_matches": {"title": "Ошибки в журнале", "unit": "count"},
    "sessions": {"title": "Сеансы", "unit": "count"},
    "sessions_active": {"title": "Активные сеансы", "unit": "count"},
    "lock_waits": {"title": "Ожидания на блокировках", "unit": "count"},
    "max_call_sec": {"title": "Самый долгий вызов", "unit": "sec"},
    "processes": {"title": "Рабочие процессы", "unit": "count"},
    "process_memory_mb": {"title": "Память рабочих процессов", "unit": "mb"},
    "min_performance": {"title": "Минимальная производительность процесса", "unit": "count"},
    "used_percent": {"title": "Занято на диске", "unit": "percent"},
    "free_gb": {"title": "Свободно на диске", "unit": "gb"},
}

SKIP = {"received", "modified", "status", "version", "in_use", "size_human", "http", "infobases"}

PRIMARY = {
    "mysql": "size",
    "postgresql": "size",
    "mssql": "size",
    "onec_file": "size",
    "onec_server": "size",
    "onec_cluster": "sessions",
    "http_check": "latency_ms",
    "zabbix_api": "problems",
}

PERIODS = {
    "24h": (timedelta(hours=24), 300),
    "7d": (timedelta(days=7), 3600),
    "30d": (timedelta(days=30), 4 * 3600),
}

MIN_INTERVAL = 300


def numeric_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, value in (metrics or {}).items():
        if key in SKIP or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if len(key) > 64:
            continue
        values[key] = float(value)
    return values


def describe(name: str) -> dict[str, str]:
    info = METRIC_INFO.get(name)
    if info:
        return {"name": name, "title": tr(info["title"]), "unit": info["unit"]}
    return {"name": name, "title": name, "unit": "count"}


def bucketize(rows: list[tuple[datetime, float]], start: datetime, bucket: int) -> list[list]:
    buckets: dict[int, list[float]] = {}
    for ts, value in rows:
        index = int((ts - start).total_seconds() // bucket)
        buckets.setdefault(index, []).append(value)
    points = []
    for index in sorted(buckets):
        values = buckets[index]
        moment = start + timedelta(seconds=index * bucket + bucket / 2)
        points.append([moment, sum(values) / len(values)])
    return points


class MetricStore:
    def __init__(self, db: Database, min_interval: int = MIN_INTERVAL) -> None:
        self.db = db
        self.min_interval = min_interval
        self._last: dict[tuple[int, str], datetime] = {}

    async def record(self, source_id: int, metrics: dict[str, Any], now: datetime | None = None) -> int:
        values = numeric_metrics(metrics)
        if not values:
            return 0
        now = now or utcnow()
        added = 0
        async with self.db.session() as session:
            for name, value in values.items():
                key = (source_id, name)
                last = self._last.get(key)
                if last is not None and (now - last).total_seconds() < self.min_interval:
                    continue
                session.add(MetricPoint(source_id=source_id, name=name, value=value, ts=now))
                self._last[key] = now
                added += 1
            await session.commit()
        return added

    async def series(self, source_id: int) -> list[dict[str, Any]]:
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(MetricPoint.name, func.count(MetricPoint.id), func.max(MetricPoint.ts))
                    .where(MetricPoint.source_id == source_id)
                    .group_by(MetricPoint.name)
                )
            ).all()
            result = []
            for name, count, last_ts in rows:
                last_value = await session.scalar(
                    select(MetricPoint.value)
                    .where(MetricPoint.source_id == source_id, MetricPoint.name == name, MetricPoint.ts == last_ts)
                    .limit(1)
                )
                result.append({**describe(name), "points": count, "last": last_value, "last_at": last_ts})
        order = list(METRIC_INFO)
        result.sort(key=lambda item: (order.index(item["name"]) if item["name"] in order else len(order), item["name"]))
        return result

    async def points(self, source_id: int, name: str, period: str = "24h", now: datetime | None = None) -> list[list]:
        span, bucket = PERIODS.get(period, PERIODS["24h"])
        now = now or utcnow()
        start = now - span
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(MetricPoint.ts, MetricPoint.value)
                    .where(MetricPoint.source_id == source_id, MetricPoint.name == name, MetricPoint.ts >= start)
                    .order_by(MetricPoint.ts)
                )
            ).all()
        return bucketize([(ts, value) for ts, value in rows], start, bucket)

    async def sparkline(self, source_id: int, name: str, now: datetime | None = None) -> list[float]:
        now = now or utcnow()
        start = now - timedelta(hours=24)
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(MetricPoint.ts, MetricPoint.value)
                    .where(MetricPoint.source_id == source_id, MetricPoint.name == name, MetricPoint.ts >= start)
                    .order_by(MetricPoint.ts)
                )
            ).all()
        return [round(value, 3) for _, value in bucketize([(ts, value) for ts, value in rows], start, 1800)]

    async def cleanup(self, days: int) -> int:
        threshold = utcnow() - timedelta(days=max(1, days))
        async with self.db.session() as session:
            result = await session.execute(delete(MetricPoint).where(MetricPoint.ts < threshold))
            await session.commit()
            return result.rowcount or 0
