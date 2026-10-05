from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from opswatch.core.render import event_keyboard, link_keyboard, render_notification
from opswatch.core.router import in_quiet_hours
from opswatch.db import Database
from opswatch.i18n import ts
from opswatch.models import Event, Notification, User

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, db: Database, settings, crypto, bot_provider) -> None:
        self.db = db
        self.settings = settings
        self.crypto = crypto
        self.bot_provider = bot_provider
        self.queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def submit(self, notification_ids: list[int]) -> None:
        for notification_id in notification_ids:
            self.queue.put_nowait(("send", notification_id))

    def submit_update(self, event_id: int) -> None:
        self.queue.put_nowait(("update", event_id))

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._worker(), name="opswatch-notifier")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def drain(self) -> None:
        while not self.queue.empty():
            action, item_id = self.queue.get_nowait()
            await self._handle(action, item_id)
            self.queue.task_done()

    async def _worker(self) -> None:
        while True:
            action, item_id = await self.queue.get()
            try:
                await self._handle(action, item_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(ts("Ошибка доставки уведомления %s %s"), action, item_id)
            finally:
                self.queue.task_done()

    async def _handle(self, action: str, item_id: int) -> None:
        if action == "send":
            await self._send(item_id)
        elif action == "update":
            await self._update(item_id)

    def render(
        self,
        event: Event,
        kind: str,
        acked: str,
        resolved: str,
        lang: str,
        public_url: str,
        use_custom: bool = True,
    ) -> str:
        template = self.settings.get(f"template_{kind}_{lang}") if use_custom else ""
        return render_notification(event, kind, acked, resolved, lang, template or "", public_url)

    async def _names(self, session, event: Event) -> tuple[str, str]:
        acked = resolved = ""
        if event.acked_by_id:
            user = await session.get(User, event.acked_by_id)
            acked = (user.full_name or user.username) if user else ""
        if event.resolved_by_id:
            user = await session.get(User, event.resolved_by_id)
            resolved = (user.full_name or user.username) if user else ""
        return acked, resolved

    async def _send(self, notification_id: int) -> None:
        bot = self.bot_provider()
        async with self.db.session() as session:
            notification = await session.get(Notification, notification_id)
            if notification is None:
                return
            user = await session.get(User, notification.user_id)
            event = await session.get(Event, notification.event_id) if notification.event_id else None
            if user is None or event is None:
                notification.telegram_status = "skipped"
                await session.commit()
                return
            if not user.notify_telegram:
                notification.telegram_status = "disabled"
                await session.commit()
                return
            personal_token = self.crypto.decrypt(user.personal_bot_token or "")
            use_personal = bool(personal_token and user.personal_chat_id)
            if not use_personal and (bot is None or not bot.available or not user.telegram_chat_id):
                notification.telegram_status = "no_chat"
                await session.commit()
                return
            acked, resolved = await self._names(session, event)
            lang = user.language or "ru"
            public_url = self.settings.get("public_url") or ""
            text = self.render(event, notification.kind, acked, resolved, lang, public_url)
            fallback = self.render(event, notification.kind, acked, resolved, lang, public_url, use_custom=False)
            keyboard = [] if notification.kind == "resolved" else event_keyboard(event, lang)
            silent = in_quiet_hours(user) and notification.severity != "critical"
            reply_to = None
            chat_id = user.personal_chat_id if use_personal else user.telegram_chat_id
            if notification.kind in {"resolved", "repeat", "escalation"}:
                reply_to = await session.scalar(
                    select(Notification.telegram_message_id)
                    .where(
                        Notification.event_id == event.id,
                        Notification.user_id == user.id,
                        Notification.telegram_chat_id == chat_id,
                        Notification.telegram_message_id.is_not(None),
                        Notification.kind == "event",
                    )
                    .order_by(Notification.id)
                    .limit(1)
                )
            async def deliver(body: str) -> int:
                if use_personal:
                    return await bot.send_personal(
                        personal_token,
                        chat_id,
                        body,
                        keyboard=link_keyboard(public_url, event, lang) if notification.kind != "resolved" else [],
                        silent=silent,
                        reply_to=reply_to,
                    )
                return await bot.send(chat_id, body, keyboard=keyboard, silent=silent, reply_to=reply_to)

            try:
                try:
                    message_id = await deliver(text)
                except Exception as exc:
                    if text == fallback or "parse" not in str(exc).lower():
                        raise
                    log.warning(ts("Шаблон уведомления не принят Telegram, отправляю стандартный: %s"), exc)
                    message_id = await deliver(fallback)
                notification.telegram_status = "sent"
                notification.telegram_chat_id = chat_id
                notification.telegram_message_id = message_id
                notification.telegram_via_personal = use_personal
            except Exception as exc:
                log.warning(ts("Не удалось отправить уведомление пользователю %s: %s"), user.username, exc)
                notification.telegram_status = "failed"
            await session.commit()

    async def _update(self, event_id: int) -> None:
        bot = self.bot_provider()
        if bot is None:
            return
        async with self.db.session() as session:
            event = await session.get(Event, event_id)
            if event is None:
                return
            acked, resolved = await self._names(session, event)
            rows = (
                await session.execute(
                    select(Notification).where(
                        Notification.event_id == event_id,
                        Notification.telegram_message_id.is_not(None),
                        Notification.kind.in_(["event", "repeat", "escalation"]),
                    )
                )
            ).scalars().all()
            public_url = self.settings.get("public_url") or ""
            for notification in rows:
                user = await session.get(User, notification.user_id)
                lang = (user.language if user else "") or "ru"
                text = self.render(event, notification.kind, acked, resolved, lang, public_url)
                try:
                    if notification.telegram_via_personal:
                        token = self.crypto.decrypt(user.personal_bot_token or "") if user else ""
                        if token:
                            await bot.edit_personal(
                                token,
                                notification.telegram_chat_id,
                                notification.telegram_message_id,
                                text,
                                keyboard=link_keyboard(public_url, event, lang),
                            )
                    elif bot.available:
                        await bot.edit(
                            notification.telegram_chat_id,
                            notification.telegram_message_id,
                            text,
                            keyboard=event_keyboard(event, lang),
                        )
                except Exception as exc:
                    log.debug(ts("Не удалось обновить сообщение %s: %s"), notification.telegram_message_id, exc)
