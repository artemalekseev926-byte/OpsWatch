from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from opswatch.backup.archive import BackupError
from opswatch.connectors import Connector
from opswatch.connectors.onec import is_file_locked

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


async def run_tool(command: list[str], env: dict[str, str] | None = None, timeout: int = 6 * 3600) -> str:
    merged = dict(os.environ)
    merged.update(env or {})
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            env=merged,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise BackupError(f"Не найдена программа {command[0]}. Укажите путь в настройках") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError("Превышено время выполнения резервного копирования") from exc
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        raise BackupError(f"{Path(command[0]).name} завершился с кодом {result.returncode}: {stderr[-1500:]}")
    return stderr


class BackupEngine:
    title = ""

    def __init__(self, connector: Connector, options: dict[str, Any], settings) -> None:
        self.connector = connector
        self.options = options or {}
        self.settings = settings

    def setting(self, key: str, default: str = "") -> str:
        if self.settings is None:
            return default
        return str(self.settings.get(key) or default)

    async def dump(self, workdir: Path) -> list[Path]:
        raise NotImplementedError


class MySQLDumpEngine(BackupEngine):
    title = "mysqldump"

    async def dump(self, workdir: Path) -> list[Path]:
        p = self.connector.params()
        tool = self.options.get("tool_path") or self.setting("mysqldump_path", "mysqldump")
        out = workdir / f"{p['database'] or 'all'}.sql"
        command = [
            tool,
            f"--host={p['host']}",
            f"--port={p['port']}",
            f"--user={p['user']}",
            "--single-transaction",
            "--routines",
            "--triggers",
            "--events",
            "--default-character-set=utf8mb4",
            f"--result-file={out}",
        ]
        command += [p["database"]] if p["database"] else ["--all-databases"]
        await run_tool(command, {"MYSQL_PWD": p["password"]})
        if not out.exists() or out.stat().st_size == 0:
            raise BackupError("mysqldump не создал файл дампа")
        return [out]


class PgDumpEngine(BackupEngine):
    title = "pg_dump"

    async def dump(self, workdir: Path) -> list[Path]:
        p = self.connector.params()
        tool = self.options.get("tool_path") or self.setting("pg_dump_path", "pg_dump")
        out = workdir / f"{p['database']}.dump"
        command = [
            tool,
            "-h",
            str(p["host"]),
            "-p",
            str(p["port"]),
            "-F",
            "c",
            "--no-password",
            "-f",
            str(out),
        ]
        if p["user"]:
            command += ["-U", p["user"]]
        command.append(p["database"])
        await run_tool(command, {"PGPASSWORD": p["password"], "PGCONNECT_TIMEOUT": "30"})
        if not out.exists() or out.stat().st_size == 0:
            raise BackupError("pg_dump не создал файл дампа")
        return [out]


class MSSQLBackupEngine(BackupEngine):
    title = "BACKUP DATABASE"

    async def dump(self, workdir: Path) -> list[Path]:
        server_dir = str(self.options.get("server_dir") or "").strip()
        if not server_dir:
            raise BackupError("Укажите каталог для BACKUP DATABASE на сервере SQL")
        local_dir = str(self.options.get("local_dir") or server_dir).strip()
        p = self.connector.params()
        name = f"{p['database']}_{datetime.now():%Y%m%d_%H%M%S}.bak"
        separator = "\\" if ("\\" in server_dir or ":" in server_dir) else "/"
        server_path = server_dir.rstrip("\\/") + separator + name
        await self.connector.execute_backup(server_path)
        source = Path(local_dir) / name
        if not source.exists():
            raise BackupError(f"Файл бэкапа не найден по пути {source}. Проверьте доступ к каталогу")
        target = workdir / name
        await asyncio.to_thread(shutil.move, str(source), str(target))
        return [target]


def _powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        timeout=600,
        creationflags=CREATE_NO_WINDOW,
    )
    output = result.stdout.decode("cp866", errors="replace").strip()
    if result.returncode != 0:
        raise BackupError("VSS: " + result.stderr.decode("cp866", errors="replace").strip()[-800:])
    return output


def vss_copy(source: Path, target: Path) -> None:
    if sys.platform != "win32":
        raise BackupError("Теневое копирование доступно только в Windows")
    source = source.resolve()
    drive = source.drive
    if not drive or len(drive) != 2:
        raise BackupError("Теневое копирование возможно только для локального диска")
    create = (
        f"$r = (Get-WmiObject -List Win32_ShadowCopy).Create('{drive}\\', 'ClientAccessible'); "
        "if ($r.ReturnValue -ne 0) { throw ('Win32_ShadowCopy.Create: ' + $r.ReturnValue) }; "
        "$s = Get-WmiObject Win32_ShadowCopy | Where-Object { $_.ID -eq $r.ShadowID }; "
        "Write-Output ($s.ID + '|' + $s.DeviceObject)"
    )
    output = _powershell(create).splitlines()[-1]
    shadow_id, device = output.split("|", 1)
    try:
        relative = str(source)[len(drive) + 1 :]
        shutil.copyfile(device.rstrip("\\") + "\\" + relative, target)
    finally:
        try:
            _powershell(
                f"Get-WmiObject Win32_ShadowCopy | Where-Object {{ $_.ID -eq '{shadow_id}' }} | ForEach-Object {{ $_.Delete() }}"
            )
        except BackupError:
            pass


class OneCFileEngine(BackupEngine):
    title = "Копирование 1Cv8.1CD"

    async def dump(self, workdir: Path) -> list[Path]:
        db_file: Path = self.connector.db_file
        if not db_file.exists():
            raise BackupError(f"Файл базы не найден: {db_file}")
        target = workdir / "1Cv8.1CD"
        if is_file_locked(db_file):
            if self.options.get("use_vss"):
                await asyncio.to_thread(vss_copy, db_file, target)
            else:
                raise BackupError(
                    "База занята пользователями. Включите теневое копирование (VSS) или запланируйте бэкап на нерабочее время"
                )
        else:
            await asyncio.to_thread(shutil.copy2, db_file, target)
        files = [target]
        if self.options.get("include_log"):
            log_dir = self.connector.folder / "1Cv8Log"
            if log_dir.is_dir():
                copy_dir = workdir / "1Cv8Log"
                await asyncio.to_thread(shutil.copytree, log_dir, copy_dir, dirs_exist_ok=True)
                files += [p for p in copy_dir.rglob("*") if p.is_file()]
        return files


class OneCServerEngine(BackupEngine):
    title = "Бэкап базы 1С через СУБД"

    async def dump(self, workdir: Path) -> list[Path]:
        sql = self.connector.dbms_connector()
        engine_cls = PgDumpEngine if sql.type == "postgresql" else MSSQLBackupEngine
        return await engine_cls(sql, self.options, self.settings).dump(workdir)


ENGINES: dict[str, type[BackupEngine]] = {
    "mysql": MySQLDumpEngine,
    "postgresql": PgDumpEngine,
    "mssql": MSSQLBackupEngine,
    "onec_file": OneCFileEngine,
    "onec_server": OneCServerEngine,
}
