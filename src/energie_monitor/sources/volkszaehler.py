from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from energie_monitor.config import Settings

# Große Zeiträume in einem Request lösen bei Volkszähler oft 504 aus → chunking.
DEFAULT_CHUNK_DAYS = 3
MAX_PARALLEL_CHUNKS = 8


def volkszaehler_value_to_kwh(settings: Settings, raw: float) -> float:
    """Volkszähler-Kanäle liefern hier Wh; Middleware/API sprechen kWh."""
    if settings.volkszaehler_raw_unit == "Wh":
        return raw / 1000.0
    return raw


def _ms(dt: datetime) -> int:
    return int(dt.astimezone(UTC).timestamp() * 1000)


def _parse_tuples_from_payload(settings: Settings, payload: dict[str, Any]) -> list[tuple[datetime, float]]:
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
            v = volkszaehler_value_to_kwh(settings, float(val))
        except (TypeError, ValueError, OSError):
            continue
        out.append((ts, v))
    return out


async def _vz_fetch_chunk(
    client: httpx.AsyncClient,
    settings: Settings,
    uuid: str,
    start: datetime,
    end: datetime,
    *,
    group: str | None = None,
    tuples: int | None = None,
    options: str | None = None,
) -> list[tuple[datetime, float]]:
    base = settings.volkszaehler_base_url.rstrip("/")
    url = f"{base}/data/{uuid}.json"
    params: dict[str, object] = {"from": _ms(start), "to": _ms(end)}
    if group:
        params["group"] = group
    if tuples is not None:
        params["tuples"] = int(tuples)
    if options:
        params["options"] = options
    r = await client.get(
        url,
        params=params,
        timeout=settings.request_timeout_seconds,
    )
    r.raise_for_status()
    return _parse_tuples_from_payload(settings, r.json())


def _merge_points(chunks: list[list[tuple[datetime, float]]]) -> list[tuple[datetime, float]]:
    by_ts: dict[datetime, float] = {}
    for part in chunks:
        for ts, val in part:
            by_ts[ts] = val
    return sorted(by_ts.items(), key=lambda x: x[0])


def _chunk_ranges(
    start: datetime, end: datetime, chunk_days: int
) -> list[tuple[datetime, datetime]]:
    start_u = start.astimezone(UTC)
    end_u = end.astimezone(UTC)
    ranges: list[tuple[datetime, datetime]] = []
    cursor = start_u
    step = timedelta(days=chunk_days)
    while cursor < end_u:
        chunk_end = min(cursor + step, end_u)
        ranges.append((cursor, chunk_end))
        cursor = chunk_end
    return ranges


async def vz_get_tuples(
    client: httpx.AsyncClient,
    settings: Settings,
    uuid: str,
    start: datetime,
    end: datetime,
    *,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    group: str | None = None,
    tuples: int | None = None,
    options: str | None = None,
) -> list[tuple[datetime, float]]:
    if not settings.volkszaehler_base_url:
        raise RuntimeError("Volkszähler ist nicht konfiguriert (VOLKSZAEHLER_BASE_URL).")
    start_u = start.astimezone(UTC)
    end_u = end.astimezone(UTC)
    if end_u <= start_u:
        return []

    if end_u - start_u <= timedelta(days=chunk_days):
        try:
            return await _vz_fetch_chunk(
                client,
                settings,
                uuid,
                start_u,
                end_u,
                group=group,
                tuples=tuples,
                options=options,
            )
        except httpx.HTTPError:
            return []

    ranges = _chunk_ranges(start_u, end_u, chunk_days)
    sem = asyncio.Semaphore(MAX_PARALLEL_CHUNKS)

    async def load_one(chunk_start: datetime, chunk_end: datetime) -> list[tuple[datetime, float]]:
        async with sem:
            try:
                return await _vz_fetch_chunk(
                    client,
                    settings,
                    uuid,
                    chunk_start,
                    chunk_end,
                    group=group,
                    tuples=tuples,
                    options=options,
                )
            except httpx.HTTPError:
                return []

    parts = await asyncio.gather(*(load_one(a, b) for a, b in ranges))
    return _merge_points(list(parts))
