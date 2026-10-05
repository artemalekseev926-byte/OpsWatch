from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update

from opswatch import APP_NAME, __version__
from opswatch.connectors import REGISTRY
from opswatch.constants import (
    CATEGORIES,
    CATEGORY_TITLES,
    EVENT_STATUS_TITLES,
    PERMISSIONS,
    SEVERITIES,
    SEVERITY_TITLES,
)
from opswatch.db import iso
from opswatch.models import Attachment, BackupJob, Event, Notification, Role, Source, User
from opswatch.permissions import has_perm, visible_categories
from opswatch.services.bugs import create_bug, save_attachment
from opswatch.services.queries import event_for_user, open_counts, search_filter, visible_events_query, visible_sources
from opswatch.web.deps import active_user, current_user, get_rt, optional_user, require
from opswatch.web.serializers import event_dict, event_user_ids, notification_dict, short_user, user_names

router = APIRouter(prefix="/api", tags=["events"])


class ResolveIn(BaseModel):
    note: str = ""


class ReadIn(BaseModel):
    ids: list[int] = []
    all: bool = False


@router.get("/health")
async def health():
    return {"status": "ok", "app": APP_NAME, "version": __version__}


@router.get("/meta")
async def meta(user: User | None = Depends(optional_user), rt=Depends(get_rt)):
    data = {
        "app": APP_NAME,
        "version": __version__,
        "registration_enabled": bool(rt.settings.get("registration_enabled")),
        "bot_username": rt.bot.username,
        "categories": [{"id": c, "title": CATEGORY_TITLES[c]} for c in CATEGORIES],
        "severities": [{"id": s, "title": SEVERITY_TITLES[s]} for s in SEVERITIES],
        "statuses": [{"id": k, "title": v} for k, v in EVENT_STATUS_TITLES.items()],
    }
    if user is not None and user.status == "active":
        async with rt.db.session() as session:
            roles = (await session.execute(select(Role).order_by(Role.id))).scalars().all()
            data["roles"] = [{"id": r.id, "name": r.name, "title": r.title} for r in roles]
            if any(has_perm(user, p) for p in ("rules.manage", "backups.manage", "users.manage", "sources.manage")):
                users = (await session.execute(select(User).where(User.status == "active").order_by(User.username))).scalars().unique().all()
                data["users"] = [short_user(u) for u in users]
                sources = (await session.execute(select(Source).order_by(Source.name))).scalars().all()
                data["sources"] = [{"id": s.id, "name": s.name, "type": s.type, "category": s.category} for s in sources]
        data["permissions"] = [{"id": k, "title": v} for k, v in PERMISSIONS.items()]
        data["connectors"] = [cls.describe() for cls in REGISTRY.values()]
    return data


