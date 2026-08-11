# v1.1.9 - Correct station name in dispatch message

## Changes

- Fixed the generated dispatch/Facebook message so it no longer uses the Home Assistant config-entry title as the public station name.
- The incident-related Brandweerrooster group is preferred when determining the `{kazerne}` value.
- Crew/team-style names such as `Ploeg 2 (4292)` are no longer exposed as the public station name.
- The logic remains generic and works for other configured stations.
- Existing incident, personnel, turnout statistics and vehicle functionality is unchanged.

## Example

A configuration for the Echt main group now generates:

```text
🚒 Brandweer Echt uitgerukt

Voor een incident alert is de brandweer gealarmeerd.
📍 Kraanbergweg Herkenbosch
🕐 Alarmering: 19:39 uur
📟 Prioriteit: P1
🚒 Voertuigen: DA-OVD Roermond, DV-HOD Roermond, SB Venlo, TST Montfort, TS Regionaal

Meer informatie volgt indien beschikbaar.

#Brandweer #Hulpverlening
```
