from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

from opswatch.constants import CATEGORY_TITLES, EVENT_STATUS_TITLES, SEVERITY_ICONS, SEVERITY_TITLES
from opswatch.db import to_local
from opswatch.i18n import tr
from opswatch.models import Event

Keyboard = list[list[dict[str, str]]]

TEMPLATE_KINDS = ("event", "repeat", "escalation", "resolved")
ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "a", "tg-spoiler", "blockquote"}

PLACEHOLDERS = {
    "icon": "Значок важности",
    "severity": "Важность",
    "SEVERITY": "Важность заглавными буквами",
    "category": "Категория",
    "title": "Заголовок события",
    "message": "Текст события",
    "source": "Источник",
    "time": "Время первого появления",
    "last_time": "Время последнего повтора",
    "count": "Количество повторов",
    "type": "Тип события",
    "id": "Номер события",
    "meta": "Строка «Источник · время · повторы»",
    "status": "Статус",
    "status_line": "Кто принял или решил",
    "resolution": "Комментарий к решению",
    "resolved_by": "Кто закрыл событие",
    "resolved_time": "Время закрытия",
    "link": "Ссылка на событие в OpsWatch",
}

DEFAULT_TEMPLATES = {
    "ru": {
        "event": "{icon} <b>{SEVERITY}</b> · {category}\n<b>{title}</b>\n{message}\n<i>{meta}</i>\n{status_line}\n#ev{id}",
        "repeat": "🔁 <b>Повторяется ({count} раз)</b>\n{icon} <b>{SEVERITY}</b> · {category}\n<b>{title}</b>\n{message}\n<i>{meta}</i>\n{status_line}\n#ev{id}",
        "escalation": "⏫ <b>ЭСКАЛАЦИЯ: событие не подтверждено</b>\n{icon} <b>{SEVERITY}</b> · {category}\n<b>{title}</b>\n{message}\n<i>{meta}</i>\n{status_line}\n#ev{id}",
        "resolved": "✅ <b>Решено</b> · {category}\n<b>{title}</b>\n{resolution}\n<i>{resolved_meta}</i>\n#ev{id}",
    },
    "en": {
        "event": "{icon} <b>{SEVERITY}</b> · {category}\n<b>{title}</b>\n{message}\n<i>{meta}</i>\n{status_line}\n#ev{id}",
        "repeat": "🔁 <b>Repeating ({count} times)</b>\n{icon} <b>{SEVERITY}</b> · {category}\n<b>{title}</b>\n{message}\n<i>{meta}</i>\n{status_line}\n#ev{id}",
        "escalation": "⏫ <b>ESCALATION: event not acknowledged</b>\n{icon} <b>{SEVERITY}</b> · {category}\n<b>{title}</b>\n{message}\n<i>{meta}</i>\n{status_line}\n#ev{id}",
        "resolved": "✅ <b>Resolved</b> · {category}\n<b>{title}</b>\n{resolution}\n<i>{resolved_meta}</i>\n#ev{id}",
    },
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


TIME_FORMATS = {"ru": "%d.%m.%Y %H:%M", "en": "%Y-%m-%d %H:%M"}


def fmt_time(value, lang: str = "ru") -> str:
    local = to_local(value)
    return local.strftime(TIME_FORMATS.get(lang, TIME_FORMATS["ru"])) if local else ""


def default_template(kind: str, lang: str = "ru") -> str:
    return DEFAULT_TEMPLATES.get(lang, DEFAULT_TEMPLATES["ru"]).get(kind, DEFAULT_TEMPLATES["ru"]["event"])


def template_context(
    event: Event,
    acked_by: str = "",
    resolved_by: str = "",
    lang: str = "ru",
    public_url: str = "",
) -> dict[str, str]:
    severity = tr(SEVERITY_TITLES.get(event.severity, event.severity), lang)
    category = tr(CATEGORY_TITLES.get(event.category, event.category), lang)
    meta = []
    if event.source_name:
        meta.append(tr("Источник: {name}", lang, name=esc(event.source_name)))
    meta.append(fmt_time(event.created_at, lang))
    if (event.count or 1) > 1:
        meta.append(tr("Повторов: {count}", lang, count=event.count))
    status_line = ""
    if event.status == "acked":
        status_line = "✅ " + tr("Принято", lang) + (f": {esc(acked_by)}" if acked_by else "")
    elif event.status == "resolved":
        status_line = "☑️ " + tr("Решено", lang) + (f": {esc(resolved_by)}" if resolved_by else "")
    resolved_meta = []
    if resolved_by:
        resolved_meta.append(tr("Закрыл: {name}", lang, name=esc(resolved_by)))
    resolved_meta.append(fmt_time(event.resolved_at, lang))
    link = f"{public_url.rstrip('/')}/#/event/{event.id}" if public_url else ""
    return {
        "icon": SEVERITY_ICONS.get(event.severity, "⚪"),
        "severity": esc(severity),
        "SEVERITY": esc(severity.upper()),
        "category": esc(category),
        "title": esc(truncate(event.title, 300)),
        "message": esc(truncate(event.message or "", 1800)),
        "source": esc(event.source_name or ""),
        "time": fmt_time(event.created_at, lang),
        "last_time": fmt_time(event.last_seen_at, lang),
        "count": str(event.count or 1),
        "type": esc(event.type),
        "id": str(event.id),
        "meta": " · ".join(m for m in meta if m),
        "status": esc(tr(EVENT_STATUS_TITLES.get(event.status, event.status), lang)),
        "status_line": status_line,
        "resolution": esc(truncate(event.resolution or "", 1000)),
        "resolved_by": esc(resolved_by),
        "resolved_time": fmt_time(event.resolved_at, lang),
        "resolved_meta": " · ".join(m for m in resolved_meta if m),
        "link": esc(link),
    }


def render_template(template: str, context: dict[str, str]) -> str:
    lines = []
    for line in template.replace("\r\n", "\n").split("\n"):
        names = _PLACEHOLDER.findall(line)
        known = [n for n in names if n in context]
        rendered = _PLACEHOLDER.sub(lambda m: context.get(m.group(1), m.group(0)), line)
        if known and all(not context[n] for n in known):
            stripped = re.sub(r"<[^>]+>", "", _PLACEHOLDER.sub("", line)).strip(" ·:-—")
            if not stripped:
                continue
        lines.append(rendered)
    return "\n".join(lines).strip()


class _TagChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS and not tag.startswith("{"):
            self.errors.append(f"<{tag}>")
            return
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag not in ALLOWED_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}>")
            return
        self.stack.pop()


