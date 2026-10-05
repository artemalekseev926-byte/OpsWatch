from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from opswatch.models import Event, Source, User
from opswatch.permissions import can_view_source, visible_categories


async def hidden_source_ids(session: AsyncSession, user: User) -> list[int]:
    if user.is_superuser:
        return []
    rows = (await session.execute(select(Source.id, Source.visible_roles))).all()
    return [source_id for source_id, roles in rows if not can_view_source(user, roles)]


async def visible_events_query(
    session: AsyncSession,
    user: User,
    categories: list[str] | None = None,
) -> Select:
    allowed = visible_categories(user)
    if categories:
        allowed = [c for c in categories if c in allowed]
    query = select(Event).where(Event.category.in_(allowed or ["__none__"]))
    hidden = await hidden_source_ids(session, user)
    if hidden:
        query = query.where(or_(Event.source_id.is_(None), Event.source_id.notin_(hidden)))
    return query


async def visible_sources(session: AsyncSession, user: User, categories: list[str] | None = None) -> list[Source]:
    allowed = visible_categories(user)
    if categories:
        allowed = [c for c in categories if c in allowed]
    rows = (
        await session.execute(select(Source).where(Source.category.in_(allowed or ["__none__"])).order_by(Source.name))
    ).scalars().all()
    return [s for s in rows if can_view_source(user, s.visible_roles)]


async def event_for_user(session: AsyncSession, event_id: int, user: User) -> Event | None:
    event = await session.get(Event, event_id)
    if event is None:
        return None
    if event.category not in visible_categories(user):
        return None
    if event.source_id:
        source = await session.get(Source, event.source_id)
        if source is not None and not can_view_source(user, source.visible_roles):
            return None
    return event


async def open_counts(session: AsyncSession, user: User) -> dict[str, dict[str, int]]:
    query = await visible_events_query(session, user)
    subquery = query.where(Event.status != "resolved").subquery()
    rows = (
        await session.execute(
            select(subquery.c.category, subquery.c.severity, func.count()).group_by(subquery.c.category, subquery.c.severity)
        )
    ).all()
    result: dict[str, dict[str, int]] = {}
    for category, severity, count in rows:
        result.setdefault(category, {})[severity] = count
    return result


def search_filter(query: Select, text: str) -> Select:
    pattern = f"%{text.strip()}%"
    return query.where(
        or_(Event.title.ilike(pattern), Event.message.ilike(pattern), Event.source_name.ilike(pattern))
    )

