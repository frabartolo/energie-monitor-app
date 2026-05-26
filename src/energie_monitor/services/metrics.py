from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from energie_monitor.aggregation import (
    consumption_kwh_cumulative,
    daily_buckets_from_cumulative,
    rollup_daily_to_monthly,
    rollup_daily_to_yearly,
    slice_points_for_window,
)
from energie_monitor.config import Settings
from energie_monitor.models import (
    AggregateBucket,
    CurrentValueResponse,
    DailyAggregateResponse,
    MeasurementKind,
    MetricCatalogEntry,
    MetricId,
    MonthlyAggregateResponse,
    TimeSeriesPoint,
    TimeSeriesResponse,
    YearlyAggregateResponse,
)
from energie_monitor.sources import heat_pump as hp_api
from energie_monitor.sources import homeassistant as ha
from energie_monitor.sources import volkszaehler as vz

_WP_CATALOG = (
    (MetricId.waermepumpe, "Wärmepumpe – El. Energie gesamt"),
    (MetricId.waermepumpe_heizung, "Wärmepumpe – El. Energie Heizen"),
    (MetricId.waermepumpe_warmwasser, "Wärmepumpe – El. Energie Warmwasser"),
    (MetricId.waermepumpe_kuehlen, "Wärmepumpe – El. Energie Kühlen"),
)