def validate_template(template: str) -> list[str]:
    checker = _TagChecker()
    checker.feed(_PLACEHOLDER.sub("x", template))
    checker.close()
    problems = []
    if checker.errors:
        problems.append(tr("Недопустимые или непарные теги: {tags}", tags=", ".join(checker.errors[:5])))
    if checker.stack:
        problems.append(tr("Незакрытые теги: {tags}", tags=", ".join(f"<{t}>" for t in checker.stack)))
    if len(template) > 3000:
        problems.append(tr("Шаблон длиннее 3000 символов"))
    unknown = sorted({n for n in _PLACEHOLDER.findall(template) if n not in PLACEHOLDERS and n != "resolved_meta"})
    if unknown:
        problems.append(tr("Неизвестные подстановки: {names}", names=", ".join("{" + n + "}" for n in unknown)))
    return problems


def render_notification(
    event: Event,
    kind: str = "event",
    acked_by: str = "",
    resolved_by: str = "",
    lang: str = "ru",
    template: str = "",
    public_url: str = "",
) -> str:
    context = template_context(event, acked_by, resolved_by, lang, public_url)
    text = render_template(template or default_template(kind, lang), context)
    return truncate(text or render_template(default_template(kind, lang), context), 4000)


def render_event(event: Event, kind: str = "event", acked_by: str = "", resolved_by: str = "", lang: str = "ru") -> str:
    return render_notification(event, kind, acked_by, resolved_by, lang)


def render_resolved(event: Event, by: str = "", lang: str = "ru") -> str:
    return render_notification(event, "resolved", "", by, lang)


def render_details(event: Event, public_url: str = "", lang: str = "ru") -> str:
    lines = [
        f"{SEVERITY_ICONS.get(event.severity, '⚪')} <b>{esc(event.title)}</b>",
        tr("Категория: {value}", lang, value=esc(tr(CATEGORY_TITLES.get(event.category, event.category), lang))),
        tr("Важность: {value}", lang, value=esc(tr(SEVERITY_TITLES.get(event.severity, event.severity), lang))),
        tr("Статус: {value}", lang, value=esc(tr(EVENT_STATUS_TITLES.get(event.status, event.status), lang))),
        tr("Тип: {value}", lang, value=f"<code>{esc(event.type)}</code>"),
    ]
    if event.source_name:
        lines.append(tr("Источник: {name}", lang, name=esc(event.source_name)))
    lines.append(tr("Впервые: {value}", lang, value=fmt_time(event.created_at, lang)))
    lines.append(tr("Последний раз: {value}", lang, value=fmt_time(event.last_seen_at, lang)))
    lines.append(tr("Повторов: {count}", lang, count=event.count))
    if event.message:
        lines.append("")
        lines.append(esc(truncate(event.message, 2000)))
    if event.details:
        lines.append("")
        for key, value in list(event.details.items())[:25]:
            lines.append(f"<b>{esc(key)}</b>: {esc(truncate(str(value), 200))}")
    if event.attachments:
        lines.append("\n" + tr("Вложений: {count}", lang, count=len(event.attachments)))
    if public_url:
        lines.append(f"\n{esc(public_url.rstrip('/'))}/#/event/{event.id}")
    return truncate("\n".join(lines), 4000)


def event_keyboard(event: Event, lang: str = "ru") -> Keyboard:
    row: list[dict[str, str]] = []
    if event.status == "new":
        row.append({"text": "👌 " + tr("Принял", lang), "data": f"ev:ack:{event.id}"})
    if event.status != "resolved":
        row.append({"text": "✅ " + tr("Решено", lang), "data": f"ev:res:{event.id}"})
    row.append({"text": "ℹ️ " + tr("Подробнее", lang), "data": f"ev:info:{event.id}"})
    return [row]


def link_keyboard(public_url: str, event: Event, lang: str = "ru") -> Keyboard:
    if not public_url:
        return []
    return [[{"text": tr("Открыть в OpsWatch", lang), "url": f"{public_url.rstrip('/')}/#/event/{event.id}"}]]


def sample_event(lang: str | None = None) -> Event:
    from opswatch.db import utcnow

    now = utcnow()
    return Event(
        id=128,
        created_at=now,
        last_seen_at=now,
        source_name="ERP — PostgreSQL",
        category="database",
        type="check.threshold",
        severity="critical",
        title=tr("Ошибки в очереди заданий: 9 > 3", lang),
        message=tr("Текущее значение: 9\nПорог: > 3", lang),
        count=3,
        status="new",
        resolution=tr("Перезапустили службу обмена", lang),
        resolved_at=now,
        details={},
    )
