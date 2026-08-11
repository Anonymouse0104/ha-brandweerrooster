# Brandweerrooster API — versie 1.1.5

## Uitrukbericht uitgebreid

Versie 1.1.5 breidt het automatisch gegenereerde `Uitrukbericht` uit. Het bericht bevat, wanneer de API deze gegevens daadwerkelijk aan het incident koppelt:

- de naam van de geconfigureerde brandweerpost/groep;
- het meldingstype;
- de locatie;
- de alarmeringstijd op basis van `created_at`;
- de prioriteit;
- daadwerkelijk aan het incident gekoppelde voertuigen/brandweereenheden.

### Belangrijk: tasks zijn geen voertuigen

`task_ids` worden vanaf deze versie **niet** meer als voertuignamen gebruikt. Een Brandweerrooster-task kan een ploeg- of inzettaak zijn en is daarmee niet automatisch een voertuig.

De voertuigextractie kijkt alleen naar expliciete voertuig-/appliance-/unitvelden in de ontvangen incidentdata. Als die gegevens niet aanwezig zijn, wordt de regel `🚒 Voertuigen:` weggelaten. Er worden dus geen voertuigen gegokt of afgeleid uit een tasknaam.

## API-belasting

De normale incidentverwerking blijft event-driven. De integratie luistert naar de officiële FireServiceRota-entiteit `sensor.incidents` en vraagt de Brandweerrooster-API alleen op wanneer een nieuw incident-ID wordt gedetecteerd. De eenmalige historische synchronisatie voor persoonlijke statistieken blijft afzonderlijk en wordt met vertraging uitgevoerd.

## Compatibiliteit

De bestaande entity `sensor.<ploeg>_uitrukbericht` blijft bestaan. De tekst staat in het attribuut `bericht`, waardoor bestaande dashboards en de kopieerfunctie niet aangepast hoeven te worden.

## Installatie / update

1. Vervang de inhoud van je bestaande repository door deze versie.
2. Commit en push naar `main`.
3. Laat HACS de nieuwe versie ophalen of installeer de integratie opnieuw vanuit de custom repository.
4. Herstart Home Assistant.

De integratie blijft afhankelijk van de officiële FireServiceRota-integratie voor live beschikbaarheid en opkomen/afwijzen. Houd daarvoor de bestaande entity-ID's aan zoals beschreven in de README.
