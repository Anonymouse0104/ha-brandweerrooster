[README.md](https://github.com/user-attachments/files/30925360/README.md)
# Brandweerrooster API for Home Assistant

Custom Home Assistant integration for the public Brandweerrooster API v2.

## What it does

- Logs in using the documented Brandweerrooster OAuth password flow.
- Lets you select a station/group during setup instead of hard-coding a specific fire station.
- Polls recent incidents and filters them to the configured station/groups/tasks.
- Retrieves full details for the latest relevant incident.
- Exposes incident details, incident responses and assigned personnel as Home Assistant entities.
- Keeps the integration generic so the same component can be used by different stations and users.

The integration deliberately does **not** write incident responses in version 1.0.0. Use the official FireServiceRota/Brandweerrooster Home Assistant integration for the existing response switch until the exact write contract has been validated against the API account. This avoids accidentally accepting or declining an alarm from a custom integration.

## Installation with HACS

1. Open HACS.
2. Add this GitHub repository as a custom repository.
3. Select **Integration**.
4. Install **Brandweerrooster API**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**.
7. Search for **Brandweerrooster API**.
8. Sign in and select the relevant station/group.

## Installation manually

Copy `custom_components/brandweerrooster` into:

```text
/config/custom_components/brandweerrooster
```

Restart Home Assistant and add the integration from the UI.

## Entities

The integration creates one device per configured account with:

- `sensor.<...>_laatste_incident`
- `sensor.<...>_ingezet_personeel`
- `sensor.<...>_opkomst`
- `sensor.<...>_gebruiker`
- `binary_sensor.<...>_api_beschikbaar`

The incident sensor contains attributes for incident ID, message, location, priority, timestamps, groups, tasks, responses and personnel.

## API

Brandweerrooster documents API v2 at:

https://www.brandweerrooster.nl/apidocs/

The API supports OAuth2, incidents, incident responses, groups, tasks, users, memberships and skills.

## Security

Credentials are stored in the Home Assistant config entry and are not committed to this repository. Never put a Brandweerrooster password or token in YAML, GitHub issues or commits.

## Development

The project is intended as a custom integration and can be installed through HACS. Run Home Assistant's `hassfest` validator from a Home Assistant development checkout before publishing changes.

## Persoonlijke uitrukstatistieken

De integratie kan persoonlijke uitrukstatistieken bijhouden. Tijdens de configuratie wordt de naam van de gebruiker gevraagd. De integratie gebruikt daarnaast het gebruikers-ID uit de Brandweerrooster API wanneer dat beschikbaar is.

De volgende sensoren worden aangemaakt:

- `Uitrukken deze maand`: incidenten waarbij de gebruiker een positieve opkomst heeft gemeld én in de ingezette personeelsindeling voorkomt. Kalendermaand.
- `Uitrukken dit jaar`: dezelfde definitie, voor het kalenderjaar.
- `Uitrukken totaal`: dezelfde definitie, over de volledige bekende incidenthistorie.
- `Opgekomen, niet ingedeeld`: incidenten waarbij de gebruiker een positieve opkomst heeft gemeld maar niet in de personeelsindeling voorkomt.

De tellingen worden lokaal in Home Assistant opgeslagen. Bij de eerste installatie wordt de beschikbare incidenthistorie eenmalig gesynchroniseerd; daarna worden recente incidenten bijgewerkt. Een incident telt voor de eerste drie tellers alleen wanneer de API een positieve persoonlijke opkomst én een personeelsindeling voor dezelfde gebruiker laat zien.

> Let op: de exacte statuswaarden van Brandweerrooster kunnen per API-versie verschillen. De integratie behandelt onder andere `dispatched`, `responded`, `accepted`, `coming`, `on_the_way` en `arrived` als positieve opkomststatussen en expliciete afwijzingsstatussen als negatief.
