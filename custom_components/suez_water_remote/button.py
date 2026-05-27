"""Button entities for the Suez Water Remote integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SuezConfigEntry, SuezWaterCoordinator
from .entity import meter_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuezConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the force-refresh button for each configured meter."""
    coordinator = entry.runtime_data
    async_add_entities(
        SuezRefreshButton(coordinator, meter_id)
        for meter_id in coordinator.meter_ids
    )


class SuezRefreshButton(CoordinatorEntity[SuezWaterCoordinator], ButtonEntity):
    """Button that forces an immediate refresh of the meter data."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SuezWaterCoordinator, meter_id: str) -> None:
        super().__init__(coordinator)
        self._meter_id = meter_id
        self._attr_unique_id = f"{meter_id}_refresh"
        self._attr_device_info = meter_device_info(coordinator, meter_id)

    @property
    def available(self) -> bool:
        # Stay pressable even after a failed update — retrying is exactly when
        # the user reaches for this button. CoordinatorEntity would otherwise
        # report unavailable whenever ``last_update_success`` is False.
        return True

    async def async_press(self) -> None:
        """Fetch the latest data from the portal on demand."""
        await self.coordinator.async_request_refresh()
