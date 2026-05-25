"""Sensor entities for the Suez Water Remote integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import ConsumptionPoint, MeterSnapshot
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import SuezConfigEntry, SuezWaterCoordinator

SensorValue = float | int | datetime | None


@dataclass(frozen=True, kw_only=True, slots=True)
class SuezSensorDescription(SensorEntityDescription):
    """Sensor description binding a metric to a snapshot extractor."""

    value_fn: Callable[[MeterSnapshot], SensorValue]


def _last_year_consumption(snapshot: MeterSnapshot) -> float | None:
    today = date.today()
    target = today.year - 1
    for point in snapshot.yearly_consumption:
        if point.period_start.year == target:
            return point.value_m3
    return None


def _this_year_consumption(snapshot: MeterSnapshot) -> float | None:
    today = date.today()
    for point in snapshot.yearly_consumption:
        if point.period_start.year == today.year:
            return point.value_m3
    return None


def _by_month(points: tuple[ConsumptionPoint, ...], target: date) -> float | None:
    for p in points:
        if p.period_start.year == target.year and p.period_start.month == target.month:
            return p.value_m3
    return None


def _this_month_consumption(snapshot: MeterSnapshot) -> float | None:
    return _by_month(snapshot.monthly_consumption, date.today())


def _last_month_consumption(snapshot: MeterSnapshot) -> float | None:
    today = date.today()
    if today.month == 1:
        target = date(today.year - 1, 12, 1)
    else:
        target = date(today.year, today.month - 1, 1)
    return _by_month(snapshot.monthly_consumption, target)


def _yesterday_consumption(snapshot: MeterSnapshot) -> float | None:
    today = date.today()
    if not snapshot.daily_consumption:
        return None
    for point in reversed(snapshot.daily_consumption):
        if point.period_start < today:
            return point.value_m3
    return None


def _today_consumption(snapshot: MeterSnapshot) -> float | None:
    if snapshot.today_total_liters is None:
        return None
    return snapshot.today_total_liters / 1000.0


def _last_reading_time(snapshot: MeterSnapshot) -> datetime:
    # The portal exposes a naive local timestamp (Europe/Prague). HA expects
    # timezone-aware datetimes for SensorDeviceClass.TIMESTAMP.
    return dt_util.as_utc(dt_util.as_local(snapshot.current_index.timestamp))


def _latest_alarm_time(snapshot: MeterSnapshot) -> datetime | None:
    if not snapshot.alarms:
        return None
    latest = max(a.occurred_at for a in snapshot.alarms)
    return dt_util.as_utc(dt_util.as_local(latest))


SENSORS: tuple[SuezSensorDescription, ...] = (
    SuezSensorDescription(
        key="meter_total",
        translation_key="meter_total",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=lambda s: s.current_index.value_m3,
    ),
    SuezSensorDescription(
        key="last_reading_time",
        translation_key="last_reading_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_reading_time,
    ),
    SuezSensorDescription(
        key="today_consumption",
        translation_key="today_consumption",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=_today_consumption,
    ),
    SuezSensorDescription(
        key="yesterday_consumption",
        translation_key="yesterday_consumption",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=_yesterday_consumption,
    ),
    SuezSensorDescription(
        key="this_month_consumption",
        translation_key="this_month_consumption",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=_this_month_consumption,
    ),
    SuezSensorDescription(
        key="last_month_consumption",
        translation_key="last_month_consumption",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=_last_month_consumption,
    ),
    SuezSensorDescription(
        key="this_year_consumption",
        translation_key="this_year_consumption",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=_this_year_consumption,
    ),
    SuezSensorDescription(
        key="last_year_consumption",
        translation_key="last_year_consumption",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=_last_year_consumption,
    ),
    SuezSensorDescription(
        key="alarm_count",
        translation_key="alarm_count",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: len(s.alarms),
    ),
    SuezSensorDescription(
        key="latest_alarm_time",
        translation_key="latest_alarm_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_latest_alarm_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuezConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Suez Water Remote sensors."""
    coordinator = entry.runtime_data
    entities: list[SuezWaterSensor] = []
    for meter_id in coordinator.meter_ids:
        for desc in SENSORS:
            entities.append(SuezWaterSensor(coordinator, meter_id, desc))
    async_add_entities(entities)


class SuezWaterSensor(CoordinatorEntity[SuezWaterCoordinator], SensorEntity):
    """A single sensor attached to a Suez meter."""

    entity_description: SuezSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SuezWaterCoordinator,
        meter_id: str,
        description: SuezSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._meter_id = meter_id
        self._attr_unique_id = f"{meter_id}_{description.key}"
        # Use the site label rendered by the portal (e.g.
        # "99999-XX-1234567") as a stable, human-readable device name; fall
        # back to the meter id alone before the first snapshot lands.
        device_name = meter_id
        if coordinator.data is not None:
            snapshot = coordinator.data.meters.get(meter_id)
            if snapshot is not None:
                device_name = snapshot.site_label
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, meter_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=device_name,
            configuration_url=str(coordinator.client.base_url),
        )

    @callback
    def _snapshot(self) -> MeterSnapshot | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.meters.get(self._meter_id)

    @property
    def available(self) -> bool:
        return super().available and self._snapshot() is not None

    @property
    def native_value(self) -> SensorValue:
        snapshot = self._snapshot()
        if snapshot is None:
            return None
        return self.entity_description.value_fn(snapshot)
