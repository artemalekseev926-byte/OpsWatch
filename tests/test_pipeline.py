from datetime import timedelta

from sqlalchemy import select

from opswatch.core.events import EventIn
from opswatch.core.router import in_quiet_hours, rule_matches
from opswatch.models import Event, Notification, Rule, Source, User
from tests.conftest import drain, make_user


async def test_rule_matching():
    rule = Rule(name="r", enabled=True, categories=["database"], source_ids=[], event_types=["check.*"], min_severity="warning")
    event = Event(category="database", type="check.threshold", severity="critical", source_id=1)
    assert rule_matches(rule, event)
    event.type = "source.down"
    assert not rule_matches(rule, event)
    event.type = "check.rows"
    event.severity = "info"
    assert not rule_matches(rule, event)
    rule.enabled = False
    event.severity = "critical"
    assert not rule_matches(rule, event)


def test_quiet_hours_over_midnight():
    from datetime import datetime

    user = User(quiet_start="23:00", quiet_end="07:00")
    assert in_quiet_hours(user, datetime(2026, 1, 1, 23, 30))
    assert in_quiet_hours(user, datetime(2026, 1, 1, 6, 59))
    assert not in_quiet_hours(user, datetime(2026, 1, 1, 12, 0))
    assert not in_quiet_hours(User(quiet_start="", quiet_end=""), datetime(2026, 1, 1, 0, 0))


async def test_ingest_routes_by_rules_and_permissions(rt, client, admin):
    sys_user = await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    acc_user = await make_user(client, admin, "acc", "accountant", chat_id=222, rt=rt)
    rt.bot.sent.clear()
    event = await rt.pipeline.ingest(EventIn(title="srv: диск", severity="critical", category="monitoring", source_name="zbx"))
    await drain(rt)
    async with rt.db.session() as session:
        recipients = set((await session.execute(select(Notification.user_id).where(Notification.event_id == event.id))).scalars())
    assert sys_user["id"] in recipients
    assert acc_user["id"] not in recipients
    chats = {m["chat_id"] for m in rt.bot.sent}
    assert 111 in chats and 222 not in chats
    message = next(m for m in rt.bot.sent if m["chat_id"] == 111)
    assert "Критично".upper() in message["text"]
    labels = [b["text"] for b in message["keyboard"][0]]
    assert any("Принял" in t for t in labels) and any("Решено" in t for t in labels) and any("Подробнее" in t for t in labels)


async def test_grouping_and_repeat_notifications(rt, client, admin):
    await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    data = EventIn(title="Повтор", severity="warning", category="monitoring", source_name="x")
    first = await rt.pipeline.ingest(data)
    second = await rt.pipeline.ingest(data)
    await drain(rt)
    assert first.id == second.id
    assert second.count == 2
    async with rt.db.session() as session:
        count = len((await session.execute(select(Notification).where(Notification.event_id == first.id))).scalars().all())
        stored = await session.get(Event, first.id)
        stored.notified_at = stored.notified_at - timedelta(hours=1)
        await session.commit()
    third = await rt.pipeline.ingest(data)
    await drain(rt)
    async with rt.db.session() as session:
        rows = (await session.execute(select(Notification).where(Notification.event_id == first.id))).scalars().all()
    assert third.count == 3
    assert len(rows) > count
    assert any(n.kind == "repeat" for n in rows)


async def test_auto_resolve_notifies_previous_recipients(rt, client, admin):
    await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    created = await rt.pipeline.ingest(EventIn(title="down", severity="critical", category="monitoring", source_name="s", external_id="e1"))
    await drain(rt)
    resolved = await rt.pipeline.ingest(EventIn(title="down", category="monitoring", source_name="s", external_id="e1", resolve=True))
    await drain(rt)
    assert resolved is not None and resolved.id == created.id
    async with rt.db.session() as session:
        event = await session.get(Event, created.id)
        kinds = (await session.execute(select(Notification.kind).where(Notification.event_id == created.id))).scalars().all()
    assert event.status == "resolved"
    assert "resolved" in kinds
    assert any("Решено" in m["text"] and m["reply_to"] for m in rt.bot.sent)


