# Brandweerrooster API for Home Assistant

Unofficial Home Assistant custom integration for the Brandweerrooster API v2. This project is **not affiliated with, endorsed by, or an official integration from Brandweerrooster**.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Anonymouse0104&repository=ha-brandweerrooster&category=integration) [![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/anonymouse0501)

Everything is configured from the Home Assistant UI — you never have to create or edit YAML files.

## What it does

- Logs in with your Brandweerrooster account (OAuth password flow) and asks you to sign in again when your password changes.
- Receives live incidents from the official **FireServiceRota** integration and fetches the matching Brandweerrooster incident, responses and assigned crew.
- **One account, several functions.** Create a function for every role you have — for example *OvD West* and *TS Echt* — each with its own groups/tasks, its own way of counting turnouts and its own device with sensors and an event. Automate per function.
- Shows the latest incident, the assigned crew per role, whether the crew is complete, the responses and your own response.
- Names the alerted vehicles (23-5331 → *TST Echt*) using [Brandbase](https://brandbase.hetbrandweerforum.nl/), with optional own names.
- Calculates the distance from your home; *Laatste incident* has `latitude`/`longitude`, so a map card can show it.
- Fires an event for every new incident (`p1_incident`, `p2_incident`, `new_incident`).
- Generates a copy-ready Facebook dispatch message from a template you edit in the UI.
- Keeps personal turnout statistics per function: this month, last month, this year, total, response rate, per role, per category and per time of day — plus a combined total over all functions.
- Ships three ready-made automation blueprints: phone notification, night alarm and dispatch message to your phone.

## Requirements

- Home Assistant **2025.8** or newer.
- The official **FireServiceRota** integration, configured with the same account. It provides the live incident trigger (`sensor.incidents`), availability (`binary_sensor.duty`) and the accept/decline switch (`switch.incident_response`). This integration does not replace those.

## Installation

### HACS (recommended)

1. Open HACS → **Integrations** → three-dot menu → **Custom repositories**.
2. Add `https://github.com/Anonymouse0104/ha-brandweerrooster` as an **Integration**.
3. Install **Brandweerrooster API** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for **Brandweerrooster API**.

### Manual

Copy `custom_components/brandweerrooster` to `/config/custom_components/brandweerrooster`, restart Home Assistant and add the integration from the UI.

## Setup

1. Sign in with your Brandweerrooster e-mail address and password.
2. Fill in your account details and your **first function**:
   - **Your name**: used for personal statistics (your Brandweerrooster user ID is used whenever available).
   - **FireServiceRota incident sensor**: normally `sensor.incidents`.
   - **Function name**: for example `OvD West` or `TS Echt`.
   - **Groups / tasks**: an incident belongs to this function when one of these groups or tasks is in it. The first group names the station in the dispatch message.
   - **How is a turnout counted?**
     - *Turnout confirmed in the app* (crew): counts when you confirmed in the app/pager.
     - *Standby duty* (OvD, piket): the function gets a **Piketdienst** switch. Turn it on while you have duty; an alarm for this function counts as a turnout while the switch is on, unless you explicitly rejected it. Brandweerrooster's own "on duty" flag is not used, because it reflects your volunteer availability, not your standby duty.
   - **Minimum crew size**: for the *Crew complete* sensor (e.g. 6 for a TS, 4 for a TS-4).

### More functions

On the integration page, click **Add function** (or the ⋮ menu of the account). Each function gets its own device with all incident and statistics entities. An incident that matches two functions appears in both.

To change a function: ⋮ next to the function → **Reconfigure**. To remove it: ⋮ → **Delete** (its entities and statistics are removed). Changing *How is a turnout counted?* rebuilds that function's statistics.

### Account settings

**Settings → Devices & services → Brandweerrooster → Configure**:

| Setting | What it does |
|---|---|
| Your name | Used to find your responses when the user ID is missing |
| FireServiceRota incident sensor | The entity that triggers incident processing |
| Dispatch message template | The text of the Facebook message (see below) |
| Look up vehicle names on Brandbase | On by default |
| Own vehicle names (exceptions) | Only when you want a different name than Brandbase gives (`235331 = TS Echt`, one per line) |
| Install automation blueprints | Puts the bundled blueprints in your blueprint list |

The integration reloads automatically after saving. If your password changes, Home Assistant shows a **Re-authenticate** notification; enter the new password there.

## Entities

Entity names below are the Dutch names.

### Per function

| Entity | Description |
|---|---|
| **Laatste incident** (sensor) | `Incident <id>`; attributes: message, classification, category, street, place, location, address, priority, vehicles, unknown vehicle numbers, coordinates, distance, crew, source (API or FireServiceRota fallback) |
| **Laatste alarmering** | When the latest incident was alarmed (`16-10-2026 14:32`, or *Nog geen alarmering*); exact time in attribute `tijdstip` |
| **Afstand tot incident** | Distance from your Home Assistant home location (`4,2 km`, *Geen incident* or *Geen locatie bekend*); number in attribute `km` |
| **Ingezet personeel** | Number of assigned people; attributes per role and the crew list |
| **Bezetting compleet** (binary sensor) | On when there is a commander, a driver and at least the minimum crew size; off otherwise and while there is no incident. Attribute `status` (*Compleet*, *Niet compleet*, *Geen incident*) and what is missing |
| **Opkomst** | Number of responses; attributes `opgekomen`, `afgewezen`, `overig` |
| **Mijn opkomst** | Your own response status for the latest incident |
| **Uitrukbericht** | Attribute `bericht` contains the generated Facebook message |
| **Uitrukken deze maand / vorige maand / dit jaar / totaal** | Your turnouts for this function (see *How is a turnout counted?*) |
| **Opgekomen, niet ingedeeld** | App mode: you confirmed but were not assigned |
| **Opkomstpercentage dit jaar** | Share of alarms this year where you turned out (0 % until the first alarm) |
| **Laatste uitruk** | Your most recent turnout (`16-10-2026 14:32`, or *Nog geen uitruk*); exact time in attribute `tijdstip` |
| **Nieuw incident** (event) | Fires once per new incident of this function |
| **Piketdienst** (switch, standby functions only) | On while you have duty; alarms only count while it is on. The on/off periods are stored, so history syncs use the same rule. Alarms from before you first used the switch are not counted |
| **Correctie uitrukken totaal** (number) | Your own number added to *Uitrukken totaal*, e.g. turnouts from another system. Negative values are allowed |
| **Correctie uitrukken dit jaar** (number) | Your own number added to *Uitrukken dit jaar*; back to 0 on 1 January |

*Uitrukken dit jaar* and *Uitrukken totaal* show `geteld` (counted by the integration) and `correctie` as attributes. *Uitrukken dit jaar* also has `per_functie`, `per_categorie`, `per_classificatie` and `per_dagdeel`; *Uitrukken totaal* has `per_functie`, `telwijze` and `historie_samenvatting` (what the last history sync found).

### Account

| Entity | Description |
|---|---|
| **Uitrukken totaal (alle functies)** | Turnouts over all functions; an incident in two functions counts once. Attributes: this year, this month, per function |
| **Incident verversen** (button) | Fetches the latest incident again |
| **Statistieken opnieuw synchroniseren** (button) | Rebuilds the statistics from the full history |
| **API beschikbaar** (diagnostic) | Whether the last Brandweerrooster API call succeeded; attributes show the last error |
| **Gebruiker** (diagnostic) | Logged-in user (name and ID only) |

No entity shows *unknown* or *unavailable* just because there hasn't been an alarm yet; the only exception is the *Nieuw incident* event, whose state is the time of the last event (Home Assistant shows *unknown* until the first one).

### Privacy

Crew names and response lists are shown on the entities but are **not stored in the recorder database**. The user sensor exposes only name and ID. For troubleshooting use **Download diagnostics** on the integration page. It is safe to attach to a public issue: passwords, e-mail addresses and names are redacted, and the crew lists of an incident only keep non-personal fields (status, group, roles) plus whether an entry is yours - no account or membership ids, photos, locations or response times of colleagues.

## Incident event and automations

Each function's **Nieuw incident** event entity fires one of these event types:

- `p1_incident` — a new P1 incident
- `p2_incident` — a new P2 incident
- `new_incident` — any other or unknown priority

The event data contains `functie`, `incident_id`, `melding`, `classificatie`, `categorie`, `locatie`, `straat`, `plaats`, `prioriteit`, `kazerne`, `voertuigen`, `bericht` (the dispatch message), timestamps and — when available — `latitude`, `longitude` and `afstand_km`. For standby functions it also contains `piketdienst` (whether the switch was on), so an automation can act only while you have duty.

### Ready-made blueprints

When *Install automation blueprints* is enabled (default), these appear under **Settings → Automations & scenes → Blueprints**. In each one you pick the function(s) it is for — e.g. the night alarm only for *TS Echt*, a notification only for *OvD West*.

- **Brandweerrooster – melding bij nieuw incident**: push notification to your phone for the priorities you choose.
- **Brandweerrooster – nachtalarm**: turns on the lights you choose during the night hours you choose, plus optional extra actions.
- **Brandweerrooster – uitrukbericht naar telefoon**: sends the ready-made Facebook message to your phone a few minutes after the alarm.

Click a blueprint → **Create automation**, pick your function(s) and phone/lights and save. The integration keeps these files up to date; if you edit one yourself, remove its first line (`# managed-by: brandweerrooster`) and your version is left alone.

### Actions

| Action | Description |
|---|---|
| `brandweerrooster.generate_message` | Returns `{functie, incident_id, bericht}`; optional `functie` (name) and `template` to use a different text once. Without `functie`: the function with the most recent incident |
| `brandweerrooster.refresh_incident` | Fetches the latest incident again |
| `brandweerrooster.resync_statistics` | Rebuilds the statistics from the full history |

## Facebook dispatch message

Edit the template under **Configure → Dispatch message template**. The default is:

```text
🚒 Brandweer {kazerne} uitgerukt – {classificatie}

{uitrukbericht}
📍 {locatie}
🕐 Alarmering: {tijd}
📟 Prioriteit: {prioriteit}
🚒 Voertuigen: {voertuigen}

Meer informatie volgt indien beschikbaar.

#Brandweer #Hulpverlening
```

| Placeholder | Example |
|---|---|
| `{kazerne}` | `Echt` |
| `{classificatie}` | `Woningbrand`, `Buitenbrand` |
| `{categorie}` | `Brand`, `Hulpverlening`, `OMS / automatische melding`, `Overig` |
| `{uitrukbericht}` | `Voor een incident alert is de brandweer gealarmeerd.` |
| `{incident_type}` | `incident alert` |
| `{melding}` | Parsed P2000 message text |
| `{locatie}` | `Kraanbergweg Herkenbosch` |
| `{straat}` / `{plaats}` | `Kraanbergweg` / `Herkenbosch` |
| `{tijd}` / `{datum}` | `19:39 uur` / `10-08-2026` |
| `{prioriteit}` | `P1` |
| `{voertuigen}` | `TST Echt, HV Echt` |
| `{incident_id}`, `{created_at}`, `{start_time}` | Raw values |

A line whose placeholder has no value is left out, so the vehicle line disappears when no vehicles are known. Unknown placeholders are rejected when saving.

## Vehicle names

1. Explicit vehicle data in the incident, when Brandweerrooster provides it.
2. Otherwise the P2000 call signs in the alert (`235331` = `23-5331`):
   - your own names from *Own vehicle names* win;
   - otherwise [Brandbase](https://brandbase.hetbrandweerforum.nl/) is used: type and post become a short name such as `TST Echt`, `HV Echt`, `AL Venlo` or `OvD`.

Brandbase is queried politely: only for regions that appear in your incidents, at most once a week per region, at least 15 seconds between requests, and cached across restarts. Unknown numbers are never guessed; they are listed in the attribute `onbekende_voertuignummers` of *Laatste incident*.

## How it works (API usage)

- The integration **does not poll** the incident list. It listens to the FireServiceRota incident sensor and only fetches an incident from Brandweerrooster when a new incident ID appears; that incident is then given to every function it belongs to.
- Crew assignments and responses are often added minutes after the alarm. After a new incident, the integration fetches it again after 15 s, 30 s, 1, 2, 5, 10 and 20 minutes, and stops early as soon as the crew is known and the data no longer changes.
- If the API is unavailable or rate-limited during an alarm, the incident is still shown using the FireServiceRota data (attribute `bron: FireServiceRota`) and the API is retried. Your statistics are never changed by this fallback.
- Statistics are built once from your full history in the background (throttled, resumes after a restart, pauses and retries automatically when rate-limited). A small catch-up runs every night. A newly added function gets its own history sync.
- Month and year counters roll over at midnight.
- If the FireServiceRota incident sensor does not exist, a **Repair** notification explains how to fix it.

## Upgrading

- **From 1.4.x:** your existing setup becomes one function with the same name as before, keeping all entity IDs, history and statistics. The account entities (*API beschikbaar*, *Gebruiker*, buttons) move to a new account device. An untouched built-in vehicle list is replaced by Brandbase; your own changes to it are kept as exceptions.
- **From 1.3.x:** a customised `/config/brandweerrooster/facebook_template.yaml` is imported into the options automatically once. After that the file is no longer used and can be deleted.

## Troubleshooting

- **No incidents arrive**: check that FireServiceRota is working and that the right incident sensor is selected under *Configure*. Look under **Settings → Repairs**.
- **An incident appears under the wrong function (or none)**: compare `group_ids`/`task_ids` of *Laatste incident* with the function's groups/tasks, or look at `voorbeelden_niet_relevant` in `historie_samenvatting`.
- **Statistics look wrong**: check *How is a turnout counted?* and press **Statistieken opnieuw synchroniseren**.
- **Crew is empty**: Brandweerrooster may not have assigned anyone yet; the integration keeps checking for 20 minutes. Use **Incident verversen** to fetch it once more.
- **Report a bug**: attach the **Download diagnostics** file (it is redacted) to an issue at <https://github.com/Anonymouse0104/ha-brandweerrooster/issues>.

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest
```

CI runs Hassfest, HACS validation and the test suite on every push.

## Security

Credentials are stored in the Home Assistant config entry only. Never put a Brandweerrooster password or token in YAML, GitHub issues or commits.

## License

MIT License.
