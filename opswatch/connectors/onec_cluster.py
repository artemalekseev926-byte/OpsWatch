from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

from opswatch.connectors.base import Connector, ConnectorError, Field, PollResult, register
from opswatch.connectors.onec import find_platform_bin
from opswatch.core.events import EventIn
from opswatch.i18n import ts

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
EMPTY_UUID = "00000000-0000-0000-0000-000000000000"
MAX_SESSION_EVENTS = 15


def decode_output(raw: bytes) -> str:
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_rac(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip():
            if current:
                items.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('""', '"')
        current[key.strip()] = value
    if current:
        items.append(current)
    return items


def to_int(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return 0


def to_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


@register
class OneCClusterConnector(Connector):
    type = "onec_cluster"
    title = "1С: кластер серверов (RAS)"
    category = "onec"
    description = "Сеансы, долгие вызовы, ожидания на блокировках и рабочие процессы через сервер администрирования RAS"
    default_interval = 60
    fields = [
        Field("ras_address", "Адрес RAS", default="localhost:1545", placeholder="srv1c:1545", group="Подключение",
              help="Служба «Сервер администрирования 1С» (ras), обычно порт 1545"),
        Field("rac_path", "Путь к rac.exe или каталогу bin", type="path", group="Подключение",
              placeholder=r"C:\Program Files\1cv8\8.3.24.1691\bin\rac.exe", help="Пусто — найти автоматически"),
        Field("cluster_name", "Кластер", group="Подключение", help="Имя кластера. Пусто — все кластеры"),
        Field("cluster_user", "Администратор кластера", group="Подключение"),
        Field("cluster_password", "Пароль администратора кластера", type="password", secret=True, group="Подключение"),
        Field("infobases", "Только эти базы", group="Подключение", placeholder="buh, zup", help="Имена через запятую. Пусто — все базы"),
        Field("timeout", "Таймаут, сек", type="number", default=30, group="Подключение"),
        Field("sessions_warn", "Предупреждать при числе сеансов больше", type="number", default=0, group="Пороги",
              help="Например, число лицензий. 0 — не проверять"),
        Field("call_warn_sec", "Долгий серверный вызов, сек", type="number", default=60, group="Пороги", help="0 — не проверять"),
        Field("lock_wait", "Сообщать об ожиданиях на блокировках", type="bool", default=True, group="Пороги"),
        Field("memory_warn_mb", "Память рабочего процесса больше, МБ", type="number", default=0, group="Пороги", help="0 — не проверять"),
        Field("performance_warn", "Доступная производительность процесса меньше", type="number", default=0, group="Пороги",
              help="0 — не проверять"),
    ]

    def rac_executable(self) -> str:
        configured = str(self.option("rac_path", "") or "").strip()
        name = "rac.exe" if sys.platform == "win32" else "rac"
        if configured:
            path = Path(configured)
            return str(path / name) if path.is_dir() else str(path)
        settings_path = self.ctx.settings.get("onec_platform_path") if self.ctx.settings else ""
        bin_dir = find_platform_bin(str(settings_path or ""))
        if bin_dir is not None and (bin_dir / name).exists():
            return str(bin_dir / name)
        return name

    def auth_args(self) -> list[str]:
        args = []
        if self.option("cluster_user"):
            args.append(f"--cluster-user={self.option('cluster_user')}")
            if self.option("cluster_password"):
                args.append(f"--cluster-pwd={self.option('cluster_password')}")
        return args

    def run_rac_sync(self, *args: str) -> str:
        command = [self.rac_executable(), *args, str(self.option("ras_address", "localhost:1545"))]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=max(5, self.int_option("timeout", 30)),
                creationflags=CREATE_NO_WINDOW,
            )
        except FileNotFoundError as exc:
            raise ConnectorError(ts("Не найдена утилита rac. Укажите путь к rac.exe из каталога платформы 1С")) from exc
        except subprocess.TimeoutExpired as exc:
            raise ConnectorError(ts("Сервер администрирования RAS не ответил вовремя")) from exc
        output = decode_output(result.stdout)
        if result.returncode != 0:
            error = (decode_output(result.stderr) or output).strip()
            raise ConnectorError(ts("rac: {error}", error=error[-500:] or ts("код {code}", code=result.returncode)))
        return output

    async def rac(self, *args: str) -> list[dict[str, str]]:
        return parse_rac(await asyncio.to_thread(self.run_rac_sync, *args))

    async def clusters(self) -> list[dict[str, str]]:
        clusters = await self.rac("cluster", "list")
        name = str(self.option("cluster_name", "") or "").strip().lower()
        if name:
            clusters = [c for c in clusters if c.get("name", "").lower() == name or c.get("cluster") == name]
            if not clusters:
                raise ConnectorError(ts("Кластер «{option}» не найден", option=self.option('cluster_name')))
        return clusters

    async def snapshot(self) -> dict[str, Any]:
        clusters = await self.clusters()
        allowed = {x.strip().lower() for x in str(self.option("infobases", "") or "").split(",") if x.strip()}
        sessions: list[dict[str, str]] = []
        processes: list[dict[str, str]] = []
        infobase_names: dict[str, str] = {}
        for cluster in clusters:
            uuid = cluster.get("cluster", "")
            base = [f"--cluster={uuid}", *self.auth_args()]
            for infobase in await self.rac("infobase", "summary", "list", *base):
                infobase_names[infobase.get("infobase", "")] = infobase.get("name", "")
            for session in await self.rac("session", "list", *base):
                session["_cluster"] = cluster.get("name", uuid)
                session["_infobase"] = infobase_names.get(session.get("infobase", ""), session.get("infobase", ""))
                sessions.append(session)
            for process in await self.rac("process", "list", *base):
                process["_cluster"] = cluster.get("name", uuid)
                processes.append(process)
        if allowed:
            sessions = [s for s in sessions if s["_infobase"].lower() in allowed]
        return {"clusters": clusters, "sessions": sessions, "processes": processes, "infobases": infobase_names}

    def session_label(self, session: dict[str, str]) -> str:
        user = session.get("user-name") or ts("без имени")
        host = session.get("host") or ""
        return f"{user}{' @ ' + host if host else ''}, {session.get('_infobase') or '—'}"

    def evaluate(self, data: dict[str, Any], state: dict[str, Any]) -> tuple[list[EventIn], dict[str, Any], dict[str, Any]]:
        sessions = data["sessions"]
        processes = data["processes"]
        active: dict[str, EventIn] = {}
        sessions_by_id = {s.get("session-id"): s for s in sessions}
        call_limit = self.int_option("call_warn_sec", 60) * 1000
        long_calls = []
        lock_waits = []
        for session in sessions:
            duration = to_int(session.get("duration-current"))
            if call_limit and duration >= call_limit:
                long_calls.append((duration, session))
            blocker = to_int(session.get("blocked-by-dbms")) or to_int(session.get("blocked-by-ls"))
            if blocker and self.bool_option("lock_wait", True):
                lock_waits.append((blocker, session))
        for duration, session in sorted(long_calls, key=lambda item: -item[0])[:MAX_SESSION_EVENTS]:
            fp = self.fingerprint("call", session.get("session"))
            details = [ts("Длительность: {value} сек", value=duration // 1000)]
            if session.get("app-id"):
                details.append(ts("Приложение: {app_id}", app_id=session['app-id']))
            if session.get("current-service-name"):
                details.append(ts("Сервис: {current_service_name}", current_service_name=session['current-service-name']))
            if session.get("db-proc-info"):
                details.append(ts("СУБД: {db_proc_info}", db_proc_info=session['db-proc-info']))
            active[fp] = self.event(
                title=ts("Долгий серверный вызов: {session_label}", session_label=self.session_label(session)),
                message="\n".join(details),
                severity="warning",
                type="onec.cluster.long_call",
                fingerprint=fp,
                details={"session": session.get("session-id"), "infobase": session.get("_infobase"), "duration_ms": duration},
            )
        for blocker, session in lock_waits[:MAX_SESSION_EVENTS]:
            fp = self.fingerprint("lock", session.get("session"))
            other = sessions_by_id.get(str(blocker))
            culprit = self.session_label(other) if other else ts("сеанс {blocker}", blocker=blocker)
            kind = ts("СУБД") if to_int(session.get("blocked-by-dbms")) else ts("управляемой блокировке")
            active[fp] = self.event(
                title=ts("Ожидание на блокировке: {session_label}", session_label=self.session_label(session)),
                message=ts("Ожидает {kind}, блокирует: {culprit}", kind=kind, culprit=culprit),
                severity="warning",
                type="onec.cluster.lock_wait",
                fingerprint=fp,
                details={"session": session.get("session-id"), "blocked_by": blocker},
            )
        limit = self.int_option("sessions_warn", 0)
        if limit and len(sessions) > limit:
            fp = self.fingerprint("sessions")
            active[fp] = self.event(
                title=ts("{name}: сеансов {len} при пороге {limit}", name=self.ctx.name, len=len(sessions), limit=limit),
                message=ts("Проверьте количество лицензий и зависшие сеансы"),
                severity="warning",
                type="onec.cluster.sessions",
                fingerprint=fp,
            )
        memory_limit = self.int_option("memory_warn_mb", 0)
        performance_limit = self.int_option("performance_warn", 0)
        memory_total = 0.0
        performances = []
        for process in processes:
            memory_mb = to_int(process.get("memory-size")) / 1024
            memory_total += memory_mb
            name = f"rphost {process.get('host', '')}:{process.get('port', '')} (pid {process.get('pid', '?')})"
            if process.get("turned-on") == "yes" and process.get("running") == "no":
                fp = self.fingerprint("proc-down", process.get("host"), process.get("port"))
                active[fp] = self.event(
                    title=ts("Рабочий процесс не работает: {name}", name=name),
                    severity="critical",
                    type="onec.cluster.process_down",
                    fingerprint=fp,
                )
            if memory_limit and memory_mb > memory_limit:
                fp = self.fingerprint("proc-memory", process.get("host"), process.get("port"))
                active[fp] = self.event(
                    title=ts("Рабочий процесс занимает {memory_mb:.0f} МБ: {name}", memory_mb=memory_mb, name=name),
                    message=ts("Порог {memory_limit} МБ", memory_limit=memory_limit),
                    severity="warning",
                    type="onec.cluster.process_memory",
                    fingerprint=fp,
                )
            performance = to_int(process.get("available-perfomance") or process.get("available-performance"))
            if process.get("running") != "no":
                performances.append(performance)
            if performance_limit and process.get("running") != "no" and performance < performance_limit:
                fp = self.fingerprint("proc-performance", process.get("host"), process.get("port"))
                active[fp] = self.event(
                    title=ts("Низкая производительность ({performance}): {name}", performance=performance, name=name),
                    message=ts("Порог {performance_limit}", performance_limit=performance_limit),
                    severity="warning",
                    type="onec.cluster.process_performance",
                    fingerprint=fp,
                )
        events, new_state = self.track(state, "open", active)
        metrics = {
            "sessions": len(sessions),
            "sessions_active": sum(1 for s in sessions if to_int(s.get("calls-last-5min")) or to_int(s.get("duration-current"))),
            "lock_waits": len(lock_waits),
            "max_call_sec": max((to_int(s.get("duration-current")) for s in sessions), default=0) / 1000,
            "processes": len(processes),
            "process_memory_mb": round(memory_total, 1),
            "infobases": len(data["infobases"]),
        }
        if performances:
            metrics["min_performance"] = min(performances)
        return events, new_state, metrics

    async def poll(self) -> PollResult:
        data = await self.snapshot()
        events, state, metrics = self.evaluate(data, dict(self.ctx.state or {}))
        message = ts("Сеансов: {sessions}, процессов: {processes}", sessions=metrics['sessions'], processes=metrics['processes'])
        return PollResult(events=events, metrics=metrics, state=state, message=message)

    async def test(self) -> PollResult:
        data = await self.snapshot()
        names = ", ".join(c.get("name", "?") for c in data["clusters"])
        return PollResult(
            metrics={"sessions": len(data["sessions"]), "processes": len(data["processes"])},
            message=ts("Кластеры: {names}; баз: {bases}, сеансов: {sessions}, рабочих процессов: {processes}", names=names, bases=len(data['infobases']), sessions=len(data['sessions']), processes=len(data['processes'])),
        )
