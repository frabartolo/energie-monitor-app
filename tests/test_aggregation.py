from datetime import UTC, datetime, timedelta

from energie_monitor.aggregation import (
    consumption_kwh_cumulative,
    daily_buckets_from_cumulative,
    rollup_daily_to_monthly,
)


def test_consumption_simple():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    pts = [(t0, 10.0), (t0 + timedelta(hours=1), 12.5)]
    assert consumption_kwh_cumulative(pts) == 2.5


def test_consumption_reset():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    pts = [(t0, 100.0), (t0 + timedelta(hours=1), 5.0)]
    assert consumption_kwh_cumulative(pts) == 5.0


def test_daily_buckets():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    pts = [
        (t0, 0.0),
        (t0 + timedelta(hours=18), 5.0),
        (t0 + timedelta(days=1), 5.0),
        (t0 + timedelta(days=1, hours=12), 9.0),
    ]
    start = t0
    end = datetime(2025, 1, 3, 0, 0, tzinfo=UTC)
    daily = daily_buckets_from_cumulative(pts, start, end)
    assert len(daily) == 2
    assert daily[0][2] == 5.0
    assert daily[1][2] == 4.0


def test_monthly_rollup():
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    t1 = datetime(2025, 1, 2, tzinfo=UTC)
    tfeb = datetime(2025, 2, 1, tzinfo=UTC)
    daily = [
        (t0, t1, 3.0),
        (t1, tfeb, 2.0),
        (tfeb, datetime(2025, 2, 2, tzinfo=UTC), 10.0),
    ]
    m = rollup_daily_to_monthly(daily)
    assert len(m) == 2
    assert m[0][2] == 5.0
    assert m[1][2] == 10.0
