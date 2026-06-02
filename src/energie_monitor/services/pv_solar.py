from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from energie_monitor.models import AggregateBucket, MetricId, PvSolarYieldResponse, PvSolarYieldRow
from energie_monitor.services.metrics import MetricService

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

    # Woche = Montag..Sonntag. Zuordnung zum Monat = Monat des Montags.
    # week=1 ist der erste Montag, der im Monat liegt; week=2 der nächste Montag, usw.
    first_monday = first + timedelta(days=(7 - first.weekday()) % 7)  # weekday(): Mo=0..So=6
    start_local = first_monday + timedelta(days=(week - 1) * 7)
    end_local = start_local + timedelta(days=7)

    if start_local.month != month or start_local >= month_end:
        raise ValueError(f"Woche {week} liegt außerhalb des Monats {month}/{year}.")
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


class PvSolarService:
    def __init__(self, metrics: MetricService):
        self.metrics = metrics

    async def available_years(self, tz: ZoneInfo) -> list[int]:
        now = datetime.now(tz=UTC)
        start = datetime(now.year - 20, 1, 1, tzinfo=UTC)
        daily = await self.metrics.daily(MetricId.pv, start, now)
        years = {
            b.period_start.astimezone(tz).year
            for b in daily.buckets
            if b.value_kwh is not None and b.value_kwh > 0
        }
        if not years:
            years = {now.astimezone(tz).year}
        return sorted(years)

    async def monthly_matrix_wide(self, start_year: int, end_year: int, tz: ZoneInfo) -> list[dict]:
        """
        Wide-Format für Grafana Bar-Charts:
        Eine Zeile pro Monat, Spalten pro Jahr (z. B. "y2024": 123.4).
        """
        if end_year < start_year:
            raise ValueError("end_year muss >= start_year sein.")
        start = datetime(start_year, 1, 1, tzinfo=tz).astimezone(UTC)
        end = datetime(end_year + 1, 1, 1, tzinfo=tz).astimezone(UTC)
        daily = await self.metrics.daily(MetricId.pv, start, end)
        by_month: dict[tuple[int, int], float] = defaultdict(float)
        for b in daily.buckets:
            if b.value_kwh is None:
                continue
            local = b.period_start.astimezone(tz)
            by_month[(local.year, local.month)] += b.value_kwh

        rows: list[dict] = []
        for month in range(1, 13):
            row: dict[str, object] = {"month": month, "month_label": _month_label(month)}
            for year in range(start_year, end_year + 1):
                row[f"y{year}"] = by_month.get((year, month))
            rows.append(row)
        return rows

    async def monthly_matrix(
        self, start_year: int, end_year: int, tz: ZoneInfo
    ) -> PvSolarYieldResponse:
        if end_year < start_year:
            raise ValueError("end_year muss >= start_year sein.")
        start = datetime(start_year, 1, 1, tzinfo=tz).astimezone(UTC)
        end = datetime(end_year + 1, 1, 1, tzinfo=tz).astimezone(UTC)
        daily = await self.metrics.daily(MetricId.pv, start, end)
        by_month: dict[tuple[int, int], float] = defaultdict(float)
        for b in daily.buckets:
            if b.value_kwh is None:
                continue
            local = b.period_start.astimezone(tz)
            by_month[(local.year, local.month)] += b.value_kwh
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
        return PvSolarYieldResponse(
            timezone=str(tz),
            start_year=start_year,
            end_year=end_year,
            rows=rows,
        )

    async def monthly_year(self, year: int, tz: ZoneInfo) -> PvSolarYieldResponse:
        start = datetime(year, 1, 1, tzinfo=tz).astimezone(UTC)
        end = datetime(year + 1, 1, 1, tzinfo=tz).astimezone(UTC)
        daily = await self.metrics.daily(MetricId.pv, start, end)
        by_month: dict[int, float] = defaultdict(float)
        for b in daily.buckets:
            if b.value_kwh is None:
                continue
            by_month[b.period_start.astimezone(tz).month] += b.value_kwh
        rows = [
            PvSolarYieldRow(
                year=year,
                month=m,
                month_label=_month_label(m),
                day=None,
                value_kwh=by_month.get(m),
            )
            for m in range(1, 13)
        ]
        return PvSolarYieldResponse(timezone=str(tz), year=year, rows=rows)

    async def daily_month(self, year: int, month: int, tz: ZoneInfo) -> PvSolarYieldResponse:
        if not 1 <= month <= 12:
            raise ValueError("month muss 1–12 sein.")
        start, end = _month_bounds(year, month, tz)
        daily = await self.metrics.daily(MetricId.pv, start, end)
        by_day: dict[int, float] = defaultdict(float)
        for b in daily.buckets:
            if b.value_kwh is None:
                continue
            by_day[b.period_start.astimezone(tz).day] += b.value_kwh
        dim = _days_in_month(year, month)
        rows = [
            PvSolarYieldRow(
                year=year,
                month=month,
                month_label=_month_label(month),
                day=d,
                date=f"{year:04d}-{month:02d}-{d:02d}",
                weekday_label=WEEKDAY_LABELS_DE[datetime(year, month, d, tzinfo=tz).weekday()],
                value_kwh=by_day.get(d),
            )
            for d in range(1, dim + 1)
        ]
        return PvSolarYieldResponse(timezone=str(tz), year=year, month=month, rows=rows)

    async def daily_week(self, year: int, month: int, week: int, tz: ZoneInfo) -> PvSolarYieldResponse:
        start, end = _week_bounds_in_month(year, month, week, tz)
        daily = await self.metrics.daily(MetricId.pv, start, end)

        # Auf lokale Kalendertage normalisieren (verhindert Doppelungen an UTC-Grenzen)
        by_date: dict[str, float] = defaultdict(float)
        for b in daily.buckets:
            if b.value_kwh is None:
                continue
            local_date = b.period_start.astimezone(tz).date().isoformat()
            by_date[local_date] += b.value_kwh

        # Immer Mo–So ausgeben
        start_local = start.astimezone(tz).date()
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
        return PvSolarYieldResponse(
            timezone=str(tz),
            year=year,
            month=month,
            week=week,
            rows=rows,
        )
