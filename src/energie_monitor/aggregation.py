from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def _day_start_utc(d: datetime) -> datetime:
    x = d.astimezone(UTC)
    return datetime(x.year, x.month, x.day, tzinfo=UTC)


def _calendar_days_in_range(start: datetime, end: datetime) -> list[datetime]:
    """UTC-Kalendertage, die mit [start, end) überlappen (end exklusiv)."""
    start_u = start.astimezone(UTC)
    end_u = end.astimezone(UTC)
    if end_u <= start_u:
        return []
    first = _day_start_utc(start_u)
    last = _day_start_utc(end_u - timedelta(microseconds=1))
    days: list[datetime] = []
    day = first
    while day <= last:
        days.append(day)
        day += timedelta(days=1)
    return days


def _clip_period_to_query(
    period_start: datetime, period_end: datetime, start: datetime, end: datetime
) -> tuple[datetime, datetime] | None:
    start_u = start.astimezone(UTC)
    end_u = end.astimezone(UTC)
    ps = max(period_start.astimezone(UTC), start_u)
    pe = min(period_end.astimezone(UTC), end_u)
    if pe <= ps:
        return None
    return ps, pe


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


LOAD_INTERVALS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
}


def choose_load_profile_interval(start: datetime, end: datetime) -> timedelta:
    """Automatische Bucket-Größe aus Zeitraumlänge (Lastgang)."""
    hours = max((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 3600.0, 0.0)
    if hours <= 48:
        return timedelta(minutes=15)
    if hours <= 24 * 14:
        return timedelta(hours=1)
    if hours <= 24 * 120:
        return timedelta(hours=6)
    return timedelta(days=1)


def resolve_load_profile_interval(name: str, start: datetime, end: datetime) -> timedelta:
    key = name.strip().lower()
    if key in ("auto", ""):
        return choose_load_profile_interval(start, end)
    if key not in LOAD_INTERVALS:
        allowed = ", ".join(["auto", *LOAD_INTERVALS])
        raise ValueError(f"Unbekanntes interval {name!r}. Erlaubt: {allowed}")
    return LOAD_INTERVALS[key]


def interval_label(bucket: timedelta) -> str:
    for label, td in LOAD_INTERVALS.items():
        if td == bucket:
            return label
    secs = int(bucket.total_seconds())
    if secs % 86400 == 0:
        return f"{secs // 86400}d"
    if secs % 3600 == 0:
        return f"{secs // 3600}h"
    if secs % 60 == 0:
        return f"{secs // 60}m"
    return f"{secs}s"


def load_profile_buckets(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
    bucket: timedelta,
    *,
    use_apparent_va: bool,
    use_power_kw: bool = False,
) -> list[tuple[datetime, float | None, float | None]]:
    """
    Lastgang: (Bucket-Start UTC, mittlere Leistung kW/kVA, Energie im Bucket kWh).
    """
    start_u = start.astimezone(UTC)
    end_u = end.astimezone(UTC)
    if end_u <= start_u:
        return []
    out: list[tuple[datetime, float | None, float | None]] = []
    cur = start_u
    while cur < end_u:
        nxt = min(cur + bucket, end_u)
        window_pts = slice_points_for_window(points, cur, nxt)
        if len(window_pts) < 2:
            energy = None
        elif use_apparent_va:
            energy = energy_kwh_from_apparent_va(window_pts)
        elif use_power_kw:
            energy = energy_kwh_from_power_kw(window_pts)
        else:
            energy = consumption_kwh_cumulative(window_pts)
        hours = (nxt - cur).total_seconds() / 3600.0
        power = energy / hours if energy is not None and hours > 0 else None
        out.append((cur, power, energy))
        cur = nxt
    return out


def energy_kwh_from_power_kw(points: list[tuple[datetime, float]]) -> float | None:
    """Trapezintegration einer kW-Leistungszeitreihe → kWh."""
    if len(points) < 2:
        return None
    total_kwh = 0.0
    for i in range(1, len(points)):
        t1, p1 = points[i - 1]
        t2, p2 = points[i]
        dt_h = (t2.astimezone(UTC) - t1.astimezone(UTC)).total_seconds() / 3600.0
        if dt_h <= 0:
            continue
        avg_kw = max((p1 + p2) / 2.0, 0.0)
        total_kwh += avg_kw * dt_h
    return total_kwh


def energy_kwh_from_apparent_va(points: list[tuple[datetime, float]]) -> float | None:
    """
    Trapezintegration der Scheinleistung (VA) → kVAh.
    API-Feld heißt value_kwh; bei 400-V-Drehstrom ist das die übliche Abrechnungsgröße aus VA.
    """
    if len(points) < 2:
        return None
    total_kva_h = 0.0
    for i in range(1, len(points)):
        t1, v1 = points[i - 1]
        t2, v2 = points[i]
        dt_h = (t2.astimezone(UTC) - t1.astimezone(UTC)).total_seconds() / 3600.0
        if dt_h <= 0:
            continue
        avg_va = max((v1 + v2) / 2.0, 0.0)
        total_kva_h += avg_va * dt_h / 1000.0
    return total_kva_h


def daily_buckets_from_apparent_va(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime, float | None]]:
    out: list[tuple[datetime, datetime, float | None]] = []
    for day in _calendar_days_in_range(start, end):
        nxt = day + timedelta(days=1)
        clipped = _clip_period_to_query(day, nxt, start, end)
        if clipped is None:
            continue
        ps, pe = clipped
        window_pts = slice_points_for_window(points, ps, pe)
        if len(window_pts) < 2:
            out.append((ps, pe, None))
        else:
            out.append((ps, pe, energy_kwh_from_apparent_va(window_pts)))
    return out


