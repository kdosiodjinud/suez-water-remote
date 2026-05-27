"""Sensor entities for the Suez Water Remote integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .alarm_labels import alarm_param_concept, alarm_type_concept
from .api import AlarmConfig, ConsumptionPoint, MeterSnapshot
from .coordinator import SuezConfigEntry, SuezWaterCoordinator
from .entity import meter_device_info

SensorValue = float | int | str | datetime | None

# Liters in one cubic meter — used for the parallel ``*_liters`` sensors.
_LITERS_PER_M3 = 1000.0

_ALARM_ACTIVE_OPTIONS = ("on", "off")


@dataclass(frozen=True, kw_only=True, slots=True)
class SuezSensorDescription(SensorEntityDescription):
    """Sensor description binding a metric to a snapshot extractor."""

    value_fn: Callable[[MeterSnapshot], SensorValue]
    attrs_fn: Callable[[MeterSnapshot], Mapping[str, object] | None] | None = None


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


def _by_day(points: tuple[ConsumptionPoint, ...], target: date) -> float | None:
    """Return the consumption (in m³) for ``target`` or ``None`` if absent."""
    for p in points:
        if p.period_start == target:
            return p.value_m3
    return None


def _yesterday_consumption(snapshot: MeterSnapshot) -> float:
    # Exact-date lookup against the daily-statistics page: never mixes the
    # previous day's measured value into a different day. Falls back to 0.0
    # when the portal has not published yesterday's row yet, so the sensor
    # always reports a number rather than ``unknown``.
    value = _by_day(snapshot.daily_consumption, date.today() - timedelta(days=1))
    return value if value is not None else 0.0


def _today_consumption(snapshot: MeterSnapshot) -> float:
    # Exact-date lookup against the daily-statistics page. Until the portal
    # publishes today's row, this reports 0.0 rather than echoing another
    # day's value — yesterday's measurement is never surfaced as "today".
    value = _by_day(snapshot.daily_consumption, date.today())
    return value if value is not None else 0.0


def _today_consumption_liters(snapshot: MeterSnapshot) -> float:
    return _today_consumption(snapshot) * _LITERS_PER_M3


def _yesterday_consumption_liters(snapshot: MeterSnapshot) -> float:
    return _yesterday_consumption(snapshot) * _LITERS_PER_M3


def _measured_date_attrs(
    days_ago: int,
) -> Callable[[MeterSnapshot], Mapping[str, object]]:
    """Expose whether the target day actually has a row on the daily page.

    ``days_ago`` is resolved against ``date.today()`` at read time (not at
    module import). Lets a dashboard distinguish a genuinely measured 0 m³
    from "no data published yet" — both render as 0 in the state.
    """

    def fn(snapshot: MeterSnapshot) -> Mapping[str, object]:
        target = date.today() - timedelta(days=days_ago)
        present = _by_day(snapshot.daily_consumption, target) is not None
        return {
            "measured_date": target.isoformat() if present else None,
            "data_available": present,
        }

    return fn


def _meter_total_liters(snapshot: MeterSnapshot) -> float:
    return snapshot.current_index.value_m3 * _LITERS_PER_M3


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
        key="meter_total_liters",
        translation_key="meter_total_liters",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        value_fn=_meter_total_liters,
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
        attrs_fn=_measured_date_attrs(0),
    ),
    SuezSensorDescription(
        key="today_consumption_liters",
        translation_key="today_consumption_liters",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        value_fn=_today_consumption_liters,
        attrs_fn=_measured_date_attrs(0),
    ),
    SuezSensorDescription(
        key="yesterday_consumption",
        translation_key="yesterday_consumption",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=_yesterday_consumption,
        attrs_fn=_measured_date_attrs(1),
    ),
    SuezSensorDescription(
        key="yesterday_consumption_liters",
        translation_key="yesterday_consumption_liters",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        value_fn=_yesterday_consumption_liters,
        attrs_fn=_measured_date_attrs(1),
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
        icon="mdi:bell",
        value_fn=lambda s: len(s.alarms),
    ),
    SuezSensorDescription(
        key="latest_alarm_time",
        translation_key="latest_alarm_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:bell-ring",
        value_fn=_latest_alarm_time,
    ),
)


# --- Alarm configuration sensors ---------------------------------------------


def _find_alarm_config(snapshot: MeterSnapshot, config_id: str) -> AlarmConfig | None:
    for cfg in snapshot.alarm_configs:
        if cfg.config_id == config_id:
            return cfg
    return None


def _alarm_active_state(config_id: str) -> Callable[[MeterSnapshot], str | None]:
    def fn(snapshot: MeterSnapshot) -> str | None:
        cfg = _find_alarm_config(snapshot, config_id)
        if cfg is None:
            return None
        return "on" if cfg.active else "off"

    return fn


def _alarm_active_attrs(
    config_id: str,
) -> Callable[[MeterSnapshot], Mapping[str, object] | None]:
    def fn(snapshot: MeterSnapshot) -> Mapping[str, object] | None:
        cfg = _find_alarm_config(snapshot, config_id)
        if cfg is None:
            return None
        labels = [p.label for p in cfg.parameters if p.is_configured]
        return {
            "alarm_type": cfg.alarm_type,
            "email": cfg.email,
            "phone": cfg.phone,
            "parameter_labels": labels,
        }

    return fn


def _alarm_param_state(
    config_id: str, slot: int
) -> Callable[[MeterSnapshot], float | str | None]:
    def fn(snapshot: MeterSnapshot) -> float | str | None:
        cfg = _find_alarm_config(snapshot, config_id)
        if cfg is None:
            return None
        param = cfg.parameters[slot]
        if not param.is_configured:
            return None
        # Surface the numeric value when the portal serialised it as a plain
        # decimal (kept numeric so automations can compare it); collapse whole
        # numbers to int so a threshold shows as "800"/"1", not "800.0"/"1.0".
        # Fall back to the raw text when the value is not numeric (rare).
        num = param.value_numeric
        if num is None:
            return param.value
        return int(num) if num.is_integer() else num

    return fn


def _alarm_param_attrs(
    config_id: str, slot: int
) -> Callable[[MeterSnapshot], Mapping[str, object] | None]:
    def fn(snapshot: MeterSnapshot) -> Mapping[str, object] | None:
        cfg = _find_alarm_config(snapshot, config_id)
        if cfg is None:
            return None
        param = cfg.parameters[slot]
        if not param.is_configured:
            return None
        return {"label": param.label, "raw_value": param.value}

    return fn


def _alarm_sensors_for(config: AlarmConfig) -> tuple[SuezSensorDescription, ...]:
    """Build the per-alarm sensor descriptions.

    Each alarm gets one "active" sensor (exposing the type/email/phone in its
    attributes) plus one sensor for every *configured* parameter slot. Empty
    slots are skipped entirely so the device list is not cluttered with
    ``unknown`` placeholders, and entities are named after the portal's own
    localized labels (e.g. "Mez nadměrné spotřeby") instead of opaque
    "parameter 1/2/3" — the alarm type and label are carried as translation
    placeholders. The slot-indexed ``key`` keeps each ``unique_id`` stable
    even if the user later fills another slot.
    """
    cid = config.config_id
    # Known concepts (recognised in cs/en) get a localized translation key so
    # the name follows HA's UI language; everything else falls back to the raw
    # portal label carried as a placeholder. See ``alarm_labels``.
    type_concept = alarm_type_concept(config.alarm_type)
    if type_concept is not None:
        active_key = f"alarm_active_{type_concept}"
        active_placeholders: dict[str, str] | None = None
    else:
        active_key = "alarm_active"
        active_placeholders = {"alarm_type": config.alarm_type}

    descriptions: list[SuezSensorDescription] = [
        SuezSensorDescription(
            key=f"alarm_{cid}_active",
            translation_key=active_key,
            translation_placeholders=active_placeholders,
            device_class=SensorDeviceClass.ENUM,
            options=list(_ALARM_ACTIVE_OPTIONS),
            icon="mdi:bell-alert",
            value_fn=_alarm_active_state(cid),
            attrs_fn=_alarm_active_attrs(cid),
        )
    ]
    for slot, param in enumerate(config.parameters):
        if not param.is_configured:
            continue
        param_concept = alarm_param_concept(param.label)
        if param_concept is not None:
            param_key = f"alarm_param_{param_concept}"
            param_placeholders: dict[str, str] | None = None
        else:
            param_key = "alarm_param"
            param_placeholders = {
                "alarm_type": config.alarm_type,
                "param_label": param.label,
            }
        descriptions.append(
            SuezSensorDescription(
                key=f"alarm_{cid}_param_{slot + 1}",
                translation_key=param_key,
                translation_placeholders=param_placeholders,
                icon="mdi:bell-cog",
                value_fn=_alarm_param_state(cid, slot),
                attrs_fn=_alarm_param_attrs(cid, slot),
            )
        )
    return tuple(descriptions)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuezConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Suez Water Remote sensors.

    Alarm-config sensors are derived from the first snapshot — the
    coordinator's ``async_config_entry_first_refresh`` has already run by
    the time we get here, so the per-alarm descriptions are known.
    """
    coordinator = entry.runtime_data
    entities: list[SuezWaterSensor] = []
    snapshots = coordinator.data.meters if coordinator.data is not None else {}
    for meter_id in coordinator.meter_ids:
        for desc in SENSORS:
            entities.append(SuezWaterSensor(coordinator, meter_id, desc))
        snapshot = snapshots.get(meter_id)
        if snapshot is None:
            continue
        for config in snapshot.alarm_configs:
            for desc in _alarm_sensors_for(config):
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
        self._attr_device_info = meter_device_info(coordinator, meter_id)

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

    @property
    def extra_state_attributes(self) -> Mapping[str, object] | None:
        attrs_fn = self.entity_description.attrs_fn
        if attrs_fn is None:
            return None
        snapshot = self._snapshot()
        if snapshot is None:
            return None
        return attrs_fn(snapshot)
