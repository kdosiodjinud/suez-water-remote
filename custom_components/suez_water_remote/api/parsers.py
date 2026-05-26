"""HTML parsers for the Suez Smart Solutions portal.

The portal is an ASP.NET WebForms application whose DOM structure has been
stable across multiple releases and across the four supported UI languages.
Parsing is deliberately defensive: every helper raises :class:`SuezParseError`
when the document layout drifts in a way that prevents the integration from
producing a sensible value, so problems surface as actionable error messages
rather than silent zeros.

Where the structure differs only in language (date format, decimal separator,
month names), parsing is parameterised on a :class:`Locale`. Where the
structure is identical, parsers anchor on DOM (``id`` attributes, CSS
classes) rather than localised text labels.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup, Tag

from .exceptions import SuezParseError
from .locales import DEFAULT_LOCALE, Locale, detect_locale
from .models import AlarmEntry, ConsumptionPoint, MeterReading

# --- Generic helpers ---------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(text.split())


def parse_decimal(raw: str, locale: Locale = DEFAULT_LOCALE) -> float:
    """Parse a portal-formatted decimal in the given locale.

    Whitespace and U+00A0 non-breaking spaces are tolerated. The thousands
    separator (if present) and the decimal separator are derived from
    ``locale``.
    """
    cleaned = raw.replace("\xa0", " ").strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace(locale.thousands_separator, "")
    cleaned = cleaned.replace(locale.decimal_separator, ".")
    if not cleaned:
        raise SuezParseError(f"empty numeric value: {raw!r}")
    try:
        return float(cleaned)
    except ValueError as err:
        raise SuezParseError(
            f"cannot parse decimal {raw!r} as {locale.code} locale"
        ) from err


def parse_localized_month(label: str, locale: Locale) -> date:
    """Convert a label like ``"prosinec 2024"`` to ``date(2024, 12, 1)``.

    Month names are looked up against :attr:`Locale.months` case-insensitively.
    """
    parts = _normalize(label).split()
    if len(parts) != 2:
        raise SuezParseError(f"unexpected month label {label!r}")
    month_name, year = parts
    month = locale.month_index(month_name)
    if month is None:
        raise SuezParseError(
            f"unknown month {month_name!r} for locale {locale.code}"
        )
    try:
        year_int = int(year)
    except ValueError as err:
        raise SuezParseError(f"non-numeric year in {label!r}") from err
    return date(year_int, month, 1)


def parse_localized_date(label: str, locale: Locale) -> date:
    """Parse a date from ``label`` using ``locale.date_format``."""
    try:
        return datetime.strptime(_normalize(label), locale.date_format).date()
    except ValueError as err:
        raise SuezParseError(
            f"cannot parse date {label!r} using format {locale.date_format!r}"
        ) from err


def parse_localized_datetime(label: str, locale: Locale) -> datetime:
    """Parse a ``date + time`` value using ``locale``'s formats.

    Accepts both ``HH:MM`` and ``HH:MM:SS`` as the time component, optionally
    followed by ``AM``/``PM`` for 12-hour locales.
    """
    text = _normalize(label)
    time_formats = (
        ["%H:%M:%S", "%H:%M"]
        if locale.time_format_24h
        else ["%I:%M:%S %p", "%I:%M %p"]
    )
    for t_fmt in time_formats:
        try:
            return datetime.strptime(text, f"{locale.date_format} {t_fmt}")
        except ValueError:
            continue
    raise SuezParseError(
        f"cannot parse datetime {label!r} for locale {locale.code}"
    )


def _end_of_month(start: date) -> date:
    last_day = calendar.monthrange(start.year, start.month)[1]
    return start.replace(day=last_day)


# --- Login form helpers ------------------------------------------------------


def extract_hidden_inputs(soup: BeautifulSoup) -> dict[str, str]:
    """Return a name/value mapping for every ``<input type="hidden">``."""
    out: dict[str, str] = {}
    for inp in soup.find_all("input", attrs={"type": "hidden"}):
        name = inp.get("name")
        if name:
            out[name] = inp.get("value", "")
    return out


def find_login_form_action(soup: BeautifulSoup) -> str:
    form = soup.find("form")
    if form is None:
        raise SuezParseError("login form missing")
    action = form.get("action") or ""
    if not action:
        raise SuezParseError("login form has no action")
    return action


def find_submit_button(soup: BeautifulSoup) -> tuple[str, str]:
    """Return ``(name, value)`` for the form's submit input.

    Used so the client can replay the form exactly as the browser would,
    including the localised button label without having to know it
    statically.
    """
    submit = soup.find("input", attrs={"type": "submit"})
    if submit is None:
        raise SuezParseError("login form has no submit input")
    name = submit.get("name") or ""
    value = submit.get("value") or ""
    if not name:
        raise SuezParseError("submit input has no name attribute")
    return name, value


# --- Home page ---------------------------------------------------------------

_TITRE_LABEL_ID = "ctl00_PHTitre_LabelTitreSite"
_ODOMETER_VALUE_RE = re.compile(
    r"var\s+indexMeter_(?P<idx>\d+)\s*=\s*new\s+odometer\b[^;]*"
)
_ODOMETER_FINAL_RE = re.compile(
    r"updateOdometerIndex_(?P<idx>\d+)\s*=.*?if\s*\(\s*val\s*>\s*"
    r"(?P<value>-?[0-9.]+)\s*\)\s*val\s*=\s*(?P=value)",
    re.DOTALL,
)

# DOM-anchored regex: matches a ``date time`` pattern in the odometer title.
# The localised prefix (``Poslední odečet z`` / ``Index Base du`` / etc.) is
# intentionally not matched; we only care about the trailing timestamp.
#
# Date alternatives: ``DD.MM.YYYY``, ``DD/MM/YYYY``, ``M/D/YYYY``.
# Time alternatives: ``HH:MM[:SS]`` (24h) or ``H:MM[:SS] AM/PM`` (12h).
_ODOMETER_TITLE_RE = re.compile(
    r"(?P<date>\d{1,2}[./]\d{1,2}[./]\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)",
    re.IGNORECASE,
)


def parse_home_page(
    html: str, locale: Locale | None = None
) -> tuple[str, str, MeterReading, float | None]:
    """Extract the site label, meter id, latest reading and today's total.

    When ``locale`` is ``None`` the function auto-detects the locale from the
    page; otherwise the supplied locale is used for date/time parsing.
    """
    soup = BeautifulSoup(html, "html.parser")
    label = soup.find("span", id=_TITRE_LABEL_ID)
    if label is None:
        raise SuezParseError(_describe_unexpected_page(soup, "site title label"))
    site_label = _normalize(label.get_text())
    meter_id = site_label.rsplit("-", 1)[-1] if "-" in site_label else site_label

    effective_locale = locale or detect_locale(html)
    last_reading = _find_last_reading(soup, meter_id, effective_locale)
    today_total = _find_today_chart_total(soup, effective_locale)
    return site_label, meter_id, last_reading, today_total


def _find_last_reading(
    soup: BeautifulSoup, meter_id: str, locale: Locale
) -> MeterReading:
    # The home page renders one ``.OdometerIndex`` div per meter. The title
    # uses a locale-specific label followed by the timestamp; we anchor on
    # the DOM structure and pull the date+time via a regex.
    odom = soup.find("div", class_="OdometerIndex")
    if odom is None:
        raise SuezParseError("home page has no OdometerIndex widget")
    title_node = odom.find(class_="jqplot-title") or odom
    title_text = _normalize(title_node.get_text())
    match = _ODOMETER_TITLE_RE.search(title_text)
    if match is None:
        raise SuezParseError(
            f"odometer title does not contain a parseable date: {title_text!r}"
        )
    timestamp = parse_localized_datetime(
        f"{match.group('date')} {match.group('time')}", locale
    )

    odometer_value: float | None = None
    for script in soup.find_all("script"):
        body = script.string or ""
        if "indexMeter_" not in body:
            continue
        final_match = _ODOMETER_FINAL_RE.search(body)
        if final_match is None:
            continue
        try:
            odometer_value = float(final_match.group("value"))
        except ValueError:
            continue
        break
    if odometer_value is None:
        raise SuezParseError("odometer value missing on home page")
    return MeterReading(
        meter_id=meter_id, timestamp=timestamp, value_m3=odometer_value
    )


def _find_today_chart_total(soup: BeautifulSoup, locale: Locale) -> float | None:
    # The daily chart title is rendered inside the jqPlot script as a string
    # literal of the form ``"<label> <span>date</span> &bull; <span>value
    # unit</span>"``. We extract the rightmost ``(value, unit)`` pair from
    # that script. This is script-anchored (we look at scripts that mention
    # ``jqPlot_Eau`` — the chart id for the day curve) and locale agnostic.
    for script in soup.find_all("script"):
        body = script.string or ""
        if "jqPlot_Eau" not in body:
            continue
        # Match the value + unit inside a <span> of the chart title.
        match = re.search(
            r"<span[^>]*>\s*(?P<value>[0-9][0-9\s.,]*)\s*"
            r"(?P<unit>l|L|m\xb3|m3)\s*</span>",
            body,
        )
        if match is None:
            continue
        try:
            value = parse_decimal(match.group("value"), locale)
        except SuezParseError:
            continue
        unit = match.group("unit").lower()
        return value if unit == "l" else value * 1000.0
    return None


# --- Energy tables -----------------------------------------------------------


def _data_table(soup: BeautifulSoup, *, container_id: str) -> Tag:
    table = soup.find("table", id=container_id)
    if not isinstance(table, Tag):
        raise SuezParseError(f"data table {container_id!r} missing")
    return table


def _table_rows(table: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [_normalize(c.get_text(" ")) for c in tr.find_all(("th", "td"))]
        if cells:
            rows.append(cells)
    return rows


_DATA_TABLE_ID = "ctl00_PHZonePrincipale_ctl01_TableTableau"


def parse_monthly_consumption(
    html: str, locale: Locale = DEFAULT_LOCALE
) -> tuple[ConsumptionPoint, ...]:
    """Parse the monthly consumption table."""
    soup = BeautifulSoup(html, "html.parser")
    table = _data_table(soup, container_id=_DATA_TABLE_ID)
    points: list[ConsumptionPoint] = []
    for row in _table_rows(table)[1:]:
        if len(row) < 2:
            continue
        month_start = parse_localized_month(row[0], locale)
        value = parse_decimal(row[1], locale)
        points.append(
            ConsumptionPoint(
                period_start=month_start,
                period_end=_end_of_month(month_start),
                value_m3=value,
            )
        )
    if not points:
        raise SuezParseError("monthly consumption table is empty")
    return tuple(points)


def parse_daily_consumption(
    html: str, locale: Locale = DEFAULT_LOCALE
) -> tuple[ConsumptionPoint, ...]:
    """Parse the daily consumption table."""
    soup = BeautifulSoup(html, "html.parser")
    table = _data_table(soup, container_id=_DATA_TABLE_ID)
    points: list[ConsumptionPoint] = []
    for row in _table_rows(table)[1:]:
        if len(row) < 2:
            continue
        day = parse_localized_date(row[0], locale)
        value = parse_decimal(row[1], locale)
        points.append(
            ConsumptionPoint(period_start=day, period_end=day, value_m3=value)
        )
    if not points:
        raise SuezParseError("daily consumption table is empty")
    return tuple(points)


def parse_yearly_consumption(
    html: str, locale: Locale = DEFAULT_LOCALE
) -> tuple[ConsumptionPoint, ...]:
    """Parse the yearly consumption table."""
    soup = BeautifulSoup(html, "html.parser")
    table = _data_table(soup, container_id=_DATA_TABLE_ID)
    points: list[ConsumptionPoint] = []
    for row in _table_rows(table)[1:]:
        if len(row) < 2:
            continue
        try:
            year = int(row[0].strip())
        except ValueError:
            continue
        value = parse_decimal(row[1], locale)
        points.append(
            ConsumptionPoint(
                period_start=date(year, 1, 1),
                period_end=date(year, 12, 31),
                value_m3=value,
            )
        )
    if not points:
        raise SuezParseError("yearly consumption table is empty")
    return tuple(points)


def parse_monthly_index(
    html: str, meter_id: str, locale: Locale = DEFAULT_LOCALE
) -> tuple[MeterReading, ...]:
    """Parse the monthly meter-readings table."""
    soup = BeautifulSoup(html, "html.parser")
    table = _data_table(soup, container_id=_DATA_TABLE_ID)
    readings: list[MeterReading] = []
    for row in _table_rows(table)[1:]:
        if len(row) < 2:
            continue
        month_start = parse_localized_month(row[0], locale)
        value = parse_decimal(row[1], locale)
        readings.append(
            MeterReading(
                meter_id=meter_id,
                timestamp=datetime.combine(
                    _end_of_month(month_start), datetime.min.time()
                ),
                value_m3=value,
            )
        )
    if not readings:
        raise SuezParseError("monthly index table is empty")
    return tuple(readings)


def parse_daily_index(
    html: str, meter_id: str, locale: Locale = DEFAULT_LOCALE
) -> tuple[MeterReading, ...]:
    """Parse the daily meter-readings table."""
    soup = BeautifulSoup(html, "html.parser")
    table = _data_table(soup, container_id=_DATA_TABLE_ID)
    readings: list[MeterReading] = []
    for row in _table_rows(table)[1:]:
        if len(row) < 2:
            continue
        day = parse_localized_date(row[0], locale)
        value = parse_decimal(row[1], locale)
        readings.append(
            MeterReading(
                meter_id=meter_id,
                timestamp=datetime.combine(day, datetime.min.time())
                + timedelta(hours=23),
                value_m3=value,
            )
        )
    if not readings:
        raise SuezParseError("daily index table is empty")
    return tuple(readings)


# --- Alarms ------------------------------------------------------------------

_ALARMS_TABLE_ID = "ctl00_PHZonePrincipale_GridViewAlarmesClient"


def parse_alarms(
    html: str, locale: Locale = DEFAULT_LOCALE
) -> tuple[AlarmEntry, ...]:
    """Parse alarm records from the alarms page.

    Rows whose second cell is not parseable as a datetime are silently
    skipped — that covers the header row and the pager row that the GridView
    appends, regardless of locale.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=_ALARMS_TABLE_ID)
    if not isinstance(table, Tag):
        return ()

    alarms: list[AlarmEntry] = []
    for row in _table_rows(table):
        if len(row) < 4:
            continue
        try:
            occurred_at = parse_localized_datetime(row[1], locale)
        except SuezParseError:
            continue
        value: float | None
        try:
            value = parse_decimal(row[2], locale)
        except SuezParseError:
            value = None
        notified_at: datetime | None
        try:
            notified_at = parse_localized_datetime(row[3], locale)
        except SuezParseError:
            notified_at = None
        email = row[4].strip() if len(row) > 4 else None
        sms = row[5].strip() if len(row) > 5 else None
        alarms.append(
            AlarmEntry(
                alarm_type=row[0],
                occurred_at=occurred_at,
                notified_at=notified_at,
                value=value,
                email_status=email or None,
                sms_status=sms or None,
            )
        )
    return tuple(alarms)


