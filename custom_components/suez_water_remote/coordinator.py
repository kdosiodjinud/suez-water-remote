"""Data update coordinator for the Suez Water Remote integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    LOCALES,
    MeterSnapshot,
    SuezAuthenticationError,
    SuezConnectionError,
    SuezError,
    SuezVhsClient,
)
from .const import (
    CONF_BASE_URL,
    CONF_LOCALE,
    CONF_METERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .statistics import async_import_meter_statistics

_LOGGER = logging.getLogger(__name__)

type SuezConfigEntry = ConfigEntry["SuezWaterCoordinator"]


@dataclass(slots=True)
class SuezData:
    """Container holding the latest snapshot for each configured meter."""

    meters: Mapping[str, MeterSnapshot]


class SuezWaterCoordinator(DataUpdateCoordinator[SuezData]):
    """Coordinator that polls a Suez Smart Solutions portal once per cycle."""

    config_entry: SuezConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SuezConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        # Dedicated session so two accounts on the same instance don't
        # contaminate each other's auth cookies through HA's shared session.
        session = async_create_clientsession(
            hass, cookie_jar=CookieJar(unsafe=False)
        )
        locale = LOCALES.get(entry.data.get(CONF_LOCALE, ""))
        self._client = SuezVhsClient(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            base_url=entry.data[CONF_BASE_URL],
            locale=locale,
            session=session,
        )
        self._meter_ids: tuple[str, ...] = tuple(entry.data[CONF_METERS])

    @property
    def meter_ids(self) -> tuple[str, ...]:
        return self._meter_ids

    @property
    def client(self) -> SuezVhsClient:
        return self._client

    async def _async_update_data(self) -> SuezData:
        results: dict[str, MeterSnapshot] = {}
        try:
            for meter_id in self._meter_ids:
                results[meter_id] = await self._client.async_fetch_snapshot(meter_id)
        except SuezAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SuezConnectionError as err:
            raise UpdateFailed(f"network error: {err}") from err
        except SuezError as err:
            raise UpdateFailed(f"portal error: {err}") from err
        # Import long-term statistics with the real per-day timestamps so the
        # Energy dashboard attributes consumption to the correct day even when
        # the portal publishes it late. This covers the recent polling window;
        # deeper history is handled by ``async_backfill``.
        for snapshot in results.values():
            async_import_meter_statistics(
                self.hass, snapshot.meter_id, snapshot.daily_index
            )
        return SuezData(meters=results)

    async def async_backfill_meter(self, meter_id: str) -> None:
        """Import the full daily history for one meter into statistics.

        Fetches the portal's complete daily series (not just the recent
        window) and imports it; safe to run repeatedly (idempotent upsert).
        Errors are logged and swallowed so a backfill never breaks the entry.
        """
        try:
            readings = await self._client.async_fetch_daily_index(
                meter_id, complete=True
            )
        except SuezError as err:
            _LOGGER.warning("statistics backfill failed for %s: %s", meter_id, err)
            return
        async_import_meter_statistics(self.hass, meter_id, readings)

    async def async_backfill(self) -> None:
        """Backfill the full daily history for every configured meter."""
        for meter_id in self._meter_ids:
            await self.async_backfill_meter(meter_id)
