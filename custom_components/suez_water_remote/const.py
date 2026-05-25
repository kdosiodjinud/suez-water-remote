"""Constants for the Suez Water Remote integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "suez_water_remote"

CONF_URL: Final = "url"
"""Full URL to any page of the user's portal (login page typically)."""

CONF_BASE_URL: Final = "base_url"
"""Application root derived from :data:`CONF_URL` at config-flow time."""

CONF_LOCALE: Final = "locale"
"""Two-letter language code auto-detected at config-flow time."""

CONF_METERS: Final = "meters"

# Polling cadence: the upstream telemetry refreshes once per day at 23:00; a
# short interval would just waste API calls. Every 6 hours is enough to
# surface new data within hours of release.
DEFAULT_SCAN_INTERVAL: Final = timedelta(hours=6)

MANUFACTURER: Final = "Suez Smart Solutions"
MODEL: Final = "Remote water meter"
