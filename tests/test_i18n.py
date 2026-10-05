from __future__ import annotations

import re
import sys

import pytest
from sqlalchemy import select

from opswatch.config import AppConfig
from opswatch.core.events import EventIn
from opswatch.core.render import render_notification, sample_event
from opswatch.i18n import catalog, set_default_language, system_language, tr, ts
from opswatch.models import User
from opswatch.runtime import Runtime
from opswatch.sizes import human_size
from tests.conftest import FakeBot, drain, make_user
from tests.i18n_keys import all_keys, load_catalog, placeholders

CYR = re.compile(r"[А-Яа-яЁё]")


def test_catalog_is_complete():
    keys = all_keys()
    english = load_catalog("en")
    assert sorted(keys - set(english)) == []
    assert sorted(set(english) - keys) == []


def test_catalog_values_match_keys():
    for key, value in load_catalog("en").items():
        assert value.strip(), key
        assert placeholders(key) == placeholders(value), key
        assert key.count("%s") == value.count("%s"), key
        assert key.count("\n") == value.count("\n"), key
        assert key.startswith(" ") == value.startswith(" "), key
        assert key.endswith(" ") == value.endswith(" "), key
        if key != "Русский":
            assert not CYR.search(value), key


def test_translation_helpers():
    assert tr("Сохранено", "en") == "Saved"
    assert tr("Сохранено", "ru") == "Сохранено"
    assert tr("Источников: {n}", "en", n=3) == "Sources: 3"
    assert tr("Нет такой строки {x}", "en", x=1) == "Нет такой строки 1"
    assert catalog("ru") == {}
    try:
        set_default_language("en")
        assert ts("Бэкапы") == "Backups"
        assert human_size(512) == "512 B"
        assert human_size(5 * 1024 * 1024) == "5.0 MB"
        assert human_size(3 * 1024**5) == "3072.0 TB"
    finally:
        set_default_language("ru")
    assert human_size(2048) == "2.0 КБ"


def test_english_notification():
    event = sample_event("en")
    text = render_notification(event, "event", lang="en")
    assert "CRITICAL" in text and "Errors in the job queue" in text
    assert not CYR.search(text)


async def test_api_language(client, admin):
    meta = (await client.get("/api/meta", headers={**admin, "X-Lang": "en"})).json()
    assert meta["language"] == "en"
    assert {c["title"] for c in meta["categories"]} >= {"Databases", "Backups"}
    meta_ru = (await client.get("/api/meta", headers={**admin, "Accept-Language": "ru-RU,ru;q=0.9"})).json()
    assert "Бэкапы" in {c["title"] for c in meta_ru["categories"]}
    meta_accept = (await client.get("/api/meta", headers={**admin, "Accept-Language": "en-US,en;q=0.9"})).json()
    assert meta_accept["language"] == "en"
    bad = await client.post("/api/auth/login", json={"username": "admin1", "password": "wrong"}, headers={"X-Lang": "en"})
    assert bad.json()["detail"] == "Invalid login or password"
    titles = {item["type"]: item for item in meta["connectors"]}
    assert titles["onec_cluster"]["title"] == "1C: server cluster (RAS)"
    assert all(not CYR.search(field["label"]) for item in meta["connectors"] for field in item["fields"])
    locales = await client.get("/locales.js")
    assert locales.status_code == 200 and "window.OW_LOCALES" in locales.text


async def test_user_language_for_notifications(rt, client, admin):
    user = await make_user(client, admin, "eng", "sysadmin", chat_id=222, rt=rt)
    response = await client.put("/api/profile", json={"language": "en"}, headers=user["headers"])
    assert response.json()["language"] == "en"
    assert (await client.put("/api/profile", json={"language": "xx"}, headers=user["headers"])).status_code == 422
    await rt.pipeline.ingest(EventIn(title="Disk full", severity="critical", category="monitoring", source_name="zbx"))
    await drain(rt)
    sent = [m for m in rt.bot.sent if m["chat_id"] == 222]
    assert sent and "CRITICAL" in sent[-1]["text"]
    buttons = [button["text"] for row in sent[-1]["keyboard"] for button in row]
    assert "👌 Acknowledge" in buttons and "ℹ️ Details" in buttons


async def test_system_language_setting(rt, client, admin):
    try:
        settings = (await client.put("/api/settings", json={"language": "en"}, headers=admin)).json()
        assert settings["values"]["language"] == "en"
        await client.post("/api/auth/register", json={"username": "newbie", "password": "secret1", "full_name": "New Bie"})
        events = (await client.get("/api/events", headers=admin)).json()["items"]
        assert any(e["title"] == "New user awaiting approval: New Bie" for e in events)
        settings = (await client.put("/api/settings", json={"language": "zz"}, headers=admin)).json()
        assert settings["values"]["language"] == "ru"
    finally:
        set_default_language("ru")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX locale variables")
@pytest.mark.parametrize(
    ("env", "expected"),
    [({}, "ru"), ({"LANG": "C.UTF-8"}, "ru"), ({"LANG": "en_US.UTF-8"}, "en"), ({"LC_ALL": "ru_RU.UTF-8", "LANG": "en_US.UTF-8"}, "ru"), ({"OPSWATCH_LANGUAGE": "en", "LANG": "ru_RU.UTF-8"}, "en")],
)
def test_system_language(monkeypatch, env, expected):
    for key in ("OPSWATCH_LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert system_language() == expected


async def test_default_admin_follows_system_language(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSWATCH_LANGUAGE", "en")
    config = AppConfig(data_dir=tmp_path / "data", plugins_dir=tmp_path / "plugins")
    config.prepare()
    runtime = Runtime(config, start_bot=False, start_scheduler=False)
    runtime.bot = FakeBot()
    await runtime.start()
    try:
        async with runtime.db.session() as session:
            admin = await session.scalar(select(User).where(User.username == "admin1"))
        assert admin.language == "en" and admin.full_name == "Administrator"
        assert runtime.settings.get("language") == "en"
    finally:
        await runtime.stop()
        set_default_language("ru")
