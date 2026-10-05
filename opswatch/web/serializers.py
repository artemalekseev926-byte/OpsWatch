from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opswatch.db import iso
from opswatch.i18n import tr
from opswatch.models import BackupJob, BackupRecord, Event, Notification, Role, Rule, Source, User
from opswatch.permissions import effective_permissions


def role_dict(role: Role | None) -> dict[str, Any] | None:
    if role is None:
        return None
    return {
        "id": role.id,
        "name": role.name,
        "title": tr(role.title),
        "permissions": list(role.permissions or []),
        "builtin": role.builtin,
    }


def user_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "status": user.status,
        "is_superuser": user.is_superuser,
        "role": role_dict(user.role),
        "permissions": sorted(effective_permissions(user)),
        "telegram_username": user.telegram_username,
        "telegram_linked": bool(user.telegram_chat_id),
        "personal_bot": user.personal_bot_username if user.personal_bot_token else "",
        "personal_bot_linked": bool(user.personal_bot_token and user.personal_chat_id),
        "notify_telegram": user.notify_telegram,
        "notify_desktop": user.notify_desktop,
        "quiet_start": user.quiet_start,
        "quiet_end": user.quiet_end,
        "language": user.language or "ru",
        "chat_telegram": user.chat_telegram,
        "note": user.note,
        "created_at": iso(user.created_at),
        "last_login_at": iso(user.last_login_at),
    }


def short_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.name if user.role else "",
        "status": user.status,
    }


async def user_names(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.full_name, User.username).where(User.id.in_(ids)))).all()
    return {row[0]: row[1] or row[2] for row in rows}


def event_dict(event: Event, names: dict[int, str] | None = None, full: bool = False) -> dict[str, Any]:
    names = names or {}
    data = {
        "id": event.id,
        "created_at": iso(event.created_at),
        "last_seen_at": iso(event.last_seen_at),
        "source_id": event.source_id,
        "source_name": event.source_name,
        "category": event.category,
        "type": event.type,
        "severity": event.severity,
        "title": event.title,
        "message": event.message if full else (event.message or "")[:300],
        "count": event.count,
        "status": event.status,
        "acked_by": names.get(event.acked_by_id, ""),
        "acked_at": iso(event.acked_at),
        "resolved_by": names.get(event.resolved_by_id, ""),
        "resolved_at": iso(event.resolved_at),
        "resolution": event.resolution,
        "escalation_level": event.escalation_level,
        "reporter": names.get(event.reporter_id, ""),
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "size": a.size,
                "content_type": a.content_type,
                "url": f"/api/attachments/{a.id}",
            }
            for a in event.attachments
        ],
    }
    if full:
        data["details"] = event.details or {}
        data["escalation"] = event.escalation or []
    return data


def event_user_ids(events: list[Event]) -> set[int]:
    ids: set[int] = set()
    for event in events:
        ids.update({event.acked_by_id, event.resolved_by_id, event.reporter_id})
    return {i for i in ids if i}


def notification_dict(item: Notification) -> dict[str, Any]:
    return {
        "id": item.id,
        "event_id": item.event_id,
        "created_at": iso(item.created_at),
        "kind": item.kind,
        "title": item.title,
        "body": item.body,
        "severity": item.severity,
        "category": item.category,
        "is_read": item.is_read,
        "telegram_status": item.telegram_status,
    }


def source_dict(
    source: Source,
    config: dict[str, Any] | None,
    type_title: str,
    passive: bool,
    manage: bool,
    next_run=None,
    base_url: str = "",
) -> dict[str, Any]:
    data = {
        "id": source.id,
        "name": source.name,
        "type": source.type,
        "type_title": type_title,
        "category": source.category,
        "enabled": source.enabled,
        "poll_interval": source.poll_interval,
        "visible_roles": list(source.visible_roles or []),
        "status": source.status,
        "last_check_at": iso(source.last_check_at),
        "last_error": source.last_error,
        "metrics": source.metrics or {},
        "passive": passive,
        "next_run": next_run.isoformat() if next_run else None,
        "created_at": iso(source.created_at),
    }
    if manage:
        data["config"] = config or {}
        if passive and source.ingest_token:
            data["ingest_path"] = f"/api/ingest/{source.ingest_token}"
            data["ingest_url"] = f"{base_url.rstrip('/')}/api/ingest/{source.ingest_token}" if base_url else ""
    return data


def job_dict(job: BackupJob, source: Source | None, next_run=None, running: bool = False) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "source_id": job.source_id,
        "source_name": source.name if source else "",
        "source_type": source.type if source else "",
        "schedule": job.schedule,
        "enabled": job.enabled,
        "keep_last": job.keep_last,
        "encrypt": job.encrypt,
        "has_password": bool(job.password),
        "options": job.options or {},
        "destinations": job.destinations or {},
        "last_run_at": iso(job.last_run_at),
        "last_status": "running" if running else job.last_status,
        "last_error": job.last_error,
        "next_run": next_run.isoformat() if next_run else None,
        "running": running,
    }


def record_dict(record: BackupRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "job_id": record.job_id,
        "started_at": iso(record.started_at),
        "finished_at": iso(record.finished_at),
        "status": record.status,
        "manual": record.manual,
        "file_name": Path(record.file_path).name if record.file_path else "",
        "size": record.size,
        "sha256": record.sha256,
        "verified": record.verified,
        "delivery": record.delivery or {},
        "error": record.error,
        "deleted": record.deleted,
        "available": bool(record.file_path) and not record.deleted and Path(record.file_path).exists(),
    }


def rule_dict(rule: Rule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": tr(rule.name),
        "enabled": rule.enabled,
        "priority": rule.priority,
        "categories": rule.categories or [],
        "source_ids": rule.source_ids or [],
        "event_types": rule.event_types or [],
        "min_severity": rule.min_severity,
        "target_roles": rule.target_roles or [],
        "target_users": rule.target_users or [],
        "escalate_after_min": rule.escalate_after_min,
        "escalate_roles": rule.escalate_roles or [],
        "escalate_users": rule.escalate_users or [],
        "stop": rule.stop,
    }
