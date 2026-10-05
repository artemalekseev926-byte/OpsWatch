from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE = "0001"

log = logging.getLogger(__name__)


def alembic_config(connection=None, url: str = "") -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        config.set_main_option("sqlalchemy.url", url)
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def upgrade(connection) -> str | None:
    config = alembic_config(connection)
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" not in tables and "users" in tables:
        log.info("Обнаружена база версии 0.1.0, отмечаю базовую ревизию %s", BASELINE)
        command.stamp(config, BASELINE)
    before = current_revision(connection)
    command.upgrade(config, "head")
    after = current_revision(connection)
    if before != after:
        log.info("Схема базы обновлена: %s → %s", before or "пусто", after)
    return after
