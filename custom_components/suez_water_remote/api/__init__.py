"""HTTP client for the Suez Smart Solutions customer portal."""

from .client import SuezVhsClient, derive_base_url
from .exceptions import (
    SuezAuthenticationError,
    SuezConnectionError,
    SuezError,
    SuezParseError,
)
from .locales import (
    DEFAULT_LOCALE,
    LOCALE_CS,
    LOCALE_DE,
    LOCALE_EN,
    LOCALE_FR,
    LOCALES,
    Locale,
    detect_locale,
)
from .models import (
    AlarmEntry,
    ConsumptionPoint,
    MeterReading,
    MeterSnapshot,
)

__all__ = [
    "DEFAULT_LOCALE",
    "LOCALES",
    "LOCALE_CS",
    "LOCALE_DE",
    "LOCALE_EN",
    "LOCALE_FR",
    "AlarmEntry",
    "ConsumptionPoint",
    "Locale",
    "MeterReading",
    "MeterSnapshot",
    "SuezAuthenticationError",
    "SuezConnectionError",
    "SuezError",
    "SuezParseError",
    "SuezVhsClient",
    "derive_base_url",
    "detect_locale",
]
