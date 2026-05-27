"""Locale support for the Suez Smart Solutions portal.

The portal ships in four languages: Czech (``cs``), French (``fr``),
English (``en``) and German (``de``). They differ in:

* month names (twelve full forms per locale);
* date format (``DD.MM.YYYY``, ``DD/MM/YYYY``, ``M/D/YYYY``);
* time format (24-hour vs. 12-hour with AM/PM);
* decimal separator (``,`` vs. ``.``).

Submit-button labels also vary but the client extracts the rendered value from
the form on every login, so we don't track them here.

The Czech (``cs``) and French (``fr``) tables were captured from the live
portal. English and German tables are derived from the same vendor
deployment served via ``Culture=en``/``Culture=de`` cookies. If the upstream
ever ships a locale we don't cover, ``DEFAULT_LOCALE`` (French — the portal's
own default) is used as a safe fallback for date/decimal parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from bs4 import BeautifulSoup


def attr_str(value: object, default: str = "") -> str:
    """Coerce a BeautifulSoup attribute value to a single string.

    ``Tag.get`` returns ``str`` for ordinary attributes, a list
    (``AttributeValueList``) for space-separated multi-valued ones such as
    ``class``, or ``None`` when the attribute is absent. Every attribute we
    read here (``name``, ``value``, ``action``, …) is single-valued, but this
    normalises all three cases so callers always work with a ``str``.
    """
    if value is None:
        return default
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


@dataclass(frozen=True, slots=True)
class Locale:
    """A user-interface locale supported by the portal."""

    code: str
    """Two-letter language code as accepted by ``DropDownListLangues``."""
    native_name: str
    """The way the language is spelled in itself (e.g. ``Česky``)."""
    months: tuple[str, ...]
    """Twelve month names in calendar order. Compared case-insensitively."""
    decimal_separator: str
    """Character used as the radix point in number tables."""
    date_format: str
    """:func:`datetime.strptime` format for date cells (no time component)."""
    time_format_24h: bool
    """``True`` for ``HH:MM[:SS]``, ``False`` for ``H:MM[:SS] AM/PM``."""

    @property
    def thousands_separator(self) -> str:
        """Separator used (when present) for thousand groupings.

        We accept whichever character is NOT the decimal separator.
        """
        return "." if self.decimal_separator == "," else ","

    def month_index(self, name: str) -> int | None:
        """Return the 1-based index of ``name`` in this locale, or ``None``."""
        target = name.strip().casefold()
        for idx, candidate in enumerate(self.months, start=1):
            if candidate.casefold() == target:
                return idx
        return None


LOCALE_CS: Final = Locale(
    code="cs",
    native_name="Česky",
    months=(
        "leden",
        "únor",
        "březen",
        "duben",
        "květen",
        "červen",
        "červenec",
        "srpen",
        "září",
        "říjen",
        "listopad",
        "prosinec",
    ),
    decimal_separator=",",
    date_format="%d.%m.%Y",
    time_format_24h=True,
)

LOCALE_FR: Final = Locale(
    code="fr",
    native_name="Français",
    months=(
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ),
    decimal_separator=",",
    date_format="%d/%m/%Y",
    time_format_24h=True,
)

LOCALE_EN: Final = Locale(
    code="en",
    native_name="English",
    months=(
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    decimal_separator=".",
    # The portal renders dates without leading zeros (``5/24/2026``); strptime
    # tolerates this with the standard ``%m/%d/%Y`` directive.
    date_format="%m/%d/%Y",
    time_format_24h=False,
)

LOCALE_DE: Final = Locale(
    code="de",
    native_name="Deutsch",
    months=(
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ),
    decimal_separator=",",
    date_format="%d.%m.%Y",
    time_format_24h=True,
)

LOCALES: Final[dict[str, Locale]] = {
    LOCALE_CS.code: LOCALE_CS,
    LOCALE_FR.code: LOCALE_FR,
    LOCALE_EN.code: LOCALE_EN,
    LOCALE_DE.code: LOCALE_DE,
}

DEFAULT_LOCALE: Final = LOCALE_FR
"""Used when auto-detection cannot identify a known locale."""

LANGUAGE_DROPDOWN_NAME: Final = "ctl00$PHZonePrincipale$Langues$DropDownListLangues"


def detect_locale(html: str) -> Locale:
    """Detect the active locale from a portal HTML page.

    Strategy (most reliable first):

    1. ``<select name="…DropDownListLangues">`` carries the current language
       on the option with ``selected="selected"`` or whose ``value`` matches
       the form value attribute.
    2. Hidden ``HiddenMessageConnexion`` value is rendered locale-specifically
       on the login page.
    3. The submit button label / page navigation menu — last-resort string
       match against known labels.
    4. Fallback: :data:`DEFAULT_LOCALE`.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: language dropdown
    select = soup.find("select", attrs={"name": LANGUAGE_DROPDOWN_NAME})
    if select is not None:
        selected_value: str | None = None
        for option in select.find_all("option"):
            if option.has_attr("selected"):
                selected_value = attr_str(option.get("value")) or None
                break
        if selected_value is None:
            # Some ASP.NET renderings just set ``value`` on the select element
            # without ``selected`` on any option.
            selected_value = attr_str(select.get("value")) or None
        if selected_value and selected_value in LOCALES:
            return LOCALES[selected_value]

    # Strategy 2: hidden Connexion label (login pages only)
    hidden = soup.find(
        "input",
        attrs={"name": "ctl00$PHZonePrincipale$HiddenMessageConnexion"},
    )
    if hidden is not None:
        value = attr_str(hidden.get("value")).strip()
        if value:
            locale = _match_login_phrase(value)
            if locale is not None:
                return locale

    # Strategy 3: submit-button label
    submit = soup.find("input", attrs={"type": "submit"})
    if submit is not None:
        label = attr_str(submit.get("value")).strip()
        if label:
            locale = _SUBMIT_LABELS.get(label.casefold())
            if locale is not None:
                return locale

    # Strategy 4: date format in an OdometerIndex title (post-login pages).
    # Matches a date+time pattern and dispatches on the punctuation used.
    odom = soup.find("div", class_="OdometerIndex")
    if odom is not None:
        title = (odom.find(class_="jqplot-title") or odom).get_text(" ", strip=True)
        match = _ODOMETER_TIMESTAMP_RE.search(title)
        if match is not None:
            return _locale_from_timestamp_shape(
                match.group("date"), match.group("time")
            )

    return DEFAULT_LOCALE


