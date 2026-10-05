from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from opswatch.core.events import EventIn
from opswatch.core.router import parse_hhmm
from opswatch.db import iso, utcnow
from opswatch.i18n import LANGUAGES, current_language, tr, ts
from opswatch.models import AuthSession, User
from opswatch.security import hash_password, new_link_code, new_token, token_hash, verify_password
from opswatch.services.subscriptions import get_states, set_state
from opswatch.web.deps import SESSION_DAYS, _token, active_user, current_user, get_rt
from opswatch.web.serializers import user_dict

router = APIRouter(prefix="/api", tags=["account"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
MASK = "••••••••"


class RegisterIn(BaseModel):
    username: str
    password: str
    full_name: str = ""
    email: str = ""
    telegram_username: str = ""
    language: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    full_name: str | None = None
    email: str | None = None
    telegram_username: str | None = None
    notify_telegram: bool | None = None
    notify_desktop: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    language: str | None = None


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=6)


class PersonalBotIn(BaseModel):
    token: str


class SubscriptionItem(BaseModel):
    category: str
    mode: str
    min_severity: str = "info"


class SubscriptionsIn(BaseModel):
    items: list[SubscriptionItem]


def _client(request: Request) -> str:
    host = request.client.host if request.client else ""
    agent = request.headers.get("user-agent", "")[:200]
    return f"{host} {agent}".strip()


@router.post("/auth/register")
async def register(data: RegisterIn, rt=Depends(get_rt)):
    if not rt.settings.get("registration_enabled"):
        raise HTTPException(403, tr("Регистрация отключена администратором"))
    username = data.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(422, tr("Логин: 3–32 символа, латиница, цифры, точка, дефис, подчёркивание"))
    if len(data.password) < 6:
        raise HTTPException(422, tr("Пароль должен быть не короче 6 символов"))
    async with rt.db.session() as session:
        exists = await session.scalar(select(func.count(User.id)).where(func.lower(User.username) == username.lower()))
        if exists:
            raise HTTPException(409, tr("Такой логин уже занят"))
        user = User(
            username=username,
            password_hash=hash_password(data.password),
            full_name=data.full_name.strip()[:200],
            email=data.email.strip()[:200],
            telegram_username=data.telegram_username.strip().lstrip("@")[:100],
            language=data.language if data.language in LANGUAGES else current_language(),
            status="pending",
        )
        session.add(user)
        await session.commit()
    await rt.pipeline.ingest(
        EventIn(
            title=ts("Новый пользователь ожидает подтверждения: {name}", name=data.full_name.strip() or username),
            message=ts("Логин: {username}\nTelegram: {telegram}\nОткройте «Пользователи», чтобы выдать права.", username=username, telegram=data.telegram_username or "—"),
            severity="warning",
            category="system",
            type="user.registered",
            source_name="OpsWatch",
            fingerprint=f"user-registered-{username.lower()}",
        )
    )
    return {"status": "pending", "message": tr("Заявка отправлена. Дождитесь подтверждения администратором.")}


@router.post("/auth/login")
async def login(data: LoginIn, request: Request, rt=Depends(get_rt)):
    key = f"{request.client.host if request.client else ''}:{data.username.lower()}"
    wait = rt.throttle.locked_for(key)
    if wait:
        raise HTTPException(429, tr("Слишком много попыток. Повторите через {wait} сек.", wait=wait))
    async with rt.db.session() as session:
        user = await session.scalar(select(User).where(func.lower(User.username) == data.username.strip().lower()))
        if user is None or not verify_password(data.password, user.password_hash):
            rt.throttle.failure(key)
            raise HTTPException(401, tr("Неверный логин или пароль"))
        if user.status == "blocked":
            raise HTTPException(403, tr("Учётная запись заблокирована"))
        rt.throttle.success(key)
        token = new_token()
        session.add(
            AuthSession(
                token_hash=token_hash(token),
                user_id=user.id,
                expires_at=utcnow() + timedelta(days=SESSION_DAYS),
                client=_client(request),
            )
        )
        user.last_login_at = utcnow()
        await session.commit()
        await session.refresh(user)
        return {"token": token, "user": user_dict(user)}


@router.post("/auth/logout")
async def logout(request: Request, rt=Depends(get_rt)):
    token = _token(request)
    if token:
        async with rt.db.session() as session:
            await session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
            await session.commit()
    return {"ok": True}


@router.get("/auth/me")
async def me(user: User = Depends(current_user)):
    return user_dict(user)


@router.put("/profile")
async def update_profile(data: ProfileIn, user: User = Depends(current_user), rt=Depends(get_rt)):
    for field in ("quiet_start", "quiet_end"):
        value = getattr(data, field)
        if value not in (None, "") and parse_hhmm(value) is None:
            raise HTTPException(422, tr("Время тихих часов в формате ЧЧ:ММ"))
    if data.language is not None and data.language not in LANGUAGES:
        raise HTTPException(422, tr("Неизвестный язык"))
    async with rt.db.session() as session:
        db_user = await session.get(User, user.id)
        for field, value in data.model_dump(exclude_none=True).items():
            if isinstance(value, str):
                value = value.strip()
                if field == "telegram_username":
                    value = value.lstrip("@")
            setattr(db_user, field, value)
        await session.commit()
        await session.refresh(db_user)
        return user_dict(db_user)


@router.post("/profile/password")
async def change_password(data: PasswordIn, user: User = Depends(current_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        db_user = await session.get(User, user.id)
        if not verify_password(data.current, db_user.password_hash):
            raise HTTPException(400, tr("Текущий пароль указан неверно"))
        db_user.password_hash = hash_password(data.new)
        await session.commit()
    return {"ok": True}


@router.post("/profile/telegram/link")
async def telegram_link(user: User = Depends(current_user), rt=Depends(get_rt)):
    code = new_link_code()
    expires = utcnow() + timedelta(minutes=15)
    async with rt.db.session() as session:
        db_user = await session.get(User, user.id)
        db_user.telegram_link_code = code
        db_user.telegram_link_expires = expires
        await session.commit()
    username = rt.bot.username
    return {
        "code": code,
        "expires_at": iso(expires),
        "bot_username": username,
        "bot_running": rt.bot.available,
        "deep_link": f"https://t.me/{username}?start={code}" if username else "",
    }


@router.delete("/profile/telegram")
async def telegram_unlink(user: User = Depends(current_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        db_user = await session.get(User, user.id)
        db_user.telegram_chat_id = None
        db_user.telegram_link_code = None
        await session.commit()
        await session.refresh(db_user)
        return user_dict(db_user)


@router.post("/profile/telegram/test")
async def telegram_test(user: User = Depends(current_user), rt=Depends(get_rt)):
    personal = rt.crypto.decrypt(user.personal_bot_token or "")
    text = tr("✅ <b>Тестовое уведомление OpsWatch</b>\nУведомления настроены правильно.")
    try:
        if personal and user.personal_chat_id:
            await rt.bot.send_text(user.personal_chat_id, text, personal)
        elif user.telegram_chat_id and rt.bot.available:
            await rt.bot.send_text(user.telegram_chat_id, text)
        else:
            raise HTTPException(400, tr("Telegram не привязан или бот не запущен"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Telegram: {exc}") from exc
    return {"ok": True}


@router.put("/profile/personal-bot")
async def personal_bot_set(data: PersonalBotIn, user: User = Depends(current_user), rt=Depends(get_rt)):
    token = data.token.strip()
    if not re.match(r"^\d+:[\w-]{30,}$", token):
        raise HTTPException(422, tr("Неверный формат токена бота"))
    try:
        username = await rt.bot.validate_personal(token)
    except Exception as exc:
        raise HTTPException(400, tr("Токен не принят Telegram: {exc}", exc=exc)) from exc
    async with rt.db.session() as session:
        db_user = await session.get(User, user.id)
        db_user.personal_bot_token = rt.crypto.encrypt(token)
        db_user.personal_bot_username = username
        db_user.personal_chat_id = None
        await session.commit()
    return {"username": username, "link": f"https://t.me/{username}"}


@router.post("/profile/personal-bot/detect")
async def personal_bot_detect(user: User = Depends(current_user), rt=Depends(get_rt)):
    token = rt.crypto.decrypt(user.personal_bot_token or "")
    if not token:
        raise HTTPException(400, tr("Сначала сохраните токен своего бота"))
    try:
        found = await rt.bot.detect_personal_chat(token)
    except Exception as exc:
        raise HTTPException(502, f"Telegram: {exc}") from exc
    if not found:
        raise HTTPException(404, tr("Сообщение не найдено. Откройте своего бота в Telegram, нажмите «Старт» и повторите"))
    chat_id, tg_username = found
    async with rt.db.session() as session:
        db_user = await session.get(User, user.id)
        db_user.personal_chat_id = chat_id
        if tg_username and not db_user.telegram_username:
            db_user.telegram_username = tg_username
        await session.commit()
        await session.refresh(db_user)
    try:
        await rt.bot.send_text(chat_id, tr("✅ Бот привязан к OpsWatch. Уведомления будут приходить сюда."), token)
    except Exception:
        pass
    return user_dict(db_user)


@router.delete("/profile/personal-bot")
async def personal_bot_delete(user: User = Depends(current_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        db_user = await session.get(User, user.id)
        db_user.personal_bot_token = None
        db_user.personal_bot_username = ""
        db_user.personal_chat_id = None
        await session.commit()
        await session.refresh(db_user)
        return user_dict(db_user)


@router.get("/profile/subscriptions")
async def subscriptions(user: User = Depends(active_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        return {"items": await get_states(session, user)}


@router.put("/profile/subscriptions")
async def save_subscriptions(data: SubscriptionsIn, user: User = Depends(active_user), rt=Depends(get_rt)):
    async with rt.db.session() as session:
        for item in data.items:
            await set_state(session, user, item.category, item.mode, item.min_severity)
        await session.commit()
        return {"items": await get_states(session, user)}
