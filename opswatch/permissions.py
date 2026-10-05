from __future__ import annotations

from typing import Iterable

from opswatch.constants import CATEGORIES, CATEGORY_PERMISSION, PERMISSIONS
from opswatch.models import User


def effective_permissions(user: User | None) -> set[str]:
    if user is None or user.status != "active":
        return set()
    if user.is_superuser:
        return set(PERMISSIONS)
    if user.role is None:
        return set()
    return {p for p in (user.role.permissions or []) if p in PERMISSIONS}


def has_perm(user: User | None, permission: str) -> bool:
    return permission in effective_permissions(user)


def visible_categories(user: User | None) -> list[str]:
    perms = effective_permissions(user)
    return [c for c in CATEGORIES if CATEGORY_PERMISSION[c] in perms]


def role_name(user: User | None) -> str:
    if user is None or user.role is None:
        return ""
    return user.role.name


def can_view_source(user: User | None, visible_roles: Iterable[str] | None) -> bool:
    if user is None:
        return False
    roles = list(visible_roles or [])
    if not roles or user.is_superuser:
        return True
    return role_name(user) in roles


def can_view_event(user: User | None, category: str, visible_roles: Iterable[str] | None = None) -> bool:
    if category not in visible_categories(user):
        return False
    return can_view_source(user, visible_roles)
