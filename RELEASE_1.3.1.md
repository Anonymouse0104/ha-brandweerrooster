# v1.3.1 - Startup incident detection fix

## Highlights

Version 1.3.1 is a maintenance release for installations where the FireServiceRota `sensor.incidents` entity becomes available after Brandweerrooster has completed its initial setup.

### Fixed

- The integration now performs a short, bounded startup check for `sensor.incidents`.
- If FireServiceRota loads after Brandweerrooster, the current incident is now picked up automatically instead of leaving the Brandweerrooster sensors on `Geen incident` / `Geen uitruk`.
- The existing state-change listener remains in place for normal new incidents.
- No continuous polling of the FireServiceRota entity was added.

### Compatibility

The integration continues to use the official FireServiceRota entity:

```text
sensor.incidents
```

The event entity, incident coordinates, configurable Facebook template, personnel data and statistics from v1.3.0 remain unchanged.

## Upgrade

1. Replace the existing `custom_components/brandweerrooster` directory with the v1.3.1 files.
2. Restart Home Assistant.
3. Open the Brandweerrooster device and verify that the latest incident is populated when `sensor.incidents` contains an incident ID.

No dashboard entity needs to be removed.
