from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from energie_monitor.aggregation import (
    daily_balance_kwh,
    estimate_daily_self_consumed_pv_kwh,
)
from energie_monitor.config import Settings, get_settings
from energie_monitor.main import app
from energie_monitor.sources import volkszaehler as vz


def test_estimate_daily_self_consumed():
    assert estimate_daily_self_consumed_pv_kwh(0, 0) == 0.0
    assert estimate_daily_self_consumed_pv_kwh(10, 5) == 5.0
    assert estimate_daily_self_consumed_pv_kwh(5, 20) == pytest.approx(11.0)  # 5 + 15*0.4


def test_daily_balance_with_export():
    gross, self_u, total, export = daily_balance_kwh(10.0, 20.0, 5.0)
    assert gross == pytest.approx(15.0)
    assert self_u == pytest.approx(15.0)
    assert total == pytest.approx(25.0)
    assert export == pytest.approx(5.0)


def test_daily_balance_gross_bezug():
    gross, self_u, total, export = daily_balance_kwh(15.0, 20.0, 5.0, grid_is_gross_bezug=True)
    assert gross == pytest.approx(15.0)
    assert self_u == pytest.approx(15.0)
    assert total == pytest.approx(25.0)
    assert export == pytest.approx(5.0)


def test_daily_balance_without_export():
    gross, self_u, total, export = daily_balance_kwh(10.0, 20.0, None)
    assert gross == pytest.approx(10.0)
    assert self_u == pytest.approx(14.0)
    assert total == pytest.approx(24.0)
    assert export == pytest.approx(0.0)


def test_raw_energy_wh_to_kwh():
    from energie_monitor.aggregation import raw_energy_to_kwh

    assert raw_energy_to_kwh("Wh", 5000.0) == pytest.approx(5.0)
    assert raw_energy_to_kwh("kWh", 5.0) == pytest.approx(5.0)


@pytest.fixture()
def balance_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    settings = Settings(
        volkszaehler_base_url="http://vz.local",
        volkszaehler_uuid_haus="uuid-haus",
        volkszaehler_uuid_pv="uuid-pv",
        volkszaehler_raw_unit="kWh",
        energy_timezone="Europe/Berlin",
        request_timeout_seconds=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz(_client, _settings, uuid: str, start: datetime, end: datetime, **kwargs):
        berlin = ZoneInfo("Europe/Berlin")
        if kwargs.get("group") == "day" and kwargs.get("options") == "consumption":
            d1 = datetime(2026, 5, 2, 0, 0, tzinfo=berlin).astimezone(UTC)
            d2 = datetime(2026, 5, 3, 0, 0, tzinfo=berlin).astimezone(UTC)
            if uuid == "uuid-haus":
                return [(d1, 10.0), (d2, 20.0)]
            return [(d1, 5.0), (d2, 20.0)]
        return []

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_energy_balance_api_estimated(balance_client: TestClient):
    start = "2026-05-01T22:00:00Z"
    end = "2026-05-03T22:00:00Z"
    r = balance_client.get(f"/api/v1/energy/balance?start={start}&end={end}")
    assert r.status_code == 200
    data = r.json()
    assert data["balance_method"] == "estimated"
    assert data["grid_import_kwh"] == pytest.approx(20.0)
    assert data["grid_import_net_kwh"] == pytest.approx(20.0)
    assert data["grid_export_kwh"] is None
    assert data["pv_generation_kwh"] == pytest.approx(20.0)
    assert data["self_consumed_pv_kwh"] == pytest.approx(20.0)
    assert data["total_consumption_kwh"] == pytest.approx(40.0)


@pytest.fixture()
def balance_export_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    settings = Settings(
        volkszaehler_base_url="http://vz.local",
        volkszaehler_uuid_haus="uuid-haus",
        volkszaehler_uuid_pv="uuid-pv",
        volkszaehler_uuid_grid_export="uuid-export",
        volkszaehler_raw_unit="kWh",
        energy_timezone="Europe/Berlin",
        request_timeout_seconds=1,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def fake_vz(_client, _settings, uuid: str, start: datetime, end: datetime, **kwargs):
        berlin = ZoneInfo("Europe/Berlin")
        if kwargs.get("group") == "day" and kwargs.get("options") == "consumption":
            d1 = datetime(2026, 5, 2, 0, 0, tzinfo=berlin).astimezone(UTC)
            d2 = datetime(2026, 5, 3, 0, 0, tzinfo=berlin).astimezone(UTC)
            if uuid == "uuid-haus":
                return [(d1, 10.0), (d2, 20.0)]
            if uuid == "uuid-export":
                return [(d1, 5.0), (d2, 5.0)]
            return [(d1, 5.0), (d2, 20.0)]
        return []

    monkeypatch.setattr(vz, "vz_get_tuples", fake_vz)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_energy_balance_api_with_export(balance_export_client: TestClient):
    start = "2026-05-01T22:00:00Z"
    end = "2026-05-03T22:00:00Z"
    r = balance_export_client.get(f"/api/v1/energy/balance?start={start}&end={end}")
    assert r.status_code == 200
    data = r.json()
    assert data["balance_method"] == "export_meter"
    assert data["grid_import_net_kwh"] == pytest.approx(15.0)
    assert data["grid_export_kwh"] == pytest.approx(5.0)
    assert data["grid_import_kwh"] == pytest.approx(20.0)
    assert data["self_consumed_pv_kwh"] == pytest.approx(15.0)
    assert data["total_consumption_kwh"] == pytest.approx(30.0)
