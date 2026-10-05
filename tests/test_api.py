from sqlalchemy import select

from opswatch.models import Source, User
from tests.conftest import drain, login, make_user


async def test_health_and_index(client):
    assert (await client.get("/api/health")).json()["status"] == "ok"
    index = await client.get("/")
    assert index.status_code == 200 and "app.js" in index.text
    assert (await client.get("/static/app.js")).status_code == 200


async def test_default_admin_login_and_wrong_password(client):
    headers = await login(client, "admin1", "admin1")
    me = (await client.get("/api/auth/me", headers=headers)).json()
    assert me["is_superuser"] and "users.manage" in me["permissions"]
    bad = await client.post("/api/auth/login", json={"username": "admin1", "password": "nope"})
    assert bad.status_code == 401


async def test_login_throttling(client):
    for _ in range(5):
        await client.post("/api/auth/login", json={"username": "admin1", "password": "bad"})
    locked = await client.post("/api/auth/login", json={"username": "admin1", "password": "admin1"})
    assert locked.status_code == 429


async def test_registration_requires_approval(rt, client, admin):
    response = await client.post("/api/auth/register", json={"username": "ivan", "password": "secret1", "full_name": "Иван"})
    assert response.json()["status"] == "pending"
    duplicate = await client.post("/api/auth/register", json={"username": "IVAN", "password": "secret1"})
    assert duplicate.status_code == 409
    headers = await login(client, "ivan", "secret1")
    me = (await client.get("/api/auth/me", headers=headers)).json()
    assert me["status"] == "pending" and me["permissions"] == []
    assert (await client.get("/api/events", headers=headers)).status_code == 403
    assert (await client.post("/api/profile/telegram/link", headers=headers)).status_code == 200
    events = (await client.get("/api/events?category=system", headers=admin)).json()["items"]
    assert any("ожидает подтверждения" in e["title"] for e in events)
    users = (await client.get("/api/users", headers=admin)).json()["items"]
    assert users[0]["username"] == "ivan" and users[0]["status"] == "pending"


async def test_registration_can_be_disabled(client, admin):
    await client.put("/api/settings", json={"registration_enabled": False}, headers=admin)
    response = await client.post("/api/auth/register", json={"username": "petr", "password": "secret1"})
    assert response.status_code == 403
    meta = (await client.get("/api/meta")).json()
    assert meta["registration_enabled"] is False


async def test_permissions_restrict_tabs_and_admin_api(rt, client, admin):
    accountant = await make_user(client, admin, "buh", "accountant")
    me = (await client.get("/api/auth/me", headers=accountant["headers"])).json()
    assert set(me["permissions"]) == {"onec.view", "bugs.report"}
    for path in ("/api/users", "/api/rules", "/api/settings", "/api/backups/jobs"):
        assert (await client.get(path, headers=accountant["headers"])).status_code == 403
    assert (await client.post("/api/sources", json={"name": "x", "type": "webhook"}, headers=accountant["headers"])).status_code == 403
    dashboard = (await client.get("/api/dashboard", headers=accountant["headers"])).json()
    assert list(dashboard["categories"]) == ["onec"]


async def test_superuser_cannot_be_blocked_or_deleted(client, admin):
    me = (await client.get("/api/auth/me", headers=admin)).json()
    other = await make_user(client, admin, "second", "admin")
    assert (await client.put(f"/api/users/{me['id']}", json={"status": "blocked"}, headers=other["headers"])).status_code == 403
    assert (await client.delete(f"/api/users/{me['id']}", headers=other["headers"])).status_code == 403


async def test_blocked_user_loses_access(client, admin):
    user = await make_user(client, admin, "temp", "sysadmin")
    await client.put(f"/api/users/{user['id']}", json={"status": "blocked"}, headers=admin)
    assert (await client.get("/api/auth/me", headers=user["headers"])).status_code == 401
    assert (await client.post("/api/auth/login", json={"username": "temp", "password": "secret1"})).status_code == 403


async def test_profile_update_and_password_change(client, admin):
    user = await make_user(client, admin, "anna", "admin1c")
    response = await client.put(
        "/api/profile",
        json={"full_name": "Анна", "telegram_username": "@anna", "notify_desktop": True, "quiet_start": "22:00", "quiet_end": "08:00"},
        headers=user["headers"],
    )
    data = response.json()
    assert data["telegram_username"] == "anna" and data["notify_desktop"] and data["quiet_start"] == "22:00"
    bad = await client.put("/api/profile", json={"quiet_start": "25:99"}, headers=user["headers"])
    assert bad.status_code == 422
    wrong = await client.post("/api/profile/password", json={"current": "x", "new": "newpass1"}, headers=user["headers"])
    assert wrong.status_code == 400
    ok = await client.post("/api/profile/password", json={"current": "secret1", "new": "newpass1"}, headers=user["headers"])
    assert ok.status_code == 200
    await login(client, "anna", "newpass1")


