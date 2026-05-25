"""Typed data containers returned by the Suez VHS client."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class MeterReading:
    """A single cumulative meter reading."""

    meter_id: str
    timestamp: datetime
    """Absolute timestamp the reading was produced by the device."""
    value_m3: float
    """Meter value expressed in cubic meters."""


@dataclass(frozen=True, slots=True)
class ConsumptionPoint:
    """A single delta consumption point covering a fixed period."""

    period_start: date
    """First day of the period this point summarises."""
    period_end: date
    """Last day (inclusive) of the period."""
    value_m3: float
    """Consumption during the period expressed in cubic meters."""


@dataclass(frozen=True, slots=True)
class AlarmEntry:
    """A single threshold alarm record reported by the portal."""

    alarm_type: str
    """Human readable description, in the portal's UI language."""
    occurred_at: datetime
    """When the anomaly was detected by the meter."""
    notified_at: datetime | None
    """When the customer was notified (email/SMS), if known."""
    value: float | None
    """Reported volume that triggered the alarm. ``None`` if not numeric."""
    email_status: str | None
    sms_status: str | None


@dataclass(frozen=True, slots=True)
class MeterSnapshot:
    """A point-in-time view across every dataset for a single meter."""

    meter_id: str
    """Stable identifier as printed in the portal title bar (e.g. ``1234567``)."""
    site_label: str
    """Full account identifier (e.g. ``99999-XX-1234567``)."""
    current_index: MeterReading
    """Latest cumulative reading, also exposed by the home page odometer."""
    today_total_liters: float | None
    """Volume already consumed today, derived from the home-page chart."""
    monthly_consumption: tuple[ConsumptionPoint, ...] = field(default_factory=tuple)
    yearly_consumption: tuple[ConsumptionPoint, ...] = field(default_factory=tuple)
    daily_consumption: tuple[ConsumptionPoint, ...] = field(default_factory=tuple)
    monthly_index: tuple[MeterReading, ...] = field(default_factory=tuple)
    daily_index: tuple[MeterReading, ...] = field(default_factory=tuple)
    alarms: tuple[AlarmEntry, ...] = field(default_factory=tuple)

    def to_diagnostic_dict(self) -> Mapping[str, object]:
        """Return a representation suitable for diagnostics output."""
        return {
            "meter_id": self.meter_id,
            "site_label": self.site_label,
            "current_index_m3": self.current_index.value_m3,
            "current_index_at": self.current_index.timestamp.isoformat(),
            "today_total_liters": self.today_total_liters,
            "monthly_consumption_points": len(self.monthly_consumption),
            "yearly_consumption_points": len(self.yearly_consumption),
            "daily_consumption_points": len(self.daily_consumption),
            "monthly_index_points": len(self.monthly_index),
            "daily_index_points": len(self.daily_index),
            "alarm_count": len(self.alarms),
        }
