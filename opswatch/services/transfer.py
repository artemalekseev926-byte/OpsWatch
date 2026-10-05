from __future__ import annotations

from typing import Callable

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from opswatch import models
from opswatch.config import normalize_database_url
from opswatch.i18n import ts
from opswatch.migrator import upgrade

BATCH = 1000


class TransferError(Exception):
    pass


def describe_url(url: str) -> str:
    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        return "SQLite: " + url.split("///", 1)[-1]
    tail = url.split("@", 1)[-1]
    return "PostgreSQL: " + tail


async def transfer(
    source_url: str,
    target_url: str,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    source_url = normalize_database_url(source_url)
    target_url = normalize_database_url(target_url)
    if source_url == target_url:
        raise TransferError(ts("Источник и приёмник совпадают"))
    say = progress or (lambda message: None)
    source = create_async_engine(source_url)
    target = create_async_engine(target_url)
    counts: dict[str, int] = {}
    tables = models.Base.metadata.sorted_tables
    try:
        async with source.begin() as connection:
            await connection.run_sync(upgrade)
        async with target.begin() as connection:
            await connection.run_sync(upgrade)
            existing = await connection.scalar(select(func.count()).select_from(models.User.__table__))
            if existing and not force:
                raise TransferError(ts("В целевой базе уже есть данные. Используйте --force, чтобы перезаписать их"))
            for table in reversed(tables):
                await connection.execute(table.delete())
        async with source.connect() as reader, target.begin() as writer:
            for table in tables:
                total = 0
                result = await reader.stream(select(table))
                batch: list[dict] = []
                async for row in result.mappings():
                    batch.append(dict(row))
                    if len(batch) >= BATCH:
                        await writer.execute(table.insert(), batch)
                        total += len(batch)
                        batch = []
                if batch:
                    await writer.execute(table.insert(), batch)
                    total += len(batch)
                counts[table.name] = total
                say(f"{table.name}: {total}")
            if writer.dialect.name == "postgresql":
                for table in tables:
                    if "id" in table.c and table.c.id.autoincrement in (True, "auto") and table.c.id.primary_key:
                        await writer.execute(
                            text(
                                f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                                f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), "
                                f"(SELECT MAX(id) FROM {table.name}) IS NOT NULL)"
                            )
                        )
    finally:
        await source.dispose()
        await target.dispose()
    return counts