_ODOMETER_TIMESTAMP_RE = re.compile(
    r"(?P<date>\d{1,2}[./]\d{1,2}[./]\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)",
    re.IGNORECASE,
)


def _locale_from_timestamp_shape(date_part: str, time_part: str) -> Locale:
    """Pick a locale from the punctuation shape of a portal timestamp.

    The portal renders dates differently per locale: ``DD.MM.YYYY`` for
    ``cs``/``de``, ``DD/MM/YYYY`` for ``fr``, and ``M/D/YYYY`` for ``en``;
    times use 24h for all except ``en``. We map shape → locale.
    """
    am_pm = "am" in time_part.lower() or "pm" in time_part.lower()
    if "." in date_part:
        # CS or DE — both share the same date/decimal/time format.
        # Disambiguate by guessing CS (the operator's branded language for
        # the only deployment we tested). Users are not affected because
        # both locales parse the same input identically.
        return LOCALE_CS
    if am_pm:
        return LOCALE_EN
    # Slash-separated dates with 24h time → French.
    return LOCALE_FR


# Login progress phrases the portal renders into a hidden input on the login
# page; useful when the language dropdown is collapsed/hidden.
_LOGIN_PROGRESS_PHRASES: Final[dict[str, Locale]] = {
    "connexion en cours": LOCALE_FR,
    "spojení se navazuje": LOCALE_CS,
    "spojeni se navazuje": LOCALE_CS,
    "connecting": LOCALE_EN,
    "verbinden": LOCALE_DE,
}


def _match_login_phrase(value: str) -> Locale | None:
    folded = value.casefold()
    for phrase, locale in _LOGIN_PROGRESS_PHRASES.items():
        if phrase in folded:
            return locale
    return None


_SUBMIT_LABELS: Final[dict[str, Locale]] = {
    "přihlásit": LOCALE_CS,
    "prihlasit": LOCALE_CS,
    "connexion": LOCALE_FR,
    "connection": LOCALE_EN,
    "verbindung": LOCALE_DE,
}
