from __future__ import annotations

import operator
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable

from opswatch.connectors.base import Connector, ConnectorError
from opswatch.core.events import EventIn

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

CHECK_MODES = [
    ["new_rows", "Новые записи"],
    ["threshold", "Порог значения"],
    ["rows_exist", "Есть строки — тревога"],
]

_COMMENTS = re.compile(r"(--[^\n]*)|(/\*.*?\*/)", re.S)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|call|into)\b",
    re.I,
)

MAX_ROW_EVENTS = 5


def ensure_read_only(query: str) -> str:
    cleaned = _COMMENTS.sub(" ", query or "").strip().rstrip(";").strip()
    if not cleaned:
        raise ConnectorError("Пустой запрос")
    head = cleaned.split(None, 1)[0].lower()
    if head not in {"select", "with", "show"}:
        raise ConnectorError("Разрешены только запросы SELECT / WITH")
    if ";" in cleaned:
        raise ConnectorError("Разрешён только один запрос")
    if _FORBIDDEN.search(re.sub(r"'(?:[^']|'')*'", "''", cleaned)):
        raise ConnectorError("Запрос содержит изменяющие операторы")
    return cleaned


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def sql_literal(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def compare_keys(a: Any, b: Any) -> int:
    try:
        if a > b:
            return 1
        if a < b:
            return -1
        return 0
    except TypeError:
        sa, sb = str(a), str(b)
        return (sa > sb) - (sa < sb)


def to_number(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ConnectorError(f"Значение «{value}» не является числом") from exc


def format_row(row: dict[str, Any], limit: int = 12) -> str:
    lines = []
    for key, value in list(row.items())[:limit]:
        text = str(json_value(value))
        if len(text) > 120:
            text = text[:119] + "…"
        lines.append(f"{key}: {text}")
    return "\n".join(lines)


def render_title(template: str, row: dict[str, Any], fallback: str) -> str:
    if not template:
        return fallback
    values = defaultdict(str, {k: json_value(v) for k, v in row.items()})
    try:
        return template.format_map(values)
    except (ValueError, IndexError, KeyError, AttributeError):
        return template


Fetch = Callable[[str], Awaitable[list[dict[str, Any]]]]


async def run_checks(
    connector: Connector,
    fetch: Fetch,
    checks: list[dict[str, Any]],
    state: dict[str, Any],
) -> tuple[list[EventIn], dict[str, Any]]:
    events: list[EventIn] = []
    new_state = dict(state)
    for index, check in enumerate(checks or []):
        if not check or not check.get("enabled", True):
            continue
        name = (check.get("name") or f"Проверка {index + 1}").strip()
        mode = check.get("mode") or "threshold"
        severity = check.get("severity") or "warning"
        state_key = f"check:{name}"
        fp = connector.fingerprint("check", name)
        error_fp = connector.fingerprint("check-error", name)
        try:
            query = ensure_read_only(check.get("query", ""))
            if mode == "new_rows":
                last = state.get(state_key)
                rows = await fetch(query.replace("{last}", sql_literal(last)))
                key_column = check.get("key_column") or (next(iter(rows[0])) if rows else "")
                keyed = []
                for row in rows:
                    if key_column in row and row[key_column] is not None:
                        keyed.append((json_value(row[key_column]), row))
                if keyed:
                    top = keyed[0][0]
                    for key_value, _row in keyed[1:]:
                        if compare_keys(key_value, top) > 0:
                            top = key_value
                else:
                    top = last
                if last is None:
                    new_state[state_key] = top if top is not None else 0
                else:
                    fresh = sorted(
                        [(k, r) for k, r in keyed if compare_keys(k, last) > 0],
                        key=lambda item: (str(type(item[0])), item[0]),
                    )
                    for key_value, row in fresh[:MAX_ROW_EVENTS]:
                        events.append(
                            connector.event(
                                title=render_title(check.get("title", ""), row, f"{name}: новая запись {key_value}"),
                                message=format_row(row),
                                severity=severity,
                                type="check.new_row",
                                fingerprint=connector.fingerprint("row", name, key_value),
                                details={"check": name, "key": key_value},
                            )
                        )
                    if len(fresh) > MAX_ROW_EVENTS:
                        events.append(
                            connector.event(
                                title=f"{name}: ещё {len(fresh) - MAX_ROW_EVENTS} новых записей",
                                severity=severity,
                                type="check.new_row",
                                fingerprint=connector.fingerprint("rows", name, top),
                                details={"check": name, "count": len(fresh)},
                            )
                        )
                    if top is not None and compare_keys(top, last) > 0:
                        new_state[state_key] = top
            elif mode == "rows_exist":
                rows = await fetch(query)
                if rows:
                    preview = "\n\n".join(format_row(r, 6) for r in rows[:3])
                    events.append(
                        connector.event(
                            title=render_title(check.get("title", ""), rows[0], f"{name}: найдено строк: {len(rows)}"),
                            message=preview,
                            severity=severity,
                            type="check.rows",
                            fingerprint=fp,
                            details={"check": name, "rows": len(rows)},
                        )
                    )
                else:
                    events.append(connector.resolved(fp, message=f"{name}: условие больше не выполняется"))
            else:
                rows = await fetch(query)
                if not rows:
                    raise ConnectorError("Запрос не вернул значение")
                value = to_number(next(iter(rows[0].values())))
                threshold = to_number(check.get("threshold", 0))
                op = check.get("operator") or ">"
                if op not in OPERATORS:
                    raise ConnectorError(f"Неизвестный оператор {op}")
                new_state[f"value:{name}"] = value
                if OPERATORS[op](value, threshold):
                    events.append(
                        connector.event(
                            title=render_title(
                                check.get("title", ""),
                                {"value": value, "threshold": threshold},
                                f"{name}: {value:g} {op} {threshold:g}",
                            ),
                            message=f"Текущее значение: {value:g}\nПорог: {op} {threshold:g}",
                            severity=severity,
                            type="check.threshold",
                            fingerprint=fp,
                            details={"check": name, "value": value, "threshold": threshold, "operator": op},
                        )
                    )
                else:
                    events.append(connector.resolved(fp, message=f"{name}: значение в норме ({value:g})"))
        except Exception as exc:
            events.append(
                connector.event(
                    title=f"Ошибка проверки «{name}»",
                    message=str(exc),
                    severity="warning",
                    type="check.error",
                    fingerprint=error_fp,
                )
            )
        else:
            events.append(connector.resolved(error_fp))
    return events, new_state
