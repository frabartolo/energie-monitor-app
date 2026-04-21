from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.sources import volkszaehler as vz


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = Settings(
        volkszaehler_base_url="http://volkszaehler.local:8080",
        volkszaehler_uuid_haus="uuid-haus",
        volkszaehler_uuid_pv="uuid-pv",
        request_timeout_seconds=1,
    )

    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz_get_tuples(_client, _settings, uuid: str, start: datetime, end: datetime):
        start_u = start.astimezone(UTC)
        end_u = end.astimezone(UTC)
        if uuid == "uuid-pv":
            # liefert Werte über 2 Tage: Tag1 +5kWh, Tag2 +4kWh
            # Fixes Datum, damit Tests unabhängig von start/end der App sind
            t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
            pts = [
                (t0, 100.0),
                (t0 + timedelta(hours=18), 105.0),
                (t0 + timedelta(days=1), 105.0),
                (t0 + timedelta(days=1, hours=12), 109.0),
            ]

            # Für /current fragt die App i. d. R. "now-2d..now" ab.
            # Wenn dieses Fenster unser fixes Testdatum nicht überlappt, liefern wir
            # einen synthetischen aktuellen Punkt zurück, damit current != None ist.
            if end_u < t0 or start_u > (t0 + timedelta(days=2)):
                return [(end_u, 999.0)]
        else:
            # Default: minimal
            t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
            pts = [(t0, 10.0), (t0 + timedelta(hours=1), 11.0)]

        return [(ts, v) for ts, v in pts if start_u <= ts <= end_u]

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz_get_tuples)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_health_ok(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_catalog_contains_pv(client: TestClient):
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()}
    assert "pv" in ids


def test_current_pv_returns_kwh_value(client: TestClient):
    r = client.get("/api/v1/metrics/pv/current")
    assert r.status_code == 200
    data = r.json()
    assert data["metric_id"] == "pv"
    assert data["unit"] == "kWh"
    assert isinstance(data["value"], (int, float))


def test_metric_id_case_insensitive(client: TestClient):
    r = client.get("/api/v1/metrics/PV/current")
    assert r.status_code == 200
    assert r.json()["metric_id"] == "pv"


def test_unknown_metric_id_is_400(client: TestClient):
    r = client.get("/api/v1/metrics/does_not_exist/current")
    assert r.status_code == 400
    assert "Unbekannte metric_id" in r.json()["detail"]


def test_timeseries_requires_start_and_end(client: TestClient):
    r = client.get("/api/v1/metrics/pv/timeseries")
    assert r.status_code == 422


def test_timeseries_pv_returns_points(client: TestClient):
    start = "2026-04-01T00:00:00Z"
    end = "2026-04-03T00:00:00Z"
    r = client.get(f"/api/v1/metrics/pv/timeseries?start={start}&end={end}")
    assert r.status_code == 200
    data = r.json()
    assert data["metric_id"] == "pv"
    assert data["unit"] == "kWh"
    assert len(data["points"]) >= 2


def test_daily_aggregate_pv_returns_expected_consumption(client: TestClient):
    start = "2026-04-01T00:00:00Z"
    end = "2026-04-03T00:00:00Z"
    r = client.get(f"/api/v1/metrics/pv/aggregate/daily?start={start}&end={end}")
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    assert len(buckets) == 2
    assert buckets[0]["value_kwh"] == 5.0
    assert buckets[1]["value_kwh"] == 4.0


def test_window_total_pv(client: TestClient):
    start = "2026-04-01T00:00:00Z"
    end = "2026-04-03T00:00:00Z"
    r = client.get(f"/api/v1/metrics/pv/window-total?start={start}&end={end}")
    assert r.status_code == 200
    data = r.json()
    assert data["metric_id"] == "pv"
    assert data["unit"] == "kWh"
    assert data["value_kwh"] in (9.0, 9)  # 5 + 4

