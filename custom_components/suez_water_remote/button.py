"""Button entities for the Suez Water Remote integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
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
    """Set up the per-meter refresh and history-backfill buttons."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = []
    for meter_id in coordinator.meter_ids:
        entities.append(SuezRefreshButton(coordinator, meter_id))
        entities.append(SuezBackfillButton(coordinator, meter_id))
    async_add_entities(entities)


class _SuezButton(CoordinatorEntity[SuezWaterCoordinator], ButtonEntity):
    """Base for Suez action buttons (always pressable, attached to the meter)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SuezWaterCoordinator, meter_id: str) -> None:
        super().__init__(coordinator)
        self._meter_id = meter_id
        self._attr_device_info = meter_device_info(coordinator, meter_id)

    @property
    def available(self) -> bool:
        # Stay pressable even after a failed update — retrying is exactly when
        # the user reaches for these buttons. CoordinatorEntity would otherwise
        # report unavailable whenever ``last_update_success`` is False.
        return True


class SuezRefreshButton(_SuezButton):
    """Button that forces an immediate refresh of the meter data."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SuezWaterCoordinator, meter_id: str) -> None:
        super().__init__(coordinator, meter_id)
        self._attr_unique_id = f"{meter_id}_refresh"

    async def async_press(self) -> None:
        """Fetch the latest data from the portal on demand."""
        await self.coordinator.async_request_refresh()


class SuezBackfillButton(_SuezButton):
    """Button that re-imports the full daily history into statistics."""

    _attr_translation_key = "backfill"
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SuezWaterCoordinator, meter_id: str) -> None:
        super().__init__(coordinator, meter_id)
        self._attr_unique_id = f"{meter_id}_backfill"

    async def async_press(self) -> None:
        """Re-import the meter's full daily history into long-term statistics."""
        await self.coordinator.async_backfill_meter(self._meter_id)
