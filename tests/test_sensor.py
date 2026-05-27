"""Unit tests for the sensor value/attribute helpers and alarm builder."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from custom_components.suez_water_remote import sensor
from custom_components.suez_water_remote.api import (
    AlarmConfig,
    AlarmConfigParameter,
    ConsumptionPoint,
    MeterReading,
    MeterSnapshot,
)


def _snapshot(daily: tuple[ConsumptionPoint, ...]) -> MeterSnapshot:
    return MeterSnapshot(
        meter_id="1234567",
        site_label="99999-XX-1234567",
        current_index=MeterReading(
            meter_id="1234567",
            timestamp=datetime(2026, 5, 27, 8, 0),
            value_m3=123.456,
        ),
        today_total_liters=None,
        daily_consumption=daily,
    )


def _point(day: date, value: float) -> ConsumptionPoint:
    return ConsumptionPoint(period_start=day, period_end=day, value_m3=value)


# --- daily consumption: 0.0 fallback, never mixes days ----------------------


def test_today_consumption_returns_value_when_present() -> None:
    today = date.today()
    snap = _snapshot((_point(today, 0.42),))
    assert sensor._today_consumption(snap) == 0.42
    assert sensor._today_consumption_liters(snap) == 420.0


def test_today_consumption_falls_back_to_zero_without_mixing_yesterday() -> None:
    yesterday = date.today() - timedelta(days=1)
    # Only yesterday is published; today must report 0.0, not yesterday's value.
    snap = _snapshot((_point(yesterday, 0.99),))
    assert sensor._today_consumption(snap) == 0.0
    assert sensor._today_consumption_liters(snap) == 0.0


def test_yesterday_consumption_value_and_fallback() -> None:
    yesterday = date.today() - timedelta(days=1)
    snap = _snapshot((_point(yesterday, 0.5),))
    assert sensor._yesterday_consumption(snap) == 0.5
    assert sensor._yesterday_consumption_liters(snap) == 500.0
    # No yesterday row -> 0.0.
    assert sensor._yesterday_consumption(_snapshot(())) == 0.0


def test_measured_date_attrs_flag_data_availability() -> None:
    today = date.today()
    with_data = sensor._measured_date_attrs(0)(_snapshot((_point(today, 0.1),)))
    assert with_data == {"measured_date": today.isoformat(), "data_available": True}

    without_data = sensor._measured_date_attrs(0)(_snapshot(()))
    assert without_data == {"measured_date": None, "data_available": False}


# --- alarm sensor builder ---------------------------------------------------


def _alarm(*params: AlarmConfigParameter, alarm_type: str = "Spotřeba") -> AlarmConfig:
    while len(params) < 3:
        params = (*params, AlarmConfigParameter(label="", value="", value_numeric=None))
    return AlarmConfig(
        config_id="1",
        alarm_type=alarm_type,
        active=True,
        email="a@b.cz",
        phone=None,
        parameters=(params[0], params[1], params[2]),
    )


def test_alarm_builder_skips_empty_params_and_labels_by_value() -> None:
    cfg = _alarm(
        AlarmConfigParameter(label="Mez nadměrné spotřeby", value="800", value_numeric=800.0),
        AlarmConfigParameter(label="Počet dnů", value="1", value_numeric=1.0),
        alarm_type="Upozornění na příliš velikou spotřebu",
    )
    descs = sensor._alarm_sensors_for(cfg)
    keys = [d.key for d in descs]
    assert keys == ["alarm_1_active", "alarm_1_param_1", "alarm_1_param_2"]

    active = descs[0]
    assert active.translation_key == "alarm_active"
    assert active.translation_placeholders == {
        "alarm_type": "Upozornění na příliš velikou spotřebu"
    }

    param1 = descs[1]
    assert param1.translation_key == "alarm_param"
    assert param1.translation_placeholders == {
        "alarm_type": "Upozornění na příliš velikou spotřebu",
        "param_label": "Mez nadměrné spotřeby",
    }


def test_alarm_builder_empty_config_only_active_sensor() -> None:
    cfg = _alarm(alarm_type="Upozornění na netěsnost")
    descs = sensor._alarm_sensors_for(cfg)
    assert [d.key for d in descs] == ["alarm_1_active"]


def test_alarm_param_state_renders_whole_numbers_without_decimals() -> None:
    cfg = _alarm(
        AlarmConfigParameter(label="Mez nadměrné spotřeby", value="800", value_numeric=800.0),
        AlarmConfigParameter(label="Počet dnů", value="1", value_numeric=1.0),
    )
    snap = MeterSnapshot(
        meter_id="1234567",
        site_label="99999-XX-1234567",
        current_index=MeterReading(
            meter_id="1234567", timestamp=datetime(2026, 5, 27), value_m3=1.0
        ),
        today_total_liters=None,
        alarm_configs=(cfg,),
    )
    # Whole numbers come back as int (800, not 800.0) but stay numeric.
    threshold = sensor._alarm_param_state("1", 0)(snap)
    assert threshold == 800
    assert isinstance(threshold, int)
    assert sensor._alarm_param_state("1", 1)(snap) == 1


def test_alarm_param_state_keeps_fractional_and_text_values() -> None:
    cfg = _alarm(
        AlarmConfigParameter(label="Mez", value="3,5", value_numeric=3.5),
        AlarmConfigParameter(label="Pásmo", value="noční", value_numeric=None),
    )
    snap = MeterSnapshot(
        meter_id="1234567",
        site_label="99999-XX-1234567",
        current_index=MeterReading(
            meter_id="1234567", timestamp=datetime(2026, 5, 27), value_m3=1.0
        ),
        today_total_liters=None,
        alarm_configs=(cfg,),
    )
    assert sensor._alarm_param_state("1", 0)(snap) == 3.5
    assert sensor._alarm_param_state("1", 1)(snap) == "noční"


def test_alarm_active_attrs_list_only_configured_labels() -> None:
    cfg = _alarm(
        AlarmConfigParameter(label="Mez nadměrné spotřeby", value="800", value_numeric=800.0),
        AlarmConfigParameter(label="Počet dnů", value="1", value_numeric=1.0),
    )
    snap = MeterSnapshot(
        meter_id="1234567",
        site_label="99999-XX-1234567",
        current_index=MeterReading(
            meter_id="1234567", timestamp=datetime(2026, 5, 27), value_m3=1.0
        ),
        today_total_liters=None,
        alarm_configs=(cfg,),
    )
    attrs = sensor._alarm_active_attrs("1")(snap)
    assert attrs is not None
    assert attrs["parameter_labels"] == ["Mez nadměrné spotřeby", "Počet dnů"]
