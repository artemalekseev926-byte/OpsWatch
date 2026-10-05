import sqlite3
from datetime import datetime

from opswatch.connectors import SourceContext, get_connector_class
from opswatch.connectors.onec_log import LgdReader, LgpReader, find_log_folder, parse_braces, split_records

LGF = '﻿1CV8LOG(ver 2.0)\n00000000-0000-0000-0000-000000000000\n\n{1,8d2e7bb1-0000-0000-0000-000000000000,"Иванова",1},\n{2,"BUH-PC",1},\n{3,"1CV8C",1},\n{4,"_$Job$_.Fail",1},\n{4,"_$Session$_.Start",2},\n'


def lgp_record(level: str, comment: str, event: int = 1) -> str:
    return (
        '{20260105120000,N,\n{0,0},1,1,1,1,' + str(event) + ',' + level + ',"' + comment.replace('"', '""') + '",0,\n{"U"},"",1,1,0,1,0,\n{0}\n},\n'
    )


def test_parse_braces_handles_quotes_and_nesting():
    record, _ = parse_braces('{1,"a ""quoted"", text",{2,3},"x{y}"}')
    assert record == ["1", 'a "quoted", text', ["2", "3"], "x{y}"]
    records, consumed = split_records('{1,"}"},\n{2,{3}},\n{4,')
    assert len(records) == 2 and consumed > 0


def test_lgp_reader_incremental(tmp_path):
    folder = tmp_path / "1Cv8Log"
    folder.mkdir()
    (folder / "1Cv8.lgf").write_text(LGF, encoding="utf-8")
    log_file = folder / "20260105000000.lgp"
    log_file.write_text("﻿1CV8LOG(ver 2.0)\n00000000-0000-0000-0000-000000000000\n\n" + lgp_record("I", "start", 2), encoding="utf-8")
    reader = LgpReader(folder)
    entries, state = reader.read({})
    assert entries == [] and state["lgp_offset"] == log_file.stat().st_size
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(lgp_record("E", 'Ошибка "обмена" с банком'))
        handle.write('{20260105120001,N,\n{0,0},1,1')
    entries, state = reader.read(state)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.level == "error" and entry.event == "_$Job$_.Fail" and entry.user == "Иванова"
    assert entry.comment == 'Ошибка "обмена" с банком'
    assert entry.event_title == "Фоновое задание. Ошибка выполнения"
    entries, state2 = reader.read(state)
    assert entries == [] and state2 == state
    (folder / "20260106000000.lgp").write_text("﻿1CV8LOG(ver 2.0)\nx\n\n" + lgp_record("W", "warn"), encoding="utf-8")
    entries, state3 = reader.read(state)
    assert [e.level for e in entries] == ["warning"]
    assert state3["lgp_file"] == "20260106000000.lgp"


def make_lgd(path, base: int = 1):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE EventLog(rowID INTEGER PRIMARY KEY, severity INTEGER, date INTEGER, userCode INTEGER, computerCode INTEGER,
            appCode INTEGER, eventCode INTEGER, comment TEXT, dataPresentation TEXT);
        CREATE TABLE EventCodes(code INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE UserCodes(code INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE ComputerCodes(code INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE AppCodes(code INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO EventCodes VALUES (1, '_$Session$_.Start'), (2, '_$Job$_.Fail');
        INSERT INTO UserCodes VALUES (1, 'Админ');
        INSERT INTO ComputerCodes VALUES (1, 'SRV');
        INSERT INTO AppCodes VALUES (1, 'BackgroundJob');
        """
    )
    stamp = int((datetime(2026, 1, 5, 12, 0) - datetime(1, 1, 1)).total_seconds() * 10000)
    for _ in range(3):
        db.execute("INSERT INTO EventLog(severity, date, userCode, computerCode, appCode, eventCode, comment) VALUES (?, ?, 1, 1, 1, 1, '')", (base, stamp))
    db.commit()
    return db, stamp


def test_lgd_reader_detects_base_and_reads_new_rows(tmp_path):
    for base in (0, 1):
        path = tmp_path / f"base{base}.lgd"
        db, stamp = make_lgd(path, base)
        reader = LgdReader(path)
        entries, state = reader.read({})
        assert entries == [] and state["lgd_row"] == 3
        db.execute("INSERT INTO EventLog(severity, date, userCode, computerCode, appCode, eventCode, comment) VALUES (?, ?, 1, 1, 1, 2, 'Таймаут')", (base + 2, stamp))
        db.commit()
        entries, state = reader.read(state)
        assert state["lgd_base"] == base
        assert len(entries) == 1
        assert entries[0].level == "error" and entries[0].event == "_$Job$_.Fail" and entries[0].comment == "Таймаут"
        assert entries[0].time == datetime(2026, 1, 5, 12, 0)
        db.close()


async def test_onec_file_connector(tmp_path):
    base = tmp_path / "Buh"
    (base / "1Cv8Log").mkdir(parents=True)
    (base / "1Cv8.1CD").write_bytes(b"\0" * 4096)
    db, stamp = make_lgd(base / "1Cv8Log" / "1Cv8.lgd")
    assert find_log_folder(base) == base / "1Cv8Log"
    cls = get_connector_class("onec_file")
    ctx = SourceContext(id=5, name="Бухгалтерия", category="onec", config={"path": str(base), "size_warn_mb": 0})
    first = await cls(ctx).poll()
    assert first.metrics["size"] == 4096 and first.metrics["in_use"] is False
    db.execute("INSERT INTO EventLog(severity, date, userCode, computerCode, appCode, eventCode, comment) VALUES (3, ?, 1, 1, 1, 2, 'Ошибка обмена')", (stamp,))
    db.commit()
    db.close()
    ctx.state = first.state
    second = await cls(ctx).poll()
    log_events = [e for e in second.events if e.type.startswith("onec.log")]
    assert len(log_events) == 1
    assert log_events[0].severity == "warning" and "Ошибка обмена" in log_events[0].message
    test = await cls(ctx).test()
    assert "База найдена" in test.message


async def test_onec_file_connector_missing_base(tmp_path):
    cls = get_connector_class("onec_file")
    ctx = SourceContext(id=6, name="x", category="onec", config={"path": str(tmp_path / "nope")})
    try:
        await cls(ctx).poll()
    except Exception as exc:
        assert "недоступен" in str(exc)
    else:
        raise AssertionError("expected error")
