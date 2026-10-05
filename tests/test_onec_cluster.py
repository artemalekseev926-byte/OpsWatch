from pathlib import Path

import pytest

from opswatch.connectors import ConnectorError, SourceContext, get_connector_class
from opswatch.connectors.onec_cluster import decode_output, parse_rac

DATA = Path(__file__).parent / "data"
SAMPLES = {
    ("cluster", "list"): "rac_cluster_list.txt",
    ("infobase", "summary"): "rac_infobase_list.txt",
    ("session", "list"): "rac_session_list.txt",
    ("process", "list"): "rac_process_list.txt",
}


def connector(state=None, **config):
    cls = get_connector_class("onec_cluster")
    base = {"ras_address": "srv1c:1545", "cluster_user": "admin", "cluster_password": "pw"}
    base.update(config)
    instance = cls(SourceContext(id=9, name="Кластер 1С", category="onec", config=base, state=state or {}))
    calls = []

    def fake(*args):
        calls.append(args)
        return (DATA / SAMPLES[(args[0], args[1])]).read_text(encoding="utf-8")

    instance.run_rac_sync = fake
    instance.calls = calls
    return instance


def test_parse_rac_blocks():
    items = parse_rac((DATA / "rac_infobase_list.txt").read_text(encoding="utf-8"))
    assert items == [
        {"infobase": "0d8e9f6a-1111-4c5e-9a39-0e3bd3d3a001", "name": "buh", "descr": "Бухгалтерия предприятия"},
        {"infobase": "0d8e9f6a-2222-4c5e-9a39-0e3bd3d3a002", "name": "zup", "descr": ""},
    ]


def test_decode_output_cp866():
    assert decode_output("Кластер".encode("cp866")) == "Кластер"
    assert decode_output("Кластер".encode("utf-8")) == "Кластер"


async def test_cluster_poll_events_and_metrics():
    instance = connector(call_warn_sec=60, memory_warn_mb=2000, performance_warn=50, sessions_warn=2)
    result = await instance.poll()
    titles = {e.type: e.title for e in result.events if not e.resolve}
    assert "Иванова @ BUH-PC01, buh" in titles["onec.cluster.long_call"]
    assert "Петров" in titles["onec.cluster.lock_wait"]
    lock = next(e for e in result.events if e.type == "onec.cluster.lock_wait")
    assert "Иванова" in lock.message
    assert "сеансов 3" in titles["onec.cluster.sessions"]
    assert "2500 МБ" in titles["onec.cluster.process_memory"]
    assert "(35)" in titles["onec.cluster.process_performance"]
    assert result.metrics["sessions"] == 3 and result.metrics["lock_waits"] == 1
    assert result.metrics["max_call_sec"] == 125.4
    assert result.metrics["process_memory_mb"] == 3000.0 and result.metrics["min_performance"] == 35
    assert ("session", "list", "--cluster=9b0a37ca-6e7c-4ef8-9f3e-cfa63d3e5e2c", "--cluster-user=admin", "--cluster-pwd=pw") in instance.calls
    assert len(result.state["open"]) == 5


async def test_cluster_resolves_cleared_problems():
    first = await connector(call_warn_sec=60).poll()
    second = await connector(state=first.state, call_warn_sec=1000, lock_wait=False).poll()
    resolved = [e for e in second.events if e.resolve]
    assert len(resolved) == 2
    assert second.state["open"] == []


async def test_infobase_filter_and_cluster_name():
    result = await connector(infobases="zup", call_warn_sec=60).poll()
    assert result.metrics["sessions"] == 1
    assert not [e for e in result.events if not e.resolve]
    with pytest.raises(ConnectorError):
        await connector(cluster_name="Другой").poll()
    test = await connector().test()
    assert "Локальный кластер" in test.message and "сеансов: 3" in test.message
