from __future__ import annotations

import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _fallback_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "OpsWatch"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "opswatch"


def normalize_database_url(url: str) -> str:
    url = (url or "").strip()
    for prefix in ("postgresql://", "postgres://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    return url


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSWATCH_", extra="ignore")

    data_dir: Path | None = None
    database_url: str | None = None
    secret_key: str | None = None
    host: str = "0.0.0.0"
    port: int = 8765
    telegram_token: str | None = None
    telegram_api_url: str | None = None
    public_url: str | None = None
    admin_username: str = "admin1"
    admin_password: str = "admin1"
    log_level: str = "INFO"
    plugins_dir: Path | None = None

    @classmethod
    def load(cls, env_file: Path | None = None, **overrides) -> "AppConfig":
        candidate = env_file or app_dir() / ".env"
        if candidate.exists():
            config = cls(_env_file=candidate, _env_file_encoding="utf-8", **overrides)
        else:
            config = cls(**overrides)
        config.prepare()
        return config

    def prepare(self) -> None:
        if self.data_dir is None:
            preferred = app_dir() / "data"
            self.data_dir = preferred if _writable(preferred) else _fallback_data_dir()
        self.data_dir = Path(self.data_dir).resolve()
        for folder in (self.data_dir, self.backups_dir, self.attachments_dir, self.logs_dir, self.tmp_dir):
            folder.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{(self.data_dir / 'opswatch.db').as_posix()}"
        self.database_url = normalize_database_url(self.database_url)
        if not self.secret_key:
            self.secret_key = self._load_or_create_key()
        if self.plugins_dir is None:
            self.plugins_dir = app_dir() / "plugins"

    def _load_or_create_key(self) -> str:
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
        key = Fernet.generate_key().decode()
        key_file.write_text(key, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return key

    @property
    def backups_dir(self) -> Path:
        return Path(self.data_dir) / "backups"

    @property
    def attachments_dir(self) -> Path:
        return Path(self.data_dir) / "attachments"

    @property
    def logs_dir(self) -> Path:
        return Path(self.data_dir) / "logs"

    @property
    def tmp_dir(self) -> Path:
        return Path(self.data_dir) / "tmp"
