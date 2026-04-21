from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MeasurementKind(str, Enum):
    cumulative_energy_kwh = "cumulative_energy_kwh"
    instantaneous_power_kw = "instantaneous_power_kw"


class MetricId(str, Enum):
    haus_gesamt = "haus_gesamt"
    waermepumpe = "waermepumpe"
    eauto = "eauto"
    pv = "pv"


class MetricCatalogEntry(BaseModel):
    id: MetricId
    label: str
    unit: str
    measurement: MeasurementKind
    source: str


class CurrentValueResponse(BaseModel):
    metric_id: MetricId
    timestamp: datetime
    value: float | None
    unit: str


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    value: float


class TimeSeriesResponse(BaseModel):
    metric_id: MetricId
    unit: str
    points: list[TimeSeriesPoint]


class AggregateBucket(BaseModel):
    period_start: datetime
    period_end: datetime
    value_kwh: float | None


class DailyAggregateResponse(BaseModel):
    metric_id: MetricId
    unit: str = Field(default="kWh")
    buckets: list[AggregateBucket]


class MonthlyAggregateResponse(BaseModel):
    metric_id: MetricId
    unit: str = Field(default="kWh")
    buckets: list[AggregateBucket]


class YearlyAggregateResponse(BaseModel):
    metric_id: MetricId
    unit: str = Field(default="kWh")
    buckets: list[AggregateBucket]
