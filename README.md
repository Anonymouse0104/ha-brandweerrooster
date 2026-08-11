# Brandweerrooster API for Home Assistant

Unofficial Home Assistant custom integration for the public Brandweerrooster API v2. This project is **not affiliated with, endorsed by, or an official integration from Brandweerrooster**.

## What it does

- Logs in using the documented Brandweerrooster OAuth password flow.
- Lets you select the station/main group during setup instead of hard-coding a fire station.
- Receives live incident triggers from the official FireServiceRota Home Assistant integration.
- Retrieves the relevant Brandweerrooster incident, response and assigned-personnel data.
- Generates a copy-ready Dutch Facebook dispatch message.
- Resolves known P2000 vehicle numbers to readable vehicle names.
- Keeps personal turnout statistics for the configured Brandweerrooster user.
- Stores incident/statistics data locally so it remains available after a Home Assistant restart.

## Required companion integration: FireServiceRota

This integration intentionally does **not** replace the official Home Assistant FireServiceRota integration for live availability and accepting/declining an alarm. Install and configure FireServiceRota as well.

For dashboards using the standard entity IDs, keep these FireServiceRota entity IDs unchanged:

- `binary_sensor.duty` — availability/duty status
- `sensor.incidents` — live incident trigger
- `switch.incident_response` — accept/decline the current incident

If your FireServiceRota setup uses different entity IDs, adapt the dashboard and/or integration constants accordingly.

## Installation with HACS

1. Open HACS.
2. Add this GitHub repository as a custom repository.
3. Select **Integration**.
4. Install **Brandweerrooster API**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**.
7. Search for **Brandweerrooster API**.
8. Sign in and select the relevant station/main group.

## Manual installation

Copy `custom_components/brandweerrooster` into:

```text
/config/custom_components/brandweerrooster
```

Restart Home Assistant and add the integration from the UI.

## Station selection

During setup, the integration retrieves the available Brandweerrooster groups and lets the user select a station/main group. The selected group is stored as `station_group_id`.

The generated Facebook message uses the selected/incident-related station group to determine the `{kazerne}` placeholder. The Home Assistant config-entry title is **not** used for the public station name, so names such as `Ploeg 2 (4292)` do not appear in the generated message.

This makes the same integration usable for different stations without changing the source code.

## Entities

The integration creates one Home Assistant device per configured account with entities for:

- latest incident
- assigned personnel
- incident response summary
- logged-in user
- current user's response
- copy-ready Facebook dispatch message
- personal turnout statistics
- API availability

Live availability and accept/decline controls remain the responsibility of FireServiceRota.

## Incident event entity

The integration creates a **New incident** event entity for automation-friendly incident notifications. The event types are:

- `p1_incident` — a new P1 incident
- `p2_incident` — a new P2 incident
- `new_incident` — another or unknown priority

The event data contains the incident ID, message, location, priority, station, vehicles and timestamps. Latitude and longitude are included when the source provides coordinates.

Example automation:

```yaml
alias: Brandweerrooster - P1 notification
triggers:
  - trigger: event.received
    target:
      entity_id: event.brandweerrooster_new_incident
    options:
      event_type:
        - p1_incident
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "🚒 P1 brandweermelding"
      message: >-
        {{ trigger.event.data.melding }} - {{ trigger.event.data.locatie }}
```

The exact entity ID depends on the configured device/entity naming in Home Assistant. See `examples/automation_new_incident.yaml` for a complete example.

Home Assistant event entities are designed for momentary events and expose their event types to the automation UI.

## Incident location and maps

The **Latest incident** sensor now exposes `latitude` and `longitude` when coordinates are available in the Brandweerrooster incident or the companion FireServiceRota incident state. If no coordinates are provided by the source, the integration leaves them empty and does not geocode or invent a position.

This allows users to show the latest incident on a Home Assistant map card. For example:

```yaml
type: map
entities:
  - entity: sensor.brandweerrooster_latest_incident
    name: Latest incident
```

Replace the example entity ID with the actual entity ID created by your Brandweerrooster config entry. See `examples/map_latest_incident.yaml`.

## Personal turnout statistics

During setup, enter the user's name for personal statistics. The integration also uses the Brandweerrooster user ID whenever available.