async def test_muted_subscription_and_opt_in(rt, client, admin):
    sys_user = await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    manager = await make_user(client, admin, "boss", "manager", chat_id=333, rt=rt)
    await client.put(
        "/api/profile/subscriptions",
        json={"items": [{"category": "monitoring", "mode": "muted"}]},
        headers=sys_user["headers"],
    )
    await client.put(
        "/api/profile/subscriptions",
        json={"items": [{"category": "monitoring", "mode": "subscribed", "min_severity": "info"}]},
        headers=manager["headers"],
    )
    event = await rt.pipeline.ingest(EventIn(title="info", severity="warning", category="monitoring", source_name="x"))
    async with rt.db.session() as session:
        users = set((await session.execute(select(Notification.user_id).where(Notification.event_id == event.id))).scalars())
    assert sys_user["id"] not in users
    assert manager["id"] in users
    critical = await rt.pipeline.ingest(EventIn(title="crit", severity="critical", category="monitoring", source_name="x"))
    async with rt.db.session() as session:
        users = set((await session.execute(select(Notification.user_id).where(Notification.event_id == critical.id))).scalars())
    assert sys_user["id"] in users


async def test_source_visibility_limits_recipients(rt, client, admin):
    sys_user = await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    async with rt.db.session() as session:
        source = Source(name="secret", type="webhook", category="monitoring", visible_roles=["admin"])
        session.add(source)
        await session.commit()
        source_id = source.id
    event = await rt.pipeline.ingest(EventIn(title="hidden", severity="critical", category="monitoring", source_id=source_id, source_name="secret"))
    async with rt.db.session() as session:
        users = set((await session.execute(select(Notification.user_id).where(Notification.event_id == event.id))).scalars())
    assert sys_user["id"] not in users
    response = await client.get("/api/events", headers=sys_user["headers"])
    assert all(item["id"] != event.id for item in response.json()["items"])
    response = await client.get("/api/events", headers=admin)
    assert any(item["id"] == event.id for item in response.json()["items"])


async def test_escalation_after_timeout(rt, client, admin):
    await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    boss = await make_user(client, admin, "boss", "manager", chat_id=333, rt=rt)
    event = await rt.pipeline.ingest(EventIn(title="db down", severity="critical", category="database", source_name="pg"))
    assert event.escalation and event.escalation[0]["after"] == 15
    assert await rt.pipeline.run_escalations() == 0
    async with rt.db.session() as session:
        stored = await session.get(Event, event.id)
        stored.created_at = stored.created_at - timedelta(minutes=20)
        await session.commit()
    assert await rt.pipeline.run_escalations() == 1
    await drain(rt)
    async with rt.db.session() as session:
        rows = (await session.execute(select(Notification).where(Notification.event_id == event.id, Notification.kind == "escalation"))).scalars().all()
        refreshed = await session.get(Event, event.id)
    assert boss["id"] in {n.user_id for n in rows}
    assert refreshed.escalation_level == 1
    assert await rt.pipeline.run_escalations() == 0
    assert any("ЭСКАЛАЦИЯ" in m["text"] for m in rt.bot.sent if m["chat_id"] == 333)


async def test_ack_stops_escalation_and_updates_messages(rt, client, admin):
    sys_user = await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    event = await rt.pipeline.ingest(EventIn(title="db down", severity="critical", category="database", source_name="pg"))
    await drain(rt)
    response = await client.post(f"/api/events/{event.id}/ack", headers=sys_user["headers"])
    assert response.status_code == 200 and response.json()["status"] == "acked"
    await drain(rt)
    assert rt.bot.edits and "Принято" in rt.bot.edits[-1]["text"]
    async with rt.db.session() as session:
        stored = await session.get(Event, event.id)
        stored.created_at = stored.created_at - timedelta(hours=1)
        await session.commit()
    assert await rt.pipeline.run_escalations() == 0


async def test_quiet_hours_send_silently(rt, client, admin):
    user = await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    async with rt.db.session() as session:
        db_user = await session.get(User, user["id"])
        db_user.quiet_start = "00:00"
        db_user.quiet_end = "23:59"
        await session.commit()
    await rt.pipeline.ingest(EventIn(title="warn", severity="warning", category="monitoring", source_name="x"))
    await rt.pipeline.ingest(EventIn(title="crit", severity="critical", category="monitoring", source_name="x"))
    await drain(rt)
    sent = {m["text"].split("\n")[1]: m["silent"] for m in rt.bot.sent if m["chat_id"] == 111}
    assert any(silent for title, silent in sent.items() if "warn" in title)
    assert not any(silent for title, silent in sent.items() if "crit" in title)


async def test_user_without_telegram_gets_inbox_only(rt, client, admin):
    user = await make_user(client, admin, "sys", "sysadmin")
    await rt.pipeline.ingest(EventIn(title="x", severity="critical", category="monitoring", source_name="x"))
    await drain(rt)
    response = await client.get("/api/notifications", headers=user["headers"])
    items = response.json()["items"]
    assert items and items[0]["telegram_status"] == "no_chat"
    poll = await client.get("/api/notifications/poll?after=0", headers=user["headers"])
    assert poll.json()["last_id"] == items[0]["id"]
    assert poll.json()["items"][0]["id"] == items[0]["id"]
