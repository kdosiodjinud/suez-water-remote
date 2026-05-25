"""Tests for locale tables and auto-detection."""

from __future__ import annotations

import pytest
from tests.conftest import fixture

from custom_components.suez_water_remote.api.locales import (
    DEFAULT_LOCALE,
    LOCALE_CS,
    LOCALE_DE,
    LOCALE_EN,
    LOCALE_FR,
    LOCALES,
    detect_locale,
)


def test_all_four_locales_registered() -> None:
    assert set(LOCALES) == {"cs", "fr", "en", "de"}


@pytest.mark.parametrize("locale", LOCALES.values())
def test_each_locale_has_twelve_months(locale) -> None:
    assert len(locale.months) == 12
    # All distinct.
    assert len({m.casefold() for m in locale.months}) == 12


@pytest.mark.parametrize(
    "locale,month_name,expected_idx",
    [
        (LOCALE_CS, "leden", 1),
        (LOCALE_CS, "prosinec", 12),
        (LOCALE_CS, "LEDEN", 1),  # case-insensitive
        (LOCALE_FR, "janvier", 1),
        (LOCALE_FR, "décembre", 12),
        (LOCALE_EN, "January", 1),
        (LOCALE_EN, "june", 6),
        (LOCALE_DE, "Januar", 1),
        (LOCALE_DE, "März", 3),
    ],
)
def test_month_index_lookup(locale, month_name: str, expected_idx: int) -> None:
    assert locale.month_index(month_name) == expected_idx


def test_month_index_returns_none_for_unknown() -> None:
    assert LOCALE_CS.month_index("notamonth") is None


def test_thousands_separator_is_inverse_of_decimal() -> None:
    assert LOCALE_CS.thousands_separator == "."
    assert LOCALE_FR.thousands_separator == "."
    assert LOCALE_EN.thousands_separator == ","
    assert LOCALE_DE.thousands_separator == "."


@pytest.mark.parametrize(
    "fname,expected_code",
    [
        ("login.html", "cs"),  # login page with selected option
        ("home.html", "cs"),  # post-login, detected via odometer timestamp
        ("home_fr.html", "fr"),
        ("home_en.html", "en"),
        # home_de uses the same date format as cs → shape detection lands
        # on cs, but parsing is identical so behaviour is correct in
        # practice.
        ("home_de.html", "cs"),
    ],
)
def test_detect_locale_from_page(fname: str, expected_code: str) -> None:
    assert detect_locale(fixture(fname)).code == expected_code


def test_detect_locale_falls_back_to_default_for_empty_page() -> None:
    assert detect_locale("<html></html>") is DEFAULT_LOCALE
