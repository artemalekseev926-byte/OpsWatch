from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from opswatch.connectors import get_connector_class
from opswatch.constants import CATEGORIES, PERMISSIONS, SEVERITIES
from opswatch.core.scheduler import next_cron_run, validate_cron
from opswatch.models import AuthSession, BackupJob, BackupRecord, Role, Rule, Source, Subscription, User
from opswatch.security import hash_password
from opswatch.web.deps import get_rt, require
from opswatch.web.serializers import job_dict, record_dict, role_dict, rule_dict, user_dict

router = APIRouter(prefix="/api", tags=["admin"])

MASK = "••••••••"


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_id: int
    schedule: str = "0 2 * * *"
    enabled: bool = True
    keep_last: int = 7
    encrypt: bool = True
    password: str = ""
    options: dict[str, Any] = {}
    destinations: dict[str, Any] = {}


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    priority: int = 100
    categories: list[str] = []
    source_ids: list[int] = []
    event_types: list[str] = []
    min_severity: str = "warning"
    target_roles: list[str] = []
    target_users: list[int] = []
    escalate_after_min: int = 0
    escalate_roles: list[str] = []
    escalate_users: list[int] = []
    stop: bool = False


class UserUpdate(BaseModel):
    status: str | None = None
    role_id: int | None = None
    full_name: str | None = None
    email: str | None = None
    note: str | None = None


class ApproveIn(BaseModel):
    role_id: int


class PasswordReset(BaseModel):
    password: str = Field(min_length=6)


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    title: str = Field(min_length=1, max_length=200)
    permissions: list[str] = []


def _job_payload(rt, job: BackupJob, source: Source | None) -> dict[str, Any]:
    return job_dict(job, source, rt.scheduler.next_run(f"backup:{job.id}") or next_cron_run(job.schedule), rt.backups.is_running(job.id))


