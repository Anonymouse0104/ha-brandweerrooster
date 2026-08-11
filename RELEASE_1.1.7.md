# v1.1.7

## Fix: Facebookbericht gebruikt kazerne in plaats van ploegnaam

Het Facebookbericht gebruikt vanaf deze versie de naam van de geconfigureerde Brandweerrooster-hoofdgroep (`station_group_id`) in plaats van de Home Assistant entrytitel.

Voorbeeld:

- `Echt TS` → `🚒 Brandweer Echt uitgerukt`
- `Venlo TS` → `🚒 Brandweer Venlo uitgerukt`

Hierdoor blijft het bericht automatisch correct wanneer dezelfde integratie voor een andere kazerne wordt gebruikt. Een aangepaste of oude HA-entrytitel zoals `Ploeg 2` wordt niet meer als kazerne gebruikt zolang de hoofdgroepnaam uit Brandweerrooster beschikbaar is.
