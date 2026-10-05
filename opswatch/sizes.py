from __future__ import annotations

from opswatch.i18n import ts

UNITS = ("Б", "КБ", "МБ", "ГБ", "ТБ")


def human_size(size: int | float | None) -> str:
    if size is None:
        return "—"
    value = float(size)
    last = len(UNITS) - 1
    for index, unit in enumerate(UNITS):
        if value < 1024 or index == last:
            return f"{value:.0f} {ts(unit)}" if index == 0 else f"{value:.1f} {ts(unit)}"
        value /= 1024
    return f"{value:.1f} {ts(UNITS[last])}"
