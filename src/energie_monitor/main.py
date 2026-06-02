from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo

from energie_monitor import __version__
from energie_monitor.config import Settings, get_settings
from energie_monitor.aggregation import parse_clock
from energie_monitor.models import (
    CurrentValueResponse,
    DailyAggregateResponse,
    HourlyProfileResponse,
    LoadProfileResponse,
    MetricCatalogEntry,
    MetricId,
    MonthlyAggregateResponse,
    PvSolarYieldResponse,
    TimeSeriesResponse,
    YearlyAggregateResponse,
)
from energie_monitor.services.metrics import MetricService
from energie_monitor.services.pv_solar import PvSolarService


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    async with httpx.AsyncClient(limits=limits) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="Energie-Monitor", version=__version__, lifespan=lifespan)


def http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def metric_service(
    client: Annotated[httpx.AsyncClient, Depends(http_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MetricService:
    return MetricService(settings, client)


def pv_service(svc: Annotated[MetricService, Depends(metric_service)]) -> PvSolarService:
    return PvSolarService(svc)


def parse_metric_id(metric_id: str = Path(..., description="Kennzahl-ID, z. B. pv, haus_gesamt")) -> MetricId:
    key = metric_id.strip().casefold()
    for m in MetricId:
        if m.value == key:
            return m
    allowed = ", ".join(sorted(x.value for x in MetricId))
    raise HTTPException(
        status_code=400,
        detail=f"Unbekannte metric_id {metric_id!r}. Erlaubt: {allowed}",
    )


MetricIdPath = Annotated[MetricId, Depends(parse_metric_id)]


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def httpx_error_handler(_, exc: httpx.HTTPError):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Upstream-Fehler (Volkszähler/Home Assistant): {exc}"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/v1/metrics", response_model=list[MetricCatalogEntry])
async def list_metrics(svc: Annotated[MetricService, Depends(metric_service)]):
    return svc.catalog()


@app.get("/api/v1/metrics/{metric_id}/current", response_model=CurrentValueResponse)
async def metric_current(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
):
    return await svc.current(metric_id)


@app.get("/api/v1/metrics/{metric_id}/timeseries", response_model=TimeSeriesResponse)
async def metric_timeseries(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(..., description="Beginn (ISO-8601, TZ empfohlen)"),
    end: datetime = Query(..., description="Ende (ISO-8601)"),
    max_points: int = Query(800, ge=50, le=5000, description="Max. Punkte (Downsampling für Grafana)"),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    return await svc.timeseries(metric_id, start, end, max_points=max_points)


@app.get("/api/v1/metrics/{metric_id}/aggregate/daily", response_model=DailyAggregateResponse)
async def metric_daily(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(..., description="Zeitraumstart (Tagesaggregate ab UTC-Kalendertag)"),
    end: datetime = Query(..., description="Zeitraumende (exklusiver Grenztag in UTC)"),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    return await svc.daily(metric_id, start, end)


@app.get("/api/v1/metrics/{metric_id}/aggregate/monthly", response_model=MonthlyAggregateResponse)
async def metric_monthly(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(...),
    end: datetime = Query(...),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    return await svc.monthly(metric_id, start, end)


@app.get("/api/v1/metrics/{metric_id}/aggregate/yearly", response_model=YearlyAggregateResponse)
async def metric_yearly(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(...),
    end: datetime = Query(...),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    return await svc.yearly(metric_id, start, end)


@app.get("/api/v1/energy/wallbox-split", response_model=dict)
async def energy_wallbox_split(
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(..., description="Zeitraumstart"),
    end: datetime = Query(..., description="Zeitraumende"),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    return await svc.wallbox_split(start, end)


@app.get("/api/v1/metrics/{metric_id}/load-profile", response_model=LoadProfileResponse)
async def metric_load_profile(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(..., description="Zeitraumstart"),
    end: datetime = Query(..., description="Zeitraumende"),
    interval: str = Query(
        "auto",
        description="Bucket-Größe: auto, 5m, 15m, 1h, 6h, 1d (auto aus Zeitraumlänge)",
    ),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    try:
        return await svc.load_profile(metric_id, start, end, interval)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/metrics/{metric_id}/aggregate/night-daily", response_model=DailyAggregateResponse)
async def metric_night_daily(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(..., description="Zeitraumstart"),
    end: datetime = Query(..., description="Zeitraumende"),
    time_from: str = Query("22:00", description="Lokale Startuhrzeit (HH oder HH:MM)"),
    time_to: str = Query("06:00", description="Lokale Enduhrzeit; kleiner/gleich Start = über Mitternacht"),
    timezone: str | None = Query(None, description="IANA-Zeitzone, Standard aus ENERGY_TIMEZONE"),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    try:
        tz = svc._resolve_tz(timezone)
        t_from = parse_clock(time_from)
        t_to = parse_clock(time_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await svc.night_daily(metric_id, start, end, t_from, t_to, tz)


@app.get("/api/v1/metrics/{metric_id}/profile/hourly", response_model=HourlyProfileResponse)
async def metric_hourly_profile(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(...),
    end: datetime = Query(...),
    time_from: str | None = Query(
        None, description="Optional: nur diese Uhrzeiten (z. B. 22:00) in die Stundenstatistik"
    ),
    time_to: str | None = Query(None, description="Optional, z. B. 06:00 (Nacht über Mitternacht)"),
    timezone: str | None = Query(None),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    try:
        tz = svc._resolve_tz(timezone)
        t_from = parse_clock(time_from) if time_from else None
        t_to = parse_clock(time_to) if time_to else None
        if (time_from is None) != (time_to is None):
            raise ValueError("time_from und time_to müssen gemeinsam gesetzt werden.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await svc.hourly_profile(metric_id, start, end, tz, t_from, t_to)


@app.get("/api/v1/metrics/{metric_id}/window-total", response_model=dict)
async def metric_window_total(
    metric_id: MetricIdPath,
    svc: Annotated[MetricService, Depends(metric_service)],
    start: datetime = Query(...),
    end: datetime = Query(...),
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    v = await svc.window_consumption_kwh(metric_id, start, end)
    return {"metric_id": metric_id.value, "start": start, "end": end, "value_kwh": v, "unit": "kWh"}


@app.get("/api/v1/pv/years", response_model=list[int])
async def pv_years(
    pv: Annotated[PvSolarService, Depends(pv_service)],
    svc: Annotated[MetricService, Depends(metric_service)],
    timezone: str | None = Query(None, description="IANA-Zeitzone, Standard aus ENERGY_TIMEZONE"),
):
    try:
        tz = svc._resolve_tz(timezone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await pv.available_years(tz)


@app.get("/api/v1/pv/yield/yearly", response_model=list[dict])
async def pv_yearly_totals(
    pv: Annotated[PvSolarService, Depends(pv_service)],
    svc: Annotated[MetricService, Depends(metric_service)],
    start_year: int = Query(..., ge=2000, le=2100),
    end_year: int = Query(..., ge=2000, le=2100),
    timezone: str | None = Query(None),
):
    try:
        tz = svc._resolve_tz(timezone)
        return await pv.yearly_totals(start_year, end_year, tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/pv/yield/monthly-wide", response_model=list[dict])
async def pv_monthly_wide(
    pv: Annotated[PvSolarService, Depends(pv_service)],
    svc: Annotated[MetricService, Depends(metric_service)],
    start_year: int = Query(..., ge=2000, le=2100),
    end_year: int = Query(..., ge=2000, le=2100),
    timezone: str | None = Query(None),
):
    try:
        tz = svc._resolve_tz(timezone)
        return await pv.monthly_matrix_wide(start_year, end_year, tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/pv/yield/monthly-matrix", response_model=PvSolarYieldResponse)
async def pv_monthly_matrix(
    pv: Annotated[PvSolarService, Depends(pv_service)],
    svc: Annotated[MetricService, Depends(metric_service)],
    start_year: int = Query(..., ge=2000, le=2100),
    end_year: int = Query(..., ge=2000, le=2100),
    timezone: str | None = Query(None),
):
    try:
        tz = svc._resolve_tz(timezone)
        return await pv.monthly_matrix(start_year, end_year, tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/pv/yield/year", response_model=PvSolarYieldResponse)
async def pv_year_monthly(
    pv: Annotated[PvSolarService, Depends(pv_service)],
    svc: Annotated[MetricService, Depends(metric_service)],
    year: int = Query(..., ge=2000, le=2100),
    timezone: str | None = Query(None),
):
    try:
        tz = svc._resolve_tz(timezone)
        return await pv.monthly_year(year, tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/pv/yield/month", response_model=PvSolarYieldResponse)
async def pv_month_daily(
    pv: Annotated[PvSolarService, Depends(pv_service)],
    svc: Annotated[MetricService, Depends(metric_service)],
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    timezone: str | None = Query(None),
):
    try:
        tz = svc._resolve_tz(timezone)
        return await pv.daily_month(year, month, tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/pv/yield/week", response_model=PvSolarYieldResponse)
async def pv_week_daily(
    pv: Annotated[PvSolarService, Depends(pv_service)],
    svc: Annotated[MetricService, Depends(metric_service)],
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    week: int = Query(..., ge=1, le=6),
    timezone: str | None = Query(None),
):
    try:
        tz = svc._resolve_tz(timezone)
        return await pv.daily_week(year, month, week, tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
