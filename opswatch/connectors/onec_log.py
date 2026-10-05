from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from opswatch.i18n import ts

LEVELS = ("info", "warning", "error", "note")
LEVEL_RANK = {"note": 0, "info": 0, "warning": 1, "error": 2}
LETTER_LEVEL = {"I": "info", "W": "warning", "E": "error", "N": "note"}

EVENT_NAMES = {
    "_$Session$_.Start": "Сеанс. Начало",
    "_$Session$_.Finish": "Сеанс. Завершение",
    "_$Session$_.Authentication": "Сеанс. Аутентификация",
    "_$Session$_.AuthenticationError": "Сеанс. Ошибка аутентификации",
    "_$Session$_.ConfigExtensionApplyError": "Сеанс. Ошибка применения расширения",
    "_$Data$_.New": "Данные. Добавление",
    "_$Data$_.Update": "Данные. Изменение",
    "_$Data$_.Delete": "Данные. Удаление",
    "_$Data$_.Post": "Данные. Проведение",
    "_$Data$_.Unpost": "Данные. Отмена проведения",
    "_$InfoBase$_.ConfigUpdate": "Информационная база. Изменение конфигурации",
    "_$InfoBase$_.DBConfigUpdate": "Информационная база. Изменение конфигурации базы данных",
    "_$InfoBase$_.EventLogSettingsUpdate": "Информационная база. Изменение параметров журнала регистрации",
    "_$InfoBase$_.InfoBaseAdmParamsUpdate": "Информационная база. Изменение параметров информационной базы",
    "_$InfoBase$_.SecondFactorAuthTemplateNew": "Информационная база. Шаблон второго фактора",
    "_$Job$_.Start": "Фоновое задание. Запуск",
    "_$Job$_.Succeed": "Фоновое задание. Успешное завершение",
    "_$Job$_.Fail": "Фоновое задание. Ошибка выполнения",
    "_$Job$_.Cancel": "Фоновое задание. Отмена",
    "_$Job$_.Terminate": "Фоновое задание. Принудительное завершение",
    "_$User$_.New": "Пользователи. Добавление",
    "_$User$_.Update": "Пользователи. Изменение",
    "_$User$_.Delete": "Пользователи. Удаление",
    "_$User$_.AuthenticationLock": "Пользователи. Блокировка аутентификации",
    "_$Transaction$_.Begin": "Транзакция. Начало",
    "_$Transaction$_.Commit": "Транзакция. Фиксация",
    "_$Transaction$_.Rollback": "Транзакция. Отмена",
    "_$PerformError$_": "Ошибка выполнения",
}


@dataclass
class LogEntry:
    time: datetime | None
    level: str
    event: str
    comment: str = ""
    user: str = ""
    computer: str = ""
    application: str = ""
    data: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def event_title(self) -> str:
        name = EVENT_NAMES.get(self.event)
        return ts(name) if name else self.event


def level_at_least(level: str, minimum: str) -> bool:
    return LEVEL_RANK.get(level, 0) >= LEVEL_RANK.get(minimum, 1)


def parse_braces(text: str, pos: int = 0) -> tuple[list[Any], int]:
    if text[pos] != "{":
        raise ValueError("expected {")
    pos += 1
    items: list[Any] = []
    token: list[str] = []
    has_token = False
    length = len(text)
    while pos < length:
        ch = text[pos]
        if ch == '"':
            pos += 1
            buf = []
            while pos < length:
                if text[pos] == '"':
                    if pos + 1 < length and text[pos + 1] == '"':
                        buf.append('"')
                        pos += 2
                        continue
                    pos += 1
                    break
                buf.append(text[pos])
                pos += 1
            token = ["".join(buf)]
            has_token = True
            continue
        if ch == "{":
            nested, pos = parse_braces(text, pos)
            items.append(nested)
            has_token = False
            token = []
            while pos < length and text[pos] in " \r\n\t":
                pos += 1
            if pos < length and text[pos] == ",":
                pos += 1
            continue
        if ch == ",":
            items.append("".join(token).strip() if has_token else "")
            token = []
            has_token = False
            pos += 1
            continue
        if ch == "}":
            if has_token:
                items.append("".join(token).strip())
            return items, pos + 1
        if ch not in "\r\n":
            token.append(ch)
            if not ch.isspace():
                has_token = True
        pos += 1
    raise ValueError("unterminated record")


