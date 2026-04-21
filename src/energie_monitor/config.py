from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "energie-monitor-app"

    homeassistant_base_url: str | None = Field(default=None, description="z.B. http://homeassistant:8123")
    homeassistant_token: str | None = Field(default=None, description="Long-Lived Access Token")

    volkszaehler_base_url: str | None = Field(default=None, description="Middleware-Basis, z.B. http://volkszaehler:8080")
    volkszaehler_uuid_haus: str | None = Field(default=None, description="UUID Hauptzähler (kumulativ kWh)")
    volkszaehler_uuid_pv: str | None = Field(default=None, description="UUID PV-Erzeugung (kumulativ kWh)")

    heat_pump_api_base_url: str | None = Field(default=None, description="Optional: REST-Basis Wärmepumpe")

    entity_id_eauto_energy: str | None = Field(
        default=None,
        description="HA Entity kumulative Energie E-Auto (Shelly 3EM), z.B. sensor.shelly_pro_3em_xxx_total_active_energy",
    )
    entity_id_waermepumpe_energy: str | None = Field(
        default=None,
        description="Optional: HA Entity kumulative Energie WP; falls leer und heat_pump_api_base_url gesetzt → API",
    )

    request_timeout_seconds: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
