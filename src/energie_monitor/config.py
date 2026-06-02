from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "energie-monitor-app"

    homeassistant_base_url: str | None = Field(
        default=None,
        description="z.B. http://homeassistant:8123",
        validation_alias=AliasChoices("HOMEASSISTANT_BASE_URL", "HOME_ASSISTANT_URL"),
    )
    homeassistant_token: str | None = Field(
        default=None,
        description="Long-Lived Access Token",
        validation_alias=AliasChoices("HOMEASSISTANT_TOKEN", "HOME_ASSISTANT_API_TOKEN"),
    )

    volkszaehler_base_url: str | None = Field(default=None, description="Middleware-Basis, z.B. http://volkszaehler:8080")
    volkszaehler_uuid_haus: str | None = Field(default=None, description="UUID Hauptzähler (kumulativ)")
    volkszaehler_uuid_pv: str | None = Field(default=None, description="UUID PV-Erzeugung (kumulativ)")
    volkszaehler_raw_unit: Literal["Wh", "kWh"] = Field(
        default="Wh",
        description="Einheit der absoluten Zählerstände aus Volkszähler; API normalisiert nach kWh",
        validation_alias=AliasChoices("VOLKSZAEHLER_RAW_UNIT", "VOLKSZAEHLER_VALUE_UNIT"),
    )
    pv_measurement: Literal["instantaneous_power_kw", "cumulative_energy_kwh"] = Field(
        default="instantaneous_power_kw",
        description="PV-Kanal in Volkszähler: instantaneous_power_kw (kW-Zeitreihe) oder cumulative_energy_kwh (kWh-Zählerstand).",
        validation_alias=AliasChoices("PV_MEASUREMENT", "VOLKSZAEHLER_PV_MEASUREMENT"),
    )

    heat_pump_api_base_url: str | None = Field(
        default=None,
        description="Optional: REST-Basis Wärmepumpe",
        validation_alias=AliasChoices("HEAT_PUMP_API_BASE_URL", "WARMEPUMPE_API_URL"),
    )

    entity_id_eauto_energy: str | None = Field(
        default=None,
        description="HA Entity Wallbox: kumulativer Energiezähler oder Scheinleistung (siehe EAUTO_MEASUREMENT)",
        validation_alias=AliasChoices("ENTITY_ID_EAUTO_ENERGY", "EAuto_ENTITY_ID"),
    )
    eauto_measurement: Literal["cumulative_energy_kwh", "apparent_power_va"] = Field(
        default="apparent_power_va",
        description="cumulative_energy_kwh = Zählerstand kWh; apparent_power_va = Shelly total_apparent_power (VA), Integration zu kVAh",
        validation_alias=AliasChoices("EAUTO_MEASUREMENT", "ENTITY_ID_EAUTO_MEASUREMENT"),
    )
    entity_id_waermepumpe_energy: str | None = Field(
        default=None,
        description="HA: kumulative elektrische Gesamtenergie WP (M-TEC El. Energie)",
        validation_alias=AliasChoices("ENTITY_ID_WAERMEPUMPE_ENERGY", "WARMEPUMPE_SENSOR_TOTAL"),
    )
    entity_id_waermepumpe_heizung: str | None = Field(
        default=None,
        description="HA: kumulative elektrische Heizenergie",
        validation_alias=AliasChoices("ENTITY_ID_WAERMEPUMPE_HEIZUNG", "WARMEPUMPE_SENSOR_HEIZUNG"),
    )
    entity_id_waermepumpe_kuehlen: str | None = Field(
        default=None,
        description="HA: kumulative elektrische Kühlenergie",
        validation_alias=AliasChoices("ENTITY_ID_WAERMEPUMPE_KUEHLEN", "WARMEPUMPE_SENSOR_KUEHLEN"),
    )
    entity_id_waermepumpe_warmwasser: str | None = Field(
        default=None,
        description="HA: kumulative elektrische Warmwasserenergie",
        validation_alias=AliasChoices("ENTITY_ID_WAERMEPUMPE_WARMWASSER", "WARMEPUMPE_SENSOR_WARMWASSER"),
    )

    energy_timezone: str = Field(
        default="Europe/Berlin",
        description="Zeitzone für Nachtfenster und Stundenprofile",
        validation_alias=AliasChoices("ENERGY_TIMEZONE", "TIMEZONE"),
    )

    request_timeout_seconds: float = 60.0

    pv_history_enabled: bool = Field(
        default=True,
        description="Excel/LibreOffice-Referenzwerte in PV-Auswertungen einbeziehen (bis pv_history_through_year)",
        validation_alias=AliasChoices("PV_HISTORY_ENABLED", "PV_SOLAR_HISTORY_ENABLED"),
    )
    pv_history_through_year: int = Field(
        default=2024,
        ge=2000,
        le=2100,
        description="Letztes Jahr, für das Referenz-Excel Vorrang vor Volkszähler hat; danach nur Live",
        validation_alias=AliasChoices("PV_HISTORY_THROUGH_YEAR", "PV_HISTORY_END_YEAR"),
    )
    pv_history_path: str | None = Field(
        default=None,
        description="Optional: JSON mit Monatswerten (Format wie pv_solar_history_2012_2025.json)",
        validation_alias=AliasChoices("PV_HISTORY_PATH", "PV_SOLAR_HISTORY_PATH"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
