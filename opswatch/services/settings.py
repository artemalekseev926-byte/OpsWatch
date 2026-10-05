from __future__ import annotations

from typing import Any

from sqlalchemy import select

from opswatch.db import Database
from opswatch.models import Setting
from opswatch.security import Crypto

DEFAULTS: dict[str, Any] = {
    "telegram_token": "",
    "telegram_api_url": "",
    "public_url": "",
    "registration_enabled": True,
    "group_window_min": 10,
    "event_retention_days": 90,
    "bot_public_bugs": False,
    "backup_dir": "",
    "telegram_part_mb": 49,
    "mysqldump_path": "mysqldump",
    "pg_dump_path": "pg_dump",
    "onec_platform_path": "",
    "s3_endpoint": "",
    "s3_region": "",
    "s3_bucket": "",
    "s3_access_key": "",
    "s3_secret_key": "",
    "s3_prefix": "opswatch/",
    "s3_link_days": 7,
}

SECRET_KEYS = {"telegram_token", "s3_secret_key"}

INT_KEYS = {"group_window_min", "event_retention_days", "telegram_part_mb", "s3_link_days"}
BOOL_KEYS = {"registration_enabled", "bot_public_bugs"}


def _coerce(key: str, value: Any) -> Any:
    if key in INT_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULTS[key]
    if key in BOOL_KEYS:
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if value is None:
        return ""
    return str(value)


class SettingsStore:
    def __init__(self, db: Database, crypto: Crypto, env_overrides: dict[str, Any] | None = None) -> None:
        self.db = db
        self.crypto = crypto
        self.env_overrides = {k: v for k, v in (env_overrides or {}).items() if v not in (None, "")}
        self._cache: dict[str, Any] = dict(DEFAULTS)

    async def load(self) -> None:
        async with self.db.session() as session:
            rows = (await session.execute(select(Setting))).scalars().all()
        values = dict(DEFAULTS)
        for row in rows:
            if row.key not in DEFAULTS:
                continue
            raw = (row.value or {}).get("v")
            if row.key in SECRET_KEYS:
                raw = self.crypto.decrypt(raw or "")
            values[row.key] = _coerce(row.key, raw)
        self._cache = values

    def get(self, key: str) -> Any:
        if key in self.env_overrides:
            return self.env_overrides[key]
        return self._cache.get(key, DEFAULTS.get(key))

    def all(self) -> dict[str, Any]:
        return {key: self.get(key) for key in DEFAULTS}

    def public(self) -> dict[str, Any]:
        data = {}
        for key in DEFAULTS:
            value = self.get(key)
            if key in SECRET_KEYS:
                data[key] = "" if not value else "••••••••"
            else:
                data[key] = value
        data["env_locked"] = sorted(self.env_overrides)
        return data

    async def update(self, changes: dict[str, Any]) -> list[str]:
        changed = []
        async with self.db.session() as session:
            for key, value in changes.items():
                if key not in DEFAULTS or key in self.env_overrides:
                    continue
                if key in SECRET_KEYS and value == "••••••••":
                    continue
                value = _coerce(key, value)
                if value == self._cache.get(key):
                    continue
                stored = self.crypto.encrypt(value) if key in SECRET_KEYS else value
                row = await session.get(Setting, key)
                if row is None:
                    session.add(Setting(key=key, value={"v": stored}))
                else:
                    row.value = {"v": stored}
                self._cache[key] = value
                changed.append(key)
            await session.commit()
        return changed
