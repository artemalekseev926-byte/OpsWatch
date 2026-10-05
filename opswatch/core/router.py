from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opswatch.constants import severity_at_least
from opswatch.models import Event, Rule, Subscription, User
from opswatch.permissions import can_view_event, role_name


@dataclass
class RouteResult:
    users: list[User] = field(default_factory=list)
    escalation: list[dict] = field(default_factory=list)
    rules: list[int] = field(default_factory=list)


def rule_matches(rule: Rule, event: Event) -> bool:
    if not rule.enabled:
        return False
    if rule.categories and event.category not in rule.categories:
        return False
    if rule.source_ids and event.source_id not in rule.source_ids:
        return False
    if rule.event_types and not any(fnmatch.fnmatch(event.type or "", pattern) for pattern in rule.event_types):
        return False
    return severity_at_least(event.severity, rule.min_severity or "info")


def select_users(users: list[User], roles: list[str] | None, user_ids: list[int] | None) -> list[User]:
    roles = roles or []
    ids = set(user_ids or [])
    return [u for u in users if u.id in ids or (roles and role_name(u) in roles)]


async def load_active_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).where(User.status == "active"))
    return list(result.scalars().unique().all())


async def route_event(session: AsyncSession, event: Event, visible_roles: list[str] | None = None) -> RouteResult:
    users = await load_active_users(session)
    by_id = {u.id: u for u in users}
    targets: set[int] = set()
    rule_targets: set[int] = set()
    escalation: list[dict] = []
    matched: list[int] = []

    rules = (await session.execute(select(Rule).order_by(Rule.priority, Rule.id))).scalars().all()
    for rule in rules:
        if not rule_matches(rule, event):
            continue
        matched.append(rule.id)
        for user in select_users(users, rule.target_roles, rule.target_users):
            targets.add(user.id)
            rule_targets.add(user.id)
        if (
            event.severity == "critical"
            and rule.escalate_after_min
            and (rule.escalate_roles or rule.escalate_users)
        ):
            escalation.append(
                {
                    "rule": rule.id,
                    "after": int(rule.escalate_after_min),
                    "roles": list(rule.escalate_roles or []),
                    "users": list(rule.escalate_users or []),
                    "done": False,
                }
            )
        if rule.stop:
            break

    subscriptions = (
        await session.execute(select(Subscription).where(Subscription.category.in_([event.category, "*"])))
    ).scalars().all()
    muted: set[int] = set()
    for sub in subscriptions:
        if sub.user_id not in by_id:
            continue
        if sub.enabled:
            if severity_at_least(event.severity, sub.min_severity or "info"):
                targets.add(sub.user_id)
        else:
            muted.add(sub.user_id)
    for user_id in muted:
        if event.severity == "critical" and user_id in rule_targets:
            continue
        targets.discard(user_id)

    recipients = [
        by_id[uid]
        for uid in sorted(targets)
        if uid in by_id and can_view_event(by_id[uid], event.category, visible_roles)
    ]
    escalation.sort(key=lambda step: step["after"])
    return RouteResult(users=recipients, escalation=escalation, rules=matched)


def parse_hhmm(value: str) -> time | None:
    try:
        hours, minutes = value.strip().split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(user: User, now: datetime | None = None) -> bool:
    start = parse_hhmm(user.quiet_start or "")
    end = parse_hhmm(user.quiet_end or "")
    if start is None or end is None or start == end:
        return False
    current = (now or datetime.now()).time()
    if start < end:
        return start <= current < end
    return current >= start or current < end
