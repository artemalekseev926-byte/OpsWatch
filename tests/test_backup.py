import os
from pathlib import Path

import pytest
from sqlalchemy import select

from opswatch.backup import engines
from opswatch.backup.archive import BackupError, join_parts, make_archive, sha256_file, split_file, verify_archive
from opswatch.backup.engines import BackupEngine
from opswatch.models import BackupRecord, Event
from tests.conftest import drain, make_user


def test_archive_encrypt_verify_and_split(tmp_path):
    source = tmp_path / "dump.sql"
    source.write_bytes(os.urandom(200_000) + b"A" * 300_000)
    archive = make_archive([source], tmp_path / "out" / "backup.zip", "Pa$$w0rd", tmp_path)
    assert verify_archive(archive, "Pa$$w0rd") == 1
    with pytest.raises(BackupError):
        verify_archive(archive, "wrong")
    with pytest.raises(BackupError):
        verify_archive(archive, "")
    plain = make_archive([source], tmp_path / "plain.zip", "", tmp_path)
    assert verify_archive(plain) == 1
    parts = split_file(archive, 50_000, tmp_path / "parts")
    assert len(parts) > 1 and all(p.stat().st_size <= 50_000 for p in parts)
    joined = join_parts(parts, tmp_path / "joined.zip")
    assert sha256_file(joined) == sha256_file(archive)


def test_corrupted_archive_detected(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("x" * 10000)
    archive = make_archive([source], tmp_path / "a.zip", "pw", tmp_path)
    data = bytearray(archive.read_bytes())
    data[len(data) // 3] ^= 0xFF
    archive.write_bytes(bytes(data))
    with pytest.raises(BackupError):
        verify_archive(archive, "pw")


class FakeEngine(BackupEngine):
    size = 120_000
    fail = False

    async def dump(self, workdir: Path) -> list[Path]:
        if FakeEngine.fail:
            raise BackupError("mysqldump завершился с кодом 2: Access denied")
        target = workdir / "dump.sql"
        target.write_bytes(os.urandom(FakeEngine.size))
        return [target]


async def create_job(client, admin, **extra):
    source = (
        await client.post(
            "/api/sources",
            json={"name": "Shop", "type": "mysql", "config": {"host": "db", "database": "shop", "user": "u", "password": "p"}},
            headers=admin,
        )
    ).json()
    job = {"name": "Shop nightly", "source_id": source["id"], "schedule": "0 2 * * *", "keep_last": 2, "encrypt": True, "password": "secret", "destinations": {"telegram": True, "split": True}}
    job.update(extra)
    response = await client.post("/api/backups/jobs", json=job, headers=admin)
    assert response.status_code == 200, response.text
    return response.json()


async def test_backup_job_runs_rotates_and_delivers(rt, client, admin, monkeypatch):
    monkeypatch.setitem(engines.ENGINES, "mysql", FakeEngine)
    FakeEngine.fail = False
    FakeEngine.size = 120_000
    await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    job = await create_job(client, admin)
    for _ in range(3):
        record = await rt.backups.run(job["id"], manual=True)
        assert record.status == "ok" and record.verified
    assert Path(record.file_path).exists()
    assert verify_archive(Path(record.file_path), "secret") == 1
    assert {f["chat_id"] for f in rt.bot.files} == {111}
    async with rt.db.session() as session:
        records = (await session.execute(select(BackupRecord).order_by(BackupRecord.id))).scalars().all()
    assert [r.deleted for r in records] == [True, False, False]
    assert not Path(records[0].file_path).exists()
    listed = (await client.get("/api/backups/records", headers=admin)).json()["items"]
    assert listed[0]["available"] and listed[0]["delivery"]["telegram"]["sent"] == 1
    download = await client.get(f"/api/backups/records/{listed[0]['id']}/download", headers=admin)
    assert download.status_code == 200 and download.content[:2] == b"PK"


async def test_large_backup_is_split_for_telegram(rt, client, admin, monkeypatch):
    monkeypatch.setitem(engines.ENGINES, "mysql", FakeEngine)
    FakeEngine.fail = False
    FakeEngine.size = 2_600_000
    await rt.settings.update({"telegram_part_mb": 1})
    await make_user(client, admin, "sys", "sysadmin", chat_id=111, rt=rt)
    job = await create_job(client, admin)
    record = await rt.backups.run(job["id"])
    assert record.delivery["telegram"]["mode"] == "parts"
    assert len(rt.bot.files) >= 3
    assert all(f["size"] <= 1024 * 1024 for f in rt.bot.files)
    assert rt.bot.files[0]["name"].endswith(".zip.001")
    assert any("copy /b" in t["text"] for t in rt.bot.texts)
    assert not list(Path(rt.config.tmp_dir).glob("*.zip.0*"))


async def test_backup_failure_raises_critical_event(rt, client, admin, monkeypatch):
    monkeypatch.setitem(engines.ENGINES, "mysql", FakeEngine)
    FakeEngine.fail = True
    job = await create_job(client, admin)
    record = await rt.backups.run(job["id"])
    assert record.status == "failed" and "Access denied" in record.error
    async with rt.db.session() as session:
        failed = (await session.execute(select(Event).where(Event.type == "backup.failed"))).scalars().all()
    assert failed and failed[0].severity == "critical"
    FakeEngine.fail = False
    await rt.backups.run(job["id"])
    await drain(rt)
    async with rt.db.session() as session:
        failed = await session.get(Event, failed[0].id)
    assert failed.status == "resolved"


async def test_backup_job_validation(client, admin):
    job = await create_job(client, admin)
    bad_cron = {**job, "schedule": "every day", "password": ""}
    assert (await client.put(f"/api/backups/jobs/{job['id']}", json=bad_cron, headers=admin)).status_code == 422
    listed = (await client.get("/api/backups/jobs", headers=admin)).json()["items"]
    assert listed[0]["has_password"] and listed[0]["next_run"]
    webhook = (await client.post("/api/sources", json={"name": "hook", "type": "webhook"}, headers=admin)).json()
    wrong = {**job, "source_id": webhook["id"], "password": ""}
    assert (await client.put(f"/api/backups/jobs/{job['id']}", json=wrong, headers=admin)).status_code == 422
    no_password = {"name": "x", "source_id": job["source_id"], "schedule": "0 1 * * *", "encrypt": True, "password": ""}
    assert (await client.post("/api/backups/jobs", json=no_password, headers=admin)).status_code == 422


async def test_onec_file_backup_refuses_busy_base(tmp_path, monkeypatch):
    from opswatch.connectors import SourceContext, get_connector_class

    base = tmp_path / "base"
    base.mkdir()
    (base / "1Cv8.1CD").write_bytes(b"1C" * 1000)
    connector = get_connector_class("onec_file")(SourceContext(id=1, name="b", category="onec", config={"path": str(base)}))
    work = tmp_path / "work"
    work.mkdir()
    files = await engines.OneCFileEngine(connector, {}, None).dump(work)
    assert files[0].read_bytes() == b"1C" * 1000
    monkeypatch.setattr(engines, "is_file_locked", lambda path: True)
    with pytest.raises(BackupError, match="занята"):
        await engines.OneCFileEngine(connector, {}, None).dump(work)