async def test_telegram_link_code_and_test_message(rt, client, admin):
    response = await client.post("/api/profile/telegram/link", headers=admin)
    data = response.json()
    assert len(data["code"]) == 8
    assert data["deep_link"].endswith("?start=" + data["code"])
    async with rt.db.session() as session:
        user = await session.scalar(select(User).where(User.telegram_link_code == data["code"]))
        assert user is not None
        user.telegram_chat_id = 555
        await session.commit()
    me = (await client.get("/api/auth/me", headers=admin)).json()
    assert me["telegram_linked"]
    assert (await client.post("/api/profile/telegram/test", headers=admin)).status_code == 200
    assert rt.bot.texts[-1]["chat_id"] == 555
    unlinked = (await client.delete("/api/profile/telegram", headers=admin)).json()
    assert not unlinked["telegram_linked"]


async def test_sources_crud_masks_secrets(rt, client, admin):
    meta = (await client.get("/api/meta", headers=admin)).json()
    assert {c["type"] for c in meta["connectors"]} >= {"mysql", "postgresql", "mssql", "onec_file", "onec_server", "zabbix_webhook"}
    payload = {"name": "PG", "type": "postgresql", "config": {"host": "db", "database": "erp", "user": "reader", "password": "topsecret"}}
    created = (await client.post("/api/sources", json=payload, headers=admin)).json()
    assert created["config"]["password"] == "••••••••"
    async with rt.db.session() as session:
        source = await session.get(Source, created["id"])
        assert "topsecret" not in source.secrets and "password" not in source.config
        assert rt.crypto.decrypt_json(source.secrets)["password"] == "topsecret"
    payload["config"]["password"] = "••••••••"
    payload["config"]["host"] = "db2"
    updated = (await client.put(f"/api/sources/{created['id']}", json=payload, headers=admin)).json()
    assert updated["config"]["host"] == "db2"
    async with rt.db.session() as session:
        source = await session.get(Source, created["id"])
        assert rt.crypto.decrypt_json(source.secrets)["password"] == "topsecret"
    missing = await client.post("/api/sources", json={"name": "x", "type": "postgresql", "config": {}}, headers=admin)
    assert missing.status_code == 422
    assert (await client.delete(f"/api/sources/{created['id']}", headers=admin)).status_code == 200


