from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from energie_monitor.aggregation import (
    choose_load_profile_interval,
    load_profile_buckets,
    resolve_load_profile_interval,
)
from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.sources import volkszaehler as vz


def test_auto_interval_scaling():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert choose_load_profile_interval(t0, t0 + timedelta(hours=24)) == timedelta(minutes=15)
    assert choose_load_profile_interval(t0, t0 + timedelta(days=10)) == timedelta(hours=1)
    assert choose_load_profile_interval(t0, t0 + timedelta(days=200)) == timedelta(days=1)


def test_load_profile_buckets_constant_ramp():
    t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    pts = [(t0, 0.0), (t0 + timedelta(hours=1), 1.0), (t0 + timedelta(hours=2), 2.0)]
    buckets = load_profile_buckets(
        pts, t0, t0 + timedelta(hours=2), timedelta(hours=1), use_apparent_va=False
    )
    assert len(buckets) == 2
    assert buckets[0][1] == pytest.approx(1.0)
    assert buckets[0][2] == pytest.approx(1.0)


def test_resolve_interval_invalid():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        resolve_load_profile_interval("2w", t0, t0 + timedelta(days=1))


@pytest.fixture()
def load_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    settings = Settings(
        volkszaehler_base_url="http://vz.local",
        volkszaehler_uuid_haus="uuid-haus",
        volkszaehler_raw_unit="kWh",
        request_timeout_seconds=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz(_client, _settings, uuid: str, start: datetime, end: datetime):
        t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        return [
            (t0, 0.0),
            (t0 + timedelta(hours=1), 1.0),
            (t0 + timedelta(hours=2), 2.0),
            (t0 + timedelta(hours=3), 3.0),
            (t0 + timedelta(hours=4), 4.0),
        ]

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_load_profile_api(load_client: TestClient):
    r = load_client.get(
        "/api/v1/metrics/haus_gesamt/load-profile"
        "?start=2026-05-01T00:00:00Z&end=2026-05-01T04:00:00Z&interval=1h"
    )
    assert r.status_code == 200
    data = r.json()
    assert data["interval"] == "1h"
    assert data["unit"] == "kW"
    assert len(data["points"]) == 4
    assert data["points"][0]["power_kw"] == pytest.approx(1.0)
