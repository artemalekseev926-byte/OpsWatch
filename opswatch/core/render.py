from __future__ import annotations

import html
from typing import Any

from opswatch.constants import CATEGORY_TITLES, EVENT_STATUS_TITLES, SEVERITY_ICONS, SEVERITY_TITLES
from opswatch.db import to_local
from opswatch.models import Event

Keyboard = list[list[dict[str, str]]]


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fmt_time(value) -> str:
    local = to_local(value)
    return local.strftime("%d.%m.%Y %H:%M") if local else ""


def render_event(
    event: Event,
    kind: str = "event",
    acked_by: str = "",
    resolved_by: str = "",
) -> str:
    icon = SEVERITY_ICONS.get(event.severity, "⚪")
    head = f"{icon} <b>{esc(SEVERITY_TITLES.get(event.severity, event.severity).upper())}</b> · {esc(CATEGORY_TITLES.get(event.category, event.category))}"
    lines = []
    if kind == "escalation":
        lines.append("⏫ <b>ЭСКАЛАЦИЯ: событие не подтверждено</b>")
    elif kind == "repeat":
        lines.append(f"🔁 <b>Повторяется ({event.count} раз)</b>")
    lines.append(head)
    lines.append(f"<b>{esc(truncate(event.title, 300))}</b>")
    if event.message:
        lines.append(esc(truncate(event.message, 1800)))
    meta = []
    if event.source_name:
        meta.append(f"Источник: {esc(event.source_name)}")
    meta.append(fmt_time(event.created_at))
    if event.count > 1:
        meta.append(f"Повторов: {event.count}")
    lines.append("<i>" + " · ".join(meta) + "</i>")
    if event.status == "acked":
        lines.append(f"✅ Принято{': ' + esc(acked_by) if acked_by else ''}")
    elif event.status == "resolved":
        lines.append(f"☑️ Решено{': ' + esc(resolved_by) if resolved_by else ''}")
    lines.append(f"#ev{event.id}")
    return truncate("\n".join(lines), 4000)


def render_resolved(event: Event, by: str = "") -> str:
    lines = [
        "✅ <b>Решено</b> · " + esc(CATEGORY_TITLES.get(event.category, event.category)),
        f"<b>{esc(truncate(event.title, 300))}</b>",
    ]
    if event.resolution:
        lines.append(esc(truncate(event.resolution, 1000)))
    meta = []
    if by:
        meta.append(f"Закрыл: {esc(by)}")
    meta.append(fmt_time(event.resolved_at))
    lines.append("<i>" + " · ".join(meta) + "</i>")
    lines.append(f"#ev{event.id}")
    return "\n".join(lines)


def render_details(event: Event, public_url: str = "") -> str:
    lines = [
        f"{SEVERITY_ICONS.get(event.severity, '⚪')} <b>{esc(event.title)}</b>",
        f"Категория: {esc(CATEGORY_TITLES.get(event.category, event.category))}",
        f"Важность: {esc(SEVERITY_TITLES.get(event.severity, event.severity))}",
        f"Статус: {esc(EVENT_STATUS_TITLES.get(event.status, event.status))}",
        f"Тип: <code>{esc(event.type)}</code>",
    ]
    if event.source_name:
        lines.append(f"Источник: {esc(event.source_name)}")
    lines.append(f"Впервые: {fmt_time(event.created_at)}")
    lines.append(f"Последний раз: {fmt_time(event.last_seen_at)}")
    lines.append(f"Повторов: {event.count}")
    if event.message:
        lines.append("")
        lines.append(esc(truncate(event.message, 2000)))
    if event.details:
        lines.append("")
        for key, value in list(event.details.items())[:25]:
            lines.append(f"<b>{esc(key)}</b>: {esc(truncate(str(value), 200))}")
    if event.attachments:
        lines.append(f"\nВложений: {len(event.attachments)}")
    if public_url:
        lines.append(f"\n{esc(public_url.rstrip('/'))}/#/event/{event.id}")
    return truncate("\n".join(lines), 4000)


def event_keyboard(event: Event) -> Keyboard:
    row: list[dict[str, str]] = []
    if event.status == "new":
        row.append({"text": "👌 Принял", "data": f"ev:ack:{event.id}"})
    if event.status != "resolved":
        row.append({"text": "✅ Решено", "data": f"ev:res:{event.id}"})
    row.append({"text": "ℹ️ Подробнее", "data": f"ev:info:{event.id}"})
    return [row]


def link_keyboard(public_url: str, event: Event) -> Keyboard:
    if not public_url:
        return []
    return [[{"text": "Открыть в OpsWatch", "url": f"{public_url.rstrip('/')}/#/event/{event.id}"}]]
