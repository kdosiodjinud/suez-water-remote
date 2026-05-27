"""Unit tests for the force-refresh button."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

from custom_components.suez_water_remote.button import SuezRefreshButton

if TYPE_CHECKING:
    from custom_components.suez_water_remote.coordinator import SuezWaterCoordinator


def _coordinator() -> SimpleNamespace:
    return SimpleNamespace(
        data=None,
        client=SimpleNamespace(base_url="https://cz-sitr.example/eMIS.SE_X/"),
        async_request_refresh=AsyncMock(),
    )


def test_button_identity() -> None:
    coordinator = _coordinator()
    button = SuezRefreshButton(cast("SuezWaterCoordinator", coordinator), "1234567")
    assert button._attr_unique_id == "1234567_refresh"
    assert button._attr_translation_key == "refresh"
    assert button.coordinator is coordinator


def test_button_always_available() -> None:
    # Must stay pressable even when the last coordinator update failed.
    coordinator = _coordinator()
    coordinator.last_update_success = False
    button = SuezRefreshButton(cast("SuezWaterCoordinator", coordinator), "1234567")
    assert button.available is True


async def test_button_press_triggers_refresh() -> None:
    coordinator = _coordinator()
    button = SuezRefreshButton(cast("SuezWaterCoordinator", coordinator), "1234567")
    await button.async_press()
    coordinator.async_request_refresh.assert_awaited_once()
