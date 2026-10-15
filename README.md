# Brandweerrooster API for Home Assistant

Unofficial Home Assistant custom integration for the Brandweerrooster API v2. This project is **not affiliated with, endorsed by, or an official integration from Brandweerrooster**.

Everything is configured from the Home Assistant UI — you never have to create or edit YAML files.

## What it does

- Logs in with your Brandweerrooster account (OAuth password flow) and asks you to sign in again when your password changes.
- Receives live incidents from the official **FireServiceRota** integration and fetches the matching Brandweerrooster incident, responses and assigned crew.
- Shows the latest incident, the assigned crew per function, whether the crew is complete, the responses and your own response.
- Puts the incident on the Home Assistant map and calculates the distance from your home.
- Fires an event for every new incident (`p1_incident`, `p2_incident`, `new_incident`) for automations.
- Generates a copy-ready Facebook dispatch message from a template you edit in the UI.
- Keeps personal turnout statistics: this month, last month, this year, total, response rate, per function, per category and per time of day.
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
2. Choose:
   - **Your name**: used for personal statistics (your Brandweerrooster user ID is used whenever available).
   - **Station / main group**: the group whose incidents count as "yours".
   - **Additional groups / tasks** (optional): extra groups or tasks that should also count.
   - **FireServiceRota incident sensor**: normally `sensor.incidents`; pick another one if yours has a different entity ID.
   - **Minimum crew size**: used for the *Crew complete* sensor (e.g. 6 for a TS, 4 for a TS-4).

### Changing settings later

Everything can be changed afterwards under **Settings → Devices & services → Brandweerrooster → Configure**:

| Setting | What it does |
|---|---|
| Station, groups, tasks | Which incidents are relevant |
| FireServiceRota incident sensor | The entity that triggers incident processing |
| Minimum crew size | Threshold for *Crew complete* |
| Dispatch message template | The text of the Facebook message (see below) |
| Vehicle names | P2000 number → readable name, one per line (`235331 = TS Echt`) |
| Install automation blueprints | Puts the bundled blueprints in your blueprint list |

The integration reloads automatically after saving.

If your password changes, Home Assistant shows a **Re-authenticate** notification; enter the new password there.

## Entities

One device is created per configured account. Entity names below are the Dutch names; the entity IDs are based on the device name.

| Entity | Description |
|---|---|
| **Laatste incident** (sensor) | `Incident <id>`; attributes: message, classification, category, street, place, location, priority, vehicles, coordinates, distance, crew, source (API or FireServiceRota fallback) |
| **Laatste alarmering** (timestamp) | When the latest incident was alarmed |
| **Afstand tot incident** (km) | Distance from your Home Assistant home location |
| **Locatie laatste incident** (geo_location) | Shows the incident on the map (only when coordinates are known) |
| **Ingezet personeel** | Number of assigned people; attributes per function and the crew list |
| **Bezetting compleet** (binary sensor) | On when there is a commander, a driver and at least the minimum crew size; attributes say what is missing |
| **Opkomst** | Number of responses; attributes `opgekomen`, `afgewezen`, `overig` |
| **Mijn opkomst** | Your own response status for the latest incident |
| **Uitrukbericht** | Attribute `bericht` contains the generated Facebook message |
| **Uitrukken deze maand / vorige maand / dit jaar / totaal** | Turnouts where you responded positively **and** were assigned |
| **Opgekomen, niet ingedeeld** | You responded positively but were not assigned |
| **Opkomstpercentage dit jaar** | Share of alarms this year where you turned out |
| **Laatste uitruk** (timestamp) | Your most recent turnout |
| **Nieuw incident** (event) | Fires once per new incident |
| **Incident verversen** (button) | Fetches the latest incident again |
| **Statistieken opnieuw synchroniseren** (button) | Rebuilds the statistics from the full history |
| **API beschikbaar** (diagnostic) | Whether the last Brandweerrooster API call succeeded; attributes show the last error |
| **Gebruiker** (diagnostic) | Logged-in user (name and ID only) |

