from __future__ import annotations

from datetime import UTC, datetime

import httpx

from energie_monitor.config import Settings


async def heat_pump_energy_kwh(
    client: httpx.AsyncClient,
    settings: Settings,
    start: datetime,
    end: datetime,
) -> float | None:
    """
    Platzhalter-Integration: erwartet JSON { "energy_kwh": <float> } für den Zeitraum,
    oder 501 wenn nicht implementiert. Ohne URL → None.
    """
    if not settings.heat_pump_api_base_url:
        return None
    base = settings.heat_pump_api_base_url.rstrip("/")
    url = f"{base}/energy"
    r = await client.get(
        url,
        params={
            "from": start.astimezone(UTC).isoformat(),
            "to": end.astimezone(UTC).isoformat(),
        },
        timeout=settings.request_timeout_seconds,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "energy_kwh" in data:
        return float(data["energy_kwh"])
    return None
