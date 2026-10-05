import pytest

from opswatch.connectors import ConnectorError, SourceContext, get_connector_class
from opswatch.connectors.checks import ensure_read_only, run_checks


def connector():
    cls = get_connector_class("postgresql")
    return cls(SourceContext(id=7, name="ERP", category="database", config={}))


def test_read_only_guard():
    assert ensure_read_only("  SELECT 1;  ") == "SELECT 1"
    assert ensure_read_only("-- comment\nWITH a AS (SELECT 1) SELECT * FROM a")
    for query in ("DELETE FROM t", "SELECT 1; DROP TABLE t", "UPDATE t SET a=1", "", "SELECT * INTO x FROM t"):
        with pytest.raises(ConnectorError):
            ensure_read_only(query)
    assert ensure_read_only("SELECT 'delete me' AS note")


async def test_new_rows_baseline_then_events():
    rows = [{"id": 1, "number": "A-1"}, {"id": 2, "number": "A-2"}]

    async def fetch(query):
        return list(rows)

    checks = [{"name": "Заказы", "mode": "new_rows", "query": "SELECT id, number FROM orders ORDER BY id DESC LIMIT 50", "key_column": "id", "title": "Заказ {number}"}]
    events, state = await run_checks(connector(), fetch, checks, {})
    assert [e for e in events if not e.resolve] == []
    assert state["check:Заказы"] == 2
    rows.append({"id": 3, "number": "A-3"})
    events, state = await run_checks(connector(), fetch, checks, state)
    created = [e for e in events if not e.resolve]
    assert [e.title for e in created] == ["Заказ A-3"]
    assert state["check:Заказы"] == 3


async def test_new_rows_summary_when_many():
    async def fetch(query):
        assert "> 0" in query
        return [{"id": i} for i in range(1, 21)]

    checks = [{"name": "Лог", "mode": "new_rows", "query": "SELECT id FROM log WHERE id > {last}", "key_column": "id"}]
    events, state = await run_checks(connector(), fetch, checks, {"check:Лог": 0})
    created = [e for e in events if not e.resolve]
    assert len(created) == 6
    assert "ещё 15" in created[-1].title


async def test_threshold_violation_and_recovery():
    value = {"v": 10}

    async def fetch(query):
        return [{"count": value["v"]}]

    checks = [{"name": "Ошибки", "mode": "threshold", "query": "SELECT COUNT(*) FROM jobs", "operator": ">", "threshold": 3, "severity": "critical"}]
    events, _ = await run_checks(connector(), fetch, checks, {})
    alert = [e for e in events if not e.resolve]
    assert alert and alert[0].severity == "critical" and "10" in alert[0].title
    value["v"] = 1
    events, _ = await run_checks(connector(), fetch, checks, {})
    assert all(e.resolve for e in events)
    assert events[0].fingerprint == alert[0].fingerprint


async def test_rows_exist_and_errors():
    async def fetch(query):
        return [{"id": 5, "status": "failed"}]

    async def broken(query):
        raise RuntimeError("relation does not exist")

    checks = [{"name": "Сбои", "mode": "rows_exist", "query": "SELECT * FROM jobs WHERE status='failed'"}]
    events, _ = await run_checks(connector(), fetch, checks, {})
    assert any(not e.resolve and "найдено строк: 1" in e.title for e in events)
    events, _ = await run_checks(connector(), broken, checks, {})
    error = [e for e in events if not e.resolve]
    assert error and error[0].type == "check.error" and "relation" in error[0].message
    disabled = [{**checks[0], "enabled": False}]
    events, _ = await run_checks(connector(), broken, disabled, {})
    assert events == []


def test_dsn_parsing():
    cls = get_connector_class("mysql")
    instance = cls(SourceContext(id=1, name="m", category="database", config={"dsn": "mysql://user:p%40ss@db.local:3307/shop"}))
    assert instance.params() == {"host": "db.local", "port": 3307, "database": "shop", "user": "user", "password": "p@ss"}
    wrong = cls(SourceContext(id=1, name="m", category="database", config={"dsn": "postgresql://u@h/db"}))
    with pytest.raises(ConnectorError):
        wrong.params()