@router.get("/backups/jobs")
async def list_jobs(user: User = Depends(require("backups.view")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        jobs = (await session.execute(select(BackupJob).order_by(BackupJob.name))).scalars().all()
        sources = {s.id: s for s in (await session.execute(select(Source))).scalars().all()}
    return {"items": [_job_payload(rt, job, sources.get(job.source_id)) for job in jobs]}


async def _apply_job(rt, job: BackupJob, data: JobIn) -> None:
    try:
        validate_cron(data.schedule)
    except ValueError as exc:
        raise HTTPException(422, f"Расписание: {exc}") from exc
    async with rt.db.session() as session:
        source = await session.get(Source, data.source_id)
    if source is None:
        raise HTTPException(422, "Источник не найден")
    if not get_connector_class(source.type).supports_backup:
        raise HTTPException(422, "Этот тип источника не поддерживает резервное копирование")
    job.name = data.name.strip()
    job.source_id = data.source_id
    job.schedule = data.schedule.strip()
    job.enabled = data.enabled
    job.keep_last = max(0, min(1000, data.keep_last))
    job.encrypt = data.encrypt
    if data.password and data.password != MASK:
        job.password = rt.crypto.encrypt(data.password)
    if job.encrypt and not job.password:
        raise HTTPException(422, "Укажите пароль для шифрования архива")
    job.options = data.options
    job.destinations = data.destinations


@router.post("/backups/jobs")
async def create_job(data: JobIn, user: User = Depends(require("backups.manage")), rt=Depends(get_rt)):
    job = BackupJob()
    await _apply_job(rt, job, data)
    async with rt.db.session() as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
        source = await session.get(Source, job.source_id)
    await rt.scheduler.sync()
    return _job_payload(rt, job, source)


@router.put("/backups/jobs/{job_id}")
async def update_job(job_id: int, data: JobIn, user: User = Depends(require("backups.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        job = await session.get(BackupJob, job_id)
        if job is None:
            raise HTTPException(404, "Задание не найдено")
        await _apply_job(rt, job, data)
        await session.commit()
        await session.refresh(job)
        source = await session.get(Source, job.source_id)
    await rt.scheduler.sync()
    return _job_payload(rt, job, source)


@router.delete("/backups/jobs/{job_id}")
async def delete_job(job_id: int, user: User = Depends(require("backups.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        job = await session.get(BackupJob, job_id)
        if job is None:
            raise HTTPException(404, "Задание не найдено")
        await session.delete(job)
        await session.commit()
    await rt.scheduler.sync()
    return {"ok": True}


@router.post("/backups/jobs/{job_id}/run")
async def run_job(job_id: int, user: User = Depends(require("backups.manage")), rt=Depends(get_rt)):
    if rt.backups.is_running(job_id):
        raise HTTPException(409, "Бэкап уже выполняется")
    asyncio.create_task(rt.backups.run(job_id, manual=True))
    await asyncio.sleep(0.05)
    return {"started": True}


@router.get("/backups/records")
async def list_records(job_id: int | None = None, limit: int = 50, user: User = Depends(require("backups.view")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        query = select(BackupRecord).order_by(BackupRecord.started_at.desc(), BackupRecord.id.desc()).limit(max(1, min(500, limit)))
        if job_id:
            query = query.where(BackupRecord.job_id == job_id)
        rows = (await session.execute(query)).scalars().all()
    return {"items": [record_dict(r) for r in rows]}


@router.get("/backups/records/{record_id}/download")
async def download_record(record_id: int, user: User = Depends(require("backups.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        record = await session.get(BackupRecord, record_id)
    if record is None or not record.file_path or record.deleted or not Path(record.file_path).exists():
        raise HTTPException(404, "Файл недоступен")
    return FileResponse(record.file_path, filename=Path(record.file_path).name, media_type="application/zip")


@router.delete("/backups/records/{record_id}")
async def delete_record(record_id: int, user: User = Depends(require("backups.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        record = await session.get(BackupRecord, record_id)
        if record is None:
            raise HTTPException(404, "Запись не найдена")
        if record.file_path:
            Path(record.file_path).unlink(missing_ok=True)
        record.deleted = True
        await session.commit()
    return {"ok": True}


def _validate_rule(data: RuleIn) -> None:
    if data.min_severity not in SEVERITIES:
        raise HTTPException(422, "Неизвестный уровень важности")
    if any(c not in CATEGORIES for c in data.categories):
        raise HTTPException(422, "Неизвестная категория")


@router.get("/rules")
async def list_rules(user: User = Depends(require("rules.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        rules = (await session.execute(select(Rule).order_by(Rule.priority, Rule.id))).scalars().all()
    return {"items": [rule_dict(r) for r in rules]}


@router.post("/rules")
async def create_rule(data: RuleIn, user: User = Depends(require("rules.manage")), rt=Depends(get_rt)):
    _validate_rule(data)
    async with rt.db.session() as session:
        rule = Rule(**data.model_dump())
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
    return rule_dict(rule)


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, data: RuleIn, user: User = Depends(require("rules.manage")), rt=Depends(get_rt)):
    _validate_rule(data)
    async with rt.db.session() as session:
        rule = await session.get(Rule, rule_id)
        if rule is None:
            raise HTTPException(404, "Правило не найдено")
        for key, value in data.model_dump().items():
            setattr(rule, key, value)
        await session.commit()
        await session.refresh(rule)
    return rule_dict(rule)


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, user: User = Depends(require("rules.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        rule = await session.get(Rule, rule_id)
        if rule is None:
            raise HTTPException(404, "Правило не найдено")
        await session.delete(rule)
        await session.commit()
    return {"ok": True}


@router.get("/users")
async def list_users(user: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        users = (await session.execute(select(User).order_by(User.status.desc(), User.username))).scalars().unique().all()
    order = {"pending": 0, "active": 1, "blocked": 2}
    users = sorted(users, key=lambda u: (order.get(u.status, 3), u.username.lower()))
    return {"items": [user_dict(u) for u in users]}


async def _notify_user(rt, user: User, text: str) -> None:
    try:
        if user.telegram_chat_id and rt.bot.available:
            await rt.bot.send_text(user.telegram_chat_id, text)
    except Exception:
        pass


@router.put("/users/{user_id}")
async def update_user(user_id: int, data: UserUpdate, admin: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        target = await session.get(User, user_id)
        if target is None:
            raise HTTPException(404, "Пользователь не найден")
        changes = data.model_dump(exclude_unset=True)
        if target.is_superuser and ("status" in changes or "role_id" in changes) and target.id != admin.id:
            raise HTTPException(403, "Нельзя изменить статус или роль главного администратора")
        if target.is_superuser and changes.get("status") not in (None, "active"):
            raise HTTPException(403, "Главного администратора нельзя заблокировать")
        if "status" in changes and changes["status"] not in ("pending", "active", "blocked"):
            raise HTTPException(422, "Неизвестный статус")
        if "role_id" in changes and changes["role_id"] is not None and await session.get(Role, changes["role_id"]) is None:
            raise HTTPException(422, "Роль не найдена")
        for key, value in changes.items():
            setattr(target, key, value)
        if target.status == "blocked":
            await session.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
        await session.commit()
        target = await session.get(User, user_id)
        await session.refresh(target)
        return user_dict(target)


@router.post("/users/{user_id}/approve")
async def approve_user(user_id: int, data: ApproveIn, admin: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        target = await session.get(User, user_id)
        role = await session.get(Role, data.role_id)
        if target is None or role is None:
            raise HTTPException(404, "Пользователь или роль не найдены")
        target.status = "active"
        target.role_id = role.id
        await session.commit()
        await session.refresh(target)
        result = user_dict(target)
    await _notify_user(rt, target, f"✅ Ваша учётная запись OpsWatch подтверждена. Роль: <b>{role.title}</b>.")
    return result


@router.post("/users/{user_id}/reject")
async def reject_user(user_id: int, admin: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        target = await session.get(User, user_id)
        if target is None:
            raise HTTPException(404, "Пользователь не найден")
        if target.status != "pending":
            raise HTTPException(409, "Отклонить можно только новую заявку")
        await session.delete(target)
        await session.commit()
    return {"ok": True}


@router.post("/users/{user_id}/password")
async def reset_password(
    user_id: int, data: PasswordReset, admin: User = Depends(require("users.manage")), rt=Depends(get_rt)
):
    async with rt.db.session() as session:
        target = await session.get(User, user_id)
        if target is None:
            raise HTTPException(404, "Пользователь не найден")
        if target.is_superuser and target.id != admin.id and not admin.is_superuser:
            raise HTTPException(403, "Недостаточно прав")
        target.password_hash = hash_password(data.password)
        await session.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
        await session.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        target = await session.get(User, user_id)
        if target is None:
            raise HTTPException(404, "Пользователь не найден")
        if target.is_superuser or target.id == admin.id:
            raise HTTPException(403, "Этого пользователя нельзя удалить")
        await session.execute(delete(Subscription).where(Subscription.user_id == target.id))
        await session.delete(target)
        await session.commit()
    return {"ok": True}


@router.get("/roles")
async def list_roles(user: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        roles = (await session.execute(select(Role).order_by(Role.id))).scalars().all()
    return {"items": [role_dict(r) for r in roles]}


def _clean_permissions(values: list[str]) -> list[str]:
    return [p for p in values if p in PERMISSIONS]


@router.post("/roles")
async def create_role(data: RoleIn, user: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        if await session.scalar(select(Role).where(Role.name == data.name)):
            raise HTTPException(409, "Роль с таким кодом уже есть")
        role = Role(name=data.name, title=data.title, permissions=_clean_permissions(data.permissions), builtin=False)
        session.add(role)
        await session.commit()
        await session.refresh(role)
    return role_dict(role)


@router.put("/roles/{role_id}")
async def update_role(role_id: int, data: RoleIn, user: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        role = await session.get(Role, role_id)
        if role is None:
            raise HTTPException(404, "Роль не найдена")
        if role.name == "admin":
            raise HTTPException(403, "Роль администратора не редактируется")
        role.title = data.title
        role.permissions = _clean_permissions(data.permissions)
        if not role.builtin:
            role.name = data.name
        await session.commit()
        await session.refresh(role)
    return role_dict(role)


@router.delete("/roles/{role_id}")
async def delete_role(role_id: int, user: User = Depends(require("users.manage")), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        role = await session.get(Role, role_id)
        if role is None:
            raise HTTPException(404, "Роль не найдена")
        if role.builtin:
            raise HTTPException(403, "Встроенную роль нельзя удалить")
        await session.delete(role)
        await session.commit()
    return {"ok": True}


@router.get("/settings")
async def get_settings(request: Request, user: User = Depends(require("settings.manage")), rt=Depends(get_rt)):
    return {
        "values": rt.settings.public(),
        "bot": rt.bot.info(),
        "base_url": (rt.settings.get("public_url") or str(request.base_url)).rstrip("/"),
        "data_dir": str(rt.config.data_dir),
        "backup_dir": str(rt.backups.root()),
    }


@router.put("/settings")
async def put_settings(data: dict[str, Any], request: Request, user: User = Depends(require("settings.manage")), rt=Depends(get_rt)):
    changed = await rt.settings.update(data)
    if {"telegram_token", "telegram_api_url"} & set(changed):
        await rt.restart_bot()
    return await get_settings(request, user, rt)


@router.post("/settings/telegram/restart")
async def restart_bot(request: Request, user: User = Depends(require("settings.manage")), rt=Depends(get_rt)):
    await rt.restart_bot()
    return await get_settings(request, user, rt)
