from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opswatch.constants import SEVERITY_ORDER
from opswatch.core.events import EventIn
from opswatch.core.router import load_active_users, route_event, select_users
from opswatch.core.render import truncate
from opswatch.db import Database, utcnow
from opswatch.models import Attachment, Event, Notification, Source, User
from opswatch.permissions import can_view_event

log = logging.getLogger(__name__)

KIND_PREFIX = {"event": "", "repeat": "🔁 ", "escalation": "⏫ ", "resolved": "✅ "}


class EventPipeline:
    def __init__(self, db: Database, settings, notifier) -> None:
        self.db = db
        self.settings = settings
        self.notifier = notifier

    async def _visible_roles(self, session: AsyncSession, source_id: int | None) -> list[str]:
        if not source_id:
            return []
        source = await session.get(Source, source_id)
        return list(source.visible_roles or []) if source else []

    async def ingest(self, data: EventIn) -> Event | None:
        if data.resolve:
            return await self.auto_resolve(data)
        fingerprint = data.key()
        now = utcnow()
        window = timedelta(minutes=max(0, int(self.settings.get("group_window_min") or 0)))
        notification_ids: list[int] = []
        async with self.db.session() as session:
            visible_roles = await self._visible_roles(session, data.source_id)
            existing = await session.scalar(
                select(Event)
                .where(Event.fingerprint == fingerprint, Event.status != "resolved")
                .order_by(Event.id.desc())
                .limit(1)
            )
            raised = False
            if existing is not None:
                existing.count += 1
                existing.last_seen_at = now
                if data.message:
                    existing.message = data.message
                if data.details:
                    existing.details = {**(existing.details or {}), **data.details}
                raised = SEVERITY_ORDER[data.severity] > SEVERITY_ORDER.get(existing.severity, 0)
                if raised:
                    existing.severity = data.severity
                due = existing.status == "new" and (
                    existing.notified_at is None or now - existing.notified_at >= window
                )
                if data.attachments:
                    for item in data.attachments:
                        session.add(Attachment(event_id=existing.id, **item))
                if not (due or raised):
                    await session.commit()
                    return existing
                event = existing
                kind = "repeat"
            else:
                event = Event(
                    created_at=now,
                    last_seen_at=now,
                    source_id=data.source_id,
                    source_name=data.source_name,
                    category=data.category,
                    type=data.type,
                    severity=data.severity,
                    title=data.title,
                    message=data.message,
                    details=data.details,
                    fingerprint=fingerprint,
                    external_id=data.external_id,
                    reporter_id=data.reporter_id,
                    status="new",
                )
                session.add(event)
                await session.flush()
                for item in data.attachments:
                    session.add(Attachment(event_id=event.id, **item))
                kind = "event"

            route = await route_event(session, event, visible_roles)
            if kind == "event" or (raised and not event.escalation):
                event.escalation = route.escalation
            event.notified_at = now
            notification_ids = await self._notify(session, event, route.users, kind)
            await session.commit()
            await session.refresh(event)
        self.notifier.submit(notification_ids)
        return event

    async def auto_resolve(self, data: EventIn) -> Event | None:
        fingerprint = data.key()
        now = utcnow()
        resolved: list[Event] = []
        notification_ids: list[int] = []
        async with self.db.session() as session:
            query = select(Event).where(Event.status != "resolved")
            if data.external_id:
                query = query.where(
                    (Event.fingerprint == fingerprint) | (Event.external_id == data.external_id)
                )
                if data.source_id:
                    query = query.where(Event.source_id == data.source_id)
            else:
                query = query.where(Event.fingerprint == fingerprint)
            for event in (await session.execute(query)).scalars().all():
                event.status = "resolved"
                event.resolved_at = now
                event.resolution = data.message or "Источник сообщил о восстановлении"
                users = await self._previous_recipients(session, event.id)
                notification_ids += await self._notify(session, event, users, "resolved")
                resolved.append(event)
            await session.commit()
        self.notifier.submit(notification_ids)
        for event in resolved:
            self.notifier.submit_update(event.id)
        return resolved[-1] if resolved else None

    async def ack(self, event_id: int, user: User) -> Event | None:
        async with self.db.session() as session:
            event = await session.get(Event, event_id)
            if event is None:
                return None
            if event.status == "new":
                event.status = "acked"
                event.acked_by_id = user.id
                event.acked_at = utcnow()
                await session.commit()
        self.notifier.submit_update(event_id)
        return event

    async def resolve(self, event_id: int, user: User, note: str = "") -> Event | None:
        notification_ids: list[int] = []
        async with self.db.session() as session:
            event = await session.get(Event, event_id)
            if event is None:
                return None
            if event.status != "resolved":
                event.status = "resolved"
                event.resolved_by_id = user.id
                event.resolved_at = utcnow()
                event.resolution = note or ""
                if event.acked_by_id is None:
                    event.acked_by_id = user.id
                    event.acked_at = event.resolved_at
                users = [u for u in await self._previous_recipients(session, event.id) if u.id != user.id]
                notification_ids = await self._notify(session, event, users, "resolved")
                await session.commit()
        self.notifier.submit(notification_ids)
        self.notifier.submit_update(event_id)
        return event

    async def run_escalations(self) -> int:
        now = utcnow()
        notification_ids: list[int] = []
        escalated = 0
        async with self.db.session() as session:
            events = (
                await session.execute(
                    select(Event).where(Event.status == "new", Event.severity == "critical")
                )
            ).scalars().all()
            pending = [e for e in events if any(not s.get("done") for s in (e.escalation or []))]
            if not pending:
                return 0
            users = await load_active_users(session)
            for event in pending:
                steps = [dict(step) for step in event.escalation]
                visible_roles = await self._visible_roles(session, event.source_id)
                changed = False
                for step in steps:
                    if step.get("done"):
                        continue
                    if now - event.created_at < timedelta(minutes=int(step.get("after", 0))):
                        continue
                    targets = [
                        u
                        for u in select_users(users, step.get("roles"), step.get("users"))
                        if can_view_event(u, event.category, visible_roles)
                    ]
                    notification_ids += await self._notify(session, event, targets, "escalation")
                    step["done"] = True
                    event.escalation_level += 1
                    changed = True
                    escalated += 1
                if changed:
                    event.escalation = steps
            await session.commit()
        self.notifier.submit(notification_ids)
        return escalated

    async def _previous_recipients(self, session: AsyncSession, event_id: int) -> list[User]:
        user_ids = (
            await session.execute(
                select(Notification.user_id).where(
                    Notification.event_id == event_id, Notification.kind != "resolved"
                )
            )
        ).scalars().all()
        if not user_ids:
            return []
        result = await session.execute(select(User).where(User.id.in_(set(user_ids)), User.status == "active"))
        return list(result.scalars().unique().all())

    async def _notify(self, session: AsyncSession, event: Event, users: list[User], kind: str) -> list[int]:
        if not users:
            return []
        title = KIND_PREFIX.get(kind, "") + event.title
        parts = []
        if kind == "resolved" and event.resolution:
            parts.append(event.resolution)
        elif event.message:
            parts.append(event.message)
        if event.source_name:
            parts.append(f"Источник: {event.source_name}")
        if kind == "repeat":
            parts.append(f"Повторов: {event.count}")
        body = truncate("\n".join(parts), 1000)
        created = []
        seen: set[int] = set()
        for user in users:
            if user.id in seen:
                continue
            seen.add(user.id)
            notification = Notification(
                user_id=user.id,
                event_id=event.id,
                kind=kind,
                title=truncate(title, 500),
                body=body,
                severity="info" if kind == "resolved" else event.severity,
                category=event.category,
                telegram_status="pending",
            )
            session.add(notification)
            created.append(notification)
        await session.flush()
        return [n.id for n in created]
