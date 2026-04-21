from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta


def _day_start_utc(d: datetime) -> datetime:
    x = d.astimezone(UTC)
    return datetime(x.year, x.month, x.day, tzinfo=UTC)


def slice_points_for_window(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, float]]:
    """Inkl. einem Punkt unmittelbar vor start (falls vorhanden) für saubere Startdifferenz."""
    start_u = start.astimezone(UTC)
    end_u = end.astimezone(UTC)
    before: tuple[datetime, float] | None = None
    inside: list[tuple[datetime, float]] = []
    for ts, v in points:
        tu = ts.astimezone(UTC)
        if tu < start_u:
            before = (tu, v)
        elif start_u <= tu <= end_u:
            inside.append((tu, v))
    if before and inside:
        return [before] + inside
    if before and not inside:
        return [before]
    return inside


def consumption_kwh_cumulative(points: list[tuple[datetime, float]]) -> float | None:
    """Positive Verbrauchssumme aus Zählerstand-Verlauf (Zählerreset heuristisch)."""
    if len(points) < 2:
        return None
    total = 0.0
    for i in range(1, len(points)):
        prev_v = points[i - 1][1]
        curr_v = points[i][1]
        d = curr_v - prev_v
        reset_threshold = max(0.05 * abs(prev_v), 0.5)
        if d < -reset_threshold:
            total += max(curr_v, 0.0)
        else:
            total += max(d, 0.0)
    return total


def daily_buckets_from_cumulative(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime, float | None]]:
    """
    Liefert pro Kalendertag (UTC) [day_start, day_end] den Verbrauch in kWh.
    end ist exklusiv für die äußere Schleife: der letzte eingeschlossene Tag ist end-1ns.
    """
    start_u = _day_start_utc(start)
    end_u = _day_start_utc(end.astimezone(UTC))
    if end_u <= start_u:
        return []
    out: list[tuple[datetime, datetime, float | None]] = []
    day = start_u
    while day < end_u:
        nxt = day + timedelta(days=1)
        window_pts = slice_points_for_window(points, day, nxt - timedelta(microseconds=1))
        if len(window_pts) < 2:
            out.append((day, nxt, None))
        else:
            out.append((day, nxt, consumption_kwh_cumulative(window_pts)))
        day = nxt
    return out


def rollup_daily_to_monthly(
    daily: list[tuple[datetime, datetime, float | None]],
) -> list[tuple[datetime, datetime, float | None]]:
    sums: dict[tuple[int, int], float] = defaultdict(float)
    for ds, _de, val in daily:
        if val is None:
            continue
        sums[(ds.year, ds.month)] += val
    out: list[tuple[datetime, datetime, float | None]] = []
    for y, m in sorted(sums.keys()):
        period_start = datetime(y, m, 1, tzinfo=UTC)
        if m == 12:
            period_end = datetime(y + 1, 1, 1, tzinfo=UTC)
        else:
            period_end = datetime(y, m + 1, 1, tzinfo=UTC)
        out.append((period_start, period_end, sums[(y, m)]))
    return out


def rollup_daily_to_yearly(
    daily: list[tuple[datetime, datetime, float | None]],
) -> list[tuple[datetime, datetime, float | None]]:
    sums: dict[int, float] = defaultdict(float)
    for ds, _de, val in daily:
        if val is None:
            continue
        sums[ds.year] += val
    out: list[tuple[datetime, datetime, float | None]] = []
    for y in sorted(sums.keys()):
        period_start = datetime(y, 1, 1, tzinfo=UTC)
        period_end = datetime(y + 1, 1, 1, tzinfo=UTC)
        out.append((period_start, period_end, sums[y]))
    return out
