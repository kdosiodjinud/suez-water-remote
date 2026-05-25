"""Integration tests for :class:`SuezVhsClient` using ``aioresponses``."""

from __future__ import annotations

import re

import aiohttp
import pytest
from aioresponses import aioresponses
from tests.conftest import fixture

from custom_components.suez_water_remote.api import (
    LOCALE_CS,
    LOCALE_EN,
    LOCALE_FR,
    SuezAuthenticationError,
    SuezConnectionError,
    SuezVhsClient,
    derive_base_url,
)

# Synthetic base URL used by the test suite. The same client must work for
# any sub-domain/branch — see ``test_client_works_with_alternate_base_url``.
BASE = "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/"
LOGIN_URL = f"{BASE}Login.aspx"
HOME_URL = f"{BASE}Site.aspx"

LOGIN_POST_RE = re.compile(r"https://.*\.suezsmartsolutions\.com/.*Login\.aspx.*")

DELETE_COOKIE = (
    "SE_Pilote_Cookie=; expires=Mon, 11-Oct-1999 22:00:00 GMT; path=/; "
    "HttpOnly; SameSite=Lax"
)
SET_COOKIE = "SE_Pilote_Cookie=AUTH123; path=/; HttpOnly; SameSite=Lax"


def _set_cookie_success() -> list[str]:
    return [
        "Culture=cs; expires=Mon, 24-May-2027 22:00:00 GMT; path=/",
        DELETE_COOKIE,
        SET_COOKIE,
    ]


def _set_cookie_failure() -> list[str]:
    return [
        "Culture=cs; expires=Mon, 24-May-2027 22:00:00 GMT; path=/",
        DELETE_COOKIE,
    ]


def _register_data_pages(m: aioresponses, base: str = BASE) -> None:
    """Register every URL that ``async_fetch_snapshot`` calls in order."""
    energy_pages = {
        "ConsoMois": "conso_mois.html",
        "ConsoAn": "conso_an.html",
        "ConsoJour": "conso_jour.html",
    }
    for affichage, fname in energy_pages.items():
        m.get(
            f"{base}Site_Energie.aspx?Affichage={affichage}",
            status=200,
            body=fixture(fname),
        )
    for affichage, fname in {
        "IndexMois": "index_mois.html",
        "IndexJour": "index_jour.html",
    }.items():
        m.get(
            f"{base}Site_Energie.aspx?Affichage={affichage}"
            f"&IndexesSepares=true&PeriodeComplete=false",
            status=200,
            body=fixture(fname),
        )
    m.get(f"{base}Site_AlarmesClient.aspx", status=200, body=fixture("alarms.html"))


# --- derive_base_url --------------------------------------------------------


@pytest.mark.parametrize(
    "user_url,expected",
    [
        (
            "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/Login.aspx",
            "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/",
        ),
        (
            "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/"
            "Login.aspx?ReturnUrl=%2feMIS.SE_VHS-Benesov%2fSite.aspx",
            "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/",
        ),
        (
            "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/Site_Energie.aspx?Affichage=ConsoMois",
            "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/",
        ),
        (
            "https://fr-sitr.suezsmartsolutions.com/eMIS.SE_OtherBrand/",
            "https://fr-sitr.suezsmartsolutions.com/eMIS.SE_OtherBrand/",
        ),
        (
            "https://fr-sitr.suezsmartsolutions.com/eMIS.SE_OtherBrand",
            "https://fr-sitr.suezsmartsolutions.com/eMIS.SE_OtherBrand/",
        ),
    ],
)
def test_derive_base_url_strips_page_and_query(user_url: str, expected: str) -> None:
    assert str(derive_base_url(user_url)) == expected


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "ftp://example.com/foo/",
        "https://only-host.example.com/",
        "not a url",
    ],
)
def test_derive_base_url_rejects_bad_input(bad_url: str) -> None:
    with pytest.raises(ValueError):
        derive_base_url(bad_url)


# --- Login & cookie handling -------------------------------------------------


async def test_login_short_circuits_when_auth_cookie_already_present() -> None:
    """When the cookie is already in the jar, async_login is a no-op."""
    # The HTTP layer is intentionally not stubbed: a real request would fail.
    client = SuezVhsClient("user", "pass", BASE)
    client._ingest_set_cookie(_set_cookie_success())
    await client.async_login()
    assert client._has_auth_cookie() is True
    await client.close()


async def test_login_autodetects_locale_from_login_page() -> None:
    """End-to-end login that exercises the locale detection path."""

    from multidict import CIMultiDict

    from aioresponses.core import CallbackResult

    def _login_callback(url, **kwargs):
        # Emit the real-world ``delete + set`` Set-Cookie pair via aiohttp's
        # MultiDict, since aioresponses' ``headers={}`` flattens duplicates.
        headers = CIMultiDict()
        headers.add("Location", f"{BASE}Site.aspx")
        for cookie in _set_cookie_success():
            headers.add("Set-Cookie", cookie)
        return CallbackResult(status=302, headers=headers)

    with aioresponses() as m:
        m.get(HOME_URL, status=200, body=fixture("login.html"))
        m.post(LOGIN_POST_RE, callback=_login_callback)
        client = SuezVhsClient("user", "pass", BASE)
        await client.async_login()
        assert client._has_auth_cookie() is True
        assert client.locale.code == "cs"
        await client.close()