The following sensors are created:

- **Uitrukken deze maand**: the user positively responded to an incident **and** appears in the assigned personnel list; current calendar month.
- **Uitrukken dit jaar**: the same definition for the current calendar year.
- **Uitrukken totaal**: the same definition over the known incident history.
- **Opgekomen, niet ingedeeld**: the user positively responded but does not appear in the assigned personnel list.

The month and year counters are based on incident dates and therefore roll over automatically at the start of a new month/year. Statistics are stored locally in Home Assistant and survive a restart.

## Incident updates and API usage

The integration does not continuously poll the Brandweerrooster incident endpoint. It listens to the FireServiceRota `sensor.incidents` entity and only requests the corresponding Brandweerrooster incident when a new incident ID is detected.

A one-time, throttled background history synchronization is used to build personal turnout statistics. Progress is persisted so the synchronization can resume after a restart.

If Brandweerrooster temporarily returns an HTTP 429/rate-limit response, the integration keeps the current FireServiceRota incident available instead of replacing it with an empty state.

## Configurable Facebook dispatch message

The `Uitrukbericht` sensor contains a `bericht` attribute with the generated Facebook message.

On first setup, the integration creates this file automatically:

```text
/config/brandweerrooster/facebook_template.yaml
```

The default template is:

```yaml
facebook_template: |
  🚒 Brandweer {kazerne} uitgerukt

  {uitrukbericht}
  📍 {locatie}
  🕐 Alarmering: {tijd}
  📟 Prioriteit: {prioriteit}
  🚒 Voertuigen: {voertuigen}

  Meer informatie volgt indien beschikbaar.

  #Brandweer #Hulpverlening
```

**This is the default message used by a new installation.** You can edit the file at any time to change the wording, layout, emojis or hashtags. The integration does not overwrite an existing file.

After changing the file, restart Home Assistant to load the new template.

### Available placeholders

| Placeholder | Example |
|---|---|
| `{kazerne}` | `Echt` |
| `{uitrukbericht}` | `Voor een incident alert is de brandweer gealarmeerd.` |
| `{incident_type}` | `incident alert` |
| `{melding}` | Parsed P2000 message text |
| `{locatie}` | `Kraanbergweg Herkenbosch` |
| `{straat}` | `Kraanbergweg` |
| `{plaats}` | `Herkenbosch` |
| `{tijd}` | `19:39 uur` |
| `{datum}` | `10-08-2026` |
| `{prioriteit}` | `P1` |
| `{voertuigen}` | `TS Echt, HV Echt` |
| `{incident_id}` | `3008269` |
| `{created_at}` | Original `created_at` value |
| `{start_time}` | Original `start_time` value |

Unknown placeholders are left empty and logged as warnings. If a placeholder has no value, its template line is omitted when appropriate. This keeps the default vehicle/time/priority lines clean when the API does not provide that information.

### Example custom template

```yaml
facebook_template: |
  🚒 Brandweer {kazerne} uitgerukt

  {uitrukbericht}

  📍 {locatie}
  ⏰ {tijd}
  🚒 Eenheden: {voertuigen}

  #Brandweer{kazerne} #Hulpverlening
```

The template is intentionally plain text. Markdown is not required and the result is copied directly to the clipboard by the dashboard.

## Vehicle names

The integration first uses explicit vehicle/appliance/unit information when Brandweerrooster provides it. If that information is not available, it extracts six-digit P2000 vehicle numbers from the actual incident message and resolves known codes through `custom_components/brandweerrooster/vehicles.py`.

`task_ids` and task names are **not** treated as vehicle names.

Unknown vehicle codes are not guessed. They remain available in the raw incident data but are not invented in the generated Facebook message.

## API

Brandweerrooster documents API v2 at:

https://www.brandweerrooster.nl/apidocs/

The API supports OAuth2, incidents, incident responses, groups, tasks, users, memberships and skills.

## Security

Credentials are stored in the Home Assistant config entry and are not committed to this repository. Never put a Brandweerrooster password or token in YAML, GitHub issues or commits.

## Development

The project is intended as a Home Assistant custom integration and can be installed through HACS. Before publishing changes, run Home Assistant's `hassfest` validator and the repository's Python compile validation.

## License

MIT License.
