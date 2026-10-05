from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Привязка аккаунта и справка"),
    BotCommand(command="status", description="Сводка по открытым событиям"),
    BotCommand(command="events", description="Последние открытые события"),
    BotCommand(command="subscribe", description="Подписки на категории"),
    BotCommand(command="unsubscribe", description="Отписаться от категорий"),
    BotCommand(command="bug", description="Сообщить об ошибке (можно со скриншотом)"),
    BotCommand(command="unlink", description="Отвязать Telegram от аккаунта"),
    BotCommand(command="help", description="Справка"),
]

UPLOAD_TIMEOUT = 1800


def markup(keyboard: list[list[dict[str, str]]] | None) -> InlineKeyboardMarkup | None:
    if not keyboard:
        return None
    rows = []
    for row in keyboard:
        buttons = []
        for button in row:
            if button.get("url"):
                buttons.append(InlineKeyboardButton(text=button["text"], url=button["url"]))
            else:
                buttons.append(InlineKeyboardButton(text=button["text"], callback_data=button.get("data", "noop")))
        if buttons:
            rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _defaults() -> DefaultBotProperties:
    return DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)


async def _retry(call, *args, **kwargs):
    for attempt in range(3):
        try:
            return await call(*args, **kwargs)
        except TelegramRetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(exc.retry_after + 0.5)


class BotManager:
    def __init__(self, runtime) -> None:
        self.rt = runtime
        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self.username: str = ""
        self.status: str = "disabled"
        self.error: str = ""
        self._task: asyncio.Task | None = None
        self._personal: dict[str, Bot] = {}
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self.bot is not None and self.status == "running"

    def info(self) -> dict[str, Any]:
        return {"status": self.status, "username": self.username, "error": self.error}

    def _session(self, api_url: str = "") -> AiohttpSession:
        if api_url:
            return AiohttpSession(api=TelegramAPIServer.from_base(api_url.rstrip("/"), is_local=True), timeout=120)
        return AiohttpSession(timeout=120)

    async def start(self) -> None:
        async with self._lock:
            await self._stop()
            token = (self.rt.settings.get("telegram_token") or "").strip()
            if not token:
                self.status = "disabled"
                self.error = ""
                return
            api_url = (self.rt.settings.get("telegram_api_url") or "").strip()
            bot = Bot(token=token, session=self._session(api_url), default=_defaults())
            try:
                me = await bot.get_me()
            except Exception as exc:
                await bot.session.close()
                self.status = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                log.error("Telegram-бот не запущен: %s", self.error)
                return
            from opswatch.bot.handlers import build_router

            dispatcher = Dispatcher(storage=MemoryStorage())
            dispatcher["rt"] = self.rt
            dispatcher.include_router(build_router())
            try:
                await bot.set_my_commands(COMMANDS)
            except Exception:
                log.debug("set_my_commands failed", exc_info=True)
            self.bot = bot
            self.dispatcher = dispatcher
            self.username = me.username or ""
            self.status = "running"
            self.error = ""
            self._task = asyncio.create_task(
                dispatcher.start_polling(
                    bot,
                    handle_signals=False,
                    close_bot_session=False,
                    allowed_updates=["message", "callback_query"],
                ),
                name="opswatch-bot",
            )
            log.info("Telegram-бот @%s запущен", self.username)

    async def _stop(self) -> None:
        if self.dispatcher is not None and self._task is not None:
            try:
                await self.dispatcher.stop_polling()
            except RuntimeError:
                pass
            try:
                await asyncio.wait_for(self._task, timeout=15)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._task.cancel()
        if self.bot is not None:
            try:
                await self.bot.session.close()
            except Exception:
                pass
        self.bot = None
        self.dispatcher = None
        self._task = None
        self.status = "disabled"

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()
        for bot in self._personal.values():
            try:
                await bot.session.close()
            except Exception:
                pass
        self._personal.clear()

    def personal_bot(self, token: str) -> Bot:
        bot = self._personal.get(token)
        if bot is None:
            bot = Bot(token=token, session=AiohttpSession(timeout=120), default=_defaults())
            self._personal[token] = bot
        return bot

    def _target(self, personal_token: str | None) -> Bot:
        if personal_token:
            return self.personal_bot(personal_token)
        if not self.available:
            raise RuntimeError("Telegram-бот не настроен")
        return self.bot

    async def send(self, chat_id: int, text: str, keyboard=None, silent: bool = False, reply_to: int | None = None) -> int:
        bot = self._target(None)
        reply = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
        message = await _retry(
            bot.send_message,
            chat_id=chat_id,
            text=text,
            reply_markup=markup(keyboard),
            disable_notification=silent,
            reply_parameters=reply,
        )
        return message.message_id

    async def send_personal(
        self, token: str, chat_id: int, text: str, keyboard=None, silent: bool = False, reply_to: int | None = None
    ) -> int:
        bot = self.personal_bot(token)
        reply = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
        message = await _retry(
            bot.send_message,
            chat_id=chat_id,
            text=text,
            reply_markup=markup(keyboard),
            disable_notification=silent,
            reply_parameters=reply,
        )
        return message.message_id

    async def _edit(self, bot: Bot, chat_id: int, message_id: int, text: str, keyboard) -> None:
        try:
            await _retry(
                bot.edit_message_text,
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup(keyboard),
            )
        except TelegramBadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise

    async def edit(self, chat_id: int, message_id: int, text: str, keyboard=None) -> None:
        await self._edit(self._target(None), chat_id, message_id, text, keyboard)

    async def edit_personal(self, token: str, chat_id: int, message_id: int, text: str, keyboard=None) -> None:
        await self._edit(self.personal_bot(token), chat_id, message_id, text, keyboard)

    async def send_text(self, chat_id: int, text: str, personal_token: str | None = None) -> int:
        bot = self._target(personal_token)
        message = await _retry(bot.send_message, chat_id=chat_id, text=text)
        return message.message_id

    async def send_file(self, chat_id: int, path: Path, caption: str = "", personal_token: str | None = None) -> int:
        bot = self._target(personal_token)
        message = await _retry(
            bot.send_document,
            chat_id=chat_id,
            document=FSInputFile(str(path), filename=Path(path).name),
            caption=caption[:1024] if caption else None,
            request_timeout=UPLOAD_TIMEOUT,
        )
        return message.message_id

    async def validate_personal(self, token: str) -> str:
        bot = Bot(token=token, session=AiohttpSession(timeout=30), default=_defaults())
        try:
            me = await bot.get_me()
            return me.username or ""
        finally:
            await bot.session.close()

    async def detect_personal_chat(self, token: str) -> tuple[int, str] | None:
        bot = self.personal_bot(token)
        updates = await bot.get_updates(limit=50, timeout=0, allowed_updates=["message"])
        for update in reversed(updates):
            message = update.message
            if message and message.chat and message.chat.type == "private":
                if updates:
                    try:
                        await bot.get_updates(offset=updates[-1].update_id + 1, limit=1, timeout=0)
                    except Exception:
                        pass
                return message.chat.id, (message.from_user.username if message.from_user else "") or ""
        return None
