<div align="center">

<img src="custom_components/brandweerrooster/brand/icon.png" width="128" alt="Brandweerrooster API icon">

# Brandweerrooster API

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Anonymouse0104&repository=ha-brandweerrooster&category=integration) [![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/anonymouse0501)

[Nederlands](#nederlands) | [English](#english)

</div>

## Nederlands

Onofficiële Home Assistant custom integratie voor de Brandweerrooster API v2. Dit project is **niet gelieerd aan, goedgekeurd door of een officiële integratie van Brandweerrooster**.

Alles stel je in via de Home Assistant-interface; je hoeft nooit YAML-bestanden aan te maken of te bewerken.

### Wat het doet

- Logt in met je Brandweerrooster-account (OAuth password flow) en vraagt je opnieuw in te loggen als je wachtwoord verandert.
- Ontvangt live incidenten van de officiële **FireServiceRota**-integratie en haalt het bijbehorende Brandweerrooster-incident, de reacties en de ingedeelde bezetting op.
- **Eén account, meerdere functies.** Maak een functie voor elke rol die je hebt, bijvoorbeeld *OvD West* en *TS Echt*, elk met eigen groepen/taken, een eigen manier van uitrukken tellen en een eigen apparaat met sensoren en een event. Automatiseer per functie.
- Toont het laatste incident, de ingedeelde bezetting per rol, of de bezetting compleet is, de reacties en je eigen reactie.
- Benoemt de gealarmeerde voertuigen (23-5331 → *TST Echt*) met [Brandbase](https://brandbase.hetbrandweerforum.nl/), met optionele eigen namen.
- Berekent de afstand tot je huis; *Laatste incident* heeft `latitude`/`longitude`, zodat een kaartkaart het kan tonen.
- Stuurt een event voor elk nieuw incident (`p1_incident`, `p2_incident`, `new_incident`).
- Maakt een kopieerklaar Facebook-uitrukbericht op basis van een sjabloon dat je in de interface aanpast.
- Houdt persoonlijke uitrukstatistieken per functie bij: deze maand, vorige maand, dit jaar, totaal, opkomstpercentage, per rol, per categorie en per dagdeel, plus een gezamenlijk totaal over alle functies.
- Bevat drie kant-en-klare automatiseringsblueprints: telefoonmelding, nachtalarm en uitrukbericht naar je telefoon.

### Vereisten

- Home Assistant **2025.8** of nieuwer.
- De officiële **FireServiceRota**-integratie, ingesteld met hetzelfde account. Die levert de live incidenttrigger (`sensor.incidents`), de beschikbaarheid (`binary_sensor.duty`) en de schakelaar voor accepteren/afwijzen (`switch.incident_response`). Deze integratie vervangt die niet.

### Installatie

#### HACS (aanbevolen)

1. Open HACS → **Integraties** → drie-puntjesmenu → **Aangepaste repositories**.
2. Voeg `https://github.com/Anonymouse0104/ha-brandweerrooster` toe als **Integratie**.
3. Installeer **Brandweerrooster API** en herstart Home Assistant.
4. Ga naar **Instellingen → Apparaten en services → Integratie toevoegen** en zoek **Brandweerrooster API**.

#### Handmatig

Kopieer `custom_components/brandweerrooster` naar `/config/custom_components/brandweerrooster`, herstart Home Assistant en voeg de integratie toe via de interface.

### Instellen

1. Log in met je Brandweerrooster-e-mailadres en wachtwoord.
2. Vul je accountgegevens en je **eerste functie** in:
   - **Je naam**: voor persoonlijke statistieken (je Brandweerrooster-gebruikers-ID wordt gebruikt zodra die beschikbaar is).
   - **FireServiceRota-incidentsensor**: normaal `sensor.incidents`.
   - **Functienaam**: bijvoorbeeld `OvD West` of `TS Echt`.
   - **Groepen / taken**: een incident hoort bij deze functie als een van deze groepen of taken erin zit. De eerste groep geeft de kazerne in het uitrukbericht.
   - **Hoe wordt een uitruk geteld?**
     - *Uitruk bevestigd in de app* (bemanning): telt mee als je in de app/pager hebt bevestigd.
     - *Piketdienst* (OvD, piket): de functie krijgt een schakelaar **Piketdienst**. Zet hem aan zolang je dienst hebt; een alarm voor deze functie telt als uitruk zolang de schakelaar aan staat, tenzij je het expliciet hebt afgewezen. De eigen "in dienst"-vlag van Brandweerrooster wordt niet gebruikt, want die weerspiegelt je beschikbaarheid als vrijwilliger, niet je piketdienst.
   - **Minimale bezetting**: voor de sensor *Bezetting compleet* (bijvoorbeeld 6 voor een TS, 4 voor een TS-4).

#### Meer functies

Klik op de integratiepagina op **Functie toevoegen** (of in het ⋮-menu van het account). Elke functie krijgt een eigen apparaat met alle incident- en statistiekentiteiten. Een incident dat bij twee functies past, verschijnt in beide.

Een functie wijzigen: ⋮ naast de functie → **Opnieuw configureren**. Verwijderen: ⋮ → **Verwijderen** (de entiteiten en statistieken worden verwijderd). Als je *Hoe wordt een uitruk geteld?* wijzigt, worden de statistieken van die functie opnieuw opgebouwd.

#### Accountinstellingen

**Instellingen → Apparaten en services → Brandweerrooster → Configureren**:

| Instelling | Wat het doet |
|---|---|
| Je naam | Wordt gebruikt om je reacties te vinden als het gebruikers-ID ontbreekt |
| FireServiceRota-incidentsensor | De entiteit die de verwerking van incidenten start |
| Sjabloon uitrukbericht | De tekst van het Facebook-bericht (zie hieronder) |
| Voertuignamen opzoeken op Brandbase | Standaard aan |
| Eigen voertuignamen (uitzonderingen) | Alleen als je een andere naam wilt dan Brandbase geeft (`235331 = TS Echt`, één per regel) |
| Automatiseringsblueprints installeren | Zet de meegeleverde blueprints in je blueprintlijst |

De integratie herlaadt automatisch na het opslaan. Verandert je wachtwoord, dan toont Home Assistant een melding **Opnieuw verifiëren**; voer daar het nieuwe wachtwoord in.

### Entiteiten

De entiteitsnamen hieronder zijn de Nederlandse namen.

#### Per functie

| Entiteit | Beschrijving |
|---|---|
| **Laatste incident** (sensor) | `Incident <id>`; attributen: melding, classificatie, categorie, straat, plaats, locatie, adres, prioriteit, voertuigen, onbekende voertuignummers, coördinaten, afstand, bezetting, bron (API of FireServiceRota-terugval) |
| **Laatste alarmering** | Wanneer het laatste incident is gealarmeerd (`16-10-2026 14:32`, of *Nog geen alarmering*); exacte tijd in attribuut `tijdstip` |
| **Afstand tot incident** | Afstand vanaf de thuislocatie van je Home Assistant (`4,2 km`, *Geen incident* of *Geen locatie bekend*); getal in attribuut `km` |
| **Ingezet personeel** | Aantal ingedeelde personen; attributen per rol en de bezettingslijst |
| **Bezetting compleet** (binary sensor) | Aan als er een bevelvoerder, een chauffeur en minstens de minimale bezetting is; anders uit, en ook uit zolang er geen incident is. Attribuut `status` (*Compleet*, *Niet compleet*, *Geen incident*) en wat er ontbreekt |
| **Opkomst** | Aantal reacties; attributen `opgekomen`, `afgewezen`, `overig` |
| **Mijn opkomst** | Je eigen reactiestatus voor het laatste incident |
| **Uitrukbericht** | Attribuut `bericht` bevat het gegenereerde Facebook-bericht |
| **Uitrukken deze maand / vorige maand / dit jaar / totaal** | Je uitrukken voor deze functie (zie *Hoe wordt een uitruk geteld?*) |
| **Opgekomen, niet ingedeeld** | Appmodus: je hebt bevestigd maar was niet ingedeeld |
| **Opkomstpercentage dit jaar** | Aandeel alarmeringen dit jaar waarbij je bent uitgerukt (0 % tot het eerste alarm) |
| **Laatste uitruk** | Je meest recente uitruk (`16-10-2026 14:32`, of *Nog geen uitruk*); exacte tijd in attribuut `tijdstip` |
| **Nieuw incident** (event) | Gaat één keer af per nieuw incident van deze functie |
| **Piketdienst** (schakelaar, alleen piketfuncties) | Aan zolang je dienst hebt; alarmen tellen alleen mee zolang hij aan staat. De aan/uit-periodes worden bewaard, zodat historische synchronisaties dezelfde regel gebruiken. Alarmen van vóór je de schakelaar voor het eerst gebruikte tellen niet mee |
| **Correctie uitrukken totaal** (number) | Je eigen getal, opgeteld bij *Uitrukken totaal*, bijvoorbeeld uitrukken uit een ander systeem. Negatieve waarden zijn toegestaan |
| **Correctie uitrukken dit jaar** (number) | Je eigen getal, opgeteld bij *Uitrukken dit jaar*; op 1 januari terug naar 0 |

*Uitrukken dit jaar* en *Uitrukken totaal* tonen `geteld` (geteld door de integratie) en `correctie` als attributen. *Uitrukken dit jaar* heeft ook `per_functie`, `per_categorie`, `per_classificatie` en `per_dagdeel`; *Uitrukken totaal* heeft `per_functie`, `telwijze` en `historie_samenvatting` (wat de laatste historiesynchronisatie vond).

#### Account

| Entiteit | Beschrijving |
|---|---|
| **Uitrukken totaal (alle functies)** | Uitrukken over alle functies; een incident in twee functies telt één keer. Attributen: dit jaar, deze maand, per functie |
| **Incident verversen** (knop) | Haalt het laatste incident opnieuw op |
| **Statistieken opnieuw synchroniseren** (knop) | Bouwt de statistieken opnieuw op uit de volledige historie |
| **API beschikbaar** (diagnostiek) | Of de laatste Brandweerrooster API-aanroep is gelukt; attributen tonen de laatste fout |
| **Gebruiker** (diagnostiek) | Ingelogde gebruiker (alleen naam en ID) |

Geen enkele entiteit toont *onbekend* of *niet beschikbaar* alleen omdat er nog geen alarm is geweest; de enige uitzondering is het event *Nieuw incident*, waarvan de state de tijd van het laatste event is (Home Assistant toont *onbekend* tot het eerste).

#### Privacy

Namen van bemanning en reactielijsten worden op de entiteiten getoond maar **niet opgeslagen in de recorder-database**. De gebruikerssensor toont alleen naam en ID. Gebruik voor het oplossen van problemen **Diagnostiek downloaden** op de integratiepagina. Die is veilig om bij een openbaar issue te voegen: wachtwoorden, e-mailadressen en namen zijn afgeschermd, en de bezettingslijsten van een incident bewaren alleen niet-persoonlijke velden (status, groep, rollen) plus of een regel van jou is. Geen account- of lidmaatschaps-id's, foto's, locaties of reactietijden van collega's.

### Incidentevent en automatiseringen

De event-entiteit **Nieuw incident** van elke functie stuurt een van deze eventtypes:

- `p1_incident`: een nieuw P1-incident
- `p2_incident`: een nieuw P2-incident
- `new_incident`: elke andere of onbekende prioriteit

De eventdata bevat `functie`, `incident_id`, `melding`, `classificatie`, `categorie`, `locatie`, `straat`, `plaats`, `prioriteit`, `kazerne`, `voertuigen`, `bericht` (het uitrukbericht), tijdstempels en, indien beschikbaar, `latitude`, `longitude` en `afstand_km`. Voor piketfuncties staat er ook `piketdienst` in (of de schakelaar aan stond), zodat een automatisering alleen kan handelen zolang je dienst hebt.

#### Kant-en-klare blueprints

Als *Automatiseringsblueprints installeren* aan staat (standaard), verschijnen deze onder **Instellingen → Automatiseringen en scènes → Blueprints**. In elk kies je voor welke functie(s) hij is, bijvoorbeeld het nachtalarm alleen voor *TS Echt*, een melding alleen voor *OvD West*.

- **Brandweerrooster – melding bij nieuw incident**: pushmelding naar je telefoon voor de prioriteiten die je kiest.
- **Brandweerrooster – nachtalarm**: zet de lampen die je kiest aan in de nachturen die je kiest, plus optionele extra acties.
- **Brandweerrooster – uitrukbericht naar telefoon**: stuurt het kant-en-klare Facebook-bericht een paar minuten na het alarm naar je telefoon.

Klik op een blueprint → **Automatisering maken**, kies je functie(s) en telefoon/lampen en sla op. De integratie houdt deze bestanden up-to-date; pas je er zelf een aan, verwijder dan de eerste regel (`# managed-by: brandweerrooster`) en jouw versie blijft ongemoeid.

#### Acties

| Actie | Beschrijving |
|---|---|
| `brandweerrooster.generate_message` | Geeft `{functie, incident_id, bericht}` terug; optioneel `functie` (naam) en `template` om één keer een andere tekst te gebruiken. Zonder `functie`: de functie met het meest recente incident |
| `brandweerrooster.refresh_incident` | Haalt het laatste incident opnieuw op |
| `brandweerrooster.resync_statistics` | Bouwt de statistieken opnieuw op uit de volledige historie |

#### Het alarm naar WhatsApp sturen

Wil je dat de bemanning of een familiegroep het alarm in WhatsApp krijgt? [WhatsApp Notifier](https://github.com/Anonymouse0104/ha-whatsapp-notifier) stuurt berichten vanuit Home Assistant naar een persoon of groep, zonder externe dienst. Gebruik de notify-entiteit als telefoon/doel in de blueprints, of roep `whatsapp_notifier.send_message` aan met de tekst van `brandweerrooster.generate_message`.

### Facebook-uitrukbericht

Pas het sjabloon aan onder **Configureren → Sjabloon uitrukbericht**. De standaard is:

```text
🚒 Brandweer {kazerne} uitgerukt – {classificatie}

{uitrukbericht}
📍 {locatie}
🕐 Alarmering: {tijd}
📟 Prioriteit: {prioriteit}
🚒 Voertuigen: {voertuigen}

Meer informatie volgt indien beschikbaar.

#Brandweer #Hulpverlening
```

| Plaatsaanduiding | Voorbeeld |
|---|---|
| `{kazerne}` | `Echt` |
| `{classificatie}` | `Woningbrand`, `Buitenbrand` |
| `{categorie}` | `Brand`, `Hulpverlening`, `OMS / automatische melding`, `Overig` |
| `{uitrukbericht}` | `Voor een incident alert is de brandweer gealarmeerd.` |
| `{incident_type}` | `incident alert` |
| `{melding}` | Uitgelezen P2000-meldingstekst |
| `{locatie}` | `Kraanbergweg Herkenbosch` |
| `{straat}` / `{plaats}` | `Kraanbergweg` / `Herkenbosch` |
| `{tijd}` / `{datum}` | `19:39 uur` / `10-08-2026` |
| `{prioriteit}` | `P1` |
| `{voertuigen}` | `TST Echt, HV Echt` |
| `{incident_id}`, `{created_at}`, `{start_time}` | Ruwe waarden |

Een regel waarvan de plaatsaanduiding geen waarde heeft, wordt weggelaten, dus de voertuigregel verdwijnt als er geen voertuigen bekend zijn. Onbekende plaatsaanduidingen worden bij het opslaan geweigerd.

### Voertuignamen

1. Expliciete voertuigdata in het incident, als Brandweerrooster die levert.
2. Anders de P2000-roepnummers in de melding (`235331` = `23-5331`):
   - je eigen namen uit *Eigen voertuignamen* gaan voor;
   - anders wordt [Brandbase](https://brandbase.hetbrandweerforum.nl/) gebruikt: type en post worden een korte naam zoals `TST Echt`, `HV Echt`, `AL Venlo` of `OvD`.

Brandbase wordt netjes bevraagd: alleen voor regio's die in je incidenten voorkomen, hooguit één keer per week per regio, minstens 15 seconden tussen verzoeken, en bewaard over herstarts heen. Onbekende nummers worden nooit geraden; ze staan in het attribuut `onbekende_voertuignummers` van *Laatste incident*.

### Hoe het werkt (API-gebruik)

- De integratie **pollt de incidentlijst niet**. Hij luistert naar de FireServiceRota-incidentsensor en haalt alleen een incident bij Brandweerrooster op als er een nieuw incident-ID verschijnt; dat incident wordt daarna aan elke functie gegeven waar het bij hoort.
- Bezettingsindelingen en reacties komen vaak pas minuten na het alarm binnen. Na een nieuw incident haalt de integratie het opnieuw op na 15 s, 30 s, 1, 2, 5, 10 en 20 minuten, en stopt eerder zodra de bezetting bekend is en de data niet meer verandert.
- Is de API tijdens een alarm niet beschikbaar of begrensd, dan wordt het incident toch getoond met de FireServiceRota-data (attribuut `bron: FireServiceRota`) en wordt de API opnieuw geprobeerd. Je statistieken veranderen door deze terugval nooit.
- Statistieken worden eenmalig op de achtergrond opgebouwd uit je volledige historie (gedrosseld, hervat na een herstart, pauzeert en probeert opnieuw bij begrenzing). Elke nacht draait een kleine inhaalslag. Een nieuw toegevoegde functie krijgt een eigen historiesynchronisatie.
- De maand- en jaartellers lopen om middernacht over.
- Bestaat de FireServiceRota-incidentsensor niet, dan legt een **Reparatie**-melding uit hoe je dat oplost.

### Upgraden

- **Vanaf 1.4.x:** je bestaande instelling wordt één functie met dezelfde naam als voorheen, met behoud van alle entity-ID's, historie en statistieken. De accountentiteiten (*API beschikbaar*, *Gebruiker*, knoppen) verhuizen naar een nieuw accountapparaat. Een ongewijzigde ingebouwde voertuiglijst wordt vervangen door Brandbase; je eigen wijzigingen daarin blijven als uitzonderingen behouden.
- **Vanaf 1.3.x:** een aangepaste `/config/brandweerrooster/facebook_template.yaml` wordt eenmalig automatisch in de opties geïmporteerd. Daarna wordt het bestand niet meer gebruikt en kan het weg.

### Problemen oplossen

- **Er komen geen incidenten binnen**: controleer of FireServiceRota werkt en of de juiste incidentsensor is gekozen onder *Configureren*. Kijk onder **Instellingen → Reparaties**.
- **Een incident verschijnt bij de verkeerde functie (of geen)**: vergelijk `group_ids`/`task_ids` van *Laatste incident* met de groepen/taken van de functie, of kijk naar `voorbeelden_niet_relevant` in `historie_samenvatting`.
- **Statistieken kloppen niet**: controleer *Hoe wordt een uitruk geteld?* en druk op **Statistieken opnieuw synchroniseren**.
- **Bezetting is leeg**: Brandweerrooster heeft misschien nog niemand ingedeeld; de integratie blijft 20 minuten controleren. Gebruik **Incident verversen** om het nog één keer op te halen.
- **Een bug melden**: voeg het bestand van **Diagnostiek downloaden** (afgeschermd) toe aan een issue op <https://github.com/Anonymouse0104/ha-brandweerrooster/issues>.

### Ontwikkeling

```bash
pip install pytest-homeassistant-custom-component
pytest
```

CI draait Hassfest, HACS-validatie en de testsuite bij elke push.

### Beveiliging

Inloggegevens worden alleen opgeslagen in de config entry van Home Assistant. Zet nooit een Brandweerrooster-wachtwoord of -token in YAML, GitHub-issues of commits.

### Licentie

MIT-licentie.

### Steun

Bespaart deze integratie je tijd, dan kun je me [steunen op Ko-fi](https://ko-fi.com/anonymouse0501). Het is helemaal optioneel en de integratie blijft in beide gevallen gratis.

---

## English

Unofficial Home Assistant custom integration for the Brandweerrooster API v2. This project is **not affiliated with, endorsed by, or an official integration from Brandweerrooster**.

Everything is configured from the Home Assistant UI — you never have to create or edit YAML files.

### What it does

- Logs in with your Brandweerrooster account (OAuth password flow) and asks you to sign in again when your password changes.
- Receives live incidents from the official **FireServiceRota** integration and fetches the matching Brandweerrooster incident, responses and assigned crew.
- **One account, several functions.** Create a function for every role you have — for example *OvD West* and *TS Echt* — each with its own groups/tasks, its own way of counting turnouts and its own device with sensors and an event. Automate per function.
- Shows the latest incident, the assigned crew per role, whether the crew is complete, the responses and your own response.
- Names the alerted vehicles (23-5331 → *TST Echt*) using [Brandbase](https://brandbase.hetbrandweerforum.nl/), with optional own names.
- Calculates the distance from your home; *Laatste incident* has `latitude`/`longitude`, so a map card can show it.
- Fires an event for every new incident (`p1_incident`, `p2_incident`, `new_incident`).
- Generates a copy-ready Facebook dispatch message from a template you edit in the UI.
- Keeps personal turnout statistics per function: this month, last month, this year, total, response rate, per role, per category and per time of day — plus a combined total over all functions.
- Ships three ready-made automation blueprints: phone notification, night alarm and dispatch message to your phone.

### Requirements

- Home Assistant **2025.8** or newer.
- The official **FireServiceRota** integration, configured with the same account. It provides the live incident trigger (`sensor.incidents`), availability (`binary_sensor.duty`) and the accept/decline switch (`switch.incident_response`). This integration does not replace those.

### Installation

#### HACS (recommended)

1. Open HACS → **Integrations** → three-dot menu → **Custom repositories**.
2. Add `https://github.com/Anonymouse0104/ha-brandweerrooster` as an **Integration**.
3. Install **Brandweerrooster API** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for **Brandweerrooster API**.

#### Manual

Copy `custom_components/brandweerrooster` to `/config/custom_components/brandweerrooster`, restart Home Assistant and add the integration from the UI.

### Setup

1. Sign in with your Brandweerrooster e-mail address and password.
2. Fill in your account details and your **first function**:
   - **Your name**: used for personal statistics (your Brandweerrooster user ID is used whenever available).
   - **FireServiceRota incident sensor**: normally `sensor.incidents`.
   - **Function name**: for example `OvD West` or `TS Echt`.
   - **Groups / tasks**: an incident belongs to this function when one of these groups or tasks is in it. The first group names the station in the dispatch message.
   - **How is a turnout counted?**
     - *Turnout confirmed in the app* (crew): counts when you confirmed in the app/pager.
     - *Standby duty* (OvD, piket): the function gets a **Piketdienst** switch. Turn it on while you have duty; an alarm for this function counts as a turnout while the switch is on, unless you explicitly rejected it. Brandweerrooster's own "on duty" flag is not used, because it reflects your volunteer availability, not your standby duty.
   - **Minimum crew size**: for the *Crew complete* sensor (e.g. 6 for a TS, 4 for a TS-4).

#### More functions

On the integration page, click **Add function** (or the ⋮ menu of the account). Each function gets its own device with all incident and statistics entities. An incident that matches two functions appears in both.

To change a function: ⋮ next to the function → **Reconfigure**. To remove it: ⋮ → **Delete** (its entities and statistics are removed). Changing *How is a turnout counted?* rebuilds that function's statistics.

#### Account settings

**Settings → Devices & services → Brandweerrooster → Configure**:

| Setting | What it does |
|---|---|
| Your name | Used to find your responses when the user ID is missing |
| FireServiceRota incident sensor | The entity that triggers incident processing |
| Dispatch message template | The text of the Facebook message (see below) |
| Look up vehicle names on Brandbase | On by default |
| Own vehicle names (exceptions) | Only when you want a different name than Brandbase gives (`235331 = TS Echt`, one per line) |
| Install automation blueprints | Puts the bundled blueprints in your blueprint list |

The integration reloads automatically after saving. If your password changes, Home Assistant shows a **Re-authenticate** notification; enter the new password there.

### Entities

Entity names below are the Dutch names.

#### Per function

| Entity | Description |
|---|---|
| **Laatste incident** (sensor) | `Incident <id>`; attributes: message, classification, category, street, place, location, address, priority, vehicles, unknown vehicle numbers, coordinates, distance, crew, source (API or FireServiceRota fallback) |
| **Laatste alarmering** | When the latest incident was alarmed (`16-10-2026 14:32`, or *Nog geen alarmering*); exact time in attribute `tijdstip` |
| **Afstand tot incident** | Distance from your Home Assistant home location (`4,2 km`, *Geen incident* or *Geen locatie bekend*); number in attribute `km` |
| **Ingezet personeel** | Number of assigned people; attributes per role and the crew list |
| **Bezetting compleet** (binary sensor) | On when there is a commander, a driver and at least the minimum crew size; off otherwise and while there is no incident. Attribute `status` (*Compleet*, *Niet compleet*, *Geen incident*) and what is missing |
| **Opkomst** | Number of responses; attributes `opgekomen`, `afgewezen`, `overig` |
| **Mijn opkomst** | Your own response status for the latest incident |
| **Uitrukbericht** | Attribute `bericht` contains the generated Facebook message |
| **Uitrukken deze maand / vorige maand / dit jaar / totaal** | Your turnouts for this function (see *How is a turnout counted?*) |
| **Opgekomen, niet ingedeeld** | App mode: you confirmed but were not assigned |
| **Opkomstpercentage dit jaar** | Share of alarms this year where you turned out (0 % until the first alarm) |
| **Laatste uitruk** | Your most recent turnout (`16-10-2026 14:32`, or *Nog geen uitruk*); exact time in attribute `tijdstip` |
| **Nieuw incident** (event) | Fires once per new incident of this function |
| **Piketdienst** (switch, standby functions only) | On while you have duty; alarms only count while it is on. The on/off periods are stored, so history syncs use the same rule. Alarms from before you first used the switch are not counted |
| **Correctie uitrukken totaal** (number) | Your own number added to *Uitrukken totaal*, e.g. turnouts from another system. Negative values are allowed |
| **Correctie uitrukken dit jaar** (number) | Your own number added to *Uitrukken dit jaar*; back to 0 on 1 January |

*Uitrukken dit jaar* and *Uitrukken totaal* show `geteld` (counted by the integration) and `correctie` as attributes. *Uitrukken dit jaar* also has `per_functie`, `per_categorie`, `per_classificatie` and `per_dagdeel`; *Uitrukken totaal* has `per_functie`, `telwijze` and `historie_samenvatting` (what the last history sync found).

#### Account

| Entity | Description |
|---|---|
| **Uitrukken totaal (alle functies)** | Turnouts over all functions; an incident in two functions counts once. Attributes: this year, this month, per function |
| **Incident verversen** (button) | Fetches the latest incident again |
| **Statistieken opnieuw synchroniseren** (button) | Rebuilds the statistics from the full history |
| **API beschikbaar** (diagnostic) | Whether the last Brandweerrooster API call succeeded; attributes show the last error |
| **Gebruiker** (diagnostic) | Logged-in user (name and ID only) |

No entity shows *unknown* or *unavailable* just because there hasn't been an alarm yet; the only exception is the *Nieuw incident* event, whose state is the time of the last event (Home Assistant shows *unknown* until the first one).

#### Privacy

Crew names and response lists are shown on the entities but are **not stored in the recorder database**. The user sensor exposes only name and ID. For troubleshooting use **Download diagnostics** on the integration page. It is safe to attach to a public issue: passwords, e-mail addresses and names are redacted, and the crew lists of an incident only keep non-personal fields (status, group, roles) plus whether an entry is yours - no account or membership ids, photos, locations or response times of colleagues.

### Incident event and automations

Each function's **Nieuw incident** event entity fires one of these event types:

- `p1_incident` — a new P1 incident
- `p2_incident` — a new P2 incident
- `new_incident` — any other or unknown priority

The event data contains `functie`, `incident_id`, `melding`, `classificatie`, `categorie`, `locatie`, `straat`, `plaats`, `prioriteit`, `kazerne`, `voertuigen`, `bericht` (the dispatch message), timestamps and — when available — `latitude`, `longitude` and `afstand_km`. For standby functions it also contains `piketdienst` (whether the switch was on), so an automation can act only while you have duty.

#### Ready-made blueprints

When *Install automation blueprints* is enabled (default), these appear under **Settings → Automations & scenes → Blueprints**. In each one you pick the function(s) it is for — e.g. the night alarm only for *TS Echt*, a notification only for *OvD West*.

- **Brandweerrooster – melding bij nieuw incident**: push notification to your phone for the priorities you choose.
- **Brandweerrooster – nachtalarm**: turns on the lights you choose during the night hours you choose, plus optional extra actions.
- **Brandweerrooster – uitrukbericht naar telefoon**: sends the ready-made Facebook message to your phone a few minutes after the alarm.

Click a blueprint → **Create automation**, pick your function(s) and phone/lights and save. The integration keeps these files up to date; if you edit one yourself, remove its first line (`# managed-by: brandweerrooster`) and your version is left alone.

#### Actions

| Action | Description |
|---|---|
| `brandweerrooster.generate_message` | Returns `{functie, incident_id, bericht}`; optional `functie` (name) and `template` to use a different text once. Without `functie`: the function with the most recent incident |
| `brandweerrooster.refresh_incident` | Fetches the latest incident again |
| `brandweerrooster.resync_statistics` | Rebuilds the statistics from the full history |

#### Send the alert to WhatsApp

Want the crew or a family group to get the alert in WhatsApp? [WhatsApp Notifier](https://github.com/Anonymouse0104/ha-whatsapp-notifier) sends messages from Home Assistant to a person or group without a third-party service. Use its notify entity as the phone/target in the blueprints, or call `whatsapp_notifier.send_message` with the text from `brandweerrooster.generate_message`.

### Facebook dispatch message

Edit the template under **Configure → Dispatch message template**. The default is:

```text
🚒 Brandweer {kazerne} uitgerukt – {classificatie}

{uitrukbericht}
📍 {locatie}
🕐 Alarmering: {tijd}
📟 Prioriteit: {prioriteit}
🚒 Voertuigen: {voertuigen}

Meer informatie volgt indien beschikbaar.

#Brandweer #Hulpverlening
```

| Placeholder | Example |
|---|---|
| `{kazerne}` | `Echt` |
| `{classificatie}` | `Woningbrand`, `Buitenbrand` |
| `{categorie}` | `Brand`, `Hulpverlening`, `OMS / automatische melding`, `Overig` |
| `{uitrukbericht}` | `Voor een incident alert is de brandweer gealarmeerd.` |
| `{incident_type}` | `incident alert` |
| `{melding}` | Parsed P2000 message text |
| `{locatie}` | `Kraanbergweg Herkenbosch` |
| `{straat}` / `{plaats}` | `Kraanbergweg` / `Herkenbosch` |
| `{tijd}` / `{datum}` | `19:39 uur` / `10-08-2026` |
| `{prioriteit}` | `P1` |
| `{voertuigen}` | `TST Echt, HV Echt` |
| `{incident_id}`, `{created_at}`, `{start_time}` | Raw values |

A line whose placeholder has no value is left out, so the vehicle line disappears when no vehicles are known. Unknown placeholders are rejected when saving.

### Vehicle names

1. Explicit vehicle data in the incident, when Brandweerrooster provides it.
2. Otherwise the P2000 call signs in the alert (`235331` = `23-5331`):
   - your own names from *Own vehicle names* win;
   - otherwise [Brandbase](https://brandbase.hetbrandweerforum.nl/) is used: type and post become a short name such as `TST Echt`, `HV Echt`, `AL Venlo` or `OvD`.

Brandbase is queried politely: only for regions that appear in your incidents, at most once a week per region, at least 15 seconds between requests, and cached across restarts. Unknown numbers are never guessed; they are listed in the attribute `onbekende_voertuignummers` of *Laatste incident*.

### How it works (API usage)

- The integration **does not poll** the incident list. It listens to the FireServiceRota incident sensor and only fetches an incident from Brandweerrooster when a new incident ID appears; that incident is then given to every function it belongs to.
- Crew assignments and responses are often added minutes after the alarm. After a new incident, the integration fetches it again after 15 s, 30 s, 1, 2, 5, 10 and 20 minutes, and stops early as soon as the crew is known and the data no longer changes.
- If the API is unavailable or rate-limited during an alarm, the incident is still shown using the FireServiceRota data (attribute `bron: FireServiceRota`) and the API is retried. Your statistics are never changed by this fallback.
- Statistics are built once from your full history in the background (throttled, resumes after a restart, pauses and retries automatically when rate-limited). A small catch-up runs every night. A newly added function gets its own history sync.
- Month and year counters roll over at midnight.
- If the FireServiceRota incident sensor does not exist, a **Repair** notification explains how to fix it.

### Upgrading

- **From 1.4.x:** your existing setup becomes one function with the same name as before, keeping all entity IDs, history and statistics. The account entities (*API beschikbaar*, *Gebruiker*, buttons) move to a new account device. An untouched built-in vehicle list is replaced by Brandbase; your own changes to it are kept as exceptions.
- **From 1.3.x:** a customised `/config/brandweerrooster/facebook_template.yaml` is imported into the options automatically once. After that the file is no longer used and can be deleted.

### Troubleshooting

- **No incidents arrive**: check that FireServiceRota is working and that the right incident sensor is selected under *Configure*. Look under **Settings → Repairs**.
- **An incident appears under the wrong function (or none)**: compare `group_ids`/`task_ids` of *Laatste incident* with the function's groups/tasks, or look at `voorbeelden_niet_relevant` in `historie_samenvatting`.
- **Statistics look wrong**: check *How is a turnout counted?* and press **Statistieken opnieuw synchroniseren**.
- **Crew is empty**: Brandweerrooster may not have assigned anyone yet; the integration keeps checking for 20 minutes. Use **Incident verversen** to fetch it once more.
- **Report a bug**: attach the **Download diagnostics** file (it is redacted) to an issue at <https://github.com/Anonymouse0104/ha-brandweerrooster/issues>.

### Development

```bash
pip install pytest-homeassistant-custom-component
pytest
```

CI runs Hassfest, HACS validation and the test suite on every push.

### Security

Credentials are stored in the Home Assistant config entry only. Never put a Brandweerrooster password or token in YAML, GitHub issues or commits.

### License

MIT License.

### Support

If this integration saves you some time, you can [support me on Ko-fi](https://ko-fi.com/anonymouse0501). It's entirely optional, and the integration stays free either way.
