"""Pytest configuration: load fixtures, stub heavy HA imports for unit tests.

The Suez VHS API client and parsers under :mod:`custom_components.suez_water_remote.api`
have no Home Assistant dependency. To exercise them on a vanilla Python
environment (CI, local laptop, etc.) without installing the multi-hundred-MB
``homeassistant`` package, we expose just enough fake modules to let the parent
``custom_components.suez_water_remote`` package import cleanly.

Tests that need a full Home Assistant runtime should be marked
``@pytest.mark.requires_ha`` and skipped when the stub is in effect.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    """Return the contents of a saved HTML fixture."""
    path = FIXTURES / name
    if not path.exists():
        raise FileNotFoundError(f"fixture {name} not present at {path}")
    return path.read_text(encoding="utf-8")


def _stub_homeassistant() -> None:
    """Install minimal ``homeassistant.*`` stubs into :data:`sys.modules`.

    Only attribute access shape matters — the unit tests covered by this
    conftest never call into these objects.
    """
    if "homeassistant" in sys.modules:
        return

    def make(name: str, **attrs: object) -> types.ModuleType:
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module
        return module

    class _Platform:
        SENSOR = "sensor"
        BUTTON = "button"

    class _ConfigEntryAuthFailed(Exception):
        pass

    class _ConfigEntryNotReady(Exception):
        pass

    from typing import Generic, TypeVar

    _T = TypeVar("_T")

    from typing import ClassVar

    class _ConfigEntry(Generic[_T]):
        data: ClassVar[dict] = {}
        options: ClassVar[dict] = {}
        title: str = ""
        entry_id: str = ""
        runtime_data: object | None = None

        def add_update_listener(self, _: object) -> object:
            return None

        def async_on_unload(self, _: object) -> None:
            return None

    class _DataUpdateCoordinator(Generic[_T]):
        config_entry: object | None = None
        data: object | None = None

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class _CoordinatorEntity(Generic[_T]):
        def __init__(self, coordinator: object | None = None) -> None:
            self.coordinator = coordinator

    class _UpdateFailed(Exception):
        pass

    from dataclasses import dataclass

    @dataclass(frozen=True, kw_only=True)
    class _SensorEntityDescription:
        # Permissive shape covering every field the integration sets; mirrors
        # the real HA dataclass closely enough for the pure value/attr fns and
        # the per-alarm description builder to be unit-tested without HA.
        key: str = ""
        translation_key: str | None = None
        translation_placeholders: object | None = None
        name: object | None = None
        device_class: object | None = None
        state_class: object | None = None
        native_unit_of_measurement: object | None = None
        suggested_display_precision: int | None = None
        options: object | None = None
        entity_category: object | None = None
        icon: str | None = None

    @dataclass(frozen=True, kw_only=True)
    class _ButtonEntityDescription:
        key: str = ""
        translation_key: str | None = None
        name: object | None = None
        device_class: object | None = None
        entity_category: object | None = None
        icon: str | None = None

    def _async_create_clientsession(*args: object, **kwargs: object) -> object:
        raise RuntimeError("stub: HA not available")

    make("homeassistant")
    make("homeassistant.const", Platform=_Platform,
         CONF_USERNAME="username", CONF_PASSWORD="password",
         UnitOfVolume=types.SimpleNamespace(
             CUBIC_METERS="m³", LITERS="L"))
    make("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    make("homeassistant.exceptions",
         ConfigEntryAuthFailed=_ConfigEntryAuthFailed,
         ConfigEntryNotReady=_ConfigEntryNotReady)
    make("homeassistant.config_entries", ConfigEntry=_ConfigEntry,
         ConfigFlow=object, ConfigFlowResult=dict)
    make("homeassistant.helpers")
    make("homeassistant.helpers.aiohttp_client",
         async_create_clientsession=_async_create_clientsession,
         async_get_clientsession=lambda hass: None)
    make("homeassistant.helpers.update_coordinator",
         DataUpdateCoordinator=_DataUpdateCoordinator,
         UpdateFailed=_UpdateFailed,
         CoordinatorEntity=_CoordinatorEntity)
    make("homeassistant.helpers.device_registry", DeviceInfo=dict)
    make("homeassistant.helpers.entity_platform",
         AddConfigEntryEntitiesCallback=object)
    make("homeassistant.helpers.selector",
         SelectSelector=object, SelectSelectorConfig=object,
         SelectSelectorMode=types.SimpleNamespace(LIST="list"),
         TextSelector=object, TextSelectorConfig=object,
         TextSelectorType=types.SimpleNamespace(TEXT="text", PASSWORD="password"))
    make("homeassistant.components")
    make("homeassistant.components.sensor",
         SensorDeviceClass=types.SimpleNamespace(
             WATER="water", TIMESTAMP="timestamp", ENUM="enum"),
         SensorEntity=object,
         SensorEntityDescription=_SensorEntityDescription,
         SensorStateClass=types.SimpleNamespace(
             TOTAL_INCREASING="total_increasing", TOTAL="total",
             MEASUREMENT="measurement",
         ))
    make("homeassistant.components.button",
         ButtonEntity=object,
         ButtonEntityDescription=_ButtonEntityDescription)
    make("homeassistant.components.diagnostics",
         async_redact_data=lambda d, _: d)
    make("homeassistant.components.recorder")
    # StatisticData / StatisticMetaData are TypedDicts in HA, i.e. plain dicts
    # at runtime — ``dict(**kwargs)`` mirrors their construction. The names MUST
    # match the real HA API exactly, otherwise the stub masks a bad import.
    make("homeassistant.components.recorder.models",
         StatisticData=dict, StatisticMetaData=dict)
    make("homeassistant.components.recorder.statistics",
         async_add_external_statistics=Mock())
    make("homeassistant.util")
    make("homeassistant.util.dt",
         as_utc=lambda d: d, as_local=lambda d: d)


_stub_homeassistant()
