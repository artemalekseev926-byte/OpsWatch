from __future__ import annotations

import asyncio
from datetime import datetime

from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from opswatch.core.events import EventIn
from opswatch.services.chat import mentions, reply_room
from tests.conftest import login, make_user
from tests.test_bot import setup


async def roles_by_name(client, admin) -> dict[str, int]:
    return {r["name"]: r["id"] for r in (await client.get("/api/roles", headers=admin)).json()["items"]}


async def rooms(client, headers) -> dict:
    return (await client.get("/api/chat/rooms", headers=headers)).json()


async def test_direct_chat_messages_and_unread(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    boris = await make_user(client, admin, "boris", "accountant")
    contacts = (await client.get("/api/chat/contacts", headers=anna["headers"])).json()["items"]
    assert {c["username"] for c in contacts} == {"admin1", "boris"}
    admin_id = next(c["id"] for c in contacts if c["username"] == "admin1")
    room = (await client.post("/api/chat/direct", json={"user_id": admin_id}, headers=anna["headers"])).json()
    again = (await client.post("/api/chat/direct", json={"user_id": admin_id}, headers=anna["headers"])).json()
    assert room["id"] == again["id"] and room["kind"] == "direct" and room["title"] == "Администратор"
    assert (await client.post("/api/chat/direct", json={"user_id": anna["id"]}, headers=anna["headers"])).status_code == 422
    sent = (await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "  Привет, сервер 1С тормозит  "}, headers=anna["headers"])).json()
    assert sent["text"] == "Привет, сервер 1С тормозит" and sent["author"] == "Anna"
    assert (await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "   "}, headers=anna["headers"])).status_code == 422
    listing = await rooms(client, admin)
    item = listing["items"][0]
    assert listing["unread"] == 1 and item["unread"] == 1 and item["title"] == "Anna" and item["last_message"]["text"] == sent["text"]
    assert (await rooms(client, anna["headers"]))["unread"] == 0
    history = (await client.get(f"/api/chat/rooms/{room['id']}/messages", headers=admin)).json()
    assert [m["text"] for m in history["items"]] == [sent["text"]] and not history["has_more"]
    read = (await client.post(f"/api/chat/rooms/{room['id']}/read", json={}, headers=admin)).json()
    assert read["unread"] == 0 and read["last_read_id"] == sent["id"]
    assert (await rooms(client, anna["headers"]))["items"][0]["peer_read_id"] == sent["id"]
    for path in (f"/api/chat/rooms/{room['id']}", f"/api/chat/rooms/{room['id']}/messages"):
        assert (await client.get(path, headers=boris["headers"])).status_code == 404
    assert (await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "x"}, headers=boris["headers"])).status_code == 404


