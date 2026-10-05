import os
import shutil
from urllib.parse import urlparse

import pytest

from opswatch.connectors import SourceContext, get_connector_class

DSN = os.environ.get("OPSWATCH_TEST_PG_DSN", "")

pytestmark = [pytest.mark.integration, pytest.mark.skipif(not DSN, reason="OPSWATCH_TEST_PG_DSN не задан")]


def connector(**config):
    cls = get_connector_class("postgresql")
    return cls(SourceContext(id=1, name="PG", category="database", config={"dsn": DSN, **config}))


async def test_postgres_poll_and_checks():
    result = await connector().test()
    assert "PostgreSQL" in result.message and result.metrics["size"] > 0
    checks = [{"name": "Один", "mode": "threshold", "query": "SELECT 1", "operator": ">=", "threshold": 1, "severity": "warning"}]
    poll = await connector(checks=checks).poll()
    assert any(not e.resolve and e.type == "check.threshold" for e in poll.events)


async def test_postgres_read_only_transaction():
    rows = await connector().fetch("SELECT current_setting('transaction_read_only') AS ro")
    assert rows[0]["ro"] == "on"


@pytest.mark.skipif(shutil.which("pg_dump") is None, reason="pg_dump не найден")
async def test_pg_dump_engine(tmp_path):
    from opswatch.backup.engines import PgDumpEngine

    files = await PgDumpEngine(connector(), {}, None).dump(tmp_path)
    assert files[0].stat().st_size > 0
    assert urlparse(DSN).path.lstrip("/") in files[0].name
