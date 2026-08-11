# v1.1.9 – Correcte kazerne in uitrukbericht

## Wijzigingen

Deze release corrigeert de naam van de brandweerpost in het automatisch gegenereerde uitrukbericht.

### Voorheen

Bij een configuratie waarvan de Home Assistant-entry bijvoorbeeld `Ploeg 2 (4292)` heette, kon het Facebookbericht beginnen met:

```text
🚒 Brandweer Ploeg 2 uitgerukt
```

### Vanaf v1.1.9

De integratie kijkt eerst naar de groep(en) die daadwerkelijk aan het incident gekoppeld zijn. Een echte kazerne-/hoofdgroep heeft voorrang boven ploeg- of teamnamen.

Voor Brandweer Echt wordt daardoor bijvoorbeeld:

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

De logica is niet hardcoded voor Echt en werkt ook voor andere geselecteerde Brandweerrooster-kazernes.

## Overige functionaliteit

- Event-driven incidentverwerking via FireServiceRota `sensor.incidents`.
- Personeelsindeling en opkomstgegevens.
- Persoonlijke uitruktellers.
- Kopieerbaar Facebook-uitrukbericht.
- P2000-voertuignummers worden vertaald naar leesbare voertuigbenamingen wanneer de code bekend is.
- FireServiceRota blijft verantwoordelijk voor beschikbaarheid en opkomen/afwijzen.

## Upgrade

Vervang de volledige inhoud van `custom_components/brandweerrooster` door deze release, commit en push naar GitHub en herstart Home Assistant na de update.