def daily_buckets_from_power_kw(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime, float | None]]:
    out: list[tuple[datetime, datetime, float | None]] = []
    for day in _calendar_days_in_range(start, end):
        nxt = day + timedelta(days=1)
        clipped = _clip_period_to_query(day, nxt, start, end)
        if clipped is None:
            continue
        ps, pe = clipped
        window_pts = slice_points_for_window(points, ps, pe)
        if len(window_pts) < 2:
            out.append((ps, pe, None))
        else:
            out.append((ps, pe, energy_kwh_from_power_kw(window_pts)))
    return out


def daily_buckets_from_cumulative(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime, float | None]]:
    """
    Verbrauch pro überlapptem UTC-Kalendertag; period_start/end liegen im Abfragefenster
  (wichtig für Grafana-Zeitpicker bei kurzen Bereichen).
    """
    out: list[tuple[datetime, datetime, float | None]] = []
    for day in _calendar_days_in_range(start, end):
        nxt = day + timedelta(days=1)
        clipped = _clip_period_to_query(day, nxt, start, end)
        if clipped is None:
            continue
        ps, pe = clipped
        window_pts = slice_points_for_window(points, ps, pe)
        if len(window_pts) < 2:
            out.append((ps, pe, None))
        else:
            out.append((ps, pe, consumption_kwh_cumulative(window_pts)))
    return out


def daily_buckets_from_consumption_points(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime, float | None]]:
    """
    Tageswerte aus Volkszähler-Aggregaten (group=day&options=consumption).

    Volkszähler setzt den Timestamp üblicherweise auf das Ende des Intervalls.
    Wir ordnen jeden Punkt einem UTC-Kalendertag zu und geben für alle im Bereich
    überlappten Tage einen Bucket zurück (period_start/end innerhalb des Abfragefensters).
    """
    by_day: dict[date, float] = {}
    for ts, val in points:
        t = ts.astimezone(UTC)
        # Falls Volkszähler den Intervall-Ende-Timestamp exakt auf 00:00 des Folgetags setzt,
        # ordnen wir ihn dem Vortag zu.
        if t.hour == 0 and t.minute == 0 and t.second == 0 and t.microsecond == 0:
            t = t - timedelta(microseconds=1)
        by_day[t.date()] = val

    out: list[tuple[datetime, datetime, float | None]] = []
    for day in _calendar_days_in_range(start, end):
        nxt = day + timedelta(days=1)
        clipped = _clip_period_to_query(day, nxt, start, end)
        if clipped is None:
            continue
        ps, pe = clipped
        out.append((ps, pe, by_day.get(ps.astimezone(UTC).date())))
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


def parse_clock(value: str) -> time:
    """HH oder HH:MM (24h)."""
    raw = value.strip()
    if ":" in raw:
        h_str, m_str = raw.split(":", 1)
        return time(hour=int(h_str), minute=int(m_str))
    return time(hour=int(raw), minute=0)