async def test_source_test_reports_errors(client, admin):
    response = await client.post(
        "/api/sources/test",
        json={"type": "postgresql", "config": {"host": "127.0.0.1", "port": 1, "database": "x", "timeout": 3}},
        headers=admin,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


async def test_webhook_ingest_and_auto_resolve(rt, client, admin):
    zabbix = (await client.post("/api/sources", json={"name": "Zabbix", "type": "zabbix_webhook"}, headers=admin)).json()
    assert zabbix["ingest_path"].startswith("/api/ingest/")
    problem = {"event_id": "9", "event_value": "1", "severity": "Disaster", "host": "sql", "trigger_name": "MSSQL stopped"}
    result = (await client.post(zabbix["ingest_path"], json=problem)).json()
    assert result["accepted"] == 1
    event_id = result["events"][0]
    recovery = dict(problem, event_value="0")
    await client.post(zabbix["ingest_path"], json=recovery)
    event = (await client.get(f"/api/events/{event_id}", headers=admin)).json()
    assert event["status"] == "resolved" and event["severity"] == "critical"
    assert (await client.post("/api/ingest/wrong-token", json=problem)).status_code == 404
    hook = (await client.post("/api/sources", json={"name": "Kassa", "type": "webhook", "category": "bug"}, headers=admin)).json()
    raw = await client.post(hook["ingest_path"], content="просто текст ошибки")
    assert raw.json()["accepted"] == 1
    bugs = (await client.get("/api/events?category=bug", headers=admin)).json()["items"]
    assert bugs[0]["title"] == "просто текст ошибки"


async def test_alertmanager_ingest(client, admin):
    source = (await client.post("/api/sources", json={"name": "AM", "type": "alertmanager"}, headers=admin)).json()
    payload = {"alerts": [{"status": "firing", "labels": {"alertname": "Up", "severity": "critical", "instance": "n1"}, "annotations": {"summary": "down"}, "fingerprint": "a"}]}
    result = (await client.post(source["ingest_path"], json=payload)).json()
    assert result["accepted"] == 1
    payload["alerts"][0]["status"] = "resolved"
    await client.post(source["ingest_path"], json=payload)
    event = (await client.get(f"/api/events/{result['events'][0]}", headers=admin)).json()
    assert event["status"] == "resolved"


async def test_bug_report_with_attachment(rt, client, admin):
    user = await make_user(client, admin, "buh", "accountant")
    files = [("files", ("screen.png", b"\x89PNG\r\n\x1a\nfake", "image/png"))]
    response = await client.post("/api/bugs", data={"title": "Не проводится документ", "text": "Ошибка", "severity": "warning"}, files=files, headers=user["headers"])
    assert response.status_code == 200, response.text
    bug = response.json()
    assert bug["category"] == "bug" and bug["attachments"][0]["filename"] == "screen.png"
    mine = (await client.get("/api/bugs/mine", headers=user["headers"])).json()["items"]
    assert mine[0]["id"] == bug["id"]
    file = await client.get(bug["attachments"][0]["url"], headers=user["headers"])
    assert file.status_code == 200 and file.content.startswith(b"\x89PNG")
    assert (await client.get(f"/api/events/{bug['id']}", headers=user["headers"])).status_code == 404
    admin_view = await client.get(f"/api/events/{bug['id']}", headers=admin)
    assert admin_view.json()["reporter"] == "Buh"
    bad = await client.post("/api/bugs", data={"title": "x"}, files=[("files", ("run.exe", b"MZ", "application/octet-stream"))], headers=user["headers"])
    assert bad.status_code == 422


async def test_event_resolve_via_api(rt, client, admin):
    from opswatch.core.events import EventIn

    event = await rt.pipeline.ingest(EventIn(title="x", severity="critical", category="monitoring"))
    response = await client.post(f"/api/events/{event.id}/resolve", json={"note": "Перезапустили службу"}, headers=admin)
    data = response.json()
    assert data["status"] == "resolved" and data["resolution"] == "Перезапустили службу"
    assert data["resolved_by"] == "Администратор"
    listed = (await client.get("/api/events?status=open", headers=admin)).json()["items"]
    assert all(item["id"] != event.id for item in listed)


async def test_rules_and_roles_crud(client, admin):
    rule = {"name": "SQL → сисадмины", "categories": ["database"], "min_severity": "critical", "target_roles": ["sysadmin"], "escalate_after_min": 5, "escalate_roles": ["admin"]}
    created = (await client.post("/api/rules", json=rule, headers=admin)).json()
    assert created["escalate_after_min"] == 5
    bad = await client.post("/api/rules", json={**rule, "min_severity": "huge"}, headers=admin)
    assert bad.status_code == 422
    assert (await client.delete(f"/api/rules/{created['id']}", headers=admin)).status_code == 200
    role = (await client.post("/api/roles", json={"name": "support", "title": "Поддержка", "permissions": ["bugs.view", "nonsense"]}, headers=admin)).json()
    assert role["permissions"] == ["bugs.view"]
    roles = (await client.get("/api/roles", headers=admin)).json()["items"]
    admin_role = next(r for r in roles if r["name"] == "admin")
    assert (await client.put(f"/api/roles/{admin_role['id']}", json={"name": "admin", "title": "x", "permissions": []}, headers=admin)).status_code == 403
    assert (await client.delete(f"/api/roles/{admin_role['id']}", headers=admin)).status_code == 403
    assert (await client.delete(f"/api/roles/{role['id']}", headers=admin)).status_code == 200


async def test_settings_hide_secrets(client, admin):
    response = await client.put("/api/settings", json={"s3_secret_key": "hidden", "group_window_min": "15"}, headers=admin)
    values = response.json()["values"]
    assert values["s3_secret_key"] == "••••••••"
    assert values["group_window_min"] == 15


async def test_notifications_read_and_poll(rt, client, admin):
    from opswatch.core.events import EventIn

    first = (await client.get("/api/notifications/poll", headers=admin)).json()
    assert first["items"] == []
    await rt.pipeline.ingest(EventIn(title="new one", severity="critical", category="monitoring"))
    await drain(rt)
    poll = (await client.get(f"/api/notifications/poll?after={first['last_id']}", headers=admin)).json()
    assert poll["items"] and poll["items"][-1]["title"] == "new one"
    assert poll["unread"] >= 1 and poll["open"]["monitoring"]["critical"] >= 1
    await client.post("/api/notifications/read", json={"all": True}, headers=admin)
    assert (await client.get("/api/notifications", headers=admin)).json()["unread"] == 0
