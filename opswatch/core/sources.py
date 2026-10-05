from __future__ import annotations

import asyncio
import logging
from typing import Any

from opswatch.connectors import Connector, PollResult, SourceContext, get_connector_class
from opswatch.core.events import EventIn, make_fingerprint
from opswatch.db import utcnow
from opswatch.models import Source

log = logging.getLogger(__name__)

MASK = "••••••••"
POLL_TIMEOUT = 600


class SourceService:
    def __init__(self, db, crypto, settings, pipeline, tmp_dir, metrics=None) -> None:
        self.db = db
        self.metrics = metrics
        self.crypto = crypto
        self.settings = settings
        self.pipeline = pipeline
        self.tmp_dir = tmp_dir
        self._locks: dict[int, asyncio.Lock] = {}

    def split_config(self, kind: str, data: dict[str, Any], existing_secrets: str = "") -> tuple[dict, str]:
        cls = get_connector_class(kind)
        secret_names = cls.secret_fields()
        known = {f.name for f in cls.fields}
        secrets = self.crypto.decrypt_json(existing_secrets) if existing_secrets else {}
        config: dict[str, Any] = {}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            if key in secret_names:
                if value == MASK:
                    continue
                if value in (None, ""):
                    secrets.pop(key, None)
                else:
                    secrets[key] = value
            else:
                config[key] = value
        return config, self.crypto.encrypt_json(secrets)

    def masked_config(self, source: Source) -> dict[str, Any]:
        cls = get_connector_class(source.type)
        data = dict(source.config or {})
        secrets = self.crypto.decrypt_json(source.secrets or "")
        for name in cls.secret_fields():
            data[name] = MASK if secrets.get(name) else ""
        return data

    def context(self, source: Source) -> SourceContext:
        config = dict(source.config or {})
        config.update(self.crypto.decrypt_json(source.secrets or ""))
        return SourceContext(
            id=source.id,
            name=source.name,
            category=source.category,
            config=config,
            state=dict(source.state or {}),
            settings=self.settings,
            tmp_dir=self.tmp_dir,
        )

    def build(self, source: Source) -> Connector:
        return get_connector_class(source.type)(self.context(source))

    async def test_config(
        self,
        kind: str,
        name: str,
        category: str,
        data: dict[str, Any],
        source_id: int | None = None,
    ) -> PollResult:
        existing = ""
        state: dict[str, Any] = {}
        if source_id:
            async with self.db.session() as session:
                source = await session.get(Source, source_id)
                if source is not None:
                    existing = source.secrets
                    state = dict(source.state or {})
        config, secrets = self.split_config(kind, data, existing)
        config.update(self.crypto.decrypt_json(secrets))
        cls = get_connector_class(kind)
        ctx = SourceContext(
            id=source_id,
            name=name or cls.title,
            category=category or cls.category,
            config=config,
            state=state,
            settings=self.settings,
            tmp_dir=self.tmp_dir,
        )
        return await asyncio.wait_for(cls(ctx).test(), timeout=120)

    def _lock(self, source_id: int) -> asyncio.Lock:
        if source_id not in self._locks:
            self._locks[source_id] = asyncio.Lock()
        return self._locks[source_id]

    async def poll(self, source_id: int) -> PollResult | None:
        lock = self._lock(source_id)
        if lock.locked():
            return None
        async with lock:
            async with self.db.session() as session:
                source = await session.get(Source, source_id)
                if source is None or not source.enabled:
                    return None
                cls = get_connector_class(source.type)
                if cls.passive:
                    return None
                connector = self.build(source)
                name, category = source.name, source.category
            result: PollResult | None = None
            error = ""
            try:
                result = await asyncio.wait_for(connector.poll(), timeout=POLL_TIMEOUT)
            except asyncio.TimeoutError:
                error = "Превышено время ожидания опроса"
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                log.info("Источник %s недоступен: %s", name, error)
            async with self.db.session() as session:
                source = await session.get(Source, source_id)
                if source is None:
                    return result
                source.last_check_at = utcnow()
                if error:
                    source.status = "error"
                    source.last_error = error[:2000]
                else:
                    source.status = "ok"
                    source.last_error = ""
                    source.metrics = result.metrics or {}
                    if result.state is not None:
                        source.state = result.state
                await session.commit()
            if not error and self.metrics is not None and result.metrics:
                try:
                    await self.metrics.record(source_id, result.metrics)
                except Exception:
                    log.exception("Не удалось сохранить метрики источника %s", name)
            down_fp = make_fingerprint("src", source_id, "down")
            events: list[EventIn] = []
            if error:
                events.append(
                    EventIn(
                        title=f"{name}: источник недоступен",
                        message=error,
                        severity="critical",
                        category=category,
                        type="source.down",
                        source_id=source_id,
                        source_name=name,
                        fingerprint=down_fp,
                    )
                )
            else:
                events.append(
                    EventIn(
                        title=f"{name}: источник доступен",
                        message="Источник снова отвечает",
                        category=category,
                        source_id=source_id,
                        source_name=name,
                        fingerprint=down_fp,
                        resolve=True,
                    )
                )
                events += result.events
            for item in events:
                try:
                    await self.pipeline.ingest(item)
                except Exception:
                    log.exception("Ошибка обработки события источника %s", name)
            return result

    async def maintenance(self, source_id: int) -> PollResult | None:
        async with self.db.session() as session:
            source = await session.get(Source, source_id)
            if source is None or not source.enabled:
                return None
            connector = self.build(source)
        try:
            result = await connector.maintenance()
        except Exception as exc:
            result = PollResult(
                events=[
                    connector.event(
                        title=f"{connector.ctx.name}: ошибка обслуживания",
                        message=str(exc),
                        severity="warning",
                        type="maintenance.error",
                    )
                ],
                message=str(exc),
            )
        for item in result.events:
            await self.pipeline.ingest(item)
        return result
