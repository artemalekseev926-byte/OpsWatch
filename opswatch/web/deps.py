from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, HTTPException, Request

from opswatch.db import utcnow
from opswatch.models import AuthSession, User
from opswatch.permissions import has_perm
from opswatch.security import token_hash

SESSION_DAYS = 30


def get_rt(request: Request):
    return request.app.state.rt


def _token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.query_params.get("access_token") or ""


async def optional_user(request: Request) -> User | None:
    token = _token(request)
    if not token:
        return None
    rt = get_rt(request)
    async with rt.db.session() as session:
        auth = await session.get(AuthSession, token_hash(token))
        if auth is None:
            return None
        now = utcnow()
        if auth.expires_at < now:
            await session.delete(auth)
            await session.commit()
            return None
        user = await session.get(User, auth.user_id)
        if user is None:
            return None
        if auth.expires_at - now < timedelta(days=SESSION_DAYS / 2):
            auth.expires_at = now + timedelta(days=SESSION_DAYS)
            await session.commit()
        return user


async def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    if user.status == "blocked":
        raise HTTPException(status_code=403, detail="Учётная запись заблокирована")
    return user


async def active_user(user: User = Depends(current_user)) -> User:
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Учётная запись ожидает подтверждения администратором")
    return user


def require(permission: str):
    async def dependency(user: User = Depends(active_user)) -> User:
        if not has_perm(user, permission):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user

    return dependency
