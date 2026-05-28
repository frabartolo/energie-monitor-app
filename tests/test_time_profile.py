from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from zoneinfo import ZoneInfo

from energie_monitor.aggregation import (
    daily_buckets_time_window,
    hourly_profile_mean_daily_kwh,
    local_window_bounds,
    parse_clock,
)
from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.sources import homeassistant as ha
from energie_monitor.sources import volkszaehler as vz


def test_parse_clock():
    assert parse_clock("22") == time(22, 0)
    assert parse_clock("06:30") == time(6, 30)


def test_night_window_over_midnight():
    tz = ZoneInfo("Europe/Berlin")
    d = date(2026, 5, 1)
    a, b = local_window_bounds(d, time(22, 0), time(6, 0), tz)
    assert a.astimezone(tz).hour == 22
    assert b.astimezone(tz).day == 2
    assert b.astimezone(tz).hour == 6


def test_daily_buckets_time_window_cumulative():
    tz = ZoneInfo("UTC")
    t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    pts = [
        (t0 + timedelta(hours=21), 0.0),
        (t0 + timedelta(hours=23), 2.0),
        (t0 + timedelta(days=1, hours=6), 9.0),
        (t0 + timedelta(days=1, hours=21), 9.0),
        (t0 + timedelta(days=1, hours=23), 11.0),
        (t0 + timedelta(days=2, hours=6), 18.0),
    ]
    start = t0
    end = t0 + timedelta(days=2)
    buckets = daily_buckets_time_window(pts, start, end, time(22, 0), time(6, 0), tz, use_apparent_va=False)
    assert len(buckets) == 2
    assert buckets[0][2] == pytest.approx(9.0)
    assert buckets[1][2] == pytest.approx(9.0)


@pytest.fixture()
def profile_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    monkeypatch.setenv("EAUTO_MEASUREMENT", "cumulative_energy_kwh")
    settings = Settings(
        volkszaehler_base_url="http://vz.local",
        volkszaehler_uuid_haus="uuid-haus",
        volkszaehler_raw_unit="kWh",
        energy_timezone="Europe/Berlin",
        request_timeout_seconds=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz(_client, _settings, uuid: str, start: datetime, end: datetime):
        t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        return [(t0, 0.0), (t0 + timedelta(days=2), 100.0)]

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_night_daily_api(profile_client: TestClient):
    r = profile_client.get(
        "/api/v1/metrics/haus_gesamt/aggregate/night-daily"
        "?start=2026-05-01T00:00:00Z&end=2026-05-03T00:00:00Z&time_from=22:00&time_to=06:00"
    )
    assert r.status_code == 200
    assert "buckets" in r.json()


def test_hourly_profile_api(profile_client: TestClient):
    r = profile_client.get(
        "/api/v1/metrics/haus_gesamt/profile/hourly"
        "?start=2026-05-01T00:00:00Z&end=2026-05-03T00:00:00Z&time_from=22:00&time_to=06:00"
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["buckets"]) == 24


def test_hourly_profile_mean_has_24_hours():
    tz = ZoneInfo("UTC")
    t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    pts = [(t0, 0.0), (t0 + timedelta(hours=1), 1.0), (t0 + timedelta(days=1), 1.0)]
    prof = hourly_profile_mean_daily_kwh(
        pts, t0, t0 + timedelta(days=1), tz, use_apparent_va=False
    )
    assert len(prof) == 24
