import argparse

import pytest

from opswatch.desktop.launcher import normalize_url, selftest
from opswatch.desktop.winservice import usage


def test_normalize_url():
    assert normalize_url("192.168.1.10") == "http://192.168.1.10:8765"
    assert normalize_url("https://ops.example.com/") == "https://ops.example.com"
    assert normalize_url("srv01") == "http://srv01:8765"
    assert normalize_url("http://srv:9000") == "http://srv:9000"
    assert normalize_url("") == ""


def test_service_usage_mentions_commands():
    for command in ("install", "start", "stop", "remove", "run"):
        assert command in usage()


def test_selftest_runs_server(tmp_path):
    report = tmp_path / "report.txt"
    code = selftest(argparse.Namespace(report=str(report)))
    text = report.read_text(encoding="utf-8")
    assert code == 0, text
    assert "health: OK" in text and "login: 200" in text


def test_icon_generation(tmp_path):
    pytest.importorskip("PIL")
    from opswatch.desktop.icon import save_ico, save_png

    assert save_ico(tmp_path / "a.ico").stat().st_size > 1000
    assert save_png(tmp_path / "a.png", 64).stat().st_size > 100
