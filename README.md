## 1.1.2

Fix compatibility with current Home Assistant time handling (`dt_util.now()`).

# Brandweerrooster API for Home Assistant

Unofficial custom Home Assistant integration for the Brandweerrooster API v2. This project is **not affiliated with, endorsed by, or an official integration from Brandweerrooster**.

## What it does

- Logs in using the documented Brandweerrooster OAuth password flow.
- Lets you select a station/group during setup instead of hard-coding a specific fire station.
- Retrieves incident details, responses and assigned personnel.
- Generates a copy-ready Dutch Facebook dispatch message.
- Keeps personal turnout statistics for the configured Brandweerrooster user.

## Required companion integration: FireServiceRota

This integration intentionally does **not** replace the official Home Assistant **FireServiceRota** integration for live availability and accepting/declining an alarm. Install and configure the official FireServiceRota integration as well.

For the dashboard functionality supplied with this project, keep the following entity IDs unchanged:

- `binary_sensor.duty` — your availability/duty status
- `switch.incident_response` — accept/decline the current incident

If you rename these entities in Home Assistant, dashboards or automations using these fixed entity IDs will no longer work. If you have multiple FireServiceRota configurations, the entity IDs may differ; in that case adapt your dashboard accordingly.

The Brandweerrooster API integration remains responsible for incident history, assigned personnel, Facebook text and the personal statistics described below.

## Installation with HACS

1. Open HACS.
2. Add this GitHub repository as a custom repository.
3. Select **Integration**.
4. Install **Brandweerrooster API**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**.
7. Search for **Brandweerrooster API**.
8. Sign in and select the relevant station/group.

Also install/configure the official **FireServiceRota** integration if you want availability and accept/decline controls.

## Installation manually

Copy `custom_components/brandweerrooster` into:

```text
/config/custom_components/brandweerrooster
```

Restart Home Assistant and add the integration from the UI.

## Entities

The integration creates one device per configured account with entities for:

- latest incident
- assigned personnel
- incident response summary
- logged-in user
- current user's API response
- copy-ready Facebook dispatch message
- personal turnout statistics
- API availability

For live availability and accept/decline, use the FireServiceRota entities listed above.

## Personal turnout statistics

During setup, enter the user's name for personal statistics. The integration also uses the Brandweerrooster user ID whenever available.

The following sensors are created:

- **Uitrukken deze maand**: the user positively responded to an incident **and** appears in the assigned personnel list; current calendar month.
- **Uitrukken dit jaar**: same definition for the current calendar year.
- **Uitrukken totaal**: same definition over the known incident history.
- **Opgekomen, niet ingedeeld**: the user positively responded but does not appear in the assigned personnel list.

The month and year counters are calculated from incident dates, so they automatically roll over at the start of a new month/year and do not depend on Home Assistant restarts. Statistics are stored locally in Home Assistant.

The integration treats `acknowledged` (the response state used by FireServiceRota when accepting an alarm), `dispatched`, `responded`, `accepted`, `coming`, `on_the_way` and `arrived` as positive response states, with explicit decline/no-show states treated as negative.

## Facebook dispatch message

The `Uitrukbericht` sensor contains a `bericht` attribute with a Dutch, copy-ready Facebook message based on the latest relevant incident.

## API

Brandweerrooster documents API v2 at:

https://www.brandweerrooster.nl/apidocs/

The API supports OAuth2, incidents, incident responses, groups, tasks, users, memberships and skills.

## Security

Credentials are stored in the Home Assistant config entry and are not committed to this repository. Never put a Brandweerrooster password or token in YAML, GitHub issues or commits.

## Development

The project is intended as a custom integration and can be installed through HACS. Run Home Assistant's `hassfest` validator from a Home Assistant development checkout before publishing changes.
