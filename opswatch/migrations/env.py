from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from opswatch import models

target_metadata = models.Base.metadata


def run_with_connection(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(run_with_connection)
    await engine.dispose()


def database_url() -> str:
    url = context.config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from opswatch.config import AppConfig

    return AppConfig.load().database_url


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    run_with_connection(context.config.attributes["connection"])
else:
    asyncio.run(run_async(database_url()))
