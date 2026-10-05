from __future__ import annotations

import json
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


def set_default_language(lang: str) -> None:
    global _default_language
    _default_language = normalize_language(lang) or "ru"


def default_language() -> str:
    return _default_language


def set_request_language(lang: str | None):
    return _request_language.set(normalize_language(lang) or None)


def reset_request_language(token) -> None:
    _request_language.reset(token)


def current_language() -> str:
    return _request_language.get() or _default_language


def tr(text: str, lang: str | None = None, **values: Any) -> str:
    lang = normalize_language(lang) or current_language()
    translated = catalog(lang).get(text, text) if lang != "ru" else text
    if values:
        try:
            return translated.format(**values)
        except (KeyError, IndexError, ValueError):
            return text.format(**values)
    return translated


_ = tr
