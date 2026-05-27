"""The Suez Water Remote integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import SuezAuthenticationError, SuezConnectionError
from .coordinator import SuezConfigEntry, SuezWaterCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


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
    # Import the full daily history into statistics in the background, so the
    # Energy dashboard shows older days too. Idempotent and non-blocking — it
    # must not delay or fail setup.
    entry.async_create_background_task(
        hass, coordinator.async_backfill(), "suez_water_remote_backfill"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SuezConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: SuezConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
