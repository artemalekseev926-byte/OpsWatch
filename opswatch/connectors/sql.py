from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from urllib.parse import unquote, urlparse

from opswatch.connectors.base import Connector, ConnectorError, Field, PollResult, register
from opswatch.connectors.checks import ensure_read_only, json_value, run_checks
from opswatch.i18n import ts
from opswatch.sizes import human_size

ROW_LIMIT = 1000


def connection_fields(default_port: int, dsn_example: str) -> list[Field]:
    return [
        Field("host", "Сервер", placeholder="127.0.0.1", group="Подключение"),
        Field("port", "Порт", type="number", default=default_port, group="Подключение"),
        Field("database", "База данных", required=True, group="Подключение"),
        Field("user", "Пользователь", group="Подключение", help="Рекомендуется пользователь только с правами на чтение"),
        Field("password", "Пароль", type="password", secret=True, group="Подключение"),
        Field(
            "dsn",
            "Строка подключения",
            secret=True,
            placeholder=dsn_example,
            group="Подключение",
            help="Если указана — используется вместо полей выше",
        ),
        Field("timeout", "Таймаут, сек", type="number", default=15, group="Подключение"),
    ]


SIZE_FIELD = Field("size_warn_mb", "Предупреждать при размере больше, МБ", type="number", default=0, group="Контроль")
CHECKS_FIELD = Field(
    "checks",
    "SQL-проверки",
    type="checks",
    default=[],
    group="Проверки",
    help="Только SELECT. В режиме «Новые записи» можно использовать {last} — последнее обработанное значение ключа",
)


class SqlConnector(Connector):
    category = "database"
    supports_checks = True
    supports_backup = True
    default_port: ClassVar[int] = 0
    schemes: ClassVar[tuple[str, ...]] = ()

    def params(self) -> dict[str, Any]:
        dsn = (self.config.get("dsn") or "").strip()
        if dsn:
            parsed = urlparse(dsn)
            if self.schemes and parsed.scheme.split("+")[0] not in self.schemes:
                raise ConnectorError(ts("Строка подключения должна начинаться с {value}://", value=self.schemes[0]))
            return {
                "host": parsed.hostname or "127.0.0.1",
                "port": parsed.port or self.default_port,
                "database": unquote(parsed.path.lstrip("/")),
                "user": unquote(parsed.username or ""),
                "password": unquote(parsed.password or ""),
            }
        return {
            "host": self.option("host") or "127.0.0.1",
            "port": self.int_option("port", self.default_port) or self.default_port,
            "database": self.option("database") or "",
            "user": self.option("user") or "",
            "password": self.option("password") or "",
        }

    @property
    def timeout(self) -> int:
        return max(3, self.int_option("timeout", 15))

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def database_size(self) -> int | None:
        return None

    async def server_version(self) -> str:
        return ""

    async def _probe(self) -> tuple[str, int | None]:
        try:
            version = await asyncio.wait_for(self.server_version(), self.timeout + 5)
            size = await asyncio.wait_for(self.database_size(), self.timeout + 5)
        except ConnectorError:
            raise
        except asyncio.TimeoutError as exc:
            raise ConnectorError(ts("Превышено время ожидания ответа от сервера")) from exc
        except Exception as exc:
            raise ConnectorError(f"{type(exc).__name__}: {exc}") from exc
        return version, size

    async def poll(self) -> PollResult:
        version, size = await self._probe()
        metrics = {"version": version, "size": size, "size_human": human_size(size)}
        events = []
        warn_mb = self.int_option("size_warn_mb", 0)
        size_fp = self.fingerprint("size")
        if warn_mb and size is not None:
            if size > warn_mb * 1024 * 1024:
                events.append(
                    self.event(
                        title=ts("{name}: размер базы {human_size}", name=self.ctx.name, human_size=human_size(size)),
                        message=ts("Превышен порог {warn_mb} МБ", warn_mb=warn_mb),
                        severity="warning",
                        type="db.size",
                        fingerprint=size_fp,
                        details={"size": size, "threshold_mb": warn_mb},
                    )
                )
            else:
                events.append(self.resolved(size_fp))
        state = dict(self.ctx.state or {})
        checks = self.config.get("checks") or []
        if checks:
            check_events, state = await run_checks(self, self.fetch, checks, state)
            events += check_events
        return PollResult(events=events, metrics=metrics, state=state, message=f"{version} · {human_size(size)}")

    async def test(self) -> PollResult:
        version, size = await self._probe()
        return PollResult(
            metrics={"version": version, "size": size, "size_human": human_size(size)},
            message=ts("Подключение успешно: {version}, размер {human_size}", version=version, human_size=human_size(size)),
        )

    async def run_check_preview(self, check: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await self.fetch(ensure_read_only(check.get("query", "")).replace("{last}", "0"))
        return [{k: json_value(v) for k, v in row.items()} for row in rows[:20]]


@register
class MySQLConnector(SqlConnector):
    type = "mysql"
    title = "MySQL / MariaDB"
    description = "Доступность, размер базы и пользовательские SQL-проверки"
    default_port = 3306
    schemes = ("mysql", "mariadb")
    fields = connection_fields(3306, "mysql://reader:pass@10.0.0.5:3306/shop") + [SIZE_FIELD, CHECKS_FIELD]

    async def _connect(self):
        import aiomysql

        p = self.params()
        return await aiomysql.connect(
            host=p["host"],
            port=int(p["port"]),
            user=p["user"],
            password=p["password"],
            db=p["database"] or None,
            connect_timeout=self.timeout,
            autocommit=True,
            charset="utf8mb4",
        )

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        import aiomysql

        connection = await self._connect()
        try:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                try:
                    await cursor.execute("START TRANSACTION READ ONLY")
                except Exception:
                    pass
                await cursor.execute(query)
                rows = await cursor.fetchmany(ROW_LIMIT)
                try:
                    await cursor.execute("ROLLBACK")
                except Exception:
                    pass
                return [dict(r) for r in rows]
        finally:
            connection.close()

    async def server_version(self) -> str:
        rows = await self.fetch("SELECT VERSION() AS v")
        return f"MySQL {rows[0]['v']}" if rows else "MySQL"

    async def database_size(self) -> int | None:
        database = self.params()["database"]
        connection = await self._connect()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT COALESCE(SUM(data_length + index_length), 0) FROM information_schema.tables WHERE table_schema = %s",
                    (database,),
                )
                row = await cursor.fetchone()
                return int(row[0] or 0) if row else None
        finally:
            connection.close()


