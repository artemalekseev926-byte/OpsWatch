from __future__ import annotations

import json
from typing import Any

from opswatch.core.events import EventIn, normalize_severity
from opswatch.i18n import ts

ZABBIX_NAMED = {
    "not classified": "info",
    "information": "info",
    "warning": "warning",
    "average": "warning",
    "high": "critical",
    "disaster": "critical",
}


def _first(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _is_macro(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("{") and value.endswith("}")


def _clean(value: Any) -> Any:
    return None if _is_macro(value) else value


def parse_zabbix(payload: dict[str, Any], source_id: int | None, source_name: str, category: str = "monitoring") -> list[EventIn]:
    data = {k: _clean(v) for k, v in payload.items()}
    event_id = str(_first(data, "event_id", "eventid", "EVENT.ID", default="") or "")
    raw_value = str(_first(data, "event_value", "value", default="1"))
    status = str(_first(data, "status", "event_status", default="")).upper()
    resolved = raw_value == "0" or status in {"RESOLVED", "OK"} or str(data.get("event_recovery", "")).lower() in {"1", "true"}
    severity_raw = str(_first(data, "severity", "event_severity", "priority", default="warning")).strip().lower()
    severity = ZABBIX_NAMED.get(severity_raw) or normalize_severity(severity_raw)
    host = _first(data, "host", "host_name", "hostname", default="")
    trigger = _first(data, "trigger_name", "trigger", "event_name", "name", default="")
    subject = _first(data, "subject", "title", default="")
    title = trigger or subject or ts("Событие Zabbix")
    if host and host not in title:
        title = f"{host}: {title}"
    message = _first(data, "message", "text", "opdata", default="")
    details = {
        k: v
        for k, v in data.items()
        if v not in (None, "") and k not in {"message", "subject"} and not isinstance(v, (dict, list))
    }
    tags = data.get("event_tags") or data.get("tags")
    if isinstance(tags, str) and tags:
        details["tags"] = tags
    external = f"zbx:{event_id}" if event_id else None
    event_type = "zabbix.resolved" if resolved else "zabbix.problem"
    return [
        EventIn(
            title=title,
            message=str(message or ""),
            severity="info" if resolved else severity,
            category=category,
            type=event_type,
            source_id=source_id,
            source_name=source_name,
            details=details,
            external_id=external,
            resolve=resolved and bool(external),
        )
    ]


def parse_alertmanager(payload: dict[str, Any], source_id: int | None, source_name: str, category: str = "monitoring") -> list[EventIn]:
    events: list[EventIn] = []
    common_labels = payload.get("commonLabels") or {}
    for alert in payload.get("alerts") or []:
        labels = {**common_labels, **(alert.get("labels") or {})}
        annotations = alert.get("annotations") or {}
        name = labels.get("alertname") or "Alert"
        instance = labels.get("instance") or labels.get("job") or ""
        summary = annotations.get("summary") or annotations.get("title") or ""
        title = summary or name
        if instance and instance not in title:
            title = f"{instance}: {title}"
        fingerprint = alert.get("fingerprint") or json.dumps(sorted(labels.items()), ensure_ascii=False)
        resolved = (alert.get("status") or payload.get("status")) == "resolved"
        message = annotations.get("description") or annotations.get("message") or ""
        details = {f"label:{k}": v for k, v in labels.items()}
        if alert.get("generatorURL"):
            details["url"] = alert["generatorURL"]
        if alert.get("startsAt"):
            details["startsAt"] = alert["startsAt"]
        events.append(
            EventIn(
                title=title,
                message=message,
                severity="info" if resolved else normalize_severity(labels.get("severity"), "warning"),
                category=category,
                type=f"alertmanager.{name}",
                source_id=source_id,
                source_name=source_name,
                details=details,
                external_id=f"am:{fingerprint}"[:200],
                resolve=resolved,
            )
        )
    return events


def parse_generic(
    payload: dict[str, Any] | list[Any],
    source_id: int | None,
    source_name: str,
    category: str = "monitoring",
    default_severity: str = "warning",
) -> list[EventIn]:
    items = payload if isinstance(payload, list) else payload.get("events") if isinstance(payload.get("events"), list) else [payload]
    events = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(_first(item, "status", "state", default="")).lower()
        resolved = bool(item.get("resolve")) or status in {"resolved", "ok", "recovered", "closed"}
        title = _first(item, "title", "subject", "name", "summary", default=None)
        message = _first(item, "message", "text", "description", "body", default="")
        if title is None:
            title = str(message).splitlines()[0][:200] if message else ts("Событие")
        known = {
            "title", "subject", "name", "summary", "message", "text", "description", "body", "severity", "level",
            "priority", "category", "type", "fingerprint", "id", "external_id", "status", "state", "resolve", "details",
        }
        details = dict(item.get("details") or {}) if isinstance(item.get("details"), dict) else {}
        details.update({k: v for k, v in item.items() if k not in known and not isinstance(v, (dict, list))})
        external = _first(item, "external_id", "id", default=None)
        events.append(
            EventIn(
                title=str(title),
                message=str(message),
                severity="info" if resolved else normalize_severity(_first(item, "severity", "level", "priority"), default_severity),
                category=_first(item, "category", default=category),
                type=str(_first(item, "type", default="webhook")),
                source_id=source_id,
                source_name=source_name,
                details=details,
                fingerprint=item.get("fingerprint"),
                external_id=str(external) if external is not None else None,
                resolve=resolved,
            )
        )
    return events