class MetricService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def _ha_entity_for(self, metric_id: MetricId) -> str | None:
        s = self.settings
        mapping: dict[MetricId, str | None] = {
            MetricId.waermepumpe: s.entity_id_waermepumpe_energy,
            MetricId.waermepumpe_heizung: s.entity_id_waermepumpe_heizung,
            MetricId.waermepumpe_kuehlen: s.entity_id_waermepumpe_kuehlen,
            MetricId.waermepumpe_warmwasser: s.entity_id_waermepumpe_warmwasser,
            MetricId.eauto: s.entity_id_eauto_energy,
        }
        return mapping.get(metric_id)

    def catalog(self) -> list[MetricCatalogEntry]:
        entries = [
            MetricCatalogEntry(
                id=MetricId.haus_gesamt,
                label="Haus-Gesamtverbrauch",
                unit="kWh",
                measurement=MeasurementKind.cumulative_energy_kwh,
                source="Volkszähler (Middleware)",
            ),
            MetricCatalogEntry(
                id=MetricId.pv,
                label="PV-Erzeugung",
                unit="kWh",
                measurement=MeasurementKind.cumulative_energy_kwh,
                source="Volkszähler (Middleware)",
            ),
            MetricCatalogEntry(
                id=MetricId.eauto,
                label="E-Auto (Shelly 3EM / HA)",
                unit="kWh",
                measurement=MeasurementKind.cumulative_energy_kwh,
                source="Home Assistant",
            ),
        ]
        for mid, label in _WP_CATALOG:
            entries.append(
                MetricCatalogEntry(
                    id=mid,
                    label=label,
                    unit="kWh",
                    measurement=MeasurementKind.cumulative_energy_kwh,
                    source="Home Assistant (KEBA / M-TEC)",
                )
            )
        return entries

    async def _points_ha_entity(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        rows = await ha.ha_get_history(self.client, self.settings, entity_id, start, end)
        return ha.ha_history_to_points(rows)

    async def _points_haus(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        s = self.settings
        if not s.volkszaehler_uuid_haus:
            return []
        return await vz.vz_get_tuples(self.client, s, s.volkszaehler_uuid_haus, start, end)

    async def _points_pv(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        s = self.settings
        if not s.volkszaehler_uuid_pv:
            return []
        return await vz.vz_get_tuples(self.client, s, s.volkszaehler_uuid_pv, start, end)

    async def _points(self, metric_id: MetricId, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        entity_id = self._ha_entity_for(metric_id)
        if entity_id:
            return await self._points_ha_entity(entity_id, start, end)
        if metric_id == MetricId.haus_gesamt:
            return await self._points_haus(start, end)
        if metric_id == MetricId.pv:
            return await self._points_pv(start, end)
        return []

    async def current(self, metric_id: MetricId) -> CurrentValueResponse:
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=2)
        points = await self._points(metric_id, start, now)
        if points:
            ts, val = points[-1]
            return CurrentValueResponse(metric_id=metric_id, timestamp=ts, value=val, unit="kWh")
        entity_id = self._ha_entity_for(metric_id)
        if entity_id:
            st = await ha.ha_get_state(self.client, self.settings, entity_id)
            lc = ha.parse_ts(str(st["last_updated"]))
            return CurrentValueResponse(
                metric_id=metric_id,
                timestamp=lc,
                value=ha.ha_state_to_float(st),
                unit="kWh",
            )
        if metric_id == MetricId.waermepumpe and self.settings.heat_pump_api_base_url:
            v = await hp_api.heat_pump_energy_kwh(self.client, self.settings, now - timedelta(hours=1), now)
            return CurrentValueResponse(metric_id=metric_id, timestamp=now, value=v, unit="kWh")
        return CurrentValueResponse(metric_id=metric_id, timestamp=now, value=None, unit="kWh")

    async def timeseries(self, metric_id: MetricId, start: datetime, end: datetime) -> TimeSeriesResponse:
        pts = await self._points(metric_id, start, end)
        return TimeSeriesResponse(
            metric_id=metric_id,
            unit="kWh",
            points=[TimeSeriesPoint(timestamp=a, value=b) for a, b in pts],
        )

    async def daily(self, metric_id: MetricId, start: datetime, end: datetime) -> DailyAggregateResponse:
        if (
            metric_id == MetricId.waermepumpe
            and not self.settings.entity_id_waermepumpe_energy
            and self.settings.heat_pump_api_base_url
        ):
            buckets = await self._daily_via_wp_api(start, end)
            return DailyAggregateResponse(metric_id=metric_id, buckets=buckets)
        pts = await self._points(metric_id, start - timedelta(days=1), end + timedelta(days=1))
        raw = daily_buckets_from_cumulative(pts, start, end)
        buckets = [AggregateBucket(period_start=a, period_end=b, value_kwh=c) for a, b, c in raw]
        return DailyAggregateResponse(metric_id=metric_id, buckets=buckets)

    async def _daily_via_wp_api(self, start: datetime, end: datetime) -> list[AggregateBucket]:
        start_u = start.astimezone(UTC)
        end_u = end.astimezone(UTC)
        out: list[AggregateBucket] = []
        day = datetime(start_u.year, start_u.month, start_u.day, tzinfo=UTC)
        limit = datetime(end_u.year, end_u.month, end_u.day, tzinfo=UTC)
        while day <= limit:
            nxt = day + timedelta(days=1)
            try:
                v = await hp_api.heat_pump_energy_kwh(self.client, self.settings, day, nxt - timedelta(microseconds=1))
            except (httpx.HTTPError, ValueError):
                v = None
            out.append(AggregateBucket(period_start=day, period_end=nxt, value_kwh=v))
            day = nxt
        return out

    async def monthly(self, metric_id: MetricId, start: datetime, end: datetime) -> MonthlyAggregateResponse:
        daily = await self.daily(metric_id, start, end)
        tup = [(b.period_start, b.period_end, b.value_kwh) for b in daily.buckets]
        rolled = rollup_daily_to_monthly(tup)
        buckets = [AggregateBucket(period_start=a, period_end=b, value_kwh=c) for a, b, c in rolled]
        return MonthlyAggregateResponse(metric_id=metric_id, buckets=buckets)

    async def yearly(self, metric_id: MetricId, start: datetime, end: datetime) -> YearlyAggregateResponse:
        daily = await self.daily(metric_id, start, end)
        tup = [(b.period_start, b.period_end, b.value_kwh) for b in daily.buckets]
        rolled = rollup_daily_to_yearly(tup)
        buckets = [AggregateBucket(period_start=a, period_end=b, value_kwh=c) for a, b, c in rolled]
        return YearlyAggregateResponse(metric_id=metric_id, buckets=buckets)

    async def window_consumption_kwh(self, metric_id: MetricId, start: datetime, end: datetime) -> float | None:
        pts = await self._points(metric_id, start - timedelta(days=1), end + timedelta(days=1))
        window_pts = slice_points_for_window(pts, start, end)
        return consumption_kwh_cumulative(window_pts) if len(window_pts) >= 2 else None
