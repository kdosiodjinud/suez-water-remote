"""Long-term statistics import for the Suez Water Remote integration.

The portal publishes per-day consumption with a delay (usually a day, at times
more) and revises a partially measured day later, so a live
``TOTAL_INCREASING`` sensor would attribute usage to the wrong day in the
Energy dashboard. Instead we import an external statistic with one row per
day, dated at 23:00 local time of the day it covers, whose ``sum`` is the
running total of the daily consumption table. That table is the only portal
dataset with liter precision; the daily meter-index table is rounded to whole
cubic meters.

Every import recomputes the rows of the days it covers, continuing from the
last sum already stored before that window, so late or revised days land on
their real date and the running total stays continuous with older history.
Re-importing the same ``start`` is an idempotent upsert.

The statistic is *external* (its id carries a ``:``), which lets the user add
it to the Water section of the Energy dashboard without it being tied to a
live entity. External statistics cannot be priced in the Energy dashboard, so
when the user sets a price per m³ a parallel *cost* statistic (in the
instance's currency) is imported the same way, to be picked as the water
source's cost.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import ConsumptionPoint
from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

# m³ is one of the volume units the Energy dashboard accepts for water.
_STATISTIC_UNIT = "m³"
# How far back to look for the last stored sum when continuing a series. Rows
# are daily, so this bounds the query to a few hundred rows.
_CONTINUITY_LOOKBACK = timedelta(days=400)
# The clear is queued behind whatever the recorder is busy with; right after a
# restart that backlog can take minutes on a large database.
_CLEAR_TIMEOUT = 300.0


def statistic_id(meter_id: str) -> str:
    """Return the external statistic id for a meter's cumulative water usage."""
    return f"{DOMAIN}:water_{meter_id}"


def cost_statistic_id(meter_id: str) -> str:
    """Return the external statistic id for a meter's cumulative water cost."""
    return f"{DOMAIN}:water_cost_{meter_id}"


def daily_values(points: Iterable[ConsumptionPoint]) -> dict[date, float]:
    """Return consumption per day; a later point for the same day wins."""
    return {point.period_start: point.value_m3 for point in points}


def day_start(day: date) -> datetime:
    """Return the timestamp a day's consumption is recorded at: 23:00 local.

    The Energy dashboard attributes a row to the hour it starts at, so the
    last hour of the day keeps the whole day's usage on its real date.
    """
    return datetime.combine(day, time(23), tzinfo=dt_util.get_default_time_zone())


def build_statistics(
    values: Mapping[date, float], base_sum: float, now: datetime
) -> list[StatisticData]:
    """Turn per-day values into cumulative rows continuing from ``base_sum``.

    A day that is not over yet at ``now`` is left out: the portal publishes it
    partially measured and the next refresh brings the complete value.
    """
    stats: list[StatisticData] = []
    running = base_sum
    for day in sorted(values):
        start = day_start(day)
        if start > now:
            break
        running = round(running + values[day], 3)
        stats.append(StatisticData(start=start, state=running, sum=running))
    return stats


def _last_sum_before(hass: HomeAssistant, stat_id: str, start: datetime) -> float:
    """Return the sum stored right before ``start`` (0.0 if none). Recorder thread."""
    rows = statistics_during_period(
        hass, start - _CONTINUITY_LOOKBACK, start, {stat_id}, "hour", None, {"sum"}
    ).get(stat_id)
    if not rows:
        return 0.0
    return rows[-1]["sum"] or 0.0


async def _async_import(
    hass: HomeAssistant,
    stat_id: str,
    name: str,
    unit: str,
    values: Mapping[date, float],
) -> None:
    base_sum = await get_instance(hass).async_add_executor_job(
        _last_sum_before, hass, stat_id, day_start(min(values))
    )
    stats = build_statistics(values, base_sum, dt_util.now())
    if not stats:
        return
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=stat_id,
        unit_of_measurement=unit,
    )
    async_add_external_statistics(hass, metadata, stats)


async def async_import_meter_statistics(
    hass: HomeAssistant,
    meter_id: str,
    points: Iterable[ConsumptionPoint],
    price_per_m3: float | None = None,
) -> None:
    """Import daily water consumption of one meter as cumulative statistics.

    With ``price_per_m3`` a cost statistic in the instance's currency is
    imported alongside, for the Energy dashboard to show water costs.
    """
    values = daily_values(points)
    if not values:
        return
    await _async_import(
        hass, statistic_id(meter_id), f"{MANUFACTURER} water {meter_id}", _STATISTIC_UNIT, values
    )
    if price_per_m3 is not None:
        await _async_import(
            hass,
            cost_statistic_id(meter_id),
            f"{MANUFACTURER} water cost {meter_id}",
            hass.config.currency,
            {day: value * price_per_m3 for day, value in values.items()},
        )


async def async_clear_meter_statistics(
    hass: HomeAssistant, meter_ids: Iterable[str]
) -> None:
    """Delete the statistics of ``meter_ids`` and wait until the recorder did."""
    done = asyncio.Event()
    get_instance(hass).async_clear_statistics(
        [
            stat_id
            for meter_id in meter_ids
            for stat_id in (statistic_id(meter_id), cost_statistic_id(meter_id))
        ],
        on_done=lambda: hass.loop.call_soon_threadsafe(done.set),
    )
    try:
        await asyncio.wait_for(done.wait(), _CLEAR_TIMEOUT)
    except TimeoutError:
        _LOGGER.warning("timed out waiting for the recorder to clear water statistics")
