# Suez Smart Solutions Water — Home Assistant integration

Polls any Suez Smart Solutions customer portal — the white-label deployment
served from sub-domains like `cz-sitr.suezsmartsolutions.com`,
`fr-sitr.suezsmartsolutions.com`, … under a per-branch path prefix such as
`eMIS.SE_VHS-Benesov/` — and exposes the data as Home Assistant sensors:

| Sensor | Unit | State class | Notes |
| --- | --- | --- | --- |
| Meter total | m³ | `total_increasing` | Live odometer value |
| Last reading | datetime | — | Timestamp of the most recent telemetry |
| Today consumption | m³ | `total` | Derived from hourly chart on the home page |
| Yesterday consumption | m³ | `total` | From the daily consumption table |
| This / last month consumption | m³ | `total` | From the monthly table |
| This / last year consumption | m³ | `total` | From the yearly table |
| Alarm count | — | `measurement` | Number of recent threshold alarms |
| Latest alarm | datetime | — | When the most recent alarm fired |

The integration **derives everything** (country sub-domain, branch path,
UI locale) from a single URL you paste in. No country/branch hard-codes.

## Supported locales

The portal ships in four languages. We bake locale tables for each so
parsing month names and number formats works regardless of the UI language:

| Locale | UI | Date format | Time | Decimal | Tested |
| --- | --- | --- | --- | --- | --- |
| `cs` | Česky | `DD.MM.YYYY` | 24h | `,` | ✅ live |
| `fr` | Français | `DD/MM/YYYY` | 24h | `,` | ✅ live |
| `en` | English | `M/D/YYYY` | 12h AM/PM | `.` | ✅ live |
| `de` | Deutsch | `DD.MM.YYYY` | 24h | `,` | ✅ live |

The locale is auto-detected from the login page; the user does not pick one.

## Installation

### HACS (recommended)

1. In HACS → **Integrations**, choose *Custom repositories* → add the URL
   of this repository, category *Integration*.
2. Install **Suez Smart Solutions Water**.
3. Restart Home Assistant.
4. Settings → **Devices & Services** → **+ Add integration** → *Suez Smart
   Solutions Water*.

### Manual

Copy `custom_components/suez_water_remote/` into your Home Assistant
`config/custom_components/` folder and restart.

## Configuration

The config flow asks for **three things**:

1. **Portal URL** — any page of your portal works. Examples:
   - `https://cz-sitr.suezsmartsolutions.com/eMIS.SE_VHS-Benesov/Login.aspx`
   - `https://fr-sitr.suezsmartsolutions.com/eMIS.SE_<branch>/`
2. **Customer number** — the numeric login printed on your bill.
3. **Password** — stored encrypted in Home Assistant; never logged or
   transmitted to third parties.

When the portal exposes more than one meter on the account, a second step
lets you pick which ones to monitor. For single-meter accounts the flow
finishes after the credentials step.

## Update cadence

The upstream telemetry refreshes once per day around 23:00 local time, so
the integration polls **every 6 hours** by default — frequent enough to
see new data within the next morning, but light on the portal.

## Re-authentication

If the password is changed in the portal, Home Assistant will surface a
*Re-authentication required* notification. Click it, re-enter the password,
and the entry resumes.

## Diagnostics

Settings → **Devices & Services** → *Suez Smart Solutions Water* → ⋯ →
**Download diagnostics**. The dump contains the parsed counts per dataset
and the latest reading; credentials are always redacted.

## Project status & guarantees

This integration is community-maintained. It scrapes a public-facing portal:
breakage may follow a portal redesign. Issues, PRs and reverse-engineering
notes are welcome at
[`kdosiodjinud/suez-water-remote`](https://github.com/kdosiodjinud/suez-water-remote).
