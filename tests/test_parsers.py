"""Parser unit tests."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from tests.conftest import fixture

from custom_components.suez_water_remote.api.exceptions import SuezParseError
from custom_components.suez_water_remote.api.locales import (
    LOCALE_CS,
    LOCALE_DE,
    LOCALE_EN,
    LOCALE_FR,
)
from custom_components.suez_water_remote.api.parsers import (
    discover_meter_ids,
    parse_alarm_configs,
    parse_alarms,
    parse_daily_consumption,
    parse_daily_index,
    parse_decimal,
    parse_home_page,
    parse_localized_date,
    parse_localized_datetime,
    parse_localized_month,
    parse_monthly_consumption,
    parse_monthly_index,
    parse_yearly_consumption,
)


# --- Generic helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected,locale",
    [
        ("0,000", 0.0, LOCALE_CS),
        ("1,5", 1.5, LOCALE_CS),
        ("1 234,56", 1234.56, LOCALE_CS),
        ("\xa0\xa01\xa0234,56\xa0", 1234.56, LOCALE_CS),
        ("0", 0.0, LOCALE_CS),
        ("100", 100.0, LOCALE_CS),
        ("13.961", 13.961, LOCALE_EN),
        ("1,234.56", 1234.56, LOCALE_EN),
        ("13,961", 13.961, LOCALE_FR),
        ("0,000", 0.0, LOCALE_DE),
    ],
)
def test_parse_decimal_per_locale(raw: str, expected: float, locale) -> None:
    assert parse_decimal(raw, locale) == pytest.approx(expected)


def test_parse_decimal_rejects_empty() -> None:
    with pytest.raises(SuezParseError):
        parse_decimal("   ", LOCALE_CS)


@pytest.mark.parametrize(
    "label,expected,locale",
    [
        ("prosinec 2024", date(2024, 12, 1), LOCALE_CS),
        ("Květen 2026", date(2026, 5, 1), LOCALE_CS),
        ("juin 2024", date(2024, 6, 1), LOCALE_FR),
        ("août 2024", date(2024, 8, 1), LOCALE_FR),
        ("June 2024", date(2024, 6, 1), LOCALE_EN),
        ("December 2025", date(2025, 12, 1), LOCALE_EN),
        ("Juni 2024", date(2024, 6, 1), LOCALE_DE),
        ("März 2025", date(2025, 3, 1), LOCALE_DE),
    ],
)
def test_parse_localized_month(label: str, expected: date, locale) -> None:
    assert parse_localized_month(label, locale) == expected


def test_parse_localized_month_rejects_unknown() -> None:
    with pytest.raises(SuezParseError):
        parse_localized_month("notamonth 2024", LOCALE_CS)
    with pytest.raises(SuezParseError):
        parse_localized_month("prosinec", LOCALE_CS)


@pytest.mark.parametrize(
    "label,expected,locale",
    [
        ("24.05.2026", date(2026, 5, 24), LOCALE_CS),
        ("24/05/2026", date(2026, 5, 24), LOCALE_FR),
        ("5/24/2026", date(2026, 5, 24), LOCALE_EN),
        ("24.05.2026", date(2026, 5, 24), LOCALE_DE),
    ],
)
def test_parse_localized_date(label: str, expected: date, locale) -> None:
    assert parse_localized_date(label, locale) == expected


@pytest.mark.parametrize(
    "label,expected,locale",
    [
        ("24.05.2026 23:00", datetime(2026, 5, 24, 23, 0), LOCALE_CS),
        ("25.05.2026 15:00:34", datetime(2026, 5, 25, 15, 0, 34), LOCALE_CS),
        ("24/05/2026 23:00", datetime(2026, 5, 24, 23, 0), LOCALE_FR),
        ("5/24/2026 11:00 PM", datetime(2026, 5, 24, 23, 0), LOCALE_EN),
        ("5/24/2026 1:30 AM", datetime(2026, 5, 24, 1, 30), LOCALE_EN),
        ("24.05.2026 23:00", datetime(2026, 5, 24, 23, 0), LOCALE_DE),
    ],
)
def test_parse_localized_datetime(label: str, expected: datetime, locale) -> None:
    assert parse_localized_datetime(label, locale) == expected


def test_parse_localized_datetime_rejects_bad_input() -> None:
    with pytest.raises(SuezParseError):
        parse_localized_datetime("not-a-date", LOCALE_CS)


# --- Home page (per locale) --------------------------------------------------


@pytest.mark.parametrize(
    "fname,locale",
    [
        ("home.html", LOCALE_CS),
        ("home_fr.html", LOCALE_FR),
        ("home_en.html", LOCALE_EN),
        ("home_de.html", LOCALE_DE),
    ],
)
def test_home_page_extracts_meter_and_current_index(fname, locale) -> None:
    site, meter, current, today = parse_home_page(fixture(fname), locale)
    assert site == "99999-XX-1234567"
    assert meter == "1234567"
    assert current.meter_id == "1234567"
    assert current.value_m3 == pytest.approx(1119.819)
    assert current.timestamp == datetime(2026, 5, 24, 23, 0)
    assert today == pytest.approx(3789.0)


def test_home_page_autodetects_locale() -> None:
    """Without explicit locale, parse_home_page falls back on detect_locale."""
    _site, meter, current, _today = parse_home_page(fixture("home.html"))
    assert meter == "1234567"
    assert current.value_m3 == pytest.approx(1119.819)


def test_discover_meter_ids_single_account() -> None:
    assert discover_meter_ids(fixture("home.html")) == ("1234567",)


# --- Tables (per locale) -----------------------------------------------------


@pytest.mark.parametrize(
    "fname,locale,expected_last_value",
    [
        ("conso_mois.html", LOCALE_CS, 24.736),
        ("conso_mois_fr.html", LOCALE_FR, 24.736),
        ("conso_mois_en.html", LOCALE_EN, 24.736),
        ("conso_mois_de.html", LOCALE_DE, 24.736),
    ],
)
def test_monthly_consumption_per_locale(fname, locale, expected_last_value) -> None:
    points = parse_monthly_consumption(fixture(fname), locale)
    assert points  # at least one row
    assert points[-1].value_m3 == pytest.approx(expected_last_value)


def test_yearly_consumption_rows() -> None:
    points = parse_yearly_consumption(fixture("conso_an.html"), LOCALE_CS)
    by_year = {p.period_start.year: p.value_m3 for p in points}
    assert by_year[2025] == pytest.approx(155.190)
    assert by_year[2026] == pytest.approx(91.054)


def test_daily_consumption_last_row_is_today() -> None:
    points = parse_daily_consumption(fixture("conso_jour.html"), LOCALE_CS)
    last = points[-1]
    assert last.period_start == date(2026, 5, 24)
    assert last.value_m3 == pytest.approx(3.789)


def test_monthly_index_returns_readings() -> None:
    readings = parse_monthly_index(fixture("index_mois.html"), "1234567", LOCALE_CS)
    assert readings[-1].value_m3 == pytest.approx(1120.0)
    assert readings[-1].timestamp.year == 2026


def test_daily_index_aligned_with_timestamp() -> None:
    readings = parse_daily_index(fixture("index_jour.html"), "1234567", LOCALE_CS)
    last = readings[-1]
    assert last.value_m3 == pytest.approx(1120.0)
    assert last.timestamp.hour == 23


def test_alarms_table_parsed_in_order() -> None:
    alarms = parse_alarms(fixture("alarms.html"), LOCALE_CS)
    assert len(alarms) == 7
    first = alarms[0]
    assert "spotř" in first.alarm_type.lower() or "spotr" in first.alarm_type.lower()
    assert first.occurred_at == datetime(2026, 5, 23, 0, 0)
    assert first.value == pytest.approx(20.0)
    assert first.email_status == "OK"
    assert first.sms_status is None


def test_alarm_config_parses_jqgrid_payload() -> None:
    """``parse_alarm_configs`` extracts the JSON embedded in the jqGrid init.

    The CZ fixture has a leak alarm (no threshold parameters) and an
    over-consumption alarm whose two configured parameters carry the
    threshold (``800``) and the interval (``1`` day) — verifying both the
    "empty parameter slot" and "numeric coercion" branches.
    """
    configs = parse_alarm_configs(fixture("alarms_config.html"), LOCALE_CS)
    assert len(configs) == 2

    leak, over = configs
    assert leak.config_id == "0"
    assert leak.active is True
    assert leak.email == "alerts@example.com"
    assert leak.phone is None
    assert all(not p.is_configured for p in leak.parameters)

    assert over.config_id == "1"
    assert over.active is True
    assert over.parameters[0].label == "Mez nadměrné spotřeby"
    assert over.parameters[0].value_numeric == pytest.approx(800.0)
    assert over.parameters[1].label == "Počet dnů"
    assert over.parameters[1].value_numeric == pytest.approx(1.0)
    assert not over.parameters[2].is_configured


def test_alarm_config_empty_when_grid_missing() -> None:
    """A portal that has no configured alarms still renders a valid page.

    We return an empty tuple rather than raising so the snapshot survives
    when the grid initialiser script is absent.
    """
    assert parse_alarm_configs("<html><body>no script</body></html>") == ()
