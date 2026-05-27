"""Recognition of well-known alarm types and parameters across portal languages.

The portal serves alarm configuration labels (``Libelle``) only as localized
free text — there is no language-independent code in the payload. To give the
common alarms a name that follows Home Assistant's UI language instead of the
portal session language, we recognise a small set of known concepts by their
Czech and English labels and map them to translation keys. Anything we do not
recognise (other concepts, French/German labels) falls back to the raw portal
text, so nothing ever disappears — it just stays in the portal's language.
"""

from __future__ import annotations


def _normalize(label: str) -> str:
    """Casefold and collapse whitespace for tolerant matching."""
    return " ".join(label.split()).casefold()


# concept -> recognised labels (Czech + English). Extend with fr/de once the
# exact upstream strings are known.
_ALARM_TYPE_LABELS: dict[str, tuple[str, ...]] = {
    "overconsumption": (
        "upozornění na příliš velikou spotřebu",
        "overconsumption alert",
    ),
    "leak": (
        "upozornění na netěsnost",
        "leak alert",
    ),
}

_ALARM_PARAM_LABELS: dict[str, tuple[str, ...]] = {
    "overconsumption_threshold": (
        "mez nadměrné spotřeby",
        "overconsumption threshold",
    ),
    "number_of_days": (
        "počet dnů",
        "number of days",
    ),
}


def _build_lookup(table: dict[str, tuple[str, ...]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for concept, labels in table.items():
        for label in labels:
            lookup[_normalize(label)] = concept
    return lookup


_TYPE_LOOKUP = _build_lookup(_ALARM_TYPE_LABELS)
_PARAM_LOOKUP = _build_lookup(_ALARM_PARAM_LABELS)


def alarm_type_concept(label: str) -> str | None:
    """Return the canonical concept for an alarm type label, or ``None``."""
    return _TYPE_LOOKUP.get(_normalize(label))


def alarm_param_concept(label: str) -> str | None:
    """Return the canonical concept for a parameter label, or ``None``."""
    return _PARAM_LOOKUP.get(_normalize(label))
