"""The Suez Water Remote integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import SuezAuthenticationError, SuezConnectionError
from .const import CONF_METERS
from .coordinator import SuezConfigEntry, SuezWaterCoordinator
from .statistics import async_clear_meter_statistics

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


async def async_migrate_entry(hass: HomeAssistant, entry: SuezConfigEntry) -> bool:
    """Migrate a config entry to the current version."""
    if entry.version == 1:
        # 0.5.x built the water statistic from the portal's daily meter-index
        # table, which is rounded to whole m³. Drop it; the backfill on setup
        # re-imports the history with liter precision from the consumption
        # table.
        await async_clear_meter_statistics(hass, entry.data[CONF_METERS])
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SuezConfigEntry) -> bool:
    """Set up Suez Water Remote from a config entry."""
    coordinator = SuezWaterCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except SuezAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SuezConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Import the daily history of every month the portal offers into
    # statistics in the background, so the Energy dashboard shows older days
    # too. Idempotent and non-blocking — it must not delay or fail setup.
    entry.async_create_background_task(
        hass, coordinator.async_backfill(), "suez_water_remote_backfill"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SuezConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: SuezConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
