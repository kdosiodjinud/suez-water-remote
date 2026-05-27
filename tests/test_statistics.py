"""Unit tests for the Energy-dashboard statistics import."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

from homeassistant.components.recorder.statistics import async_add_external_statistics

from custom_components.suez_water_remote import statistics
from custom_components.suez_water_remote.api import MeterReading, MeterSnapshot


def _snapshot(*readings: MeterReading) -> MeterSnapshot:
    return MeterSnapshot(
        meter_id="1234567",
        site_label="99999-XX-1234567",
        current_index=MeterReading("1234567", datetime(2026, 5, 24, 23), 100.0),
        today_total_liters=None,
        daily_index=readings,
    )


def test_build_statistics_sorted_hour_aligned_cumulative() -> None:
    # Deliberately out of order and with a non-zero minute to prove sorting
    # and hour alignment.
    snap = _snapshot(
        MeterReading("1234567", datetime(2026, 5, 24, 23, 37), 100.0),
        MeterReading("1234567", datetime(2026, 5, 23, 23), 99.5),
    )
    stats = statistics.build_statistics(snap)
    assert [s["start"] for s in stats] == [
        datetime(2026, 5, 23, 23, 0),
        datetime(2026, 5, 24, 23, 0),
    ]
    assert [s["sum"] for s in stats] == [99.5, 100.0]
    # state mirrors the cumulative reading.
    assert [s["state"] for s in stats] == [99.5, 100.0]


def test_build_statistics_empty_without_daily_index() -> None:
    assert statistics.build_statistics(_snapshot()) == []


def test_statistic_id_format() -> None:
    assert statistics.statistic_id("1234567") == "suez_water_remote:water_1234567"


def test_async_update_meter_statistics_pushes_metadata() -> None:
    mock: Mock = async_add_external_statistics  # stubbed in conftest
    mock.reset_mock()
    snap = _snapshot(MeterReading("1234567", datetime(2026, 5, 24, 23), 100.0))
    statistics.async_update_meter_statistics(Mock(), snap)
    mock.assert_called_once()
    _hass, metadata, stats = mock.call_args.args
    assert metadata["statistic_id"] == "suez_water_remote:water_1234567"
    assert metadata["unit_of_measurement"] == "m³"
    assert metadata["has_sum"] is True
    assert metadata["has_mean"] is False
    assert metadata["source"] == "suez_water_remote"
    assert len(stats) == 1


def test_async_update_meter_statistics_noop_when_empty() -> None:
    mock: Mock = async_add_external_statistics
    mock.reset_mock()
    statistics.async_update_meter_statistics(Mock(), _snapshot())
    mock.assert_not_called()
