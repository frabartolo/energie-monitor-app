from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from energie_monitor.config import Settings


def parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


async def ha_get_state(client: httpx.AsyncClient, settings: Settings, entity_id: str) -> dict[str, Any]:
    if not settings.homeassistant_base_url or not settings.homeassistant_token:
        raise RuntimeError("Home Assistant ist nicht konfiguriert (BASE_URL / TOKEN).")
    url = f"{settings.homeassistant_base_url.rstrip('/')}/api/states/{entity_id}"
    r = await client.get(
        url,
        headers={"Authorization": f"Bearer {settings.homeassistant_token}"},
        timeout=settings.request_timeout_seconds,
    )
    r.raise_for_status()
    return r.json()


async def ha_get_history(
    client: httpx.AsyncClient,
    settings: Settings,
    entity_id: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    if not settings.homeassistant_base_url or not settings.homeassistant_token:
        raise RuntimeError("Home Assistant ist nicht konfiguriert (BASE_URL / TOKEN).")
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    url = (
        f"{settings.homeassistant_base_url.rstrip('/')}/api/history/period/"
        f"{start_utc.isoformat().replace('+00:00', 'Z')}"
    )
    r = await client.get(
        url,
        params={
            "filter_entity_id": entity_id,
            "end_time": end_utc.isoformat().replace("+00:00", "Z"),
            "minimal_response": "1",
        },
        headers={"Authorization": f"Bearer {settings.homeassistant_token}"},
        timeout=settings.request_timeout_seconds,
    )
    r.raise_for_status()
    data = r.json()
    if not data or not isinstance(data, list):
        return []
    first = data[0]
    if isinstance(first, list):
        return [x for x in first if isinstance(x, dict)]
    return []


def ha_state_to_float(state: dict[str, Any]) -> float | None:
    raw = state.get("state")
    if raw in (None, "unknown", "unavailable"):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def ha_history_to_points(rows: list[dict[str, Any]]) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    for row in rows:
        ts = parse_ts(str(row["last_changed"]))
        v = ha_state_to_float(row)
        if v is not None:
            out.append((ts, v))
    out.sort(key=lambda x: x[0])
    return out
