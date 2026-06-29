from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from energie_monitor.aggregation import (
    consumption_by_local_date,
    energy_kwh_from_power_kw,
    local_window_bounds,
    normalize_pv_generation_kwh,
    slice_points_for_window,
)
from energie_monitor.models import MetricId, PvSolarYieldResponse, PvSolarYieldRow, PvSolarYieldSummary
from energie_monitor.services.metrics import MetricService
from energie_monitor.services.pv_solar_history import get_pv_history_monthly, merge_monthly
from energie_monitor.sources import volkszaehler as vz

MONTH_LABELS_DE = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

WEEKDAY_LABELS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _sum_row_values(rows: list[PvSolarYieldRow]) -> float | None:
    vals = [r.value_kwh for r in rows if r.value_kwh is not None]
    return sum(vals) if vals else None


def _resolve_kwp(settings, override: float | None) -> float | None:
    if override is not None and override > 0:
        return override
    kwp = settings.pv_peak_power_kwp
    return kwp if kwp and kwp > 0 else None


def _specific_yield(total: float | None, kwp: float | None) -> float | None:
    if total is None or kwp is None:
        return None
    return total / kwp


def _with_summary(response: PvSolarYieldResponse, *, kwp: float | None) -> PvSolarYieldResponse:
    total = _sum_row_values(response.rows)
    response.total_kwh = total
    response.peak_power_kwp = kwp
    response.specific_yield_kwh_per_kwp = _specific_yield(total, kwp)
    return response


def _month_label(month: int) -> str:
    if 1 <= month <= 12:
        return MONTH_LABELS_DE[month - 1]
    return str(month)


