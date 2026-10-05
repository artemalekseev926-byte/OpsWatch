from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from importlib.metadata import entry_points
from pathlib import Path

from opswatch.connectors.base import (
    REGISTRY,
    Connector,
    ConnectorError,
    Field,
    PollResult,
    SourceContext,
    register,
)

log = logging.getLogger(__name__)

BUILTIN_MODULES = (
    "opswatch.connectors.sql",
    "opswatch.connectors.onec",
    "opswatch.connectors.onec_cluster",
    "opswatch.connectors.monitoring",
)

_loaded = False


def load_connectors(plugins_dir: Path | None = None) -> dict[str, type[Connector]]:
    global _loaded
    if not _loaded:
        for module in BUILTIN_MODULES:
            importlib.import_module(module)
        try:
            for entry in entry_points(group="opswatch.connectors"):
                try:
                    entry.load()
                except Exception:
                    log.exception("Не удалось загрузить коннектор %s", entry.name)
        except Exception:
            log.debug("entry points unavailable", exc_info=True)
        _loaded = True
    if plugins_dir and Path(plugins_dir).is_dir():
        for path in sorted(Path(plugins_dir).glob("*.py")):
            name = f"opswatch_plugin_{path.stem}"
            if name in sys.modules:
                continue
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
                log.info("Загружен плагин %s", path.name)
            except Exception:
                log.exception("Ошибка загрузки плагина %s", path)
    return REGISTRY


def get_connector_class(kind: str) -> type[Connector]:
    load_connectors()
    if kind not in REGISTRY:
        raise ConnectorError(f"Неизвестный тип источника: {kind}")
    return REGISTRY[kind]


__all__ = [
    "Connector",
    "ConnectorError",
    "Field",
    "PollResult",
    "SourceContext",
    "REGISTRY",
    "register",
    "load_connectors",
    "get_connector_class",
]
