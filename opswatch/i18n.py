from __future__ import annotations

import json
import locale
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

LANGUAGES = ("ru", "en")
LANGUAGE_TITLES = {"ru": "Русский", "en": "English"}
LOCALES_DIR = Path(__file__).resolve().parent / "locales"

_request_language: ContextVar[str | None] = ContextVar("opswatch_language", default=None)
_default_language = "ru"


def normalize_language(value: Any) -> str:
    text = str(value or "").strip().lower()[:2]
    return text if text in LANGUAGES else ""


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, str]:
    if lang == "ru":
        return {}
    path = LOCALES_DIR / f"{lang}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


SLAVIC_LANGIDS = {0x19, 0x22, 0x23, 0x3F}


def _windows_language() -> str:
    try:
        import ctypes

        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return ""
    return "ru" if langid & 0x3FF in SLAVIC_LANGIDS else "en"


def system_language() -> str:
    env = normalize_language(os.environ.get("OPSWATCH_LANGUAGE"))
    if env:
        return env
    if sys.platform == "win32":
        detected = _windows_language()
        if detected:
            return detected
        try:
            code = locale.getlocale()[0] or ""
        except ValueError:
            code = ""
    else:
        code = next((os.environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(key)), "")
    lowered = code.lower()
    if not lowered or lowered.split(".")[0] in {"c", "posix"}:
        return "ru"
    if lowered.startswith(("ru", "uk", "be", "kk")) or "russian" in lowered:
        return "ru"
    return "en"


def set_default_language(lang: str) -> None:
    global _default_language
    _default_language = normalize_language(lang) or "ru"


def default_language() -> str:
    return _default_language


def set_request_language(lang: str | None):
    return _request_language.set(normalize_language(lang) or None)


def reset_request_language(token) -> None:
    _request_language.reset(token)


@contextmanager
def language(lang: str | None):
    token = _request_language.set(normalize_language(lang) or None)
    try:
        yield
    finally:
        _request_language.reset(token)


def current_language() -> str:
    return _request_language.get() or _default_language


def _format(translated: str, original: str, values: dict[str, Any]) -> str:
    if not values:
        return translated
    for template in (translated, original):
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            continue
    return original


def tr(text: str, lang: str | None = None, **values: Any) -> str:
    lang = normalize_language(lang) or current_language()
    translated = catalog(lang).get(text, text) if lang != "ru" else text
    return _format(translated, text, values)


def ts(text: str, **values: Any) -> str:
    lang = _default_language
    translated = catalog(lang).get(text, text) if lang != "ru" else text
    return _format(translated, text, values)


def tl(text: str, **values: Any) -> str:
    return tr(text, system_language(), **values)


_ = tr
