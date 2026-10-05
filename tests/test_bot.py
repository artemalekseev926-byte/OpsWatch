from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, GetMe, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import select

from opswatch.bot.handlers import build_router
from opswatch.core.events import EventIn
from opswatch.models import Event, User
from tests.conftest import login, make_user


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests = []

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, GetMe):
            return TgUser(id=42, is_bot=True, first_name="OpsWatch", username="opswatch_test_bot")
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True

    async def close(self) -> None:
        return None

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""

    def texts(self) -> list[str]:
        return [r.text for r in self.requests if isinstance(r, SendMessage)]


def setup(rt):
    session = RecordingSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["rt"] = rt
    dispatcher.include_router(build_router())
    return bot, dispatcher, session


def message(text: str, chat_id: int = 100, update_id: int = 1) -> Update:
    sender = TgUser(id=chat_id, is_bot=False, first_name="Anna", username="anna_tg")
    return Update(
        update_id=update_id,
        message=Message(message_id=update_id, date=datetime.now(), chat=Chat(id=chat_id, type="private"), from_user=sender, text=text),
    )


def callback(data: str, chat_id: int = 100, update_id: int = 50) -> Update:
    sender = TgUser(id=chat_id, is_bot=False, first_name="Anna")
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=sender,
            chat_instance="x",
            data=data,
            message=Message(message_id=7, date=datetime.now(), chat=Chat(id=chat_id, type="private"), text="msg"),
        ),
    )


async def test_link_account_with_code(rt, client, admin):
    user = await make_user(client, admin, "anna", "sysadmin")
    code = (await client.post("/api/profile/telegram/link", headers=user["headers"])).json()["code"]
    bot, dispatcher, session = setup(rt)
    await dispatcher.feed_update(bot, message("/start WRONG123"))
    assert "не найден" in session.texts()[-1]
    await dispatcher.feed_update(bot, message(f"/start {code}", update_id=2))
    assert "привязан" in session.texts()[-1]
    async with rt.db.session() as db:
        linked = await db.get(User, user["id"])
    assert linked.telegram_chat_id == 100 and linked.telegram_username == "anna_tg" and linked.telegram_link_code is None


async def test_status_bug_and_buttons(rt, client, admin):
    user = await make_user(client, admin, "anna", "sysadmin", chat_id=100, rt=rt)
    bot, dispatcher, session = setup(rt)
    event = await rt.pipeline.ingest(EventIn(title="SQL down", severity="critical", category="database", source_name="pg"))
    await dispatcher.feed_update(bot, message("/status"))
    assert "Базы данных" in session.texts()[-1]
    await dispatcher.feed_update(bot, message("/events", update_id=3))
    assert "SQL down" in session.texts()[-1]
    await dispatcher.feed_update(bot, callback(f"ev:info:{event.id}"))
    assert "SQL down" in session.texts()[-1]
    await dispatcher.feed_update(bot, callback(f"ev:ack:{event.id}", update_id=51))
    async with rt.db.session() as db:
        assert (await db.get(Event, event.id)).status == "acked"
    await dispatcher.feed_update(bot, callback(f"ev:res:{event.id}", update_id=52))
    async with rt.db.session() as db:
        stored = await db.get(Event, event.id)
    assert stored.status == "resolved" and stored.resolved_by_id == user["id"]
    await dispatcher.feed_update(bot, message("/bug Не печатается счёт в 1С", update_id=4))
    assert "Баг-репорт" in session.texts()[-1]
    async with rt.db.session() as db:
        bug = await db.scalar(select(Event).where(Event.category == "bug"))
    assert bug.title == "Не печатается счёт в 1С" and bug.reporter_id == user["id"]


async def test_bug_dialog_and_unknown_user(rt, client, admin):
    await make_user(client, admin, "anna", "accountant", chat_id=100, rt=rt)
    bot, dispatcher, session = setup(rt)
    await dispatcher.feed_update(bot, message("/bug"))
    assert "Опишите проблему" in session.texts()[-1]
    await dispatcher.feed_update(bot, message("Программа зависает при закрытии месяца", update_id=2))
    assert "зарегистрирован" in session.texts()[-1]
    await dispatcher.feed_update(bot, message("/bug спам", chat_id=999, update_id=3))
    assert "только подтверждённые" in session.texts()[-1]
    await dispatcher.feed_update(bot, callback("ev:ack:1", chat_id=999))
    answers = [r for r in session.requests if isinstance(r, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert


async def test_subscriptions_toggle(rt, client, admin):
    await make_user(client, admin, "anna", "admin1c", chat_id=100, rt=rt)
    bot, dispatcher, session = setup(rt)
    await dispatcher.feed_update(bot, message("/subscribe"))
    markup = session.requests[-1].reply_markup
    categories = [row[0].callback_data for row in markup.inline_keyboard]
    assert "sub:onec" in categories and "sub:monitoring" not in categories
    await dispatcher.feed_update(bot, callback("sub:onec"))
    response = await client.get("/api/profile/subscriptions", headers=await login(client, "anna", "secret1"))
    modes = {item["category"]: item["mode"] for item in response.json()["items"]}
    assert modes["onec"] == "subscribed"

