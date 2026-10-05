from opswatch.core.events import EventIn
from opswatch.core.render import default_template, render_notification, render_template, sample_event, validate_template
from tests.conftest import drain, make_user


def test_render_template_hides_empty_lines():
    text = render_template("<b>{title}</b>\n{message}\n<i>{source}</i>\nfixed {unknown}", {"title": "A", "message": "", "source": ""})
    assert text == "<b>A</b>\nfixed {unknown}"


def test_values_are_escaped():
    event = sample_event()
    event.title = "<script>x</script> & co"
    text = render_notification(event, "event", template="{title}")
    assert text == "&lt;script&gt;x&lt;/script&gt; &amp; co"


def test_validate_template():
    assert validate_template(default_template("event")) == []
    assert any("Незакрытые" in p for p in validate_template("<b>{title}"))
    assert any("Недопустимые" in p for p in validate_template("<div>{title}</div>"))
    assert any("Неизвестные" in p for p in validate_template("{nope}"))


def test_english_defaults():
    event = sample_event()
    assert "CRITICAL" in render_notification(event, "event", lang="en")
    assert "ESCALATION" in render_notification(event, "escalation", lang="en")


async def test_templates_api_and_delivery(rt, client, admin):
    data = (await client.get("/api/settings/templates", headers=admin)).json()
    assert data["kinds"] == ["event", "repeat", "escalation", "resolved"]
    assert not data["templates"]["ru"]["event"]["custom"]
    bad = await client.put("/api/settings/templates", json={"lang": "ru", "kind": "event", "value": "<b>{title}"}, headers=admin)
    assert bad.status_code == 422
    preview = (await client.post("/api/settings/templates/preview", json={"lang": "ru", "kind": "event", "value": "🚨 {title} [{count}]"}, headers=admin)).json()
    assert preview["text"].startswith("🚨 Ошибки в очереди заданий") and preview["problems"] == []
    saved = (await client.put("/api/settings/templates", json={"lang": "ru", "kind": "event", "value": "🚨 <b>{title}</b>\n{source}"}, headers=admin)).json()
    assert saved["templates"]["ru"]["event"]["custom"]
    await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    await rt.pipeline.ingest(EventIn(title="Диск заполнен", severity="critical", category="monitoring", source_name="zbx"))
    await drain(rt)
    sent = [m for m in rt.bot.sent if m["chat_id"] == 111]
    assert sent[-1]["text"] == "🚨 <b>Диск заполнен</b>\nzbx"
    reset = (await client.put("/api/settings/templates", json={"lang": "ru", "kind": "event", "value": ""}, headers=admin)).json()
    assert not reset["templates"]["ru"]["event"]["custom"]
    assert (await client.post("/api/settings/templates/test", json={"lang": "ru", "kind": "event", "value": ""}, headers=admin)).status_code == 400


async def test_rejected_template_falls_back_to_default(rt, client, admin):
    original = rt.bot.send

    async def picky(chat_id, text, keyboard=None, silent=False, reply_to=None):
        if "BROKEN" in text:
            raise RuntimeError("Bad Request: can't parse entities")
        return await original(chat_id, text, keyboard, silent, reply_to)

    rt.bot.send = picky
    await rt.settings.update({"template_event_ru": "BROKEN {title}"})
    await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    await rt.pipeline.ingest(EventIn(title="Сбой", severity="critical", category="monitoring", source_name="x"))
    await drain(rt)
    sent = [m for m in rt.bot.sent if m["chat_id"] == 111]
    assert sent and "КРИТИЧНО" in sent[-1]["text"] and "BROKEN" not in sent[-1]["text"]
