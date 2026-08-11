# Brandweerrooster API — versie 1.1.6

## Uitrukbericht: echte voertuigen uit de P2000-melding

Versie 1.1.6 wijzigt het automatisch gegenereerde `Uitrukbericht` zodat de voertuigregel gebaseerd is op de daadwerkelijk gealarmeerde voertuigcodes in de incidentmelding.

### Voorbeeld

```text
🚒 Brandweer Echt uitgerukt

Voor een incident alert is de brandweer gealarmeerd.
📍 Kraanbergweg Herkenbosch
🕐 Alarmering: 19:39 uur
📟 Prioriteit: P1
🚒 Voertuigen: TS Echt, HV Echt

Meer informatie volgt indien beschikbaar.

#Brandweer #Hulpverlening
```

### Wijzigingen

- Zes-cijferige P2000-voertuigcodes worden rechtstreeks uit de incidentmelding gehaald.
- Expliciete voertuig-/appliance-/unit-objecten uit de Brandweerrooster API krijgen voorrang wanneer die beschikbaar zijn.
- Bekende Limburg-Noord voertuigcodes worden vertaald naar korte, leesbare namen zoals `TS Echt` en `HV Echt`.
- Onbekende codes worden niet als verzonnen voertuignaam weergegeven.
- De locatie wordt uit de P2000-melding gehaald in plaats van de volledige ruwe melding te tonen.
- De vaste tekst `Voor een incident alert is de brandweer gealarmeerd.` wordt gebruikt.
- De ploegnaam wordt niet meer in de kop van het Facebookbericht gezet.
- De kop wordt bijvoorbeeld `🚒 Brandweer Echt uitgerukt`.
- De alarmeringstijd blijft gebaseerd op `created_at` en valt terug op `start_time`.
- De prioriteit wordt genormaliseerd naar `P1`/`P2`.
- Hashtags zijn gewijzigd naar `#Brandweer #Hulpverlening`.
- De bestaande entity `sensor.<ploeg>_uitrukbericht` en het attribuut `bericht` blijven ongewijzigd.

## Belangrijk over voertuigcodes

De Brandweerrooster API levert niet bij ieder incident een voertuignaam naast de P2000-code. Daarom bevat de integratie een afzonderlijke voertuigmapping voor bekende Limburg-Noord codes. Deze mapping kan onafhankelijk worden uitgebreid wanneer nieuwe voertuigen of wijzigingen in roepnummers worden vastgesteld.

Wanneer Brandweerrooster zelf expliciete voertuigobjecten teruggeeft, gebruikt de integratie die informatie vóór de lokale mapping.

## API-belasting

De incidentverwerking blijft volledig event-driven via de officiële FireServiceRota `sensor.incidents` entity. De wijziging introduceert geen periodieke polling van incidenten.
