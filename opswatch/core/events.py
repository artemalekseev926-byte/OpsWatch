from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field, field_validator

from opswatch.constants import CATEGORIES

_INFO = {"info", "information", "informational", "ok", "notice", "low", "debug", "not classified", "note", "i", "n"}
_WARNING = {"warning", "warn", "average", "medium", "minor", "w"}
_CRITICAL = {
    "critical",
    "crit",
    "error",
    "err",
    "fatal",
    "disaster",
    "high",
    "emergency",
    "alert",
    "major",
    "page",
    "severe",
    "e",
}


def normalize_severity(value: Any, default: str = "warning") -> str:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        number = int(value)
        if number <= 1:
            return "info"
        if number <= 3:
            return "warning"
        return "critical"
    text = str(value).strip().lower()
    if text.isdigit():
        return normalize_severity(int(text), default)
    if text in _INFO:
        return "info"
    if text in _WARNING:
        return "warning"
    if text in _CRITICAL:
        return "critical"
    return default


def normalize_category(value: Any, default: str = "system") -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "1c": "onec",
        "1с": "onec",
        "db": "database",
        "databases": "database",
        "bugs": "bug",
        "backups": "backup",
        "resources": "monitoring",
    }
    text = aliases.get(text, text)
    return text if text in CATEGORIES else default


def make_fingerprint(*parts: Any) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class EventIn(BaseModel):
    title: str
    message: str = ""
    severity: str = "warning"
    category: str = "system"
    type: str = "event"
    source_id: int | None = None
    source_name: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str | None = None
    external_id: str | None = None
    resolve: bool = False
    reporter_id: int | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> str:
        return normalize_severity(value)

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, value: Any) -> str:
        return normalize_category(value)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, value: Any) -> str:
        text = str(value or "").strip() or "Без названия"
        return text[:500]

    def key(self) -> str:
        if self.fingerprint:
            return self.fingerprint[:64]
        if self.external_id:
            return make_fingerprint("ext", self.source_id or self.source_name, self.external_id)
        return make_fingerprint(self.category, self.source_id or self.source_name, self.type, self.title)
