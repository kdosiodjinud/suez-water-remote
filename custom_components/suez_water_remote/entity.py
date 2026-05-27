"""Shared entity helpers for the Suez Water Remote integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import SuezWaterCoordinator


def meter_device_info(
    coordinator: SuezWaterCoordinator, meter_id: str
) -> DeviceInfo:
    """Build the :class:`DeviceInfo` for a single Suez meter.

    Uses the site label rendered by the portal (e.g. ``"99999-XX-1234567"``)
    as a stable, human-readable device name; falls back to the meter id alone
    before the first snapshot lands. Shared by every platform so the sensor
    and button entities attach to the same device.
    """
    device_name = meter_id
    if coordinator.data is not None:
        snapshot = coordinator.data.meters.get(meter_id)
        if snapshot is not None:
            device_name = snapshot.site_label
    return DeviceInfo(
        identifiers={(DOMAIN, meter_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=device_name,
        configuration_url=str(coordinator.client.base_url),
    )