async def test_group_by_roles_follows_role_changes(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    await make_user(client, admin, "boris", "accountant")
    group = (
        await client.post("/api/chat/rooms", json={"title": "Инфраструктура", "roles": ["sysadmin", "nope"], "sync_roles": True}, headers=admin)
    ).json()
    assert group["roles"] == ["sysadmin"] and group["can_manage"]
    members = {m["username"]: m for m in group["members"]}
    assert set(members) == {"admin1", "anna"} and members["anna"]["via_role"] == "sysadmin" and members["admin1"]["is_admin"]
    roles = await roles_by_name(client, admin)
    await client.post("/api/auth/register", json={"username": "viktor", "password": "secret1", "full_name": "Viktor"})
    viktor_id = next(u["id"] for u in (await client.get("/api/users", headers=admin)).json()["items"] if u["username"] == "viktor")
    await client.post(f"/api/users/{viktor_id}/approve", json={"role_id": roles["sysadmin"]}, headers=admin)
    detail = (await client.get(f"/api/chat/rooms/{group['id']}", headers=admin)).json()
    assert "viktor" in {m["username"] for m in detail["members"]}
    await client.put(f"/api/users/{viktor_id}", json={"role_id": roles["accountant"]}, headers=admin)
    detail = (await client.get(f"/api/chat/rooms/{group['id']}", headers=admin)).json()
    assert "viktor" not in {m["username"] for m in detail["members"]}
    history = (await client.get(f"/api/chat/rooms/{group['id']}/messages", headers=admin)).json()["items"]
    codes = [m["data"].get("code") for m in history if m["kind"] == "system"]
    assert codes == ["created", "added", "auto_added", "auto_removed"]
    updated = (await client.put(f"/api/chat/rooms/{group['id']}", json={"roles": ["sysadmin", "accountant"]}, headers=admin)).json()
    assert {m["username"] for m in updated["members"]} == {"admin1", "anna", "boris", "viktor"}
    updated = (await client.put(f"/api/chat/rooms/{group['id']}", json={"roles": ["sysadmin"]}, headers=admin)).json()
    assert {m["username"] for m in updated["members"]} == {"admin1", "anna"}
    frozen = (await client.put(f"/api/chat/rooms/{group['id']}", json={"sync_roles": False, "roles": ["accountant"]}, headers=admin)).json()
    assert frozen["roles"] == [] and {m["username"] for m in frozen["members"]} == {"admin1", "anna", "boris", "viktor"}
    assert all(m["via_role"] == "" for m in frozen["members"])
    await client.put(f"/api/users/{anna['id']}", json={"role_id": roles["accountant"]}, headers=admin)
    detail = (await client.get(f"/api/chat/rooms/{group['id']}", headers=admin)).json()
    assert "anna" in {m["username"] for m in detail["members"]}


async def test_group_management_permissions(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    boris = await make_user(client, admin, "boris", "accountant")
    group = (await client.post("/api/chat/rooms", json={"title": "Склад", "user_ids": [anna["id"], 999]}, headers=anna["headers"])).json()
    assert {m["username"] for m in group["members"]} == {"anna"}
    assert (await client.post("/api/chat/rooms", json={"title": "  "}, headers=anna["headers"])).status_code == 422
    group = (await client.post(f"/api/chat/rooms/{group['id']}/members", json={"user_ids": [boris["id"]], "roles": ["admin"]}, headers=anna["headers"])).json()
    assert {m["username"] for m in group["members"]} == {"anna", "boris", "admin1"}
    gid = group["id"]
    assert (await client.put(f"/api/chat/rooms/{gid}", json={"title": "Взлом"}, headers=boris["headers"])).status_code == 403
    assert (await client.delete(f"/api/chat/rooms/{gid}/members/{anna['id']}", headers=boris["headers"])).status_code == 403
    renamed = (await client.put(f"/api/chat/rooms/{gid}", json={"title": "Склад и логистика"}, headers=anna["headers"])).json()
    assert renamed["title"] == "Склад и логистика"
    assert (await client.put(f"/api/chat/rooms/{gid}/members/{anna['id']}", json={"is_admin": False}, headers=anna["headers"])).status_code == 422
    promoted = (await client.put(f"/api/chat/rooms/{gid}/members/{boris['id']}", json={"is_admin": True}, headers=anna["headers"])).json()
    assert {m["username"] for m in promoted["members"] if m["is_admin"]} == {"anna", "boris"}
    left = (await client.delete(f"/api/chat/rooms/{gid}/members/{anna['id']}", headers=anna["headers"])).json()
    assert left["left"]
    assert (await client.get(f"/api/chat/rooms/{gid}", headers=anna["headers"])).status_code == 404
    after = (await client.get(f"/api/chat/rooms/{gid}", headers=boris["headers"])).json()
    assert after["can_manage"] and {m["username"] for m in after["members"]} == {"boris", "admin1"}
    assert (await client.put(f"/api/chat/rooms/{gid}/members/{boris['id']}", json={"is_admin": False}, headers=boris["headers"])).status_code == 422
    await client.delete(f"/api/chat/rooms/{gid}/members/{boris['id']}", headers=boris["headers"])
    detail = (await client.get(f"/api/chat/rooms/{gid}", headers=admin)).json()
    assert [m["username"] for m in detail["members"] if m["is_admin"]] == ["admin1"]
    assert (await client.delete(f"/api/chat/rooms/{gid}", headers=admin)).json()["ok"]
    assert (await client.get(f"/api/chat/rooms/{gid}", headers=admin)).status_code == 404


async def test_edit_and_delete_messages(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    group = (await client.post("/api/chat/rooms", json={"title": "Дежурные", "user_ids": [anna["id"]]}, headers=admin)).json()
    message = (await client.post(f"/api/chat/rooms/{group['id']}/messages", json={"text": "Перезагружаю srv-1c"}, headers=anna["headers"])).json()
    edited = (await client.put(f"/api/chat/messages/{message['id']}", json={"text": "Перезагружаю srv-1c в 22:00"}, headers=anna["headers"])).json()
    assert edited["text"].endswith("22:00") and edited["edited_at"]
    assert (await client.put(f"/api/chat/messages/{message['id']}", json={"text": "чужое"}, headers=admin)).status_code == 403
    deleted = (await client.delete(f"/api/chat/messages/{message['id']}", headers=admin)).json()
    assert deleted["deleted"] and deleted["text"] == ""
    system = next(m for m in (await client.get(f"/api/chat/rooms/{group['id']}/messages", headers=admin)).json()["items"] if m["kind"] == "system")
    assert (await client.delete(f"/api/chat/messages/{system['id']}", headers=admin)).status_code == 403


async def test_long_poll_updates(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    room = (await client.post("/api/chat/direct", json={"user_id": anna["id"]}, headers=admin)).json()
    state = await rooms(client, anna["headers"])
    waiting = asyncio.create_task(
        client.get(f"/api/chat/updates?after={state['last_id']}&rev={state['rev']}&timeout=10", headers=anna["headers"])
    )
    await asyncio.sleep(0.2)
    assert not waiting.done()
    await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "Ты на месте?"}, headers=admin)
    data = (await asyncio.wait_for(waiting, 5)).json()
    assert [m["text"] for m in data["messages"]] == ["Ты на месте?"] and data["unread"] == 1
    quick = (await client.get(f"/api/chat/updates?after={data['last_id']}&rev={data['rev']}&timeout=0", headers=anna["headers"])).json()
    assert quick["messages"] == [] and quick["rev"] == data["rev"]
    waiting = asyncio.create_task(client.get(f"/api/chat/updates?after={data['last_id']}&rev={data['rev']}&timeout=10", headers=anna["headers"]))
    await asyncio.sleep(0.2)
    await client.post("/api/chat/rooms", json={"title": "Новая", "user_ids": [anna["id"]]}, headers=admin)
    changed = (await asyncio.wait_for(waiting, 5)).json()
    assert changed["rev"] != data["rev"]


async def test_long_poll_ends_on_shutdown(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    state = await rooms(client, anna["headers"])
    waiting = asyncio.create_task(client.get(f"/api/chat/updates?after={state['last_id']}&rev={state['rev']}&timeout=20", headers=anna["headers"]))
    await asyncio.sleep(0.2)
    rt.chat.close()
    assert (await asyncio.wait_for(waiting, 3)).status_code == 200


async def test_share_event_into_chat(rt, client, admin):
    anna = await make_user(client, admin, "anna", "accountant")
    room = (await client.post("/api/chat/direct", json={"user_id": anna["id"]}, headers=admin)).json()
    event = await rt.pipeline.ingest(EventIn(title="Диск D заполнен", severity="critical", category="monitoring", source_name="zbx"))
    shared = (await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "Посмотри", "event_id": event.id}, headers=admin)).json()
    assert shared["kind"] == "event" and shared["data"]["event"]["title"] == "Диск D заполнен" and shared["event_id"] == event.id
    hidden = (await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"event_id": event.id}, headers=anna["headers"]))
    assert hidden.status_code == 404


