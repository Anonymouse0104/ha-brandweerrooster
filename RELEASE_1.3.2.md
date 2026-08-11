# Brandweerrooster API 1.3.2

## Incident enrichment fix

Version 1.3.2 fixes an issue where personnel assignments were sometimes missing from a newly received incident.

Brandweerrooster can create an incident before personnel responses and skill assignments have been fully attached. The integration previously fetched the incident only once, so the `Ingezet personeel` sensor could remain at `0` even when personnel became available a few seconds later.

### Changes

- Added a short, bounded incident-enrichment retry window after a new incident is received.
- Re-fetches the same incident for up to 25 seconds when assigned personnel are not yet available.
- Updates the latest incident, personnel, response data, statistics and related sensors when the incident becomes enriched.
- Does not re-fire the `Event` entity for the same incident during enrichment.
- Stops retrying as soon as personnel assignments are available.
- Stops after the bounded retry window and never performs continuous polling.
- Keeps the existing 1.3.1 startup check for `sensor.incidents` after Home Assistant restarts.

## Compatibility

No configuration changes are required. Existing config entries and stored statistics remain compatible.
