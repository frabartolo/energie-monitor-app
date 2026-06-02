from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.sources import volkszaehler as vz


@pytest.fixture()
def pv_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = Settings(
        volkszaehler_base_url="http://volkszaehler.local:8080",
        volkszaehler_uuid_pv="uuid-pv",
        volkszaehler_raw_unit="kWh",
        energy_timezone="Europe/Berlin",
        request_timeout_seconds=1,
    )

    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz_get_tuples(_client, _settings, uuid: str, start: datetime, end: datetime):
        assert uuid == "uuid-pv"
        start_u = start.astimezone(UTC)
        end_u = end.astimezone(UTC)

        # Zwei Jahre, je Monat 1 kWh/Tag (für einfache Summen).
        # Wir erzeugen pro Monat zwei Tagespunkte, damit daily/window-Logik mind. 2 Punkte sieht.
        pts: list[tuple[datetime, float]] = []
        base = datetime(2024, 1, 1, tzinfo=UTC)
        v = 0.0
        for y in (2024, 2025):
            for m in range(1, 13):
                t0 = datetime(y, m, 1, tzinfo=UTC)
                t1 = t0 + timedelta(days=1)
                v += 1.0
                pts.append((t0, v))
                v += 1.0
                pts.append((t1, v))

        return [(ts, val) for ts, val in pts if start_u <= ts <= end_u]

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz_get_tuples)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_pv_years(pv_client: TestClient):
    r = pv_client.get("/api/v1/pv/years")
    assert r.status_code == 200
    years = r.json()
    assert 2024 in years
    assert 2025 in years


def test_pv_yearly_totals(pv_client: TestClient):
    r = pv_client.get("/api/v1/pv/yield/yearly?start_year=2024&end_year=2025&timezone=UTC")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]["year"] == 2024
    assert rows[1]["year"] == 2025
    assert rows[0]["value_kwh"] is not None
    assert rows[0]["value_kwh"] > 0


def test_pv_monthly_wide(pv_client: TestClient):
    r = pv_client.get("/api/v1/pv/yield/monthly-wide?start_year=2024&end_year=2025&timezone=UTC")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 12
    assert "month_label" in rows[0]
    assert "y2024" in rows[0]
    assert "y2025" in rows[0]


def test_pv_year_monthly(pv_client: TestClient):
    r = pv_client.get("/api/v1/pv/yield/year?year=2024&timezone=UTC")
    assert r.status_code == 200
    data = r.json()
    assert data["year"] == 2024
    assert len(data["rows"]) == 12


def test_pv_month_daily(pv_client: TestClient):
    r = pv_client.get("/api/v1/pv/yield/month?year=2024&month=1&timezone=UTC")
    assert r.status_code == 200
    data = r.json()
    assert data["year"] == 2024
    assert data["month"] == 1
    assert len(data["rows"]) >= 28


def test_pv_week_daily(pv_client: TestClient):
    r = pv_client.get("/api/v1/pv/yield/week?year=2024&month=1&week=1&timezone=UTC")
    assert r.status_code == 200
    data = r.json()
    assert data["week"] == 1
    assert len(data["rows"]) >= 1