The *Uitrukken dit jaar* sensor also has attributes `per_functie`, `per_categorie`, `per_classificatie` and `per_dagdeel` (night/morning/afternoon/evening), and *Uitrukken totaal* has `per_functie` for all time.

### Privacy

Crew names and response lists are shown on the entities but are **not stored in the recorder database**. The user sensor exposes only name and ID. For troubleshooting use **Download diagnostics** on the integration page; passwords, e-mail addresses and names are redacted there.

## Incident event and automations

The **Nieuw incident** event entity fires one of these event types:

- `p1_incident` — a new P1 incident
- `p2_incident` — a new P2 incident
- `new_incident` — any other or unknown priority

The event data contains `incident_id`, `melding`, `classificatie`, `categorie`, `locatie`, `straat`, `plaats`, `prioriteit`, `kazerne`, `voertuigen`, `bericht` (the dispatch message), timestamps and — when available — `latitude`, `longitude` and `afstand_km`.

### Ready-made blueprints

When *Install automation blueprints* is enabled (default), these appear under **Settings → Automations & scenes → Blueprints**:

- **Brandweerrooster – melding bij nieuw incident**: push notification to your phone for the priorities you choose.
- **Brandweerrooster – nachtalarm**: turns on the lights you choose during the night hours you choose, plus optional extra actions.
- **Brandweerrooster – uitrukbericht naar telefoon**: sends the ready-made Facebook message to your phone a few minutes after the alarm.

Click a blueprint → **Create automation**, pick your phone/lights and save. The integration keeps these files up to date; if you edit one yourself, remove its first line (`# managed-by: brandweerrooster`) and your version is left alone.

### Actions

| Action | Description |
|---|---|
| `brandweerrooster.generate_message` | Returns `{incident_id, bericht}` for the latest incident; optional `template` to use a different text once |
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
| `{voertuigen}` | `TS Echt, HV Echt` |
| `{incident_id}`, `{created_at}`, `{start_time}` | Raw values |

A line whose placeholder has no value is left out, so the vehicle line disappears when no vehicles are known. Unknown placeholders are rejected when saving.

**Upgrading from 1.3.x:** a customised `/config/brandweerrooster/facebook_template.yaml` is imported into the options automatically once. After that the file is no longer used and can be deleted.

## Vehicle names

Vehicle names come from explicit vehicle data in the incident when Brandweerrooster provides it. Otherwise the six-digit P2000 numbers in the alert are translated using the **Vehicle names** list in the options. The list is pre-filled with Limburg-Noord vehicles; replace or extend it for your own region (`235331 = TS Echt`, one per line, `#` for comments). Unknown numbers are never guessed.

## How it works (API usage)

- The integration **does not poll** the incident list. It listens to the FireServiceRota incident sensor and only fetches an incident from Brandweerrooster when a new incident ID appears.
- Crew assignments and responses are often added minutes after the alarm. After a new incident, the integration fetches it again after 15 s, 30 s, 1, 2, 5, 10 and 20 minutes, and stops early as soon as the crew is known and the data no longer changes.
- If the API is unavailable or rate-limited during an alarm, the incident is still shown using the FireServiceRota data (attribute `bron: FireServiceRota`) and the API is retried. Your statistics are never changed by this fallback.
- Statistics are built once from your full history in the background (throttled, resumes after a restart, pauses and retries automatically when rate-limited). A small catch-up runs every night to pick up incidents that happened while Home Assistant was offline and later corrections.
- Month and year counters roll over at midnight.
- If the FireServiceRota incident sensor does not exist, a **Repair** notification explains how to fix it.

## Troubleshooting

- **No incidents arrive**: check that FireServiceRota is working and that the right incident sensor is selected under *Configure*. Look under **Settings → Repairs**.
- **Statistics look wrong**: press **Statistieken opnieuw synchroniseren**.
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