async def test_login_failure_when_cookie_absent() -> None:
    """The portal returns to the login form silently; we must detect it."""
    with aioresponses() as m:
        m.get(HOME_URL, status=200, body=fixture("login.html"))
        m.post(LOGIN_POST_RE, status=200, body=fixture("login.html"))
        client = SuezVhsClient("user", "wrong-pass", BASE)
        with pytest.raises(SuezAuthenticationError):
            await client.async_login()
        await client.close()


async def test_ingest_set_cookie_handles_delete_then_set() -> None:
    """Work-around for the SimpleCookie attribute-bleed bug."""
    client = SuezVhsClient("user", "pass", BASE)
    try:
        client._ingest_set_cookie(_set_cookie_success())
        assert client._has_auth_cookie() is True
    finally:
        await client.close()


async def test_ingest_set_cookie_failure_keeps_jar_empty() -> None:
    client = SuezVhsClient("user", "pass", BASE)
    try:
        client._ingest_set_cookie(_set_cookie_failure())
        assert client._has_auth_cookie() is False
    finally:
        await client.close()


# --- async_fetch_snapshot ----------------------------------------------------


async def test_fetch_snapshot_after_manual_cookie_injection() -> None:
    """Once authenticated, fetch_snapshot composes all parsers correctly."""
    client = SuezVhsClient("user", "pass", BASE, locale=LOCALE_CS)
    client._ingest_set_cookie(_set_cookie_success())
    client._logged_in = True

    with aioresponses() as m:
        m.get(HOME_URL, status=200, body=fixture("home.html"))
        _register_data_pages(m)
        snap = await client.async_fetch_snapshot()
    await client.close()

    assert snap.meter_id == "1234567"
    assert snap.site_label == "99999-XX-1234567"
    assert snap.current_index.value_m3 == pytest.approx(1119.819)
    assert snap.today_total_liters == pytest.approx(3789.0)
    assert len(snap.monthly_consumption) == 24
    assert len(snap.yearly_consumption) == 11
    assert len(snap.daily_consumption) == 24
    assert len(snap.monthly_index) == 19
    assert len(snap.daily_index) == 24
    assert len(snap.alarms) == 7


async def test_client_works_with_alternate_base_url() -> None:
    """The client must be branch-/country-agnostic — no hardcoded URLs.

    We exercise the meter-discovery path (one GET) rather than the full
    snapshot because the snapshot would require daily/yearly fixtures in
    every locale, which we only have for cs.
    """
    alternate = "https://fr-sitr.suezsmartsolutions.com/eMIS.SE_Brand/"
    client = SuezVhsClient("user", "pass", alternate, locale=LOCALE_FR)
    client._ingest_set_cookie(_set_cookie_success())
    client._logged_in = True

    with aioresponses() as m:
        m.get(f"{alternate}Site.aspx", status=200, body=fixture("home_fr.html"))
        meters = await client.async_discover_meters()
    await client.close()

    assert str(client.base_url) == alternate
    assert meters == ("1234567",)


# --- Misc -------------------------------------------------------------------


async def test_connection_error_when_portal_unreachable() -> None:
    with aioresponses() as m:
        m.get(HOME_URL, exception=aiohttp.ClientConnectionError("boom"))
        client = SuezVhsClient("user", "pass", BASE)
        with pytest.raises(SuezConnectionError):
            await client.async_login()
        await client.close()


async def test_close_is_idempotent() -> None:
    client = SuezVhsClient("user", "pass", BASE)
    await client.close()
    await client.close()


async def test_async_discover_meters_calls_login_then_parses() -> None:
    client = SuezVhsClient("user", "pass", BASE)
    client._ingest_set_cookie(_set_cookie_success())
    client._logged_in = True
    with aioresponses() as m:
        m.get(HOME_URL, status=200, body=fixture("home.html"))
        meters = await client.async_discover_meters()
    await client.close()
    assert meters == ("1234567",)


async def test_constructor_rejects_blank_credentials() -> None:
    with pytest.raises(ValueError):
        SuezVhsClient("", "pass", BASE)
    with pytest.raises(ValueError):
        SuezVhsClient("user", "", BASE)


async def test_from_url_factory_builds_client_with_correct_base() -> None:
    client = SuezVhsClient.from_url(
        "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/Site_Energie.aspx?Affichage=ConsoMois",
        "user",
        "pass",
    )
    try:
        assert str(client.base_url) == BASE
        # locale stays default until first login
        assert client.locale.code == "fr"
    finally:
        await client.close()


async def test_from_url_factory_pinned_locale_overrides_autodetect() -> None:
    client = SuezVhsClient.from_url(
        "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/Login.aspx",
        "user",
        "pass",
        locale=LOCALE_EN,
    )
    try:
        assert client.locale is LOCALE_EN
    finally:
        await client.close()
