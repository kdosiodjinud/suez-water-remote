"""Constants for the Suez Smart Solutions API client."""

from __future__ import annotations

from typing import Final

# Path components of the portal — same across all deployments and locales.
LOGIN_PATH: Final = "Login.aspx"
HOME_PATH: Final = "Site.aspx"
ENERGY_PATH: Final = "Site_Energie.aspx"
ALARMS_PATH: Final = "Site_AlarmesClient.aspx"
ALARMS_CONFIG_PATH: Final = "Site_ConfigurationAlarmeClient.aspx"

# ASP.NET WebForms field names. ``ctl00`` is the master page, ``PHZonePrincipale``
# is the content placeholder. These identifiers are language-independent.
FIELD_USERNAME: Final = "ctl00$PHZonePrincipale$TextBoxIdentifiant"
FIELD_PASSWORD: Final = "ctl00$PHZonePrincipale$TextBoxMotDePasse"
FIELD_LANGUAGE: Final = "ctl00$PHZonePrincipale$Langues$DropDownListLangues"
FIELD_RESOLUTION: Final = "ctl00$PHZonePrincipale$HiddenResolution"

# Cookie installed by the server after a successful login.
AUTH_COOKIE: Final = "SE_Pilote_Cookie"

# Cookie that pins the UI culture; the portal honours it across requests.
CULTURE_COOKIE: Final = "Culture"

# Tab-style URL parameters used by the energy page.
AFFICHAGE_CONSO_DAY: Final = "ConsoJour"
AFFICHAGE_CONSO_MONTH: Final = "ConsoMois"
AFFICHAGE_CONSO_YEAR: Final = "ConsoAn"
AFFICHAGE_INDEX_DAY: Final = "IndexJour"
AFFICHAGE_INDEX_MONTH: Final = "IndexMois"

USER_AGENT: Final = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "HomeAssistant/SuezWaterCZ Chrome/120.0 Safari/537.36"
)

DEFAULT_TIMEOUT_SECONDS: Final = 30.0
