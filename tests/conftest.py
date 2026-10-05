from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from opswatch.config import AppConfig
from opswatch.models import User
from opswatch.runtime import Runtime
from opswatch.web.app import create_app


class FakeBot:
    def __init__(self) -> None:
        self.available = True
        self.username = "opswatch_test_bot"
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self.texts: list[dict] = []
        self.files: list[dict] = []

    def info(self) -> dict:
        return {"status": "running", "username": self.username, "error": ""}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, chat_id, text, keyboard=None, silent=False, reply_to=None) -> int:
        self.sent.append({"chat_id": chat_id, "text": text, "keyboard": keyboard, "silent": silent, "reply_to": reply_to})
        return 1000 + len(self.sent)

    async def send_personal(self, token, chat_id, text, keyboard=None, silent=False, reply_to=None) -> int:
        self.sent.append({"chat_id": chat_id, "text": text, "keyboard": keyboard, "silent": silent, "reply_to": reply_to, "token": token})
        return 2000 + len(self.sent)

    async def edit(self, chat_id, message_id, text, keyboard=None) -> None:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text, "keyboard": keyboard})

    async def edit_personal(self, token, chat_id, message_id, text, keyboard=None) -> None:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text, "token": token})

    async def send_text(self, chat_id, text, personal_token=None) -> int:
        self.texts.append({"chat_id": chat_id, "text": text, "token": personal_token})
        return 3000 + len(self.texts)

    async def send_file(self, chat_id, path, caption="", personal_token=None) -> int:
        path = Path(path)
        self.files.append({"chat_id": chat_id, "name": path.name, "size": path.stat().st_size, "caption": caption})
        return 4000 + len(self.files)


TEST_DATABASE_URL = os.environ.get("OPSWATCH_TEST_DATABASE_URL", "")


async def reset_database(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture
async def rt(tmp_path):
    config = AppConfig(data_dir=tmp_path / "data", plugins_dir=tmp_path / "plugins")
    if TEST_DATABASE_URL:
        await reset_database(TEST_DATABASE_URL)
        config.database_url = TEST_DATABASE_URL
    config.prepare()
    runtime = Runtime(config, start_bot=False, start_scheduler=False)
    runtime.bot = FakeBot()
    await runtime.start()
    yield runtime
    await runtime.stop()


@pytest.fixture
async def client(rt):
    app = create_app(rt)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


async def login(client, username: str, password: str) -> dict:
    response = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.fixture
async def admin(client) -> dict:
    return await login(client, "admin1", "admin1")


async def drain(rt) -> None:
    await asyncio.wait_for(rt.notifier.queue.join(), timeout=10)


async def make_user(client, admin_headers, username: str, role: str, chat_id: int | None = None, rt=None) -> dict:
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": "secret1", "full_name": username.title()}
    )
    assert response.status_code == 200, response.text
    users = (await client.get("/api/users", headers=admin_headers)).json()["items"]
    roles = {r["name"]: r["id"] for r in (await client.get("/api/roles", headers=admin_headers)).json()["items"]}
    user = next(u for u in users if u["username"] == username)
    response = await client.post(f"/api/users/{user['id']}/approve", json={"role_id": roles[role]}, headers=admin_headers)
    assert response.status_code == 200, response.text
    if chat_id is not None and rt is not None:
        async with rt.db.session() as session:
            db_user = await session.get(User, user["id"])
            db_user.telegram_chat_id = chat_id
            await session.commit()
    headers = await login(client, username, "secret1")
    return {"id": user["id"], "headers": headers}
