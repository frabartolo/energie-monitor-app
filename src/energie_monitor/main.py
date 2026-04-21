from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from energie_monitor import __version__
from energie_monitor.config import Settings, get_settings
from energie_monitor.models import (
    CurrentValueResponse,
    DailyAggregateResponse,
    MetricCatalogEntry,
    MetricId,
    MonthlyAggregateResponse,
    TimeSeriesResponse,
    YearlyAggregateResponse,
)
from energie_monitor.services.metrics import MetricService


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
):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise HTTPException(status_code=400, detail="end muss nach start liegen.")
    return await svc.timeseries(metric_id, start, end)


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
