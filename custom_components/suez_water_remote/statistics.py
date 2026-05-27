"""Long-term statistics import for the Suez Water Remote integration.

The portal publishes per-day consumption with a delay, so a live
``TOTAL_INCREASING`` sensor would attribute late data to the wrong day in the
Energy dashboard. Instead we import statistics with an explicit timestamp for
each day, taken from :attr:`MeterSnapshot.daily_index` (the cumulative meter
reading per day). Home Assistant derives daily consumption as the difference
between consecutive ``sum`` values, so each day lands on its real date no
matter when it was fetched. Re-importing the same ``start`` is idempotent, so
days that arrive late are simply backfilled on the next refresh.

The statistic is *external* (its id carries a ``:``), which lets the user add
it to the Water section of the Energy dashboard without it being tied to a
live entity.
"""

from __future__ import annotations

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .api import MeterSnapshot
from .const import DOMAIN, MANUFACTURER

# m³ is one of the volume units the Energy dashboard accepts for water.
_STATISTIC_UNIT = "m³"


def statistic_id(meter_id: str) -> str:
    """Return the external statistic id for a meter's cumulative water usage."""
    return f"{DOMAIN}:water_{meter_id}"


def build_statistics(snapshot: MeterSnapshot) -> list[StatisticData]:
    """Build cumulative daily statistics from a snapshot's daily index.

    Each point uses the day's reading timestamp (already 23:00 local, i.e.
    hour-aligned) made timezone-aware, and the cumulative meter value as both
    ``sum`` and ``state``. Points are returned in ascending time order.
    """
    stats: list[StatisticData] = []
    for reading in sorted(snapshot.daily_index, key=lambda r: r.timestamp):
        start = dt_util.as_local(reading.timestamp).replace(
            minute=0, second=0, microsecond=0
        )
        stats.append(
            StatisticData(
                start=start,
                sum=reading.value_m3,
                state=reading.value_m3,
            )
        )
    return stats


@callback
def async_update_meter_statistics(
    hass: HomeAssistant, snapshot: MeterSnapshot
) -> None:
    """Import the cumulative daily water statistics for one meter."""
    stats = build_statistics(snapshot)
    if not stats:
        return
    metadata = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name=f"{MANUFACTURER} water {snapshot.meter_id}",
        source=DOMAIN,
        statistic_id=statistic_id(snapshot.meter_id),
        unit_of_measurement=_STATISTIC_UNIT,
    )
    async_add_external_statistics(hass, metadata, stats)
