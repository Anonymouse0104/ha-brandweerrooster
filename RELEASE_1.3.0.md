# v1.3.0 - Incident events and incident coordinates

## Highlights

Version 1.3.0 adds two features intended to make Brandweerrooster easier to use in Home Assistant automations and dashboards:

- a dedicated Home Assistant event entity for new incidents;
- latitude and longitude on the latest-incident sensor when coordinates are available.

The existing sensors, statistics, Facebook template system and FireServiceRota workflow remain available.

## Incident event entity

The integration now creates an event entity named **New incident**.

The event entity exposes these event types:

- `p1_incident` — a new P1 incident;
- `p2_incident` — a new P2 incident;
- `new_incident` — a new incident with another or unknown priority.

The event data includes, when available:

- `incident_id`
- `melding`
- `locatie`
- `straat`
- `plaats`
- `prioriteit`
- `incident_type`
- `created_at`
- `start_time`
- `kazerne`
- `voertuigen`
- `latitude`
- `longitude`

This allows users to create automations directly from the Home Assistant automation UI instead of building automations around the internal FireServiceRota state format.

### Example: P1 notification

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
        {{ trigger.event.data.melding }} -
        {{ trigger.event.data.locatie }}
```

Replace the notification service with the service used by your Home Assistant installation.

Home Assistant event entities expose event types in the automation UI and are intended for this type of momentary event. See the Home Assistant developer documentation for event entities and the `event.received` trigger. 

## Incident coordinates

The **Latest incident** sensor now exposes:

- `latitude`
- `longitude`

when coordinates are present in the Brandweerrooster incident or in the companion FireServiceRota incident state.

If the source does not provide coordinates, the attributes remain empty. The integration does not geocode or invent coordinates.

This makes the current incident location available to dashboards and map cards. Home Assistant map cards can display entities with location information.

### Example map card

```yaml
type: map
entities:
  - entity: sensor.brandweerrooster_latest_incident
    name: Latest incident
```

The exact entity ID depends on the configured device/entity naming in your Home Assistant installation.

## Compatibility

This release continues to use the official FireServiceRota integration as the live incident trigger. The standard companion entity remains:

```text
sensor.incidents
```

The integration still retrieves the corresponding Brandweerrooster incident only when a new incident ID is detected.

## Upgrade

1. Replace the existing `custom_components/brandweerrooster` directory with the version 1.3.0 files.
2. Restart Home Assistant.
3. Open the Brandweerrooster device and verify the new **New incident** event entity.
4. Check the **Latest incident** sensor attributes for `latitude` and `longitude` when a live incident is available.

No existing dashboard entity needs to be removed. The new event entity is an additional entity.

## No changes to the Facebook template

The configurable Facebook dispatch message introduced in v1.2.0 remains unchanged. The default template is still created automatically on first setup and existing user templates are never overwritten.
