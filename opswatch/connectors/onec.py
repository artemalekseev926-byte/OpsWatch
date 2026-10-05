from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

from opswatch.connectors.base import Connector, ConnectorError, Field, PollResult, register
from opswatch.connectors.onec_log import find_log_folder, level_at_least, read_log
from opswatch.connectors.sql import CHECKS_FIELD, MSSQLConnector, PostgresConnector, human_size
from opswatch.i18n import ts

LOG_LEVEL_OPTIONS = [["error", "Только ошибки"], ["warning", "Ошибки и предупреждения"]]
LOG_SEVERITY_OPTIONS = [["warning", "Предупреждение"], ["critical", "Критично"]]
MAX_LOG_EVENTS = 20


def is_file_locked(path: Path) -> bool:
    if not path.exists():
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        handle = create_file(str(path), 0x80000000, 0, None, 3, 0x80, None)
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid or handle is None:
            return ctypes.get_last_error() in (32, 33)
        kernel32.CloseHandle(handle)
        return False
    try:
        import fcntl

        with path.open("rb+") as handle:
            try:
                fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.lockf(handle, fcntl.LOCK_UN)
        return False
    except OSError:
        return False


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", path.parent.parent.name)) or (0,)


def find_platform_bin(configured: str = "") -> Path | None:
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return candidate.parent
        if candidate.is_dir():
            return candidate / "bin" if (candidate / "bin").is_dir() and not (candidate / "1cv8.exe").exists() else candidate
    roots = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value) / "1cv8")
    roots.append(Path("/opt/1cv8"))
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        found += list(root.glob("*/bin/1cv8.exe")) + list(root.glob("*/*/1cv8"))
    if not found:
        return None
    return sorted(found, key=_version_key)[-1].parent


def log_events(connector: Connector, folder: Path, state: dict[str, Any]) -> tuple[list, dict[str, Any], int]:
    min_level = connector.option("log_min_level", "error")
    severity = connector.option("log_severity", "warning")
    entries, new_state = read_log(folder, state.get("log", {}), connector.option("lgd_severity_base", "auto"))
    matched = [e for e in entries if level_at_least(e.level, min_level)]
    events = []
    for entry in matched[:MAX_LOG_EVENTS]:
        title = ts("Журнал 1С: {value}", value=entry.event_title or ts("событие"))
        lines = []
        if entry.comment:
            lines.append(entry.comment)
        if entry.data:
            lines.append(ts("Данные: {data}", data=entry.data))
        who = ", ".join(x for x in (entry.user, entry.computer, entry.application) if x)
        if who:
            lines.append(ts("Кто: {who}", who=who))
        if entry.time:
            lines.append(ts("Время: {time:%d.%m.%Y %H:%M:%S}", time=entry.time))
        events.append(
            connector.event(
                title=title,
                message="\n".join(lines),
                severity=severity if entry.level == "error" else "info",
                type="onec.log." + entry.level,
                fingerprint=connector.fingerprint("log", entry.event, entry.comment[:160]),
                details={"level": entry.level, "event": entry.event, "user": entry.user, "computer": entry.computer},
            )
        )
    if len(matched) > MAX_LOG_EVENTS:
        events.append(
            connector.event(
                title=ts("Журнал 1С: ещё {value} записей", value=len(matched) - MAX_LOG_EVENTS),
                severity=severity,
                type="onec.log.summary",
                fingerprint=connector.fingerprint("log-summary"),
            )
        )
    return events, {**state, "log": new_state}, len(matched)


LOG_FIELDS = [
    Field("log_enabled", "Анализировать журнал регистрации", type="bool", default=True, group="Журнал регистрации"),
    Field("log_min_level", "Уровень", type="select", default="error", options=LOG_LEVEL_OPTIONS, group="Журнал регистрации"),
    Field(
        "log_severity",
        "Важность события для ошибок журнала",
        type="select",
        default="warning",
        options=LOG_SEVERITY_OPTIONS,
        group="Журнал регистрации",
    ),
    Field(
        "lgd_severity_base",
        "Кодировка уровней в 1Cv8.lgd",
        type="select",
        default="auto",
        options=[["auto", "Определять автоматически"], ["0", "0 — информация"], ["1", "1 — информация"]],
        group="Журнал регистрации",
    ),
]


