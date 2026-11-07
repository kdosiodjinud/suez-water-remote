"""Unit tests for the Energy-dashboard statistics import."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)

from custom_components.suez_water_remote import statistics
from custom_components.suez_water_remote.api import ConsumptionPoint

STAT_ID = "suez_water_remote:water_1234567"
COST_ID = "suez_water_remote:water_cost_1234567"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _point(day: date, value: float) -> ConsumptionPoint:
    return ConsumptionPoint(period_start=day, period_end=day, value_m3=value)


def test_daily_values_later_point_wins() -> None:
    values = statistics.daily_values(
        (
            _point(date(2026, 11, 2), 0.264),
            _point(date(2026, 11, 1), 0.126),  # partial value, revised below
            _point(date(2026, 11, 1), 0.586),
        )
    )
    assert values == {date(2026, 11, 1): 0.586, date(2026, 11, 2): 0.264}


def test_build_statistics_cumulative_and_sorted() -> None:
    stats = statistics.build_statistics(
        {date(2026, 11, 2): 0.264, date(2026, 11, 1): 0.586}, base_sum=10.0, now=NOW
    )
    assert [s["start"] for s in stats] == [
        datetime(2026, 11, 1, 23, tzinfo=UTC),
        datetime(2026, 11, 2, 23, tzinfo=UTC),
    ]
    assert [s["sum"] for s in stats] == [10.586, 10.85]
    assert [s["state"] for s in stats] == [10.586, 10.85]


def test_build_statistics_skips_day_still_in_progress() -> None:
    stats = statistics.build_statistics(
        {date(2026, 11, 6): 0.339, date(2026, 11, 7): 0.1}, 0.0, NOW
    )
    assert [s["sum"] for s in stats] == [0.339]


def test_build_statistics_empty() -> None:
    assert statistics.build_statistics({}, 0.0, NOW) == []


def test_statistic_id_format() -> None:
    assert statistics.statistic_id("1234567") == STAT_ID
    assert statistics.cost_statistic_id("1234567") == COST_ID


async def test_import_continues_from_last_stored_sum() -> None:
    add: Mock = async_add_external_statistics  # stubbed in conftest
    add.reset_mock()
    during: Mock = statistics_during_period
    during.reset_mock()
    during.return_value = {STAT_ID: [{"start": 1.0, "sum": 42.0}]}
    try:
        await statistics.async_import_meter_statistics(
            Mock(), "1234567", (_point(date(2026, 11, 1), 0.5),)
        )
    finally:
        during.return_value = {}
    add.assert_called_once()
    _hass, metadata, stats = add.call_args.args
    assert metadata["statistic_id"] == STAT_ID
    assert metadata["unit_of_measurement"] == "m³"
    assert metadata["has_sum"] is True
    assert metadata["mean_type"] == StatisticMeanType.NONE
    assert "has_mean" not in metadata  # deprecated, HA drops it in 2026.4
    assert metadata["source"] == "suez_water_remote"
    assert [s["sum"] for s in stats] == [42.5]
    # The lookup covers a bounded window right before the first imported day.
    _hass, start, end, ids, period, _units, types = during.call_args.args
    assert end == datetime(2026, 11, 1, 23, tzinfo=UTC)
    assert start < end
    assert ids == {STAT_ID}
    assert period == "hour"
    assert types == {"sum"}


async def test_import_starts_from_zero_without_history() -> None:
    add: Mock = async_add_external_statistics
    add.reset_mock()
    await statistics.async_import_meter_statistics(
        Mock(), "1234567", (_point(date(2026, 11, 1), 0.5),)
    )
    _hass, _metadata, stats = add.call_args.args
    assert [s["sum"] for s in stats] == [0.5]


async def test_import_with_price_adds_cost_statistic() -> None:
    add: Mock = async_add_external_statistics
    add.reset_mock()
    hass = SimpleNamespace(config=SimpleNamespace(currency="CZK"))
    await statistics.async_import_meter_statistics(
        hass, "1234567", (_point(date(2026, 11, 1), 0.5),), price_per_m3=134.7
    )
    assert add.call_count == 2
    _hass, metadata, stats = add.call_args_list[1].args
    assert metadata["statistic_id"] == COST_ID
    assert metadata["unit_of_measurement"] == "CZK"
    assert metadata["has_sum"] is True
    assert [s["sum"] for s in stats] == [67.35]


async def test_import_noop_when_empty() -> None:
    add: Mock = async_add_external_statistics
    add.reset_mock()
    await statistics.async_import_meter_statistics(Mock(), "1234567", ())
    add.assert_not_called()


async def test_clear_meter_statistics_waits_for_recorder() -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    recorder = get_instance(hass)
    recorder.cleared.clear()
    await statistics.async_clear_meter_statistics(hass, ["1234567"])
    assert recorder.cleared == [[STAT_ID, COST_ID]]


def test_day_start_is_last_hour_of_day() -> None:
    assert statistics.day_start(date(2026, 5, 24)) == datetime(2026, 5, 24, 23, tzinfo=UTC)
