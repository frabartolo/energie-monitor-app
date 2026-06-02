from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MeasurementKind(str, Enum):
    cumulative_energy_kwh = "cumulative_energy_kwh"
    instantaneous_power_kw = "instantaneous_power_kw"
    instantaneous_apparent_va = "instantaneous_apparent_va"


class MetricId(str, Enum):
    haus_gesamt = "haus_gesamt"
    haus_ohne_eauto = "haus_ohne_eauto"
    waermepumpe = "waermepumpe"
    waermepumpe_heizung = "waermepumpe_heizung"
    waermepumpe_kuehlen = "waermepumpe_kuehlen"
    waermepumpe_warmwasser = "waermepumpe_warmwasser"
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


class HourlyProfileBucket(BaseModel):
    hour: int = Field(ge=0, le=23, description="Stunde 0–23 (Ortszeit)")
    value_kwh: float | None


class HourlyProfileResponse(BaseModel):
    metric_id: MetricId
    unit: str = Field(default="kWh")
    timezone: str
    time_from: str | None = None
    time_to: str | None = None
    description: str
    buckets: list[HourlyProfileBucket]


class LoadProfilePoint(BaseModel):
    timestamp: datetime
    power_kw: float | None = Field(default=None, description="Mittlere Leistung im Intervall")
    energy_kwh: float | None = Field(default=None, description="Energie im Intervall")


class LoadProfileResponse(BaseModel):
    metric_id: MetricId
    unit: str = Field(default="kW", description="kW oder kVA (Wallbox Scheinleistung)")
    interval: str
    start: datetime
    end: datetime
    points: list[LoadProfilePoint]


class PvSolarYieldRow(BaseModel):
    year: int
    month: int
    month_label: str
    day: int | None = None
    date: str | None = Field(default=None, description="Lokales Datum (YYYY-MM-DD)")
    weekday_label: str | None = Field(default=None, description="Wochentag (Mo–So)")
    value_kwh: float | None


class PvSolarYieldResponse(BaseModel):
    unit: str = Field(default="kWh")
    timezone: str
    start_year: int | None = None
    end_year: int | None = None
    year: int | None = None
    month: int | None = None
    week: int | None = None
    rows: list[PvSolarYieldRow]
