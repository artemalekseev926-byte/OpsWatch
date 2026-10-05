from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from opswatch.connectors import ConnectorError, SourceContext, get_connector_class
from opswatch.connectors.sql import SqlConnector
from opswatch.constants import CATEGORIES
from opswatch.core.ingest import parse_alertmanager, parse_generic, parse_zabbix
from opswatch.core.metrics import PERIODS, PRIMARY, describe
from opswatch.db import iso, utcnow
from opswatch.models import Source, User
from opswatch.permissions import can_view_event, has_perm
from opswatch.security import new_token, safe_equals
from opswatch.services.queries import visible_sources
from opswatch.web.deps import active_user, get_rt, require
from opswatch.web.serializers import source_dict

router = APIRouter(prefix="/api", tags=["sources"])


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str
    category: str = ""
    enabled: bool = True
    poll_interval: int = 0
    visible_roles: list[str] = []
    config: dict[str, Any] = {}


class TestIn(BaseModel):
    id: int | None = None
    name: str = ""
    type: str
    category: str = ""
    config: dict[str, Any] = {}


class PreviewIn(TestIn):
    check: dict[str, Any] = {}


def base_url(request: Request, rt) -> str:
    return (rt.settings.get("public_url") or str(request.base_url)).rstrip("/")


def serialize(rt, source: Source, manage: bool, url: str) -> dict[str, Any]:
    try:
        cls = get_connector_class(source.type)
        title, passive = cls.title, cls.passive
        config = rt.sources.masked_config(source) if manage else None
    except ConnectorError:
        title, passive, config = source.type, False, dict(source.config or {})
    next_run = rt.scheduler.next_run(f"source:{source.id}")
    return source_dict(source, config, title, passive, manage, next_run, url)


def validate(data: SourceIn) -> type:
    try:
        cls = get_connector_class(data.type)
    except ConnectorError as exc:
        raise HTTPException(422, str(exc)) from exc
    if data.category and data.category not in CATEGORIES:
        raise HTTPException(422, "Неизвестная категория")
    for spec in cls.fields:
        if spec.required and spec.type != "checks" and data.config.get(spec.name) in (None, "") and not spec.secret:
            if spec.name == "database" and data.config.get("dsn"):
                continue
            raise HTTPException(422, f"Заполните поле «{spec.label}»")
    return cls


@router.get("/sources")
async def list_sources(request: Request, category: str = "", user: User = Depends(active_user), rt=Depends(get_rt)):
    manage = has_perm(user, "sources.manage")
    async with rt.db.session() as session:
        categories = [c for c in category.split(",") if c] or None
        sources = await visible_sources(session, user, categories)
    url = base_url(request, rt)
    return {"items": [serialize(rt, s, manage, url) for s in sources]}


@router.post("/sources")
async def create_source(
    data: SourceIn, request: Request, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)
):
    cls = validate(data)
    config, secrets = rt.sources.split_config(data.type, data.config)
    async with rt.db.session() as session:
        source = Source(
            name=data.name.strip(),
            type=data.type,
            category=data.category or cls.category,
            enabled=data.enabled,
            config=config,
            secrets=secrets,
            poll_interval=data.poll_interval or cls.default_interval or 60,
            visible_roles=data.visible_roles,
            ingest_token=new_token(24) if cls.passive else None,
            status="waiting" if cls.passive else "unknown",
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
    await rt.scheduler.sync()
    return serialize(rt, source, True, base_url(request, rt))


@router.put("/sources/{source_id}")
async def update_source(
    source_id: int, data: SourceIn, request: Request, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)
):
    cls = validate(data)
    async with rt.db.session() as session:
        source = await session.get(Source, source_id)
        if source is None:
            raise HTTPException(404, "Источник не найден")
        if source.type != data.type:
            raise HTTPException(422, "Тип источника нельзя изменить")
        config, secrets = rt.sources.split_config(data.type, data.config, source.secrets)
        source.name = data.name.strip()
        source.category = data.category or cls.category
        source.enabled = data.enabled
        source.config = config
        source.secrets = secrets
        source.poll_interval = data.poll_interval or cls.default_interval or 60
        source.visible_roles = data.visible_roles
        if cls.passive and not source.ingest_token:
            source.ingest_token = new_token(24)
        await session.commit()
        await session.refresh(source)
    await rt.scheduler.sync()
    return serialize(rt, source, True, base_url(request, rt))


@router.delete("/sources/{source_id}")
async def delete_source(source_id: int, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        source = await session.get(Source, source_id)
        if source is None:
            raise HTTPException(404, "Источник не найден")
        await session.delete(source)
        await session.commit()
    await rt.scheduler.sync()
    return {"ok": True}


@router.post("/sources/test")
async def test_source(data: TestIn, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)):
    try:
        result = await rt.sources.test_config(data.type, data.name, data.category, data.config, data.id)
    except asyncio.TimeoutError:
        return {"ok": False, "message": "Превышено время ожидания"}
    except Exception as exc:
        return {"ok": False, "message": str(exc) or type(exc).__name__}
    return {"ok": True, "message": result.message, "metrics": result.metrics}