async def test_telegram_forward_for_offline_users(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin", chat_id=111, rt=rt)
    boris = await make_user(client, admin, "boris", "sysadmin", chat_id=222, rt=rt)
    room = (await client.post("/api/chat/direct", json={"user_id": anna["id"]}, headers=admin)).json()
    rt.chat.hub.seen.clear()
    await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "Срочно позвони"}, headers=admin)
    await rt.chat.flush()
    forwarded = [m for m in rt.bot.sent if m["chat_id"] == 111]
    assert len(forwarded) == 1 and "Срочно позвони" in forwarded[0]["text"] and f"#c{room['id']}" in forwarded[0]["text"]
    await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "Ещё раз"}, headers=admin)
    await rt.chat.flush()
    assert len([m for m in rt.bot.sent if m["chat_id"] == 111]) == 1
    rt.chat._forwarded.clear()
    rt.chat.hub.touch(anna["id"])
    await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "Видишь?"}, headers=admin)
    await rt.chat.flush()
    assert len([m for m in rt.bot.sent if m["chat_id"] == 111]) == 1
    group = (await client.post("/api/chat/rooms", json={"title": "Смена", "user_ids": [anna["id"], boris["id"]]}, headers=admin)).json()
    rt.chat.hub.seen.clear()
    await client.post(f"/api/chat/rooms/{group['id']}/messages", json={"text": "@boris проверь бэкап"}, headers=admin)
    await rt.chat.flush()
    assert [m for m in rt.bot.sent if m["chat_id"] == 222] and len([m for m in rt.bot.sent if m["chat_id"] == 111]) == 1
    await client.put("/api/profile", json={"chat_telegram": False}, headers=boris["headers"])
    rt.chat._forwarded.clear()
    rt.chat.hub.seen.clear()
    await client.post(f"/api/chat/rooms/{group['id']}/messages", json={"text": "@boris ещё"}, headers=admin)
    await rt.chat.flush()
    assert len([m for m in rt.bot.sent if m["chat_id"] == 222]) == 1


