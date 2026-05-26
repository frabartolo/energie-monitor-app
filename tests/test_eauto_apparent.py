from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.sources import homeassistant as ha
from energie_monitor.sources import volkszaehler as vz


@pytest.fixture()
def apparent_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    monkeypatch.setenv("EAUTO_MEASUREMENT", "apparent_power_va")
    settings = Settings(
        volkszaehler_base_url="http://vz.local",
        volkszaehler_uuid_haus="uuid-haus",
        volkszaehler_raw_unit="kWh",
        homeassistant_base_url="http://ha.local",
        homeassistant_token="test-token",
        entity_id_eauto_energy="sensor.wallbox_total_apparent_power",
        eauto_measurement="apparent_power_va",
        request_timeout_seconds=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz(_client, _settings, uuid: str, start: datetime, end: datetime):
        t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        t_prev = t0 - timedelta(hours=1)
        if uuid == "uuid-haus":
            return [
                (t_prev, 90.0),
                (t0, 100.0),
                (t0 + timedelta(hours=12), 110.0),
                (t0 + timedelta(days=1) - timedelta(seconds=1), 115.0),
                (t0 + timedelta(days=1), 120.0),
                (t0 + timedelta(days=1, hours=12), 130.0),
                (t0 + timedelta(days=2) - timedelta(seconds=1), 135.0),
                (t0 + timedelta(days=2), 140.0),
            ]
        return []

    async def fake_ha_history(_client, _settings, entity_id: str, start: datetime, end: datetime):
        t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        t_prev = t0 - timedelta(hours=1)
        return [
            {"last_changed": t_prev.isoformat(), "state": "500"},
            {"last_changed": t0.isoformat(), "state": "500"},
            {"last_changed": (t0 + timedelta(hours=12)).isoformat(), "state": "500"},
            {"last_changed": (t0 + timedelta(days=1) - timedelta(seconds=1)).isoformat(), "state": "500"},
            {"last_changed": (t0 + timedelta(days=1)).isoformat(), "state": "500"},
            {"last_changed": (t0 + timedelta(days=1, hours=12)).isoformat(), "state": "500"},
            {"last_changed": (t0 + timedelta(days=2) - timedelta(seconds=1)).isoformat(), "state": "500"},
            {"last_changed": (t0 + timedelta(days=2)).isoformat(), "state": "500"},
        ]

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz)
    monkeypatch.setattr(ha, "ha_get_history", fake_ha_history)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_eauto_daily_from_apparent_power(apparent_client: TestClient):
    start = "2026-05-01T00:00:00Z"
    end = "2026-05-03T00:00:00Z"
    r = apparent_client.get(f"/api/v1/metrics/eauto/aggregate/daily?start={start}&end={end}")
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    assert len(buckets) == 2
    assert buckets[0]["value_kwh"] == pytest.approx(12.0, rel=0.05)
    assert buckets[1]["value_kwh"] == pytest.approx(12.0, rel=0.05)


def test_haus_ohne_eauto_with_apparent_wallbox(apparent_client: TestClient):
    start = "2026-05-01T00:00:00Z"
    end = "2026-05-03T00:00:00Z"
    haus = apparent_client.get(
        f"/api/v1/metrics/haus_gesamt/aggregate/daily?start={start}&end={end}"
    ).json()["buckets"]
    wall = apparent_client.get(f"/api/v1/metrics/eauto/aggregate/daily?start={start}&end={end}").json()[
        "buckets"
    ]
    r = apparent_client.get(f"/api/v1/metrics/haus_ohne_eauto/aggregate/daily?start={start}&end={end}")
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    for i in range(2):
        h, w = haus[i]["value_kwh"], wall[i]["value_kwh"]
        assert h is not None and w is not None
        assert buckets[i]["value_kwh"] == pytest.approx(max(h - w, 0.0))
