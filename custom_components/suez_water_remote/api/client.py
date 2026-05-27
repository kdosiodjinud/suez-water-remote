"""Asynchronous HTTP client for the Suez Smart Solutions portal.

The client wraps an :class:`aiohttp.ClientSession` (its own by default;
optionally a caller-supplied session, e.g. Home Assistant's
``async_get_clientsession``) and exposes high-level methods that return parsed
:mod:`.models` instances.

The portal is deployed under per-country sub-domains (``cz-sitr``,
``fr-sitr``…) and per-branch path prefixes (``eMIS.SE_VHS-Benesov``,
``eMIS.SE_<other-branch>``…). All of that is captured in ``base_url`` so the
client is **branch- and country-agnostic** — there are no hardcoded URLs in
the codebase.

The UI of the portal ships in four languages. The locale is auto-detected
once from the GET'd login page (or supplied explicitly); subsequent parsing
uses the detected locale.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from types import TracebackType
from typing import Final, Self

import aiohttp
from aiohttp import ClientResponseError, ClientTimeout, CookieJar
from bs4 import BeautifulSoup
from yarl import URL

from .const import (
    AFFICHAGE_CONSO_DAY,
    AFFICHAGE_CONSO_MONTH,
    AFFICHAGE_CONSO_YEAR,
    AFFICHAGE_INDEX_DAY,
    AFFICHAGE_INDEX_MONTH,
    ALARMS_CONFIG_PATH,
    ALARMS_PATH,
    AUTH_COOKIE,
    DEFAULT_TIMEOUT_SECONDS,
    ENERGY_PATH,
    FIELD_LANGUAGE,
    FIELD_PASSWORD,
    FIELD_RESOLUTION,
    FIELD_USERNAME,
    HOME_PATH,
    LOGIN_PATH,
    USER_AGENT,
)
from .exceptions import (
    SuezAuthenticationError,
    SuezConnectionError,
    SuezError,
    SuezParseError,
)
from .locales import DEFAULT_LOCALE, Locale, detect_locale
from .models import MeterSnapshot
from .parsers import (
    discover_meter_ids,
    extract_hidden_inputs,
    find_login_form_action,
    find_submit_button,
    parse_alarm_configs,
    parse_alarms,
    parse_daily_consumption,
    parse_daily_index,
    parse_home_page,
    parse_monthly_consumption,
    parse_monthly_index,
    parse_yearly_consumption,
)

_LOGGER = logging.getLogger(__name__)

_HEADERS_BASE: Final = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.7",
}

# Recognise base URLs of the form
# ``<scheme>://<host>/<application_root>/[<Page>.aspx?...]``. The application
# root encodes the branch (``eMIS.SE_VHS-Benesov`` for example).
_ASPX_PAGE_RE = re.compile(r"/[^/]+\.aspx$", re.IGNORECASE)

# Used by ``_is_login_redirect`` to spot a page that contains the username
# input of the login form. The ``$`` in ``ctl00$PHZonePrincipale$...`` is
# escaped so the pattern matches the verbatim attribute value.
_LOGIN_FORM_INPUT_RE = re.compile(
    r'name="ctl00\$PHZonePrincipale\$TextBoxIdentifiant"',
    re.IGNORECASE,
)


def derive_base_url(user_url: str) -> URL:
    """Strip the page name from a portal URL to produce the application root.

    Examples
    --------
    >>> str(derive_base_url("https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/Login.aspx?ReturnUrl=foo"))
    'https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/'
    >>> str(derive_base_url("https://fr-sitr.suezsmartsolutions.com/eMIS.SE_Brand/"))
    'https://fr-sitr.suezsmartsolutions.com/eMIS.SE_Brand/'
    """
    if not user_url:
        raise ValueError("portal URL must not be empty")
    parsed = URL(user_url)
    # Require TLS: the login flow POSTs the customer's password, so a plain
    # ``http://`` URL would expose credentials on the wire. Every real Suez
    # deployment is served over HTTPS.
    if parsed.scheme != "https":
        raise ValueError(f"portal URL must use https, got {parsed.scheme!r}")
    if not parsed.host:
        raise ValueError("portal URL must include a host")
    path = parsed.path or "/"
    if _ASPX_PAGE_RE.search(path):
        path = path.rsplit("/", 1)[0] + "/"
    elif not path.endswith("/"):
        path = path + "/"
    if path == "/":
        raise ValueError(
            "portal URL must include the branch path "
            "(e.g. '.../eMIS.SE_<branch>/')"
        )
    return parsed.with_path(path).with_query(None).with_fragment(None)


class SuezVhsClient:
    """High-level client for any Suez Smart Solutions customer portal.

    Parameters
    ----------
    username, password:
        Customer login. The client never logs the password.
    base_url:
        Application root, e.g.
        ``https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/``. Must
        include a trailing slash; use :func:`derive_base_url` to derive one
        from an arbitrary user-supplied URL.
    locale:
        UI locale used for parsing. When ``None`` it is auto-detected from
        the login page during the first login.
    session:
        Optional caller-supplied ``aiohttp`` session. When ``None`` the client
        owns its own session and closes it from :meth:`close`.
    timeout:
        Per-request timeout in seconds.
    """

    __slots__ = (
        "_base_url",
        "_locale",
        "_locale_locked",
        "_logged_in",
        "_login_lock",
        "_owns_session",
        "_password",
        "_session",
        "_timeout",
        "_username",
    )

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str | URL,
        *,
        locale: Locale | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not username:
            raise ValueError("username must not be empty")
        if not password:
            raise ValueError("password must not be empty")
        base = URL(base_url) if isinstance(base_url, str) else base_url
        if not base.host or not base.scheme:
            raise ValueError(f"invalid base URL: {base!r}")
        if not str(base.path).endswith("/"):
            base = base.with_path(str(base.path) + "/")
        self._base_url = base
        self._username = username
        self._password = password
        self._timeout = ClientTimeout(total=timeout)
        if session is None:
            self._session = aiohttp.ClientSession(
                cookie_jar=CookieJar(unsafe=False), headers=_HEADERS_BASE
            )
            self._owns_session = True
        else:
            self._session = session
            self._owns_session = False
        self._logged_in = False
        self._locale: Locale = locale or DEFAULT_LOCALE
        self._locale_locked = locale is not None
        self._login_lock = asyncio.Lock()

    # -- factories -----------------------------------------------------------

    @classmethod
    def from_url(
        cls,
        url: str,
        username: str,
        password: str,
        *,
        locale: Locale | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Self:
        """Build a client from any URL that points into the user's portal.

        The base URL (per-country sub-domain plus per-branch path prefix) is
        derived automatically; the UI locale is auto-detected during the
        first login unless an explicit ``locale`` is supplied.
        """
        base = derive_base_url(url)
        return cls(
            username,
            password,
            base,
            locale=locale,
            session=session,
            timeout=timeout,
        )

    # -- async-context-manager plumbing --------------------------------------

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and not self._session.closed:
            await self._session.close()

    # -- public properties ---------------------------------------------------

    @property
    def base_url(self) -> URL:
        return self._base_url

    @property
    def locale(self) -> Locale:
        return self._locale

    # -- public API ----------------------------------------------------------

    async def async_login(self, *, force: bool = False) -> None:
        """Perform an explicit login.

        Idempotent by default: when an authentication cookie is already
        present it returns immediately. Pass ``force=True`` to discard any
        stale session and re-authenticate unconditionally — used when the
        portal redirected an authenticated request back to the login page.
        """
        async with self._login_lock:
            if not force and self._has_auth_cookie():
                self._logged_in = True
                return
            if force:
                # Cookie can outlive the server-side session: keeping it would
                # short-circuit ``_has_auth_cookie`` checks and prevent the
                # fresh POST from re-populating the jar reliably.
                self._session.cookie_jar.clear_domain(self._base_url.host or "")
                self._logged_in = False
            await self._login_locked()

    async def async_discover_meters(self) -> tuple[str, ...]:
        """Return every meter identifier visible on the home page."""
        await self._ensure_logged_in()
        html = await self._fetch_authenticated_html(self._url(HOME_PATH))
        meters = discover_meter_ids(html)
        if not meters:
            raise SuezParseError("no meters were discovered on the home page")
        return meters

    async def async_fetch_snapshot(self, meter_id: str | None = None) -> MeterSnapshot:
        """Fetch the full dataset for ``meter_id`` (or the single account meter)."""
        await self._ensure_logged_in()
        home_html = await self._fetch_authenticated_html(self._url(HOME_PATH))
        site_label, discovered_meter, current, today_total = parse_home_page(
            home_html, self._locale
        )
        meter = meter_id or discovered_meter
        if meter_id is not None and meter_id != discovered_meter:
            _LOGGER.debug(
                "configured meter %s does not match discovered %s; using configured value",
                meter_id,
                discovered_meter,
            )
        current = current.__class__(
            meter_id=meter,
            timestamp=current.timestamp,
            value_m3=current.value_m3,
        )

        (
            monthly_html,
            yearly_html,
            daily_html,
            monthly_idx_html,
            daily_idx_html,
            alarms_html,
            alarms_config_html,
        ) = await asyncio.gather(
            self._fetch_html(self._energy_url(AFFICHAGE_CONSO_MONTH)),
            self._fetch_html(self._energy_url(AFFICHAGE_CONSO_YEAR)),
            self._fetch_html(self._energy_url(AFFICHAGE_CONSO_DAY)),
            self._fetch_html(self._index_url(AFFICHAGE_INDEX_MONTH)),
            self._fetch_html(self._index_url(AFFICHAGE_INDEX_DAY)),
            self._fetch_html(self._url(ALARMS_PATH)),
            self._fetch_html(self._url(ALARMS_CONFIG_PATH)),
        )

        return MeterSnapshot(
            meter_id=meter,
            site_label=site_label,
            current_index=current,
            today_total_liters=today_total,
            monthly_consumption=parse_monthly_consumption(monthly_html, self._locale),
            yearly_consumption=parse_yearly_consumption(yearly_html, self._locale),
            daily_consumption=parse_daily_consumption(daily_html, self._locale),
            monthly_index=parse_monthly_index(monthly_idx_html, meter, self._locale),
            daily_index=parse_daily_index(daily_idx_html, meter, self._locale),
            alarms=parse_alarms(alarms_html, self._locale),
            alarm_configs=parse_alarm_configs(alarms_config_html, self._locale),
        )

    # -- private helpers -----------------------------------------------------

    def _has_auth_cookie(self) -> bool:
        cookies = self._session.cookie_jar.filter_cookies(self._base_url)
        return AUTH_COOKIE in cookies and bool(cookies[AUTH_COOKIE].value)

    async def _ensure_logged_in(self) -> None:
        if self._logged_in and self._has_auth_cookie():
            return
        await self.async_login()

    def _url(self, path: str) -> URL:
        return self._base_url / path.lstrip("/")

    def _energy_url(self, affichage: str) -> URL:
        return self._url(ENERGY_PATH).with_query({"Affichage": affichage})

    def _index_url(self, affichage: str) -> URL:
        return self._url(ENERGY_PATH).with_query(
            {
                "Affichage": affichage,
                "IndexesSepares": "true",
                "PeriodeComplete": "false",
            }
        )

    async def _login_locked(self) -> None:
        # Hit a protected page so the portal redirects to a login URL whose
        # form action carries a ReturnUrl. We re-submit the form with the
        # exact submit button value the server rendered, so the request
        # works in any UI language without hardcoded labels.
        get_url = self._url(HOME_PATH)
        get_html = await self._fetch_html(get_url)
        soup = BeautifulSoup(get_html, "html.parser")
        action_raw = find_login_form_action(soup)
        login_url = self._url(LOGIN_PATH)
        action_url = login_url.join(URL(action_raw))

        # Lock in the locale on first login when not pinned by the caller.
        if not self._locale_locked:
            self._locale = detect_locale(get_html)
            self._locale_locked = True

        payload = extract_hidden_inputs(soup)
        submit_name, submit_value = find_submit_button(soup)
        payload.update(
            {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                FIELD_USERNAME: self._username,
                FIELD_PASSWORD: self._password,
                submit_name: submit_value,
                FIELD_LANGUAGE: self._locale.code,
                FIELD_RESOLUTION: "1920x1080",
            }
        )
        headers = {
            **_HEADERS_BASE,
            "Origin": f"{self._base_url.scheme}://{self._base_url.host}",
            "Referer": str(action_url),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # See ``_ingest_set_cookie`` for the reason we bypass aiohttp's
        # automatic redirect-time cookie ingestion here.
        try:
            async with self._session.request(
                "POST",
                str(action_url),
                data=payload,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            ) as resp:
                text = await resp.text()
                self._ingest_set_cookie(resp.headers.getall("Set-Cookie", []))
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SuezConnectionError(
                f"network error during login: {err.__class__.__name__}"
            ) from err
        if not self._has_auth_cookie():
            _LOGGER.debug("login failed; portal response size=%d", len(text))
            raise SuezAuthenticationError("Suez portal rejected the credentials")
        self._logged_in = True

    def _ingest_set_cookie(self, raw_headers: list[str]) -> None:
        """Parse ``Set-Cookie`` headers individually and push them to the jar.

        Loading multiple Set-Cookie headers into a single
        :class:`http.cookies.SimpleCookie` instance via repeated ``load()``
        calls is broken when the same cookie name is set twice in one
        response — attributes from a previous load (notably ``expires``)
        bleed into the next one. Here we instantiate one ``SimpleCookie``
        per header and feed them to the jar in order.
        """
        for header in raw_headers:
            cookies: SimpleCookie = SimpleCookie()
            try:
                cookies.load(header)
            except Exception:  # pragma: no cover - malformed header
                _LOGGER.debug("ignoring malformed Set-Cookie header")
                continue
            self._session.cookie_jar.update_cookies(cookies, self._base_url)

    async def _fetch_html(self, url: URL) -> str:
        async with self._request("GET", url) as resp:
            return await resp.text()

    def _is_login_redirect(self, final_url: URL, html: str) -> bool:
        """Return ``True`` when an authenticated GET landed on the login page.

        ASP.NET FormsAuthentication expires the session server-side while the
        client-side cookie keeps living in our in-memory jar; subsequent
        GETs are then 302'd back to ``Login.aspx``. We detect this both by
        the final URL (real portal: 302 chain follows to ``Login.aspx``) and
        by the response body (presence of the login form input), which keeps
        the check robust against server tweaks that swap one signal for the
        other.
        """
        path = (final_url.path or "").rstrip("/").lower()
        if path.endswith("/" + LOGIN_PATH.lower()) or path == LOGIN_PATH.lower():
            return True
        return _LOGIN_FORM_INPUT_RE.search(html) is not None

    async def _fetch_authenticated_html(self, url: URL) -> str:
        """Fetch ``url`` expecting a post-login response.

        When the portal redirects us back to the login page (stale session),
        we drop the cookie jar, perform a fresh login under the login lock,
        and retry exactly once. A second redirect means the credentials no
        longer work, so we raise :class:`SuezAuthenticationError` to surface
        a Home Assistant re-auth prompt.
        """
        async with self._request("GET", url) as resp:
            final_url = resp.url
            text = await resp.text()
        if not self._is_login_redirect(final_url, text):
            return text
        _LOGGER.debug(
            "session stale: GET %s landed on %s; forcing re-login",
            url.path,
            final_url.path,
        )
        await self.async_login(force=True)
        async with self._request("GET", url) as resp:
            final_url = resp.url
            text = await resp.text()
        if self._is_login_redirect(final_url, text):
            raise SuezAuthenticationError(
                f"portal redirected to login page after re-authentication "
                f"(final URL: {final_url.path})"
            )
        return text

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        url: URL,
        **kwargs: object,
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        try:
            async with self._session.request(
                method,
                str(url),
                timeout=self._timeout,
                allow_redirects=True,
                **kwargs,  # type: ignore[arg-type]
            ) as response:
                try:
                    response.raise_for_status()
                except ClientResponseError as err:
                    if err.status in (401, 403):
                        raise SuezAuthenticationError(
                            f"unauthorized {method} {url.path}"
                        ) from err
                    raise SuezConnectionError(
                        f"unexpected status {err.status} for {method} {url.path}"
                    ) from err
                yield response
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SuezConnectionError(
                f"network error for {method} {url.path}: {err.__class__.__name__}"
            ) from err
        except SuezError:
            raise


__all__ = ["SuezVhsClient", "derive_base_url"]