@router.post("/sources/preview-check")
async def preview_check(data: PreviewIn, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)):
    existing = ""
    if data.id:
        async with rt.db.session() as session:
            source = await session.get(Source, data.id)
            existing = source.secrets if source else ""
    config, secrets = rt.sources.split_config(data.type, data.config, existing)
    config.update(rt.crypto.decrypt_json(secrets))
    cls = get_connector_class(data.type)
    connector = cls(SourceContext(id=data.id, name=data.name, category=data.category or cls.category, config=config))
    if hasattr(connector, "dbms_connector"):
        connector = connector.dbms_connector()
    if not isinstance(connector, SqlConnector):
        raise HTTPException(422, "Проверки доступны только для SQL-источников")
    try:
        rows = await asyncio.wait_for(connector.run_check_preview(data.check), timeout=60)
    except Exception as exc:
        return {"ok": False, "message": str(exc) or type(exc).__name__, "rows": []}
    return {"ok": True, "message": f"Строк: {len(rows)}", "rows": rows}


@router.post("/sources/{source_id}/poll")
async def poll_source(source_id: int, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)):
    result = await rt.sources.poll(source_id)
    async with rt.db.session() as session:
        source = await session.get(Source, source_id)
        if source is None:
            raise HTTPException(404, "Источник не найден")
        status, error = source.status, source.last_error
    message = error if status == "error" else (result.message if result else "Опрос уже выполняется или источник пассивный")
    return {"ok": status != "error", "status": status, "message": message}


@router.post("/sources/{source_id}/maintenance")
async def maintenance_source(source_id: int, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)):
    result = await rt.sources.maintenance(source_id)
    return {"ok": result is not None, "message": result.message if result else "Источник не найден"}


@router.post("/sources/{source_id}/token")
async def regenerate_token(
    source_id: int, request: Request, user: User = Depends(require("sources.manage")), rt=Depends(get_rt)
):
    async with rt.db.session() as session:
        source = await session.get(Source, source_id)
        if source is None:
            raise HTTPException(404, "Источник не найден")
        source.ingest_token = new_token(24)
        await session.commit()
        await session.refresh(source)
    return serialize(rt, source, True, base_url(request, rt))


async def visible_source(rt, user: User, source_id: int) -> Source:
    async with rt.db.session() as session:
        source = await session.get(Source, source_id)
    if source is None or not can_view_event(user, source.category, source.visible_roles):
        raise HTTPException(404, "Источник не найден")
    return source


@router.get("/sources/{source_id}/metrics")
async def source_metrics(source_id: int, user: User = Depends(active_user), rt=Depends(get_rt)):
    source = await visible_source(rt, user, source_id)
    series = await rt.metrics.series(source.id)
    primary = PRIMARY.get(source.type)
    for item in series:
        item["last_at"] = iso(item["last_at"])
        item["primary"] = item["name"] == primary
    return {"source": {"id": source.id, "name": source.name, "type": source.type}, "series": series}


@router.get("/sources/{source_id}/metrics/{name}")
async def source_metric_points(
    source_id: int, name: str, period: str = "24h", user: User = Depends(active_user), rt=Depends(get_rt)
):
    source = await visible_source(rt, user, source_id)
    if period not in PERIODS:
        raise HTTPException(422, "Неизвестный период")
    points = await rt.metrics.points(source.id, name, period)
    return {**describe(name), "period": period, "points": [[iso(ts), round(value, 4)] for ts, value in points]}


@router.get("/metrics/sparklines")
async def sparklines(category: str = "", user: User = Depends(active_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        categories = [c for c in category.split(",") if c] or None
        sources = await visible_sources(session, user, categories)
    result = {}
    for source in sources:
        name = PRIMARY.get(source.type)
        if not name:
            continue
        values = await rt.metrics.sparkline(source.id, name)
        if len(values) >= 2:
            result[str(source.id)] = {**describe(name), "values": values}
    return result


@router.post("/ingest/{token}")
async def ingest(token: str, request: Request, rt=Depends(get_rt)):
    async with rt.db.session() as session:
        source = await session.scalar(select(Source).where(Source.ingest_token == token))
        if source is None or not source.ingest_token or not safe_equals(source.ingest_token, token):
            raise HTTPException(404, "Неизвестный токен")
        if not source.enabled:
            raise HTTPException(403, "Источник отключён")
        source_id, name, kind, category = source.id, source.name, source.type, source.category
        default_severity = (source.config or {}).get("default_severity") or "warning"
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except (UnicodeDecodeError, ValueError):
        payload = {"message": raw.decode("utf-8", errors="replace")}
    if isinstance(payload, dict) and isinstance(payload.get("message"), str) and kind == "zabbix_webhook":
        try:
            nested = json.loads(payload["message"])
            if isinstance(nested, dict):
                payload = {**payload, **nested}
        except ValueError:
            pass
    if kind == "zabbix_webhook":
        events = parse_zabbix(payload if isinstance(payload, dict) else {}, source_id, name, category)
    elif kind == "alertmanager":
        events = parse_alertmanager(payload if isinstance(payload, dict) else {}, source_id, name, category)
    else:
        events = parse_generic(payload, source_id, name, category, default_severity)
    ids = []
    for item in events[:100]:
        event = await rt.pipeline.ingest(item)
        if event is not None:
            ids.append(event.id)
    async with rt.db.session() as session:
        source = await session.get(Source, source_id)
        if source is not None:
            source.status = "ok"
            source.last_check_at = utcnow()
            source.metrics = {**(source.metrics or {}), "received": int((source.metrics or {}).get("received", 0)) + len(events)}
            await session.commit()
    return {"accepted": len(events), "events": ids}
