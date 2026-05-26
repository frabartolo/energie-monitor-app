from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.sources import homeassistant as ha
from energie_monitor.sources import volkszaehler as vz


@pytest.fixture()
def wallbox_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    settings = Settings(
        volkszaehler_base_url="http://vz.local",
        volkszaehler_uuid_haus="uuid-haus",
        volkszaehler_raw_unit="kWh",
        entity_id_eauto_energy="sensor.wallbox_energy",
        request_timeout_seconds=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz(_client, _settings, uuid: str, start: datetime, end: datetime):
        t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        if uuid == "uuid-haus":
            return [
                (t0, 100.0),
                (t0 + timedelta(hours=12), 110.0),
                (t0 + timedelta(days=1), 115.0),
                (t0 + timedelta(days=1, hours=12), 120.0),
                (t0 + timedelta(days=2), 130.0),
            ]
        return []

    async def fake_ha_history(_client, _settings, entity_id: str, start: datetime, end: datetime):
        t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        return [
            {"last_changed": t0.isoformat(), "state": "10.0"},
            {"last_changed": (t0 + timedelta(hours=12)).isoformat(), "state": "15.0"},
            {"last_changed": (t0 + timedelta(days=1)).isoformat(), "state": "18.0"},
            {"last_changed": (t0 + timedelta(days=1, hours=12)).isoformat(), "state": "22.0"},
            {"last_changed": (t0 + timedelta(days=2)).isoformat(), "state": "25.0"},
        ]

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz)
    monkeypatch.setattr(ha, "ha_get_history", fake_ha_history)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_wallbox_split_subtracts_consumption(wallbox_client: TestClient):
    start = "2026-05-01T00:00:00Z"
    end = "2026-05-03T00:00:00Z"
    r = wallbox_client.get(f"/api/v1/energy/wallbox-split?start={start}&end={end}")
    assert r.status_code == 200
    data = r.json()
    assert data["haus_gesamt_kwh"] == 30.0
    assert data["wallbox_kwh"] == 15.0
    assert data["haus_ohne_wallbox_kwh"] == 15.0


def test_haus_ohne_eauto_daily_buckets(wallbox_client: TestClient):
    start = "2026-05-01T00:00:00Z"
    end = "2026-05-03T00:00:00Z"
    r = wallbox_client.get(f"/api/v1/metrics/haus_ohne_eauto/aggregate/daily?start={start}&end={end}")
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    assert len(buckets) == 2
    assert buckets[0]["value_kwh"] == 5.0
    assert buckets[1]["value_kwh"] == 3.0
