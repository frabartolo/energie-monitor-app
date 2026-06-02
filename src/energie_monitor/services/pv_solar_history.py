from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

DEFAULT_HISTORY_RESOURCE = "pv_solar_history_2012_2025.json"


@lru_cache(maxsize=4)
def _load_history_file(path: str | None) -> dict[tuple[int, int], float]:
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        text = (
            resources.files("energie_monitor.data")
            .joinpath(DEFAULT_HISTORY_RESOURCE)
            .read_text(encoding="utf-8")
        )
        raw = json.loads(text)
    values: dict[str, Any] = raw.get("values") or {}
    out: dict[tuple[int, int], float] = {}
    for year_s, months in values.items():
        year = int(year_s)
        if not isinstance(months, dict):
            continue
        for month_s, val in months.items():
            if val is None:
                continue
            out[(year, int(month_s))] = float(val)
    return out


def get_pv_history_monthly(*, path: str | None = None, enabled: bool = True) -> dict[tuple[int, int], float]:
    if not enabled:
        return {}
    return _load_history_file(path)


def merge_monthly(
    live: dict[tuple[int, int], float],
    history: dict[tuple[int, int], float],
    *,
    start_year: int,
    end_year: int,
    history_through_year: int = 2024,
) -> dict[tuple[int, int], float | None]:
    """
    Referenz-Excel hat Vorrang bis einschließlich history_through_year;
    ab dem Folgejahr nur Volkszähler (Live). Fehlende Monate davor: Live als Fallback.
    """
    out: dict[tuple[int, int], float | None] = {}
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            key = (year, month)
            if year <= history_through_year and key in history:
                out[key] = history[key]
            else:
                out[key] = live.get(key)
    return out
