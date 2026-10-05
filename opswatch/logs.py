from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def ensure_streams() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def setup_logging(logs_dir: Path, level: str = "INFO", console: bool = True) -> None:
    ensure_streams()
    root = logging.getLogger()
    root.setLevel(level.upper() if isinstance(level, str) else level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(FORMAT)
    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(logs_dir / "opswatch.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if console and sys.stderr is not None and getattr(sys.stderr, "name", "") != os.devnull:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)
    for noisy in ("aiogram.event", "apscheduler.executors.default", "httpx", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
