from __future__ import annotations

import io
import logging

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from opswatch.constants import CATEGORY_TITLES, SEVERITY_ICONS
from opswatch.core.render import esc, render_details, truncate
from opswatch.db import utcnow
from opswatch.i18n import current_language, default_language, language, tr
from opswatch.models import Event, Source, User
from opswatch.permissions import has_perm, visible_categories
from opswatch.services.bugs import create_bug, save_attachment
from opswatch.services.queries import event_for_user, open_counts, visible_events_query
from opswatch.services.subscriptions import cycle_state, get_states

log = logging.getLogger(__name__)

MODE_ICONS = {"rules": "▫️", "subscribed": "🔔", "muted": "🔕"}

HELP = (
    "<b>OpsWatch</b> — уведомления о мониторинге, базах данных, 1С и бэкапах.\n\n"
    "/status — сводка по открытым событиям\n"
    "/events — последние открытые события\n"
    "/subscribe — подписки на категории\n"
    "/bug текст — сообщить об ошибке (можно приложить скриншот с подписью /bug)\n"
    "/unlink — отвязать Telegram от аккаунта\n\n"
    "Кнопки под уведомлениями: «Принял», «Решено», «Подробнее»."
)


class BugForm(StatesGroup):
    text = State()


async def linked_user(rt, chat_id: int) -> User | None:
    async with rt.db.session() as session:
        return await session.scalar(select(User).where(User.telegram_chat_id == chat_id))


