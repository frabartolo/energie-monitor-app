from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from energie_monitor.aggregation import (
    consumption_kwh_cumulative,
    daily_buckets_from_apparent_va,
    daily_buckets_from_cumulative,
    daily_buckets_time_window,
    energy_kwh_from_apparent_va,
    hourly_profile_mean_daily_kwh,
    interval_label,
    load_profile_buckets,
    resolve_load_profile_interval,
    rollup_daily_to_monthly,
    rollup_daily_to_yearly,
    slice_points_for_window,
)
from energie_monitor.config import Settings
from energie_monitor.models import (
    AggregateBucket,
    CurrentValueResponse,
    DailyAggregateResponse,
    HourlyProfileBucket,
    HourlyProfileResponse,
    LoadProfilePoint,
    LoadProfileResponse,
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

    def _eauto_apparent_va(self) -> bool:
        return self.settings.eauto_measurement == "apparent_power_va"

    def _daily_buckets_raw(
        self, metric_id: MetricId, pts: list[tuple[datetime, float]], start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime, float | None]]:
        if metric_id == MetricId.eauto and self._eauto_apparent_va():
            return daily_buckets_from_apparent_va(pts, start, end)
        return daily_buckets_from_cumulative(pts, start, end)

    def _window_energy_kwh(
        self, metric_id: MetricId, window_pts: list[tuple[datetime, float]]
    ) -> float | None:
        if len(window_pts) < 2:
            return None
        if metric_id == MetricId.eauto and self._eauto_apparent_va():
            return energy_kwh_from_apparent_va(window_pts)
        return consumption_kwh_cumulative(window_pts)

    def _resolve_tz(self, timezone: str | None) -> ZoneInfo:
        name = (timezone or self.settings.energy_timezone).strip()
        try:
            return ZoneInfo(name)
        except Exception as exc:
            raise ValueError(f"Unbekannte Zeitzone: {name!r}") from exc

    def _use_apparent_for(self, metric_id: MetricId) -> bool:
        return metric_id == MetricId.eauto and self._eauto_apparent_va()

    async def _points_padded(self, metric_id: MetricId, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        pad = timedelta(days=2)
        return await self._points(metric_id, start - pad, end + pad)

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
                label="Wallbox / E-Auto (HA)",
                unit="kVA" if self._eauto_apparent_va() else "kWh",
                measurement=(
                    MeasurementKind.instantaneous_apparent_va
                    if self._eauto_apparent_va()
                    else MeasurementKind.cumulative_energy_kwh
                ),
                source=(
                    "Home Assistant Scheinleistung (VA), Tageswerte per Integration"
                    if self._eauto_apparent_va()
                    else "Home Assistant kumulativer Energiezähler (kWh)"
                ),
            ),
            MetricCatalogEntry(
                id=MetricId.haus_ohne_eauto,
                label="Haus ohne Wallbox (berechnet)",
                unit="kWh",
                measurement=MeasurementKind.cumulative_energy_kwh,
                source="Volkszähler Haus minus Wallbox-Verbrauch im Zeitraum",
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
        if metric_id == MetricId.haus_ohne_eauto:
            return []
        entity_id = self._ha_entity_for(metric_id)
        if entity_id:
            return await self._points_ha_entity(entity_id, start, end)
        if metric_id == MetricId.haus_gesamt:
            return await self._points_haus(start, end)
        if metric_id == MetricId.pv:
            return await self._points_pv(start, end)
        return []

    @staticmethod
    def _subtract_bucket_values(
        base: list[AggregateBucket], sub: list[AggregateBucket]
    ) -> list[AggregateBucket]:
        sub_by_start = {b.period_start: b.value_kwh for b in sub}
        out: list[AggregateBucket] = []
        for b in base:
            h = b.value_kwh
            w = sub_by_start.get(b.period_start)
            if h is None:
                out.append(AggregateBucket(period_start=b.period_start, period_end=b.period_end, value_kwh=None))
            elif w is None:
                out.append(b)
            else:
                out.append(
                    AggregateBucket(
                        period_start=b.period_start,
                        period_end=b.period_end,
                        value_kwh=max(h - w, 0.0),
                    )
                )
        return out

    async def current(self, metric_id: MetricId) -> CurrentValueResponse:
        now = datetime.now(tz=UTC)
        if metric_id == MetricId.haus_ohne_eauto:
            start = now - timedelta(days=1)
            v = await self.window_consumption_kwh(metric_id, start, now)
            return CurrentValueResponse(metric_id=metric_id, timestamp=now, value=v, unit="kWh")
        if metric_id == MetricId.eauto and self._eauto_apparent_va():
            entity_id = self._ha_entity_for(metric_id)
            if entity_id:
                st = await ha.ha_get_state(self.client, self.settings, entity_id)
                lc = ha.parse_ts(str(st["last_updated"]))
                raw = ha.ha_state_to_float(st)
                val = (raw / 1000.0) if raw is not None else None
                return CurrentValueResponse(metric_id=metric_id, timestamp=lc, value=val, unit="kVA")
            return CurrentValueResponse(metric_id=metric_id, timestamp=now, value=None, unit="kVA")
        start = now - timedelta(days=2)
        points = await self._points(metric_id, start, now)
        if points:
            ts, val = points[-1]
            unit = "kWh"
            if metric_id == MetricId.eauto and self._eauto_apparent_va():
                val = val / 1000.0 if val is not None else None
                unit = "kVA"
            return CurrentValueResponse(metric_id=metric_id, timestamp=ts, value=val, unit=unit)
        entity_id = self._ha_entity_for(metric_id)
        if entity_id:
            st = await ha.ha_get_state(self.client, self.settings, entity_id)
            lc = ha.parse_ts(str(st["last_updated"]))
            raw = ha.ha_state_to_float(st)
            unit = "kWh"
            val = raw
            if metric_id == MetricId.eauto and self._eauto_apparent_va():
                val = raw / 1000.0 if raw is not None else None
                unit = "kVA"
            return CurrentValueResponse(
                metric_id=metric_id,
                timestamp=lc,
                value=val,
                unit=unit,
            )
        if metric_id == MetricId.waermepumpe and self.settings.heat_pump_api_base_url:
            v = await hp_api.heat_pump_energy_kwh(self.client, self.settings, now - timedelta(hours=1), now)
            return CurrentValueResponse(metric_id=metric_id, timestamp=now, value=v, unit="kWh")
        return CurrentValueResponse(metric_id=metric_id, timestamp=now, value=None, unit="kWh")

    @staticmethod
    def _downsample_points(
        points: list[tuple[datetime, float]], max_points: int
    ) -> list[tuple[datetime, float]]:
        if len(points) <= max_points:
            return points
        step = max(len(points) // max_points, 1)
        sampled = [points[i] for i in range(0, len(points), step)]
        if sampled[-1][0] != points[-1][0]:
            sampled.append(points[-1])
        return sampled

    async def timeseries(
        self,
        metric_id: MetricId,
        start: datetime,
        end: datetime,
        *,
        max_points: int = 800,
    ) -> TimeSeriesResponse:
        if metric_id == MetricId.haus_ohne_eauto:
            daily = await self.daily(metric_id, start, end)
            points = [
                TimeSeriesPoint(timestamp=b.period_start, value=b.value_kwh)
                for b in daily.buckets
                if b.value_kwh is not None
            ]
            return TimeSeriesResponse(metric_id=metric_id, unit="kWh", points=points)
        pts = await self._points(metric_id, start, end)
        pts = self._downsample_points(pts, max_points)
        unit = "kWh"
        series = pts
        if metric_id == MetricId.eauto and self._eauto_apparent_va():
            unit = "kVA"
            series = [(a, b / 1000.0) for a, b in pts]
        return TimeSeriesResponse(
            metric_id=metric_id,
            unit=unit,
            points=[TimeSeriesPoint(timestamp=a, value=b) for a, b in series],
        )

    async def daily(self, metric_id: MetricId, start: datetime, end: datetime) -> DailyAggregateResponse:
        if metric_id == MetricId.haus_ohne_eauto:
            h = await self.daily(MetricId.haus_gesamt, start, end)
            if not self.settings.entity_id_eauto_energy:
                return DailyAggregateResponse(metric_id=metric_id, buckets=h.buckets)
            w = await self.daily(MetricId.eauto, start, end)
            buckets = self._subtract_bucket_values(h.buckets, w.buckets)
            return DailyAggregateResponse(metric_id=metric_id, buckets=buckets)
        if (
            metric_id == MetricId.waermepumpe
            and not self.settings.entity_id_waermepumpe_energy
            and self.settings.heat_pump_api_base_url
        ):
            buckets = await self._daily_via_wp_api(start, end)
            return DailyAggregateResponse(metric_id=metric_id, buckets=buckets)
        pts = await self._points(metric_id, start - timedelta(days=1), end + timedelta(days=1))
        raw = self._daily_buckets_raw(metric_id, pts, start, end)
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
        if metric_id == MetricId.haus_ohne_eauto:
            h = await self.window_consumption_kwh(MetricId.haus_gesamt, start, end)
            if h is None:
                return None
            if not self.settings.entity_id_eauto_energy:
                return h
            w = await self.window_consumption_kwh(MetricId.eauto, start, end)
            if w is None:
                return h
            return max(h - w, 0.0)
        pts = await self._points(metric_id, start - timedelta(days=1), end + timedelta(days=1))
        window_pts = slice_points_for_window(pts, start, end)
        return self._window_energy_kwh(metric_id, window_pts)

    async def load_profile(
        self,
        metric_id: MetricId,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> LoadProfileResponse:
        bucket = resolve_load_profile_interval(interval, start, end)
        unit = "kW"
        if metric_id == MetricId.haus_ohne_eauto:
            h = await self.load_profile(MetricId.haus_gesamt, start, end, interval)
            if not self.settings.entity_id_eauto_energy:
                return LoadProfileResponse(
                    metric_id=metric_id,
                    unit=h.unit,
                    interval=h.interval,
                    start=start,
                    end=end,
                    points=h.points,
                )
            w = await self.load_profile(MetricId.eauto, start, end, interval)
            points: list[LoadProfilePoint] = []
            for hp, wp in zip(h.points, w.points, strict=True):
                if hp.energy_kwh is None:
                    e, p = None, None
                elif wp.energy_kwh is None:
                    e, p = hp.energy_kwh, hp.power_kw
                else:
                    e = max(hp.energy_kwh - wp.energy_kwh, 0.0)
                    hours = bucket.total_seconds() / 3600.0
                    p = e / hours if hours > 0 else None
                points.append(LoadProfilePoint(timestamp=hp.timestamp, power_kw=p, energy_kwh=e))
            return LoadProfileResponse(
                metric_id=metric_id,
                unit="kW",
                interval=h.interval,
                start=start,
                end=end,
                points=points,
            )

        pts = await self._points_padded(metric_id, start, end)
        apparent = self._use_apparent_for(metric_id)
        if apparent:
            unit = "kVA"
        raw = load_profile_buckets(pts, start, end, bucket, use_apparent_va=apparent)
        points = [
            LoadProfilePoint(timestamp=ts, power_kw=p, energy_kwh=e) for ts, p, e in raw
        ]
        return LoadProfileResponse(
            metric_id=metric_id,
            unit=unit,
            interval=interval_label(bucket),
            start=start,
            end=end,
            points=points,
        )

    async def night_daily(
        self,
        metric_id: MetricId,
        start: datetime,
        end: datetime,
        time_from: time,
        time_to: time,
        tz: ZoneInfo,
    ) -> DailyAggregateResponse:
        if metric_id == MetricId.haus_ohne_eauto:
            h = await self.night_daily(MetricId.haus_gesamt, start, end, time_from, time_to, tz)
            if not self.settings.entity_id_eauto_energy:
                return DailyAggregateResponse(metric_id=metric_id, buckets=h.buckets)
            w = await self.night_daily(MetricId.eauto, start, end, time_from, time_to, tz)
            buckets = self._subtract_bucket_values(h.buckets, w.buckets)
            return DailyAggregateResponse(metric_id=metric_id, buckets=buckets)
        pts = await self._points_padded(metric_id, start, end)
        raw = daily_buckets_time_window(
            pts, start, end, time_from, time_to, tz, use_apparent_va=self._use_apparent_for(metric_id)
        )
        buckets = [AggregateBucket(period_start=a, period_end=b, value_kwh=c) for a, b, c in raw]
        return DailyAggregateResponse(metric_id=metric_id, buckets=buckets)

    async def hourly_profile(
        self,
        metric_id: MetricId,
        start: datetime,
        end: datetime,
        tz: ZoneInfo,
        time_from: time | None = None,
        time_to: time | None = None,
    ) -> HourlyProfileResponse:
        if metric_id == MetricId.haus_ohne_eauto:
            h_prof = await self.hourly_profile(MetricId.haus_gesamt, start, end, tz, time_from, time_to)
            if not self.settings.entity_id_eauto_energy:
                return HourlyProfileResponse(
                    metric_id=metric_id,
                    timezone=str(tz),
                    time_from=_clock_label(time_from),
                    time_to=_clock_label(time_to),
                    description=h_prof.description,
                    buckets=h_prof.buckets,
                )
            w_prof = await self.hourly_profile(MetricId.eauto, start, end, tz, time_from, time_to)
            buckets = []
            for hb, wb in zip(h_prof.buckets, w_prof.buckets, strict=True):
                hv, wv = hb.value_kwh, wb.value_kwh
                if hv is None:
                    val = None
                elif wv is None:
                    val = hv
                else:
                    val = max(hv - wv, 0.0)
                buckets.append(HourlyProfileBucket(hour=hb.hour, value_kwh=val))
            return HourlyProfileResponse(
                metric_id=metric_id,
                timezone=str(tz),
                time_from=_clock_label(time_from),
                time_to=_clock_label(time_to),
                description="Mittlerer Tagesverbrauch je Stunde (Haus minus Wallbox)",
                buckets=buckets,
            )

        pts = await self._points_padded(metric_id, start, end)
        profile = hourly_profile_mean_daily_kwh(
            pts,
            start,
            end,
            tz,
            use_apparent_va=self._use_apparent_for(metric_id),
            time_from=time_from,
            time_to=time_to,
        )
        desc = "Mittlerer Verbrauch pro Kalendertag je Stunde (Ortszeit)"
        if time_from is not None and time_to is not None:
            desc = f"{desc}; nur Daten innerhalb {time_from:%H:%M}–{time_to:%H:%M}"
        return HourlyProfileResponse(
            metric_id=metric_id,
            timezone=str(tz),
            time_from=_clock_label(time_from),
            time_to=_clock_label(time_to),
            description=desc,
            buckets=[HourlyProfileBucket(hour=h, value_kwh=v) for h, v in profile],
        )

    async def wallbox_split(self, start: datetime, end: datetime) -> dict:
        haus = await self.window_consumption_kwh(MetricId.haus_gesamt, start, end)
        wallbox = (
            await self.window_consumption_kwh(MetricId.eauto, start, end)
            if self.settings.entity_id_eauto_energy
            else None
        )
        net = await self.window_consumption_kwh(MetricId.haus_ohne_eauto, start, end)
        return {
            "start": start,
            "end": end,
            "unit": "kWh",
            "haus_gesamt_kwh": haus,
            "wallbox_kwh": wallbox,
            "haus_ohne_wallbox_kwh": net,
        }


def _clock_label(t: time | None) -> str | None:
    if t is None:
        return None
    return t.strftime("%H:%M")
