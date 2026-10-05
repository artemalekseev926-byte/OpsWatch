from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from opswatch.constants import SEVERITIES
from opswatch.models import Subscription, User
from opswatch.permissions import visible_categories

MODES = ("rules", "subscribed", "muted")
CYCLE = {"rules": "subscribed", "subscribed": "muted", "muted": "rules"}


async def get_states(session: AsyncSession, user: User) -> list[dict]:
    rows = (await session.execute(select(Subscription).where(Subscription.user_id == user.id))).scalars().all()
    by_category = {row.category: row for row in rows}
    result = []
    for category in visible_categories(user):
        row = by_category.get(category)
        if row is None:
            mode, minimum = "rules", "info"
        elif row.enabled:
            mode, minimum = "subscribed", row.min_severity or "info"
        else:
            mode, minimum = "muted", row.min_severity or "info"
        result.append({"category": category, "mode": mode, "min_severity": minimum})
    return result


async def set_state(session: AsyncSession, user: User, category: str, mode: str, min_severity: str = "info") -> None:
    if category not in visible_categories(user) or mode not in MODES:
        return
    if min_severity not in SEVERITIES:
        min_severity = "info"
    await session.execute(
        delete(Subscription).where(Subscription.user_id == user.id, Subscription.category == category)
    )
    if mode != "rules":
        session.add(
            Subscription(
                user_id=user.id,
                category=category,
                enabled=mode == "subscribed",
                min_severity=min_severity,
            )
        )


async def cycle_state(session: AsyncSession, user: User, category: str) -> str:
    states = {s["category"]: s for s in await get_states(session, user)}
    current = states.get(category)
    if current is None:
        return "rules"
    new_mode = CYCLE[current["mode"]]
    await set_state(session, user, category, new_mode, current["min_severity"])
    return new_mode