@router.get("/dashboard")
async def dashboard(user: User = Depends(active_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        counts = await open_counts(session, user)
        sources = await visible_sources(session, user)
        query = await visible_events_query(session, user)
        recent = (await session.execute(query.order_by(Event.last_seen_at.desc()).limit(12))).scalars().all()
        names = await user_names(session, event_user_ids(recent))
        backups = []
        if has_perm(user, "backups.view"):
            jobs = (await session.execute(select(BackupJob).order_by(BackupJob.name))).scalars().all()
            for job in jobs:
                backups.append(
                    {
                        "id": job.id,
                        "name": job.name,
                        "last_status": "running" if rt.backups.is_running(job.id) else job.last_status,
                        "last_run_at": iso(job.last_run_at),
                        "enabled": job.enabled,
                    }
                )
    by_category = {}
    for category in visible_categories(user):
        cat_sources = [s for s in sources if s.category == category]
        by_category[category] = {
            "open": counts.get(category, {}),
            "sources": {
                "total": len(cat_sources),
                "ok": sum(1 for s in cat_sources if s.status == "ok"),
                "error": sum(1 for s in cat_sources if s.status == "error"),
            },
        }
    return {
        "categories": by_category,
        "recent": [event_dict(e, names) for e in recent],
        "failing_sources": [{"id": s.id, "name": s.name, "error": s.last_error} for s in sources if s.status == "error"],
        "backups": backups,
        "bot": rt.bot.info(),
    }


@router.get("/events")
async def list_events(
    category: str = "",
    severity: str = "",
    status: str = "",
    source_id: int | None = None,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(active_user),
    rt=Depends(get_rt),
):
    limit = max(1, min(200, limit))
    async with rt.db.session() as session:
        categories = [c for c in category.split(",") if c] or None
        query = await visible_events_query(session, user, categories)
        if severity:
            query = query.where(Event.severity.in_(severity.split(",")))
        if status == "open":
            query = query.where(Event.status != "resolved")
        elif status:
            query = query.where(Event.status.in_(status.split(",")))
        if source_id:
            query = query.where(Event.source_id == source_id)
        if q.strip():
            query = search_filter(query, q)
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await session.execute(query.order_by(Event.last_seen_at.desc(), Event.id.desc()).limit(limit).offset(offset))
        ).scalars().all()
        names = await user_names(session, event_user_ids(rows))
    return {"items": [event_dict(e, names) for e in rows], "total": total}


@router.get("/events/{event_id}")
async def get_event(event_id: int, user: User = Depends(active_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        event = await event_for_user(session, event_id, user)
        if event is None:
            raise HTTPException(404, "Событие не найдено")
        names = await user_names(session, event_user_ids([event]))
        return event_dict(event, names, full=True)


@router.post("/events/{event_id}/ack")
async def ack_event(event_id: int, user: User = Depends(require("events.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        if await event_for_user(session, event_id, user) is None:
            raise HTTPException(404, "Событие не найдено")
    await rt.pipeline.ack(event_id, user)
    return await get_event(event_id, user, rt)


@router.post("/events/{event_id}/resolve")
async def resolve_event(
    event_id: int, data: ResolveIn, user: User = Depends(require("events.manage")), rt=Depends(get_rt)
):
    async with rt.db.session() as session:
        if await event_for_user(session, event_id, user) is None:
            raise HTTPException(404, "Событие не найдено")
    await rt.pipeline.resolve(event_id, user, data.note.strip())
    return await get_event(event_id, user, rt)


@router.get("/attachments/{attachment_id}")
async def get_attachment(attachment_id: int, user: User = Depends(active_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        attachment = await session.get(Attachment, attachment_id)
        if attachment is None:
            raise HTTPException(404, "Файл не найден")
        event = await session.get(Event, attachment.event_id)
        own = event is not None and event.reporter_id == user.id
        if not own and await event_for_user(session, attachment.event_id, user) is None:
            raise HTTPException(404, "Файл не найден")
    path = rt.config.attachments_dir / attachment.stored_name
    if not path.exists():
        raise HTTPException(404, "Файл удалён")
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.filename)


@router.post("/bugs")
async def report_bug(
    title: str = Form(""),
    text: str = Form(""),
    severity: str = Form("warning"),
    files: list[UploadFile] | None = File(None),
    user: User = Depends(require("bugs.report")),
    rt=Depends(get_rt),
):
    if not title.strip() and not text.strip():
        raise HTTPException(422, "Опишите проблему")
    attachments = []
    for upload in (files or [])[:5]:
        content = await upload.read()
        if not content:
            continue
        try:
            attachments.append(
                save_attachment(rt.config.attachments_dir, upload.filename or "file", content, upload.content_type or "")
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    event = await create_bug(
        rt.pipeline,
        title=title,
        text=text,
        reporter=user,
        severity=severity if severity in SEVERITIES else "warning",
        attachments=attachments,
        channel="web",
    )
    async with rt.db.session() as session:
        event = await session.get(Event, event.id)
        names = await user_names(session, event_user_ids([event]))
        return event_dict(event, names, full=True)


@router.get("/bugs/mine")
async def my_bugs(user: User = Depends(active_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        rows = (
            await session.execute(
                select(Event).where(Event.reporter_id == user.id).order_by(Event.created_at.desc()).limit(100)
            )
        ).scalars().all()
        names = await user_names(session, event_user_ids(rows))
    return {"items": [event_dict(e, names) for e in rows]}


@router.get("/notifications")
async def notifications(limit: int = 30, user: User = Depends(current_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        rows = (
            await session.execute(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.id.desc())
                .limit(max(1, min(100, limit)))
            )
        ).scalars().all()
        unread = await session.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
    return {"items": [notification_dict(n) for n in rows], "unread": unread}


@router.get("/notifications/poll")
async def poll_notifications(after: int = 0, user: User = Depends(current_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        last_id = await session.scalar(select(func.max(Notification.id)).where(Notification.user_id == user.id)) or 0
        items = []
        if after > 0:
            rows = (
                await session.execute(
                    select(Notification)
                    .where(Notification.user_id == user.id, Notification.id > after)
                    .order_by(Notification.id)
                    .limit(20)
                )
            ).scalars().all()
            items = [notification_dict(n) for n in rows]
        unread = await session.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
        counts = await open_counts(session, user) if user.status == "active" else {}
    return {"items": items, "unread": unread, "last_id": last_id, "desktop": user.notify_desktop, "open": counts}


@router.post("/notifications/read")
async def read_notifications(data: ReadIn, user: User = Depends(current_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        query = update(Notification).where(Notification.user_id == user.id)
        if not data.all:
            query = query.where(Notification.id.in_(data.ids or [-1]))
        await session.execute(query.values(is_read=True))
        await session.commit()
    return {"ok": True}
