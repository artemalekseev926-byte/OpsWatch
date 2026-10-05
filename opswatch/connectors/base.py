from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from opswatch.core.events import EventIn, make_fingerprint

REGISTRY: dict[str, type["Connector"]] = {}


class ConnectorError(Exception):
    pass


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"
    required: bool = False
    default: Any = None
    secret: bool = False
    options: list[list[str]] | None = None
    help: str = ""
    placeholder: str = ""
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceContext:
    id: int | None
    name: str
    category: str
    config: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)
    settings: Any = None
    tmp_dir: Path | None = None


@dataclass
class PollResult:
    events: list[EventIn] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] | None = None
    message: str = ""


def register(cls: type["Connector"]) -> type["Connector"]:
    REGISTRY[cls.type] = cls
    return cls


class Connector:
    type: ClassVar[str] = ""
    title: ClassVar[str] = ""
    category: ClassVar[str] = "monitoring"
    description: ClassVar[str] = ""
    fields: ClassVar[list[Field]] = []
    passive: ClassVar[bool] = False
    supports_checks: ClassVar[bool] = False
    supports_backup: ClassVar[bool] = False
    supports_maintenance: ClassVar[bool] = False
    default_interval: ClassVar[int] = 60

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx
        self.config = ctx.config or {}

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "type": cls.type,
            "title": cls.title,
            "category": cls.category,
            "description": cls.description,
            "fields": [f.to_dict() for f in cls.fields],
            "passive": cls.passive,
            "supports_checks": cls.supports_checks,
            "supports_backup": cls.supports_backup,
            "supports_maintenance": cls.supports_maintenance,
            "default_interval": cls.default_interval,
        }

    @classmethod
    def secret_fields(cls) -> set[str]:
        return {f.name for f in cls.fields if f.secret}

    def option(self, name: str, default: Any = None) -> Any:
        value = self.config.get(name)
        if value in (None, ""):
            for spec in self.fields:
                if spec.name == name and spec.default is not None:
                    return spec.default
            return default
        return value

    def int_option(self, name: str, default: int = 0) -> int:
        try:
            return int(float(self.option(name, default)))
        except (TypeError, ValueError):
            return default

    def bool_option(self, name: str, default: bool = False) -> bool:
        value = self.option(name, default)
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def fingerprint(self, *parts: Any) -> str:
        return make_fingerprint("src", self.ctx.id or self.ctx.name, *parts)

    def event(
        self,
        title: str,
        severity: str = "warning",
        type: str = "event",
        message: str = "",
        fingerprint: str | None = None,
        details: dict[str, Any] | None = None,
        category: str | None = None,
        external_id: str | None = None,
    ) -> EventIn:
        return EventIn(
            title=title,
            message=message,
            severity=severity,
            category=category or self.ctx.category or self.category,
            type=type,
            source_id=self.ctx.id,
            source_name=self.ctx.name,
            details=details or {},
            fingerprint=fingerprint,
            external_id=external_id,
        )

    def resolved(self, fingerprint: str, title: str = "", message: str = "") -> EventIn:
        return EventIn(
            title=title or "resolved",
            message=message,
            category=self.ctx.category or self.category,
            source_id=self.ctx.id,
            source_name=self.ctx.name,
            fingerprint=fingerprint,
            resolve=True,
        )

    def track(self, state: dict[str, Any], key: str, active: dict[str, EventIn]) -> tuple[list[EventIn], dict[str, Any]]:
        previous = set(state.get(key) or [])
        events = list(active.values())
        for fingerprint in sorted(previous - set(active)):
            events.append(self.resolved(fingerprint))
        new_state = dict(state)
        new_state[key] = sorted(active)
        return events, new_state

    async def poll(self) -> PollResult:
        return PollResult()

    async def test(self) -> PollResult:
        result = await self.poll()
        return PollResult(metrics=result.metrics, message=result.message or "Проверка прошла успешно")

    def maintenance_cron(self) -> str:
        return ""

    async def maintenance(self) -> PollResult:
        return PollResult()