def subscriptions_keyboard(states: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for state in states:
        title = tr(CATEGORY_TITLES.get(state["category"], state["category"]))
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{MODE_ICONS[state['mode']]} {title}",
                    callback_data=f"sub:{state['category']}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


SUB_TEXT = (
    "<b>Подписки на категории</b>\n"
    "Нажимайте на категорию, чтобы переключить режим:\n"
    "▫️ — по правилам администратора\n"
    "🔔 — подписан на все события категории\n"
    "🔕 — отключено (кроме критичных по правилам)"
)


class LanguageMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        rt = data.get("rt")
        chat = data.get("event_chat")
        sender = data.get("event_from_user")
        lang = ""
        if rt is not None and chat is not None:
            async with rt.db.session() as session:
                lang = await session.scalar(select(User.language).where(User.telegram_chat_id == chat.id)) or ""
        if not lang and sender is not None and sender.language_code:
            lang = "ru" if sender.language_code.lower().startswith(("ru", "uk", "be", "kk")) else "en"
        with language(lang or default_language()):
            return await handler(event, data)


def build_router() -> Router:
    router = Router(name="opswatch")
    router.message.middleware(LanguageMiddleware())
    router.callback_query.middleware(LanguageMiddleware())

    @router.message(CommandStart())
    async def start(message: Message, command: CommandObject, rt) -> None:
        code = (command.args or "").strip().upper()
        if code:
            async with rt.db.session() as session:
                user = await session.scalar(select(User).where(User.telegram_link_code == code))
                if user is None or (user.telegram_link_expires and user.telegram_link_expires < utcnow()):
                    await message.answer(tr("Код привязки не найден или устарел. Получите новый код в профиле OpsWatch."))
                    return
                previous = (
                    await session.execute(select(User).where(User.telegram_chat_id == message.chat.id, User.id != user.id))
                ).scalars().all()
                for other in previous:
                    other.telegram_chat_id = None
                user.telegram_chat_id = message.chat.id
                if message.from_user and message.from_user.username:
                    user.telegram_username = message.from_user.username
                user.telegram_link_code = None
                user.telegram_link_expires = None
                await session.commit()
                name = user.full_name or user.username
                status = user.status
            text = tr("✅ Telegram привязан к аккаунту <b>{name}</b>.", name=esc(name))
            if status != "active":
                text += tr("\nУчётная запись ещё не подтверждена администратором — уведомления начнут приходить после подтверждения.")
            await message.answer(text + "\n\n" + tr(HELP))
            return
        user = await linked_user(rt, message.chat.id)
        if user is None:
            await message.answer(
                tr("👋 Это бот OpsWatch.\n\nЧтобы получать уведомления, откройте <b>Профиль</b> в OpsWatch и нажмите «Привязать Telegram». Затем перейдите по ссылке или отправьте сюда команду <code>/start КОД</code>.\n\nВаш chat id: <code>{id}</code>", id=message.chat.id)
            )
            return
        await message.answer(tr("Здравствуйте, {name}!", name=esc(user.full_name or user.username)) + "\n\n" + tr(HELP))

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(tr(HELP))

    @router.message(Command("unlink"))
    async def unlink(message: Message, rt) -> None:
        async with rt.db.session() as session:
            user = await session.scalar(select(User).where(User.telegram_chat_id == message.chat.id))
            if user is None:
                await message.answer(tr("Этот чат не привязан к аккаунту OpsWatch."))
                return
            user.telegram_chat_id = None
            await session.commit()
        await message.answer(tr("Telegram отвязан. Уведомления больше не будут приходить в этот чат."))

    @router.message(Command("status"))
    async def status(message: Message, rt) -> None:
        user = await linked_user(rt, message.chat.id)
        if user is None or user.status != "active":
            await message.answer(tr("Сначала привяжите подтверждённый аккаунт OpsWatch (/start)."))
            return
        async with rt.db.session() as session:
            counts = await open_counts(session, user)
            categories = visible_categories(user)
            failing = (
                await session.execute(select(Source.name).where(Source.status == "error", Source.category.in_(categories or ["-"])))
            ).scalars().all()
        lines = [tr("<b>Открытые события</b>")]
        total = 0
        for category in categories:
            bucket = counts.get(category, {})
            amount = sum(bucket.values())
            total += amount
            if amount:
                parts = " ".join(f"{SEVERITY_ICONS[s]}{bucket[s]}" for s in ("critical", "warning", "info") if bucket.get(s))
                lines.append(f"{tr(CATEGORY_TITLES[category])}: {parts}")
        if total == 0:
            lines.append(tr("Всё спокойно ✅"))
        if failing:
            lines.append(tr("\n<b>Недоступные источники</b>"))
            lines += [f"🔴 {esc(name)}" for name in failing[:15]]
        await message.answer("\n".join(lines))

    @router.message(Command("events"))
    async def events(message: Message, rt) -> None:
        user = await linked_user(rt, message.chat.id)
        if user is None or user.status != "active":
            await message.answer(tr("Сначала привяжите подтверждённый аккаунт OpsWatch (/start)."))
            return
        async with rt.db.session() as session:
            query = await visible_events_query(session, user)
            rows = (
                await session.execute(query.where(Event.status != "resolved").order_by(Event.last_seen_at.desc()).limit(10))
            ).scalars().all()
        if not rows:
            await message.answer(tr("Открытых событий нет ✅"))
            return
        lines = [tr("<b>Последние открытые события</b>")]
        for event in rows:
            lines.append(f"{SEVERITY_ICONS.get(event.severity, '⚪')} {esc(truncate(event.title, 90))} · #ev{event.id}")
        keyboard = [
            [InlineKeyboardButton(text=tr("#{id} подробнее", id=event.id), callback_data=f"ev:info:{event.id}")] for event in rows[:5]
        ]
        await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

    @router.message(Command("subscribe", "unsubscribe", "subscriptions"))
    async def subscriptions(message: Message, rt) -> None:
        user = await linked_user(rt, message.chat.id)
        if user is None or user.status != "active":
            await message.answer(tr("Сначала привяжите подтверждённый аккаунт OpsWatch (/start)."))
            return
        async with rt.db.session() as session:
            states = await get_states(session, user)
        if not states:
            await message.answer(tr("У вашей роли нет доступа к категориям событий."))
            return
        await message.answer(tr(SUB_TEXT), reply_markup=subscriptions_keyboard(states))

    @router.callback_query(F.data.startswith("sub:"))
    async def toggle_subscription(callback: CallbackQuery, rt) -> None:
        category = callback.data.split(":", 1)[1]
        async with rt.db.session() as session:
            user = await session.scalar(select(User).where(User.telegram_chat_id == callback.message.chat.id))
            if user is None or user.status != "active":
                await callback.answer(tr("Аккаунт не привязан"), show_alert=True)
                return
            mode = await cycle_state(session, user, category)
            await session.commit()
            states = await get_states(session, user)
        await callback.message.edit_reply_markup(reply_markup=subscriptions_keyboard(states))
        titles = {"rules": tr("по правилам"), "subscribed": tr("подписка включена"), "muted": tr("уведомления отключены")}
        await callback.answer(f"{tr(CATEGORY_TITLES.get(category, category))}: {titles[mode]}")

    async def _accept_bug(message: Message, rt, bot: Bot, text: str) -> None:
        user = await linked_user(rt, message.chat.id)
        allowed = user is not None and has_perm(user, "bugs.report")
        if not allowed and not rt.settings.get("bot_public_bugs"):
            await message.answer(tr("Отправлять баг-репорты могут только подтверждённые пользователи OpsWatch с правом «Отправка баг-репортов»."))
            return
        attachments = []
        try:
            if message.photo:
                photo = message.photo[-1]
                buffer = io.BytesIO()
                await bot.download(photo, destination=buffer)
                attachments.append(save_attachment(rt.config.attachments_dir, f"screenshot_{photo.file_unique_id}.jpg", buffer.getvalue(), "image/jpeg"))
            elif message.document:
                buffer = io.BytesIO()
                await bot.download(message.document, destination=buffer)
                attachments.append(
                    save_attachment(
                        rt.config.attachments_dir,
                        message.document.file_name or "file.bin",
                        buffer.getvalue(),
                        message.document.mime_type or "",
                    )
                )
        except ValueError as exc:
            await message.answer(tr("Вложение не принято: {error}", error=esc(exc)))
        except Exception:
            log.exception(tr("Не удалось скачать вложение"))
        sender = message.from_user
        label = (user.full_name or user.username) if user else (
            f"@{sender.username}" if sender and sender.username else (sender.full_name if sender else "Telegram")
        )
        event = await create_bug(
            rt.pipeline,
            title="",
            text=text,
            reporter=user if allowed else None,
            reporter_label=label,
            attachments=attachments,
            channel="telegram",
            extra={"telegram_chat": message.chat.id},
        )
        await message.answer(tr("🐞 Спасибо! Баг-репорт <b>#ev{id}</b> зарегистрирован и передан ответственным.", id=event.id))

    @router.message(Command("bug"))
    async def bug(message: Message, command: CommandObject, rt, bot: Bot, state: FSMContext) -> None:
        text = (command.args or "").strip()
        if not text:
            await state.set_state(BugForm.text)
            await message.answer(tr("Опишите проблему одним сообщением. Можно приложить скриншот с подписью. /cancel — отмена."))
            return
        await _accept_bug(message, rt, bot, text)

    @router.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(tr("Отменено."))

    @router.message(BugForm.text)
    async def bug_text(message: Message, rt, bot: Bot, state: FSMContext) -> None:
        text = (message.text or message.caption or "").strip()
        if not text and not message.photo and not message.document:
            await message.answer(tr("Нужен текст описания проблемы."))
            return
        await state.clear()
        await _accept_bug(message, rt, bot, text or tr("Скриншот без описания"))

    @router.callback_query(F.data.startswith("ev:"))
    async def event_action(callback: CallbackQuery, rt) -> None:
        try:
            _, action, raw_id = callback.data.split(":", 2)
            event_id = int(raw_id)
        except ValueError:
            await callback.answer()
            return
        async with rt.db.session() as session:
            user = await session.scalar(select(User).where(User.telegram_chat_id == callback.message.chat.id))
            if user is None or user.status != "active":
                await callback.answer(tr("Аккаунт не привязан или не подтверждён"), show_alert=True)
                return
            event = await event_for_user(session, event_id, user)
        if event is None:
            await callback.answer(tr("Событие недоступно"), show_alert=True)
            return
        if action == "info":
            await callback.message.answer(render_details(event, rt.settings.get("public_url") or "", current_language()))
            await callback.answer()
            return
        if not has_perm(user, "events.manage"):
            await callback.answer(tr("Недостаточно прав для изменения статуса"), show_alert=True)
            return
        if action == "ack":
            await rt.pipeline.ack(event_id, user)
            await callback.answer(tr("Принято в работу 👌"))
        elif action == "res":
            await rt.pipeline.resolve(event_id, user, tr("Закрыто через Telegram: {value}", value=user.full_name or user.username))
            await callback.answer(tr("Отмечено как решённое ✅"))
        else:
            await callback.answer()

    @router.message(F.text & ~F.text.startswith("/"))
    async def fallback(message: Message, rt) -> None:
        user = await linked_user(rt, message.chat.id)
        if user is None:
            await message.answer(tr("Отправьте /start, чтобы узнать, как привязать аккаунт."))
        else:
            await message.answer(tr("Не понял команду. /help — список команд, /bug текст — сообщить об ошибке."))

    return router
