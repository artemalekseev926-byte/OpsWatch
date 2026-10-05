from datetime import timedelta

from opswatch.core.metrics import MetricStore, bucketize, numeric_metrics
from opswatch.db import utcnow
from opswatch.models import Source
from tests.conftest import make_user


def test_numeric_metrics_filters_text_and_flags():
    values = numeric_metrics({"size": 1024, "version": "16", "in_use": True, "latency_ms": 12.5, "received": 4, "custom": 3})
    assert values == {"size": 1024.0, "latency_ms": 12.5, "custom": 3.0}


def test_bucketize_averages_values():
    start = utcnow()
    rows = [(start + timedelta(seconds=10), 1.0), (start + timedelta(seconds=20), 3.0), (start + timedelta(seconds=400), 10.0)]
    points = bucketize(rows, start, 300)
    assert [round(p[1], 2) for p in points] == [2.0, 10.0]


async def make_source(rt, category="database", visible_roles=None) -> int:
    async with rt.db.session() as session:
        source = Source(name="ERP", type="postgresql", category=category, config={}, visible_roles=visible_roles or [])
        session.add(source)
        await session.commit()
        return source.id


async def test_record_respects_interval_and_cleanup(rt):
    source_id = await make_source(rt)
    store = MetricStore(rt.db, min_interval=300)
    now = utcnow() - timedelta(days=40)
    assert await store.record(source_id, {"size": 100, "version": "x"}, now) == 1
    assert await store.record(source_id, {"size": 110}, now + timedelta(seconds=60)) == 0
    assert await store.record(source_id, {"size": 120}, now + timedelta(seconds=301)) == 1
    recent = utcnow()
    await store.record(source_id, {"size": 200, "latency_ms": 5}, recent)
    series = {s["name"]: s for s in await store.series(source_id)}
    assert series["size"]["points"] == 3 and series["size"]["last"] == 200
    assert series["size"]["title"] == "Размер базы" and series["latency_ms"]["unit"] == "ms"
    assert await store.cleanup(30) == 2
    series = {s["name"]: s for s in await store.series(source_id)}
    assert series["size"]["points"] == 1


async def test_metrics_api_and_visibility(rt, client, admin):
    source_id = await make_source(rt)
    hidden_id = await make_source(rt, visible_roles=["admin"])
    start = utcnow() - timedelta(hours=5)
    store = MetricStore(rt.db, min_interval=0)
    for hour in range(6):
        await store.record(source_id, {"size": 1000 + hour * 100}, start + timedelta(hours=hour))
        await store.record(hidden_id, {"size": 5}, start + timedelta(hours=hour))
    listing = (await client.get(f"/api/sources/{source_id}/metrics", headers=admin)).json()
    assert listing["series"][0]["name"] == "size" and listing["series"][0]["primary"]
    points = (await client.get(f"/api/sources/{source_id}/metrics/size?period=24h", headers=admin)).json()
    assert points["unit"] == "bytes" and len(points["points"]) == 6
    assert points["points"][-1][1] == 1500
    assert (await client.get(f"/api/sources/{source_id}/metrics/size?period=1y", headers=admin)).status_code == 422
    sparks = (await client.get("/api/metrics/sparklines?category=database", headers=admin)).json()
    assert str(source_id) in sparks and len(sparks[str(source_id)]["values"]) >= 2
    viewer = await make_user(client, admin, "boss", "manager")
    assert (await client.get(f"/api/sources/{source_id}/metrics", headers=viewer["headers"])).status_code == 200
    assert (await client.get(f"/api/sources/{hidden_id}/metrics", headers=viewer["headers"])).status_code == 404
    accountant = await make_user(client, admin, "buh", "accountant")
    assert (await client.get(f"/api/sources/{source_id}/metrics", headers=accountant["headers"])).status_code == 404


async def test_poll_records_metrics(rt, client, admin, monkeypatch):
    from opswatch.connectors import PollResult
    from opswatch.connectors.monitoring import HttpCheckConnector

    async def fake_poll(self):
        return PollResult(metrics={"status": 200, "latency_ms": 42})

    monkeypatch.setattr(HttpCheckConnector, "poll", fake_poll)
    source = (await client.post("/api/sources", json={"name": "Site", "type": "http_check", "config": {"url": "http://x"}}, headers=admin)).json()
    await rt.sources.poll(source["id"])
    series = await rt.metrics.series(source["id"])
    assert [s["name"] for s in series] == ["latency_ms"]
