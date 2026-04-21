from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from energie_monitor.config import Settings


def _ms(dt: datetime) -> int:
    return int(dt.astimezone(UTC).timestamp() * 1000)


async def vz_get_tuples(
    client: httpx.AsyncClient,
    settings: Settings,
    uuid: str,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, float]]:
    if not settings.volkszaehler_base_url:
        raise RuntimeError("Volkszähler ist nicht konfiguriert (VOLKSZAEHLER_BASE_URL).")
    base = settings.volkszaehler_base_url.rstrip("/")
    url = f"{base}/data/{uuid}.json"
    r = await client.get(
        url,
        params={"from": _ms(start), "to": _ms(end)},
        timeout=settings.request_timeout_seconds,
    )
    r.raise_for_status()
    payload: dict[str, Any] = r.json()
    data = payload.get("data") or {}
    tuples_raw: list[Any] = []
    if isinstance(data, dict):
        if "tuples" in data and isinstance(data["tuples"], list):
            tuples_raw = data["tuples"]
        else:
            for v in data.values():
                if isinstance(v, dict) and isinstance(v.get("tuples"), list):
                    tuples_raw = v["tuples"]
                    break
    out: list[tuple[datetime, float]] = []
    for item in tuples_raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        ts_ms, val = item[0], item[1]
        try:
            ts = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=UTC)
            v = float(val)
        except (TypeError, ValueError, OSError):
            continue
        out.append((ts, v))
    out.sort(key=lambda x: x[0])
    return out
