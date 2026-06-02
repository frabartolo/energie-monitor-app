from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.services.pv_solar_history import get_pv_history_monthly, merge_monthly


def test_history_file_loads_2012_august():
    hist = get_pv_history_monthly()
    assert hist[(2012, 8)] == pytest.approx(1610.41)
    assert hist[(2025, 12)] == pytest.approx(248.38)


def test_merge_prefers_history_until_cutoff():
    live = {(2024, 1): 999.0, (2024, 2): 111.0, (2025, 1): 500.0}
    hist = {(2024, 1): 430.36, (2025, 1): 346.89}
    merged = merge_monthly(live, hist, start_year=2024, end_year=2025, history_through_year=2024)
    assert merged[(2024, 1)] == pytest.approx(430.36)
    assert merged[(2024, 2)] == pytest.approx(111.0)
    assert merged[(2025, 1)] == pytest.approx(500.0)


def test_yearly_totals_from_history_without_vz(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(
        volkszaehler_base_url="http://volkszaehler.local:8080",
        volkszaehler_uuid_pv="uuid-pv",
        pv_history_enabled=True,
        energy_timezone="Europe/Berlin",
        request_timeout_seconds=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def empty_vz(*_a, **_k):
        return []

    monkeypatch.setattr(
        "energie_monitor.services.metrics.vz.vz_get_tuples",
        empty_vz,
    )

    with TestClient(app) as client:
        r = client.get("/api/v1/pv/yield/yearly?start_year=2012&end_year=2012&timezone=Europe%2FBerlin")
        assert r.status_code == 200
        row = r.json()[0]
        assert row["year"] == 2012
        assert row["value_kwh"] == pytest.approx(4312.80, rel=1e-4)

    app.dependency_overrides.clear()
