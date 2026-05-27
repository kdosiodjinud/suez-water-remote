# Suez Smart Solutions Water — Home Assistant integration

Polls any Suez Smart Solutions customer portal — the white-label deployment
served from sub-domains like `cz-sitr.suezsmartsolutions.com`,
`fr-sitr.suezsmartsolutions.com`, … under a per-branch path prefix such as
`eMIS.SE_VHS-Benesov/` — and exposes the data as Home Assistant sensors:

| Sensor | Unit | State class | Notes |
| --- | --- | --- | --- |
| Meter total | m³ | `total_increasing` | Live odometer value |
| Meter total (liters) | L | `total_increasing` | Same value as above, exposed in liters |
| Last reading | datetime | — | Timestamp of the most recent telemetry |
| Today consumption | m³ / L | `total` | Exact-date match in the daily consumption table; `0` (not `unknown`) until the portal publishes today's row (~23:00). `measured_date` / `data_available` attributes tell a measured `0` apart from "no data yet" |
| Yesterday consumption | m³ / L | `total` | Exact-date match in the daily consumption table; `0` when not yet published. Never mixes another day's value |
| This / last month consumption | m³ | `total` | From the monthly table |
| This / last year consumption | m³ | `total` | From the yearly table |
| Alarm count | — | `measurement` | Number of recent threshold alarms |
| Latest alarm | datetime | — | When the most recent alarm fired |
| `<alarm>` – active | `on`/`off` | — | One per configured alarm; type/email/phone and configured parameter labels in attributes |
| `<alarm>: <parameter>` | — | — | One per *configured* parameter slot; empty slots are omitted |

A **Refresh now** button is also created per meter to fetch the latest data on demand.

### Alarm names

The portal exposes alarm labels only as localized free text, with no
language-independent code. Common alarms (overconsumption, leak, and their
threshold / number-of-days parameters) are recognised in **Czech and English**
and named via Home Assistant translations, so they follow your HA UI language.
Any other alarm type — or a French/German portal session — falls back to the
raw label exactly as the portal sends it.

### Energy dashboard (water)

The portal publishes daily figures with a delay, so a live sensor would record
them under the wrong day. To avoid this, the integration imports **long-term
statistics** with each day's real timestamp, as an external statistic.

To add water to the Energy dashboard:

1. Go to **Settings → Dashboards → Energy → Water consumption → Add water source**.
2. Pick the statistic named **`Suez Smart Solutions water <meter id>`**
   (id `suez_water_remote:water_<meter id>`, unit m³).

> **Important — pick the statistic, not a sensor.** Do **not** select the
> *Meter total* sensor here: it carries the portal's delay and would shift your
> daily usage onto the wrong day. The external statistic above is the one that
> attributes each day's consumption to its correct date.

Notes:

- The statistic only appears **after the first successful refresh** following
  setup/upgrade. If you don't see it yet, press the **Refresh now** button (or
  wait for the next poll), then add the water source again.
- This needs the `recorder` integration (declared as a dependency).
- `<meter id>` is your meter number (the part after the last dash in the device
  name / site label).

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

## Update cadence and data freshness

**Daily consumption is not real-time.** It comes from Suez's metering hardware
and portal, which publish a day's figures only after the device reports them —
typically once a day, around 23:00 local time, and often with a lag of a day or
more. Until a given day is published:

- **Today / yesterday consumption** reports `0` (not the previous day's value);
  the `measured_date` / `data_available` attributes show whether the `0` is a
  real measurement or "not published yet".
- The **Energy dashboard** statistic backfills each day onto its correct date as
  soon as the portal makes it available.

The integration polls **every 6 hours** by default — enough to pick up new data
within the next morning, while staying light on the portal. The **Refresh now**
button re-fetches whatever the portal currently holds; it **cannot** make Suez
publish a day's reading sooner.

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
