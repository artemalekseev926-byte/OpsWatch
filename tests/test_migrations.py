import asyncio
import sqlite3

import pytest
from alembic import command

from opswatch.config import normalize_database_url
from opswatch.db import Database
from opswatch.migrator import alembic_config, head_revision
from opswatch.services.transfer import TransferError, describe_url, transfer


async def test_fresh_database_reaches_head(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    assert await db.migrate() == head_revision()
    assert await db.migrate() == head_revision()
    await db.dispose()


async def test_legacy_database_is_stamped_and_upgraded(tmp_path):
    path = tmp_path / "legacy.db"
    url = f"sqlite+aiosqlite:///{path}"
    await asyncio.to_thread(command.upgrade, alembic_config(url=url), "0001")
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE alembic_version")
    connection.execute(
        "INSERT INTO users (username, password_hash, full_name, email, status, is_superuser, telegram_username, "
        "personal_bot_username, notify_telegram, notify_desktop, quiet_start, quiet_end, note, created_at) "
        "VALUES ('old', 'x', 'Old', '', 'active', 0, '', '', 1, 0, '', '', '', '2026-01-01 00:00:00')"
    )
    connection.commit()
    connection.close()
    db = Database(url)
    assert await db.migrate() == head_revision()
    await db.dispose()
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT username, language FROM users").fetchall() == [("old", "ru")]
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == head_revision()
    connection.close()


async def test_transfer_between_databases(rt, client, admin, tmp_path):
    from opswatch.core.events import EventIn

    await rt.pipeline.ingest(EventIn(title="перенос", severity="critical", category="monitoring"))
    await client.post("/api/sources", json={"name": "PG", "type": "postgresql", "config": {"database": "x", "password": "p"}}, headers=admin)
    target = f"sqlite:///{tmp_path / 'target.db'}"
    counts = await transfer(rt.config.database_url, target)
    assert counts["users"] == 1 and counts["sources"] == 1 and counts["events"] >= 1
    with pytest.raises(TransferError):
        await transfer(rt.config.database_url, target)
    again = await transfer(rt.config.database_url, target, force=True)
    assert again == counts
    connection = sqlite3.connect(tmp_path / "target.db")
    assert connection.execute("SELECT name FROM sources").fetchone()[0] == "PG"
    connection.close()


def test_database_url_helpers():
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert normalize_database_url("postgres://u@h/db") == "postgresql+asyncpg://u@h/db"
    assert normalize_database_url("sqlite:///C:/x.db") == "sqlite+aiosqlite:///C:/x.db"
    assert describe_url("postgresql://u:secret@db:5432/ops") == "PostgreSQL: db:5432/ops"
    assert "secret" not in describe_url("postgresql://u:secret@db:5432/ops")