@register
class PostgresConnector(SqlConnector):
    type = "postgresql"
    title = "PostgreSQL"
    description = "Доступность, размер базы и пользовательские SQL-проверки"
    default_port = 5432
    schemes = ("postgresql", "postgres")
    fields = connection_fields(5432, "postgresql://reader:pass@10.0.0.6:5432/erp") + [SIZE_FIELD, CHECKS_FIELD]

    async def _connect(self):
        import asyncpg

        p = self.params()
        return await asyncpg.connect(
            host=p["host"],
            port=int(p["port"]),
            user=p["user"] or None,
            password=p["password"] or None,
            database=p["database"] or None,
            timeout=self.timeout,
            command_timeout=self.timeout * 4,
        )

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        connection = await self._connect()
        try:
            async with connection.transaction(readonly=True):
                cursor = await connection.cursor(query)
                rows = await cursor.fetch(ROW_LIMIT)
                return [dict(r) for r in rows]
        finally:
            await connection.close()

    async def server_version(self) -> str:
        rows = await self.fetch("SHOW server_version")
        return f"PostgreSQL {str(next(iter(rows[0].values()))).split(' ')[0]}" if rows else "PostgreSQL"

    async def database_size(self) -> int | None:
        rows = await self.fetch("SELECT pg_database_size(current_database()) AS size")
        return int(rows[0]["size"]) if rows else None


@register
class MSSQLConnector(SqlConnector):
    type = "mssql"
    title = "Microsoft SQL Server"
    description = "Доступность, размер базы и пользовательские SQL-проверки"
    default_port = 1433
    schemes = ("mssql", "sqlserver")
    fields = connection_fields(1433, "mssql://reader:pass@10.0.0.7:1433/Accounting") + [SIZE_FIELD, CHECKS_FIELD]

    def _fetch_sync(self, query: str) -> list[dict[str, Any]]:
        import pymssql

        p = self.params()
        connection = pymssql.connect(
            server=p["host"],
            port=str(p["port"]),
            user=p["user"],
            password=p["password"],
            database=p["database"],
            login_timeout=self.timeout,
            timeout=self.timeout * 4,
            charset="UTF-8",
        )
        try:
            cursor = connection.cursor(as_dict=True)
            cursor.execute(query)
            rows = cursor.fetchmany(ROW_LIMIT) if cursor.description else []
            connection.rollback()
            return [dict(r) for r in rows]
        finally:
            connection.close()

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_sync, query)

    async def server_version(self) -> str:
        rows = await self.fetch("SELECT CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(64)) AS v, CAST(SERVERPROPERTY('Edition') AS NVARCHAR(128)) AS e")
        if not rows:
            return "SQL Server"
        return f"SQL Server {rows[0]['v']} ({rows[0]['e']})"

    async def database_size(self) -> int | None:
        rows = await self.fetch("SELECT SUM(CAST(size AS BIGINT)) * 8192 AS size FROM sys.database_files")
        return int(rows[0]["size"] or 0) if rows else None

    async def execute_backup(self, server_path: str) -> None:
        def run() -> None:
            import pymssql

            p = self.params()
            connection = pymssql.connect(
                server=p["host"],
                port=str(p["port"]),
                user=p["user"],
                password=p["password"],
                database="master",
                login_timeout=self.timeout,
                timeout=0,
                autocommit=True,
            )
            try:
                cursor = connection.cursor()
                name = p["database"].replace("]", "]]")
                path = server_path.replace("'", "''")
                cursor.execute(f"BACKUP DATABASE [{name}] TO DISK = N'{path}' WITH COPY_ONLY, INIT, CHECKSUM")
                while cursor.nextset():
                    pass
            finally:
                connection.close()

        await asyncio.to_thread(run)