# --- Meter discovery ---------------------------------------------------------


def discover_meter_ids(html: str) -> tuple[str, ...]:
    """Return every meter identifier referenced on the home page."""
    soup = BeautifulSoup(html, "html.parser")
    label_node = soup.find("span", id=_TITRE_LABEL_ID)
    label = _normalize(label_node.get_text()) if label_node else ""
    base_meter = label.rsplit("-", 1)[-1] if "-" in label else label
    indexes = set()
    for script in soup.find_all("script"):
        body = script.string or ""
        for match in _ODOMETER_VALUE_RE.finditer(body):
            indexes.add(int(match.group("idx")))
    if not indexes:
        return (base_meter,) if base_meter else ()
    if len(indexes) == 1:
        return (base_meter,) if base_meter else ()
    discovered: list[str] = []
    for span in soup.find_all("span", id=re.compile(r"LabelMeter_\d+$")):
        discovered.append(_normalize(span.get_text()))
    if discovered:
        return tuple(dict.fromkeys(discovered))
    return (base_meter,) if base_meter else ()


def _iter_text(elements: Iterable[Tag]) -> Iterable[str]:
    for element in elements:
        yield _normalize(element.get_text())


_USERNAME_INPUT_NAME = "ctl00$PHZonePrincipale$TextBoxIdentifiant"


def _describe_unexpected_page(soup: BeautifulSoup, missing: str) -> str:
    """Build a diagnostic string for parse errors on the home page.

    Includes the page ``<title>`` and a flag noting whether the response
    contains the login form, so operators can tell stale-session redirects
    apart from a portal redesign by reading the log.
    """
    title_tag = soup.find("title")
    page_title = _normalize(title_tag.get_text()) if title_tag else ""
    has_login_form = (
        soup.find("input", attrs={"name": _USERNAME_INPUT_NAME}) is not None
    )
    parts = [f"missing {missing}"]
    if page_title:
        parts.append(f"page title: {page_title!r}")
    parts.append(f"login form present: {has_login_form}")
    return "; ".join(parts)
