from opswatch.core.events import EventIn, make_fingerprint, normalize_category, normalize_severity
from opswatch.core.ingest import parse_alertmanager, parse_generic, parse_zabbix


def test_normalize_severity():
    assert normalize_severity("Disaster") == "critical"
    assert normalize_severity("HIGH") == "critical"
    assert normalize_severity("average") == "warning"
    assert normalize_severity("information") == "info"
    assert normalize_severity(5) == "critical"
    assert normalize_severity("2") == "warning"
    assert normalize_severity(None) == "warning"
    assert normalize_severity("непонятно", "info") == "info"


def test_normalize_category():
    assert normalize_category("1C") == "onec"
    assert normalize_category("db") == "database"
    assert normalize_category("bugs") == "bug"
    assert normalize_category("unknown") == "system"


def test_event_key_is_stable():
    a = EventIn(title="CPU", category="monitoring", source_name="zbx")
    b = EventIn(title="CPU", category="monitoring", source_name="zbx", message="other")
    assert a.key() == b.key()
    assert EventIn(title="x", external_id="42", source_id=1).key() == make_fingerprint("ext", 1, "42")
    assert EventIn(title="x", fingerprint="custom").key() == "custom"


def test_parse_zabbix_problem_and_recovery():
    problem = parse_zabbix(
        {"event_id": "77", "event_value": "1", "severity": "High", "host": "srv1", "trigger_name": "CPU > 90%", "message": "load"},
        source_id=3,
        source_name="Zabbix",
    )[0]
    assert problem.severity == "critical"
    assert problem.title == "srv1: CPU > 90%"
    assert problem.external_id == "zbx:77"
    assert not problem.resolve
    recovery = parse_zabbix({"event_id": "77", "event_value": "0", "severity": "High"}, 3, "Zabbix")[0]
    assert recovery.resolve and recovery.key() == problem.key()


def test_parse_zabbix_ignores_unexpanded_macros():
    event = parse_zabbix({"event_id": "{EVENT.ID}", "trigger_name": "Disk", "severity": "Warning"}, 1, "Z")[0]
    assert event.external_id is None
    assert event.severity == "warning"


def test_parse_alertmanager():
    payload = {
        "status": "firing",
        "commonLabels": {"job": "node"},
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "DiskFull", "severity": "critical", "instance": "web-1"},
                "annotations": {"summary": "Disk 95%", "description": "/var"},
                "fingerprint": "f1",
            },
            {"status": "resolved", "labels": {"alertname": "Load"}, "annotations": {}, "fingerprint": "f2"},
        ],
    }
    firing, resolved = parse_alertmanager(payload, 1, "AM")
    assert firing.title == "web-1: Disk 95%" and firing.severity == "critical"
    assert firing.external_id == "am:f1" and not firing.resolve
    assert resolved.resolve and resolved.external_id == "am:f2"


def test_parse_generic_variants():
    events = parse_generic({"text": "Касса не печатает", "level": "error", "category": "bug", "shop": "3"}, 1, "Hook")
    assert events[0].title == "Касса не печатает"
    assert events[0].severity == "critical"
    assert events[0].category == "bug"
    assert events[0].details["shop"] == "3"
    batch = parse_generic({"events": [{"title": "a"}, {"title": "b", "status": "resolved", "id": 5}]}, 1, "Hook")
    assert len(batch) == 2 and batch[1].resolve and batch[1].external_id == "5"
    assert parse_generic([{"title": "x"}], 1, "Hook", default_severity="info")[0].severity == "info"