def _local_dates_in_range(start: datetime, end: datetime, tz: ZoneInfo) -> list[date]:
    start_u = start.astimezone(UTC)
    end_u = end.astimezone(UTC)
    if end_u <= start_u:
        return []
    cur = start.astimezone(tz).date()
    last = (end.astimezone(tz) - timedelta(microseconds=1)).date()
    out: list[date] = []
    while cur <= last:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def local_window_bounds(
    day: date, time_from: time, time_to: time, tz: ZoneInfo
) -> tuple[datetime, datetime]:
    """Lokales Zeitfenster; time_to <= time_from bedeutet Fenster über Mitternacht."""
    start_local = datetime.combine(day, time_from, tzinfo=tz)
    if time_to <= time_from:
        end_local = datetime.combine(day + timedelta(days=1), time_to, tzinfo=tz)
    else:
        end_local = datetime.combine(day, time_to, tzinfo=tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def daily_buckets_time_window(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
    time_from: time,
    time_to: time,
    tz: ZoneInfo,
    *,
    use_apparent_va: bool,
) -> list[tuple[datetime, datetime, float | None]]:
    out: list[tuple[datetime, datetime, float | None]] = []
    for day in _local_dates_in_range(start, end, tz):
        w_start, w_end = local_window_bounds(day, time_from, time_to, tz)
        clipped = _clip_period_to_query(w_start, w_end, start, end)
        if clipped is None:
            continue
        ps, pe = clipped
        window_pts = slice_points_for_window(points, ps, pe)
        if len(window_pts) < 2:
            val = None
        elif use_apparent_va:
            val = energy_kwh_from_apparent_va(window_pts)
        else:
            val = consumption_kwh_cumulative(window_pts)
        out.append((ps, pe, val))
    return out


def _in_local_time_window(local_t: time, time_from: time | None, time_to: time | None) -> bool:
    if time_from is None or time_to is None:
        return True
    if time_to <= time_from:
        return local_t >= time_from or local_t < time_to
    return time_from <= local_t < time_to


def _distribute_segment_energy_to_hours(
    t1: datetime,
    t2: datetime,
    energy_kwh: float,
    tz: ZoneInfo,
    per_day_hour: dict[date, list[float]],
    *,
    time_from: time | None = None,
    time_to: time | None = None,
) -> None:
    if energy_kwh <= 0 or t2 <= t1:
        return
    total_s = (t2 - t1).total_seconds()
    if total_s <= 0:
        return
    step = timedelta(minutes=1)
    cur = t1
    while cur < t2:
        nxt = min(cur + step, t2)
        local = cur.astimezone(tz)
        if _in_local_time_window(local.time(), time_from, time_to):
            frac = (nxt - cur).total_seconds() / total_s
            e = energy_kwh * frac
            d = local.date()
            if d not in per_day_hour:
                per_day_hour[d] = [0.0] * 24
            per_day_hour[d][local.hour] += e
        cur = nxt


def hourly_profile_mean_daily_kwh(
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    *,
    use_apparent_va: bool,
    time_from: time | None = None,
    time_to: time | None = None,
) -> list[tuple[int, float | None]]:
    """Mittlerer kWh-Verbrauch pro Kalendertag je Stunde (0–23, Ortszeit)."""
    per_day_hour: dict[date, list[float]] = {}
    if use_apparent_va:
        for i in range(1, len(points)):
            t1, v1 = points[i - 1]
            t2, v2 = points[i]
            tu1, tu2 = t1.astimezone(UTC), t2.astimezone(UTC)
            if tu2 <= start.astimezone(UTC) or tu1 >= end.astimezone(UTC):
                continue
            dt_h = (tu2 - tu1).total_seconds() / 3600.0
            if dt_h <= 0:
                continue
            e = max((v1 + v2) / 2.0, 0.0) * dt_h / 1000.0
            _distribute_segment_energy_to_hours(
                max(tu1, start.astimezone(UTC)),
                min(tu2, end.astimezone(UTC)),
                e,
                tz,
                per_day_hour,
                time_from=time_from,
                time_to=time_to,
            )
    else:
        for i in range(1, len(points)):
            t1, v1 = points[i - 1]
            t2, v2 = points[i]
            tu1, tu2 = t1.astimezone(UTC), t2.astimezone(UTC)
            if tu2 <= start.astimezone(UTC) or tu1 >= end.astimezone(UTC):
                continue
            d = v2 - v1
            reset_threshold = max(0.05 * abs(v1), 0.5)
            if d < -reset_threshold:
                seg_e = max(v2, 0.0)
            else:
                seg_e = max(d, 0.0)
            _distribute_segment_energy_to_hours(
                max(tu1, start.astimezone(UTC)),
                min(tu2, end.astimezone(UTC)),
                seg_e,
                tz,
                per_day_hour,
                time_from=time_from,
                time_to=time_to,
            )

    days = _local_dates_in_range(start, end, tz)
    out: list[tuple[int, float | None]] = []
    if not days:
        return [(h, None) for h in range(24)]
    for h in range(24):
        total = sum(per_day_hour.get(d, [0.0] * 24)[h] for d in days)
        out.append((h, total / len(days)))
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