@register
class OneCFileConnector(Connector):
    type = "onec_file"
    title = "1С: файловая база"
    category = "onec"
    description = "Доступность и размер 1Cv8.1CD, журнал регистрации, проверка целостности"
    supports_backup = True
    supports_maintenance = True
    default_interval = 120
    fields = [
        Field("path", "Каталог базы", type="path", required=True, placeholder=r"D:\Bases\Buh", group="База"),
        Field("size_warn_mb", "Предупреждать при размере больше, МБ", type="number", default=0, group="База"),
        *LOG_FIELDS,
        Field(
            "integrity_tool",
            "Проверка целостности",
            type="select",
            default="none",
            options=[["none", "Не выполнять"], ["designer", "1cv8 DESIGNER /IBCheckAndRepair"], ["chdbfl", "chdbfl.exe"]],
            group="Проверка целостности",
            help="Запускается только когда в базе нет пользователей",
        ),
        Field("integrity_cron", "Расписание проверки (cron)", default="30 3 * * 0", group="Проверка целостности"),
        Field("platform_path", "Каталог платформы 1С (bin)", type="path", placeholder=r"C:\Program Files\1cv8\8.3.24.1691\bin", group="Проверка целостности"),
        Field(
            "integrity_args",
            "Аргументы chdbfl.exe",
            default='"{db_file}"',
            group="Проверка целостности",
            help="Подстановки: {db_file}, {db_dir}, {out}. Проверьте параметры для вашей версии платформы",
        ),
        Field("ib_user", "Пользователь ИБ (для DESIGNER)", group="Проверка целостности"),
        Field("ib_password", "Пароль ИБ", type="password", secret=True, group="Проверка целостности"),
    ]

    @property
    def folder(self) -> Path:
        return Path(str(self.option("path", ""))).expanduser()

    @property
    def db_file(self) -> Path:
        return self.folder / "1Cv8.1CD"

    def _inspect(self) -> dict[str, Any]:
        folder = self.folder
        if not str(self.option("path", "")).strip():
            raise ConnectorError(ts("Не указан каталог базы"))
        if not folder.exists():
            raise ConnectorError(ts("Каталог базы недоступен: {folder}", folder=folder))
        db_file = self.db_file
        if not db_file.exists():
            raise ConnectorError(ts("Файл базы 1Cv8.1CD не найден в {folder}", folder=folder))
        stat = db_file.stat()
        return {
            "size": stat.st_size,
            "size_human": human_size(stat.st_size),
            "in_use": is_file_locked(db_file),
            "modified": stat.st_mtime,
        }

    async def poll(self) -> PollResult:
        metrics = await asyncio.to_thread(self._inspect)
        events = []
        state = dict(self.ctx.state or {})
        warn_mb = self.int_option("size_warn_mb", 0)
        size_fp = self.fingerprint("size")
        if warn_mb:
            if metrics["size"] > warn_mb * 1024 * 1024:
                events.append(
                    self.event(
                        title=ts("{name}: размер базы {size_human}", name=self.ctx.name, size_human=metrics['size_human']),
                        message=ts("Превышен порог {warn_mb} МБ", warn_mb=warn_mb),
                        type="onec.size",
                        fingerprint=size_fp,
                    )
                )
            else:
                events.append(self.resolved(size_fp))
        if self.bool_option("log_enabled", True):
            log_folder = find_log_folder(self.folder)
            if log_folder is not None:
                log_events_list, state, count = await asyncio.to_thread(log_events, self, log_folder, state)
                events += log_events_list
                metrics["log_matches"] = count
        users = ts("есть пользователи") if metrics["in_use"] else ts("пользователей нет")
        return PollResult(events=events, metrics=metrics, state=state, message=f"{metrics['size_human']}, {users}")

    async def test(self) -> PollResult:
        metrics = await asyncio.to_thread(self._inspect)
        log_folder = find_log_folder(self.folder)
        log_text = ts(", журнал: {name}", name=log_folder.name) if log_folder else ts(", журнал не найден")
        users = ts("в базе работают пользователи") if metrics["in_use"] else ts("база свободна")
        return PollResult(metrics=metrics, message=ts("База найдена: {size_human}, {users}{log_text}", size_human=metrics['size_human'], users=users, log_text=log_text))

    def maintenance_cron(self) -> str:
        if self.option("integrity_tool", "none") == "none":
            return ""
        return str(self.option("integrity_cron", "") or "")

    def integrity_command(self, out_file: Path) -> list[str] | str:
        tool = self.option("integrity_tool", "none")
        bin_dir = find_platform_bin(str(self.option("platform_path", "") or ""))
        if bin_dir is None:
            raise ConnectorError(ts("Не найден каталог платформы 1С, укажите его в настройках источника"))
        if tool == "designer":
            exe = bin_dir / ("1cv8.exe" if sys.platform == "win32" else "1cv8")
            command = [
                str(exe),
                "DESIGNER",
                f"/F{self.folder}",
                "/DisableStartupDialogs",
                "/DisableStartupMessages",
                f"/Out{out_file}",
                "/IBCheckAndRepair",
                "-LogIntegrity",
                "-TestOnly",
            ]
            if self.option("ib_user"):
                command.append(f"/N{self.option('ib_user')}")
            if self.option("ib_password"):
                command.append(f"/P{self.option('ib_password')}")
            return command
        exe = bin_dir / "chdbfl.exe"
        args = str(self.option("integrity_args", '"{db_file}"')).format(
            db_file=self.db_file, db_dir=self.folder, out=out_file
        )
        return f'"{exe}" {args}'

    async def maintenance(self) -> PollResult:
        fp = self.fingerprint("integrity")
        if is_file_locked(self.db_file):
            return PollResult(
                events=[
                    self.event(
                        title=ts("{name}: проверка целостности пропущена", name=self.ctx.name),
                        message=ts("В базе работают пользователи — проверка перенесена на следующий запуск"),
                        severity="info",
                        type="onec.integrity.skipped",
                    )
                ],
                message=ts("Пропущено: база занята"),
            )
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "check.log"
            command = self.integrity_command(out_file)
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                timeout=6 * 3600,
                shell=isinstance(command, str),
            )
            output = ""
            if out_file.exists():
                output = out_file.read_text(encoding="utf-8-sig", errors="replace")
            output = (output or result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")).strip()
        if result.returncode == 0:
            return PollResult(
                events=[self.resolved(fp, message=ts("Проверка целостности пройдена"))],
                message=ts("Проверка целостности пройдена"),
            )
        return PollResult(
            events=[
                self.event(
                    title=ts("{name}: проверка целостности выявила ошибки", name=self.ctx.name),
                    message=output[-1500:] or ts("Код возврата {returncode}", returncode=result.returncode),
                    severity="critical",
                    type="onec.integrity.failed",
                    fingerprint=fp,
                )
            ],
            message=ts("Ошибка, код {returncode}", returncode=result.returncode),
        )


@register
class OneCServerConnector(Connector):
    type = "onec_server"
    title = "1С: серверная база"
    category = "onec"
    description = "СУБД базы (PostgreSQL / MS SQL), журнал регистрации и HTTP/OData-сервисы"
    supports_backup = True
    supports_checks = True
    default_interval = 120
    fields = [
        Field(
            "dbms",
            "СУБД",
            type="select",
            default="mssql",
            options=[["mssql", "Microsoft SQL Server"], ["postgresql", "PostgreSQL"]],
            group="СУБД",
        ),
        Field("host", "Сервер СУБД", placeholder="sql01", group="СУБД"),
        Field("port", "Порт", type="number", group="СУБД"),
        Field("database", "Имя базы в СУБД", required=True, group="СУБД"),
        Field("user", "Пользователь СУБД", group="СУБД", help="Рекомендуется пользователь только с правами на чтение"),
        Field("password", "Пароль", type="password", secret=True, group="СУБД"),
        Field("timeout", "Таймаут, сек", type="number", default=15, group="СУБД"),
        Field("size_warn_mb", "Предупреждать при размере больше, МБ", type="number", default=0, group="СУБД"),
        Field(
            "log_path",
            "Каталог журнала регистрации",
            type="path",
            placeholder=r"\\srv1c\srvinfo\reg_1541\<guid>\1Cv8Log",
            group="Журнал регистрации",
        ),
        *LOG_FIELDS,
        Field("http_url", "URL HTTP/OData-сервиса", placeholder="http://srv1c/base/odata/standard.odata/", group="HTTP-сервисы"),
        Field("http_user", "Пользователь HTTP", group="HTTP-сервисы"),
        Field("http_password", "Пароль HTTP", type="password", secret=True, group="HTTP-сервисы"),
        CHECKS_FIELD,
    ]

    def dbms_connector(self) -> MSSQLConnector | PostgresConnector:
        cls = PostgresConnector if self.option("dbms", "mssql") == "postgresql" else MSSQLConnector
        config = dict(self.config)
        if not config.get("port"):
            config["port"] = cls.default_port
        ctx = type(self.ctx)(
            id=self.ctx.id,
            name=self.ctx.name,
            category=self.ctx.category or "onec",
            config=config,
            state=self.ctx.state,
            settings=self.ctx.settings,
            tmp_dir=self.ctx.tmp_dir,
        )
        return cls(ctx)

    async def http_probe(self) -> tuple[bool, str]:
        url = str(self.option("http_url", "") or "").strip()
        if not url:
            return True, ""
        auth = None
        if self.option("http_user"):
            auth = (str(self.option("http_user")), str(self.option("http_password", "")))
        try:
            async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as client:
                response = await client.get(url, auth=auth)
        except httpx.HTTPError as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}"
        return True, f"HTTP {response.status_code}"

    async def poll(self) -> PollResult:
        sql = self.dbms_connector()
        result = await sql.poll()
        events = list(result.events)
        metrics = dict(result.metrics)
        state = dict(result.state or self.ctx.state or {})
        http_fp = self.fingerprint("http")
        ok, http_message = await self.http_probe()
        if self.option("http_url"):
            metrics["http"] = http_message
            if ok:
                events.append(self.resolved(http_fp, message=ts("HTTP-сервис снова доступен")))
            else:
                events.append(
                    self.event(
                        title=ts("{name}: HTTP/OData-сервис недоступен", name=self.ctx.name),
                        message=http_message,
                        severity="critical",
                        type="onec.http.down",
                        fingerprint=http_fp,
                    )
                )
        log_path = str(self.option("log_path", "") or "").strip()
        if log_path and self.bool_option("log_enabled", True):
            folder = find_log_folder(Path(log_path))
            if folder is None:
                events.append(
                    self.event(
                        title=ts("{name}: журнал регистрации не найден", name=self.ctx.name),
                        message=log_path,
                        severity="warning",
                        type="onec.log.missing",
                        fingerprint=self.fingerprint("log-missing"),
                    )
                )
            else:
                events.append(self.resolved(self.fingerprint("log-missing")))
                log_list, state, count = await asyncio.to_thread(log_events, self, folder, state)
                events += log_list
                metrics["log_matches"] = count
        return PollResult(events=events, metrics=metrics, state=state, message=result.message)

    async def test(self) -> PollResult:
        sql = self.dbms_connector()
        result = await sql.test()
        message = result.message
        ok, http_message = await self.http_probe()
        if self.option("http_url"):
            message += ts("; HTTP: {state} ({details})", state=ts("доступен") if ok else ts("ошибка"), details=http_message)
        if self.option("log_path"):
            folder = find_log_folder(Path(str(self.option("log_path"))))
            message += ts("; журнал найден") if folder else ts("; журнал не найден")
        return PollResult(metrics=result.metrics, message=message)
