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

    heat_pump_api_base_url: str | None = Field(
        default=None,
        description="Optional: REST-Basis Wärmepumpe",
        validation_alias=AliasChoices("HEAT_PUMP_API_BASE_URL", "WARMEPUMPE_API_URL"),
    )

    entity_id_eauto_energy: str | None = Field(
        default=None,
        description="HA Entity kumulative Energie E-Auto (Shelly 3EM), z.B. sensor.shelly_pro_3em_xxx_total_active_energy",
        validation_alias=AliasChoices("ENTITY_ID_EAUTO_ENERGY", "EAuto_ENTITY_ID"),
    )
    entity_id_waermepumpe_energy: str | None = Field(
        default=None,
        description="Optional: HA Entity kumulative Energie WP; falls leer und heat_pump_api_base_url gesetzt → API",
        validation_alias=AliasChoices("ENTITY_ID_WAERMEPUMPE_ENERGY", "WARMEPUMPE_SENSOR_TOTAL"),
    )

    request_timeout_seconds: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
