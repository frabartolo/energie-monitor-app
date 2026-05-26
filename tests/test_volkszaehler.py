from energie_monitor.config import Settings
from energie_monitor.sources.volkszaehler import volkszaehler_value_to_kwh


def _settings(**kwargs: object) -> Settings:
    return Settings.model_construct(**kwargs)


def test_wh_to_kwh_conversion():
    assert volkszaehler_value_to_kwh(_settings(volkszaehler_raw_unit="Wh"), 1377.0) == 1.377


def test_kwh_passthrough():
    assert volkszaehler_value_to_kwh(_settings(volkszaehler_raw_unit="kWh"), 5.0) == 5.0