async def test_reply_from_telegram(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin", chat_id=100, rt=rt)
    room = (await client.post("/api/chat/direct", json={"user_id": anna["id"]}, headers=admin)).json()
    bot, dispatcher, session = setup(rt)
    sender = TgUser(id=100, is_bot=False, first_name="Anna")
    original = Message(message_id=5, date=datetime.now(), chat=Chat(id=100, type="private"), text=f"💬 Администратор\nПозвони\n\nОтветьте #c{room['id']}")
    update = Update(
        update_id=10,
        message=Message(message_id=6, date=datetime.now(), chat=Chat(id=100, type="private"), from_user=sender, text="Уже еду", reply_to_message=original),
    )
    await dispatcher.feed_update(bot, update)
    assert "Отправлено" in session.texts()[-1]
    history = (await client.get(f"/api/chat/rooms/{room['id']}/messages", headers=admin)).json()["items"]
    assert history[-1]["text"] == "Уже еду" and history[-1]["author"] == "Anna" and history[-1]["data"]["via"] == "telegram"
    stranger = Update(
        update_id=11,
        message=Message(message_id=7, date=datetime.now(), chat=Chat(id=555, type="private"), from_user=TgUser(id=555, is_bot=False, first_name="X"), text="hi", reply_to_message=original),
    )
    await dispatcher.feed_update(bot, stranger)
    assert "/start" in session.texts()[-1]


async def test_desktop_poll_and_mute(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    room = (await client.post("/api/chat/direct", json={"user_id": anna["id"]}, headers=admin)).json()
    base = (await client.get("/api/notifications/poll?chat_after=-1", headers=anna["headers"])).json()["chat"]
    assert base["enabled"] and base["items"] == []
    await client.post(f"/api/chat/rooms/{room['id']}/messages", json={"text": "Обед в 13:00"}, headers=admin)
    chat = (await client.get(f"/api/notifications/poll?chat_after={base['last_id']}", headers=anna["headers"])).json()["chat"]
    assert chat["unread"] == 1 and chat["items"][0]["title"] == "Администратор" and chat["items"][0]["body"] == "Обед в 13:00"
    await client.put(f"/api/chat/rooms/{room['id']}/mute", json={"muted": True}, headers=anna["headers"])
    chat = (await client.get(f"/api/notifications/poll?chat_after={base['last_id']}", headers=anna["headers"])).json()["chat"]
    assert chat["items"] == [] and chat["unread"] == 0


async def test_chat_can_be_disabled(rt, client, admin):
    anna = await make_user(client, admin, "anna", "sysadmin")
    await client.put("/api/settings", json={"chat_enabled": False}, headers=admin)
    assert (await client.get("/api/meta", headers=anna["headers"])).json()["chat_enabled"] is False
    assert (await client.get("/api/chat/rooms", headers=anna["headers"])).status_code == 403
    assert (await client.get("/api/notifications/poll", headers=anna["headers"])).json()["chat"]["enabled"] is False
    pending = await client.post("/api/auth/register", json={"username": "petr", "password": "secret1"})
    assert pending.status_code == 200
    headers = await login(client, "petr", "secret1")
    await client.put("/api/settings", json={"chat_enabled": True}, headers=admin)
    assert (await client.get("/api/chat/rooms", headers=headers)).status_code == 403


def test_helpers():
    assert mentions("@Anna, @boris.k и mail@site.ru") == {"anna", "boris.k"}
    assert reply_room("текст\n#c42") == 42 and reply_room("без тега") is None


class FakeResponse:
    status_code = 200

    def __init__(self, data: dict) -> None:
        self.data = data

    def json(self) -> dict:
        return self.data


def test_desktop_agent_shows_chat_messages(monkeypatch):
    from opswatch.desktop import launcher

    responses = [
        {"items": [], "last_id": 5, "desktop": True, "chat": {"last_id": 10, "items": []}},
        {
            "items": [{"title": "Диск заполнен", "body": "D: 95%"}],
            "last_id": 6,
            "desktop": True,
            "chat": {"last_id": 12, "items": [{"title": "Anna", "body": "Позвони", "room_id": 1}]},
        },
    ]
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr(launcher.httpx, "get", fake_get)
    agent = launcher.DesktopAgent(lambda title, body: None)
    agent.set_session("http://server", "token", True)
    assert agent.poll_once() == []
    items = agent.poll_once()
    assert calls == [{"after": -1, "chat_after": -1}, {"after": 5, "chat_after": 10}]
    assert items == [{"title": "Диск заполнен", "body": "D: 95%"}, {"title": "💬 Anna", "body": "Позвони"}]
    assert agent.chat_last_id == 12