def split_records(text: str) -> tuple[list[str], int]:
    records: list[str] = []
    depth = 0
    in_string = False
    start = -1
    consumed = 0
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if in_string:
            if ch == '"':
                if i + 1 < length and text[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                records.append(text[start : i + 1])
                consumed = i + 1
                start = -1
        i += 1
    return records, consumed


def parse_1c_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value[:14], "%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return None


def load_lgf(path: Path) -> dict[int, dict[int, str]]:
    result: dict[int, dict[int, str]] = {}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    records, _ = split_records(text)
    for raw in records:
        try:
            item, _ = parse_braces(raw)
        except ValueError:
            continue
        if len(item) < 3:
            continue
        try:
            kind = int(item[0])
            index = int(item[-1])
        except (TypeError, ValueError):
            continue
        name = item[-2]
        if isinstance(name, list):
            name = ""
        result.setdefault(kind, {})[index] = str(name)
    return result


def _ref(dictionary: dict[int, dict[int, str]], kind: int, value: Any) -> str:
    try:
        return dictionary.get(kind, {}).get(int(value), "")
    except (TypeError, ValueError):
        return ""


def entry_from_lgp(record: list[Any], dictionary: dict[int, dict[int, str]]) -> LogEntry | None:
    if len(record) < 10:
        return None
    level = LETTER_LEVEL.get(str(record[8]).strip(), "info")
    comment = record[9] if isinstance(record[9], str) else ""
    data_presentation = record[12] if len(record) > 12 and isinstance(record[12], str) else ""
    return LogEntry(
        time=parse_1c_date(str(record[0])),
        level=level,
        event=_ref(dictionary, 4, record[7]),
        comment=comment,
        user=_ref(dictionary, 1, record[3]),
        computer=_ref(dictionary, 2, record[4]),
        application=_ref(dictionary, 3, record[5]),
        data=data_presentation,
        extra={"metadata": _ref(dictionary, 5, record[10]) if len(record) > 10 else ""},
    )


class LgpReader:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def files(self) -> list[Path]:
        return sorted(self.folder.glob("*.lgp"))

    def read(self, state: dict[str, Any], limit: int = 2000) -> tuple[list[LogEntry], dict[str, Any]]:
        files = self.files()
        if not files:
            return [], state
        current = state.get("lgp_file")
        offset = int(state.get("lgp_offset") or 0)
        if not current:
            last = files[-1]
            return [], {"lgp_file": last.name, "lgp_offset": last.stat().st_size}
        dictionary = load_lgf(self.folder / "1Cv8.lgf")
        entries: list[LogEntry] = []
        names = [f.name for f in files]
        if current not in names:
            pending = [f for f in files if f.name > current]
            if not pending:
                return [], state
            current, offset = pending[0].name, 0
        index = names.index(current)
        new_state = {"lgp_file": current, "lgp_offset": offset}
        for path in files[index:]:
            start = offset if path.name == current else 0
            with path.open("rb") as handle:
                handle.seek(start)
                raw = handle.read()
            head = 0
            if start == 0:
                head = raw.find(b"{")
                if head < 0:
                    new_state = {"lgp_file": path.name, "lgp_offset": 0}
                    continue
            body = raw[head:].decode("utf-8", errors="replace")
            records, consumed = split_records(body)
            for raw_record in records:
                try:
                    parsed, _ = parse_braces(raw_record)
                except ValueError:
                    continue
                entry = entry_from_lgp(parsed, dictionary)
                if entry:
                    entries.append(entry)
            new_state = {
                "lgp_file": path.name,
                "lgp_offset": start + head + len(body[:consumed].encode("utf-8")),
            }
            if len(entries) >= limit:
                break
        return entries[:limit], new_state


class LgdReader:
    QUERY = """
        SELECT e.rowID, e.severity, e.date, e.comment, e.dataPresentation,
               ev.name, u.name, c.name, a.name
        FROM EventLog e
        LEFT JOIN EventCodes ev ON ev.code = e.eventCode
        LEFT JOIN UserCodes u ON u.code = e.userCode
        LEFT JOIN ComputerCodes c ON c.code = e.computerCode
        LEFT JOIN AppCodes a ON a.code = e.appCode
        WHERE e.rowID > ?
        ORDER BY e.rowID
        LIMIT ?
    """

    def __init__(self, path: Path, severity_base: str = "auto") -> None:
        self.path = path
        self.severity_base = severity_base

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)

    def detect_base(self, connection: sqlite3.Connection) -> int:
        if self.severity_base in {"0", "1"}:
            return int(self.severity_base)
        try:
            row = connection.execute(
                """
                SELECT e.severity, COUNT(*) FROM EventLog e
                JOIN EventCodes ev ON ev.code = e.eventCode
                WHERE ev.name IN ('_$Session$_.Start', '_$Session$_.Finish')
                GROUP BY e.severity ORDER BY COUNT(*) DESC LIMIT 1
                """
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None and row[0] in (0, 1):
            return int(row[0])
        return 1

    def level(self, value: Any, base: int) -> str:
        try:
            index = int(value) - base
        except (TypeError, ValueError):
            return "info"
        return LEVELS[index] if 0 <= index < len(LEVELS) else "info"

    @staticmethod
    def convert_date(value: Any) -> datetime | None:
        try:
            return datetime(1, 1, 1) + timedelta(seconds=int(value) / 10000)
        except (TypeError, ValueError, OverflowError):
            return None

    def read(self, state: dict[str, Any], limit: int = 2000) -> tuple[list[LogEntry], dict[str, Any]]:
        connection = self._connect()
        try:
            last = state.get("lgd_row")
            if last is None:
                row = connection.execute("SELECT MAX(rowID) FROM EventLog").fetchone()
                return [], {**state, "lgd_row": int(row[0] or 0)}
            base = state.get("lgd_base")
            if base is None:
                base = self.detect_base(connection)
            rows = connection.execute(self.QUERY, (int(last), limit)).fetchall()
        finally:
            connection.close()
        entries = []
        max_row = int(last)
        for row_id, severity, date_value, comment, data, event, user, computer, app in rows:
            max_row = max(max_row, int(row_id))
            entries.append(
                LogEntry(
                    time=self.convert_date(date_value),
                    level=self.level(severity, int(base)),
                    event=event or "",
                    comment=comment or "",
                    user=user or "",
                    computer=computer or "",
                    application=app or "",
                    data=data or "",
                )
            )
        return entries, {**state, "lgd_row": max_row, "lgd_base": int(base)}


def find_log_folder(path: Path) -> Path | None:
    candidates = [path, path / "1Cv8Log"]
    for candidate in candidates:
        if (candidate / "1Cv8.lgd").exists() or (candidate / "1Cv8.lgf").exists():
            return candidate
    return None


def read_log(folder: Path, state: dict[str, Any], severity_base: str = "auto", limit: int = 2000):
    lgd = folder / "1Cv8.lgd"
    if lgd.exists():
        return LgdReader(lgd, severity_base).read(state, limit)
    return LgpReader(folder).read(state, limit)