def _month_bounds(year: int, month: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end = datetime(year, month + 1, 1, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=UTC)
    cur = datetime(year, month, 1, tzinfo=UTC)
    return (nxt - cur).days


def _week_bounds_in_month(year: int, month: int, week: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    if week < 1:
        raise ValueError("week muss >= 1 sein.")
    first = datetime(year, month, 1, tzinfo=tz)
    dim = _days_in_month(year, month)
    month_end = first + timedelta(days=dim)

    first_monday = first + timedelta(days=(7 - first.weekday()) % 7)
    start_local = first_monday + timedelta(days=(week - 1) * 7)
    end_local = start_local + timedelta(days=7)

    if start_local.month != month or start_local >= month_end:
        raise ValueError(f"Woche {week} liegt außerhalb des Monats {month}/{year}.")
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


class PvSolarService:
    def __init__(self, metrics: MetricService):
        self.metrics = metrics

    def _kwp(self, override: float | None = None) -> float | None:
        return _resolve_kwp(self.metrics.settings, override)

    def _history_monthly(self) -> dict[tuple[int, int], float]:
        s = self.metrics.settings
        return get_pv_history_monthly(path=s.pv_history_path, enabled=s.pv_history_enabled)

    async def _live_by_month(
        self, start_year: int, end_year: int, tz: ZoneInfo
    ) -> dict[tuple[int, int], float]:
        start = datetime(start_year, 1, 1, tzinfo=tz).astimezone(UTC)
        end = datetime(end_year + 1, 1, 1, tzinfo=tz).astimezone(UTC)
        daily = await self.metrics.daily(MetricId.pv, start, end)
        by_month: dict[tuple[int, int], float] = defaultdict(float)
        for b in daily.buckets:
            if b.value_kwh is None:
                continue
            local = b.period_start.astimezone(tz)
            by_month[(local.year, local.month)] += b.value_kwh
        return dict(by_month)

    async def _by_month_merged(
        self, start_year: int, end_year: int, tz: ZoneInfo
    ) -> dict[tuple[int, int], float | None]:
        history = self._history_monthly()
        history_through = self.metrics.settings.pv_history_through_year
        # Volkszähler nur für Jahre ohne Excel-Referenz (Performance: nicht 2012–2024 abfragen)
        live_start = max(start_year, history_through + 1) if history else start_year
        live: dict[tuple[int, int], float] = {}
        if live_start <= end_year:
            live = await self._live_by_month(live_start, end_year, tz)
        return merge_monthly(
            live,
            history,
            start_year=start_year,
            end_year=end_year,
            history_through_year=history_through,
        )

    async def available_years(self, tz: ZoneInfo) -> list[int]:
        now = datetime.now(tz=UTC)
        start = datetime(now.year - 20, 1, 1, tzinfo=UTC)
        daily = await self.metrics.daily(MetricId.pv, start, now)
        years = {
            b.period_start.astimezone(tz).year
            for b in daily.buckets
            if b.value_kwh is not None and b.value_kwh > 0
        }
        for year, _month in self._history_monthly():
            years.add(year)
        if not years:
            years = {now.astimezone(tz).year}
        return sorted(years)

    async def monthly_matrix_wide(self, start_year: int, end_year: int, tz: ZoneInfo) -> list[dict]:
        if end_year < start_year:
            raise ValueError("end_year muss >= start_year sein.")
        by_month = await self._by_month_merged(start_year, end_year, tz)
        rows: list[dict] = []
        for month in range(1, 13):
            row: dict[str, object] = {"month": month, "month_label": _month_label(month)}
            for year in range(start_year, end_year + 1):
                row[f"y{year}"] = by_month.get((year, month))
            rows.append(row)
        return rows

    async def yearly_totals(
        self, start_year: int, end_year: int, tz: ZoneInfo, *, peak_power_kwp: float | None = None
    ) -> list[dict]:
        if end_year < start_year:
            raise ValueError("end_year muss >= start_year sein.")
        kwp = self._kwp(peak_power_kwp)
        by_month = await self._by_month_merged(start_year, end_year, tz)
        by_year: dict[int, float] = defaultdict(float)
        for (year, _month), val in by_month.items():
            if val is not None:
                by_year[year] += val
        return [
            {
                "year": year,
                "value_kwh": by_year[year] if by_year.get(year) else None,
                "peak_power_kwp": kwp,
                "specific_yield_kwh_per_kwp": _specific_yield(by_year.get(year), kwp),
            }
            for year in range(start_year, end_year + 1)
        ]

    async def monthly_matrix(
        self, start_year: int, end_year: int, tz: ZoneInfo
    ) -> PvSolarYieldResponse:
        if end_year < start_year:
            raise ValueError("end_year muss >= start_year sein.")
        by_month = await self._by_month_merged(start_year, end_year, tz)
        rows: list[PvSolarYieldRow] = []
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                rows.append(
                    PvSolarYieldRow(
                        year=year,
                        month=month,
                        month_label=_month_label(month),
                        day=None,
                        value_kwh=by_month.get((year, month)),
                    )
                )
        return _with_summary(
            PvSolarYieldResponse(
                timezone=str(tz),
                start_year=start_year,
                end_year=end_year,
                rows=rows,
            ),
            kwp=self._kwp(),
        )

    async def monthly_year(
        self, year: int, tz: ZoneInfo, *, peak_power_kwp: float | None = None
    ) -> PvSolarYieldResponse:
        by_month = await self._by_month_merged(year, year, tz)
        rows = [
            PvSolarYieldRow(
                year=year,
                month=m,
                month_label=_month_label(m),
                day=None,
                value_kwh=by_month.get((year, m)),
            )
            for m in range(1, 13)
        ]
        return _with_summary(
            PvSolarYieldResponse(timezone=str(tz), year=year, rows=rows),
            kwp=self._kwp(peak_power_kwp),
        )

    async def daily_month(
        self, year: int, month: int, tz: ZoneInfo, *, peak_power_kwp: float | None = None
    ) -> PvSolarYieldResponse:
        if not 1 <= month <= 12:
            raise ValueError("month muss 1–12 sein.")
        start, end = _month_bounds(year, month, tz)
        dim = _days_in_month(year, month)
        by_date: dict[str, float | None] = {}

        s = self.metrics.settings
        if self.metrics._pv_is_power() and s.volkszaehler_uuid_pv:
            cons_pts = await vz.vz_get_tuples(
                self.metrics.client,
                s,
                s.volkszaehler_uuid_pv,
                start,
                end,
                group="day",
                options="consumption",
                chunk_days=7,
            )
            by_local = consumption_by_local_date(cons_pts, tz)
            missing: list[date] = []
            for d in range(1, dim + 1):
                ld = date(year, month, d)
                iso = ld.isoformat()
                if ld in by_local:
                    by_date[iso] = normalize_pv_generation_kwh(by_local[ld])
                else:
                    missing.append(ld)
            for ld in missing:
                w_start, w_end = local_window_bounds(ld, time(0, 0), time(0, 0), tz)
                day_pts = await vz.vz_get_tuples(
                    self.metrics.client,
                    s,
                    s.volkszaehler_uuid_pv,
                    w_start - timedelta(hours=1),
                    w_end,
                    chunk_days=2,
                )
                window_pts = slice_points_for_window(day_pts, w_start, w_end)
                by_date[ld.isoformat()] = (
                    energy_kwh_from_power_kw(window_pts) if len(window_pts) >= 2 else None
                )
        else:
            daily = await self.metrics.daily(MetricId.pv, start, end)
            for b in daily.buckets:
                if b.value_kwh is None:
                    continue
                local = b.period_start.astimezone(tz)
                if local.year == year and local.month == month:
                    iso = local.date().isoformat()
                    by_date[iso] = (by_date.get(iso) or 0) + b.value_kwh
            if not any(v is not None and v > 0 for v in by_date.values()):
                month_kwh = (await self._by_month_merged(year, year, tz)).get((year, month))
                if month_kwh is not None:
                    per_day = month_kwh / dim
                    for d in range(1, dim + 1):
                        by_date[f"{year:04d}-{month:02d}-{d:02d}"] = per_day

        rows = [
            PvSolarYieldRow(
                year=year,
                month=month,
                month_label=_month_label(month),
                day=d,
                date=f"{year:04d}-{month:02d}-{d:02d}",
                weekday_label=WEEKDAY_LABELS_DE[datetime(year, month, d, tzinfo=tz).weekday()],
                value_kwh=by_date.get(f"{year:04d}-{month:02d}-{d:02d}"),
            )
            for d in range(1, dim + 1)
        ]
        return _with_summary(
            PvSolarYieldResponse(timezone=str(tz), year=year, month=month, rows=rows),
            kwp=self._kwp(peak_power_kwp),
        )

    async def daily_week(
        self,
        year: int,
        month: int,
        week: int,
        tz: ZoneInfo,
        *,
        peak_power_kwp: float | None = None,
    ) -> PvSolarYieldResponse:
        start, end = _week_bounds_in_month(year, month, week, tz)
        daily = await self.metrics.daily(MetricId.pv, start, end)

        by_date: dict[str, float] = defaultdict(float)
        for b in daily.buckets:
            if b.value_kwh is None:
                continue
            local_date = b.period_start.astimezone(tz).date().isoformat()
            by_date[local_date] += b.value_kwh

        start_local = start.astimezone(tz).date()
        if not any(by_date.values()):
            merged = await self._by_month_merged(year, year, tz)
            for i in range(7):
                d = start_local + timedelta(days=i)
                month_kwh = merged.get((d.year, d.month))
                if month_kwh is not None:
                    dim = _days_in_month(d.year, d.month)
                    by_date[d.isoformat()] = month_kwh / dim

        rows: list[PvSolarYieldRow] = []
        for i, wd in enumerate(WEEKDAY_LABELS_DE):
            d = start_local + timedelta(days=i)
            rows.append(
                PvSolarYieldRow(
                    year=d.year,
                    month=d.month,
                    month_label=_month_label(d.month),
                    day=d.day,
                    date=d.isoformat(),
                    weekday_label=wd,
                    value_kwh=by_date.get(d.isoformat()),
                )
            )
        return _with_summary(
            PvSolarYieldResponse(
                timezone=str(tz),
                year=year,
                month=month,
                week=week,
                rows=rows,
            ),
            kwp=self._kwp(peak_power_kwp),
        )

    async def yield_summary(
        self,
        tz: ZoneInfo,
        *,
        start_year: int | None = None,
        end_year: int | None = None,
        year: int | None = None,
        month: int | None = None,
        week: int | None = None,
        peak_power_kwp: float | None = None,
    ) -> PvSolarYieldSummary:
        kwp = self._kwp(peak_power_kwp)

        if week is not None:
            if year is None or month is None:
                raise ValueError("year und month sind für week erforderlich.")
            resp = await self.daily_week(year, month, week, tz, peak_power_kwp=kwp)
            return PvSolarYieldSummary(
                timezone=str(tz),
                scope="week",
                label=f"Woche {week}, {_month_label(month)} {year}",
                year=year,
                month=month,
                week=week,
                total_kwh=resp.total_kwh,
                peak_power_kwp=kwp,
                specific_yield_kwh_per_kwp=resp.specific_yield_kwh_per_kwp,
            )

        if month is not None:
            if year is None:
                raise ValueError("year ist für month erforderlich.")
            resp = await self.daily_month(year, month, tz, peak_power_kwp=kwp)
            return PvSolarYieldSummary(
                timezone=str(tz),
                scope="month",
                label=f"{_month_label(month)} {year}",
                year=year,
                month=month,
                total_kwh=resp.total_kwh,
                peak_power_kwp=kwp,
                specific_yield_kwh_per_kwp=resp.specific_yield_kwh_per_kwp,
            )

        if year is not None:
            resp = await self.monthly_year(year, tz, peak_power_kwp=kwp)
            return PvSolarYieldSummary(
                timezone=str(tz),
                scope="year",
                label=str(year),
                year=year,
                total_kwh=resp.total_kwh,
                peak_power_kwp=kwp,
                specific_yield_kwh_per_kwp=resp.specific_yield_kwh_per_kwp,
            )

        if start_year is not None and end_year is not None:
            totals = await self.yearly_totals(start_year, end_year, tz, peak_power_kwp=kwp)
            values = [t["value_kwh"] for t in totals if t["value_kwh"] is not None]
            total = sum(values) if values else None
            return PvSolarYieldSummary(
                timezone=str(tz),
                scope="range",
                label=f"{start_year}–{end_year}",
                start_year=start_year,
                end_year=end_year,
                total_kwh=total,
                peak_power_kwp=kwp,
                specific_yield_kwh_per_kwp=_specific_yield(total, kwp),
            )

        raise ValueError(
            "Parameter unvollständig: range (start_year+end_year), year, month+year oder week+month+year."
        )
