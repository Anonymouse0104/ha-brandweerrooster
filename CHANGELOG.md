# Changelog

## 1.5.2

### No more "unknown" before the first alarm
- **Laatste alarmering** and **Laatste uitruk** now show text: `16-10-2026 14:32`, or *Nog geen alarmering* / *Nog geen uitruk*. The exact time is in the attribute `tijdstip`.
- **Afstand tot incident** now shows text: `4,2 km`, *Geen incident* or *Geen locatie bekend*. The number is in the attribute `km`.
- **Bezetting compleet** is off while there is no incident. A new attribute `status` shows *Compleet*, *Niet compleet* or *Geen incident*.
- **Opkomstpercentage dit jaar** shows 0 % until the first alarm.
- The **Locatie laatste incident** map entity was removed. It was always unavailable without coordinates. *Laatste incident* has `latitude`/`longitude`, so a map card can show that sensor instead (see `examples/map_latest_incident.yaml`). The old entity, and a leftover *API diagnose laatste incident* entity, are removed automatically.

Automations that used *Laatste alarmering*, *Laatste uitruk* or *Afstand tot incident* as a time or number should now use their `tijdstip` or `km` attribute.

## 1.5.1

### Standby duty: the Piketdienst switch
- Functions set to *Standby duty* get a **Piketdienst** switch.
  - Turn it on while you have duty. An alarm for this function then counts as a turnout, unless you explicitly rejected it or were registered as no-show.
  - Not responding in time (`expired`) does not matter.
- Brandweerrooster's `on_duty` flag is no longer used. It reflects your volunteer availability, so it can't tell whether you are the OvD on duty.
- The on/off periods are stored, so the nightly and full history syncs use the same rule. Alarms from before you first used the switch are not counted.
- The event data of standby functions contains `piketdienst`.
- Functions that confirm their turnout in the app are unchanged.

### Own corrections
- Every function gets **Correctie uitrukken totaal** and **Correctie uitrukken dit jaar** (number fields), to add turnouts from another system or correct an over-count. Negative values are allowed.
- The year correction goes back to 0 on 1 January.
- The corrections also count in *Uitrukken totaal (alle functies)*.
- *Uitrukken totaal* and *Uitrukken dit jaar* show `geteld` and `correctie` as attributes.

## 1.5.0

### Functions: one account, several roles
- Every role is now a **function** (for example *OvD West* and *TS Echt*). Add one with **Add function** on the integration page.
- Each function has its own groups and tasks, way of counting turnouts and minimum crew size.
- Each function gets its own device with its own entities: latest incident, *Nieuw incident* event, crew, crew complete, dispatch message, map location and statistics. You can automate per function.
- An incident that matches several functions appears in each of them. The new account sensor **Uitrukken totaal (alle functies)** counts each incident once.
- The event data and `brandweerrooster.generate_message` include the function (`functie`).
- The blueprints let you pick one or more functions.
- The account device holds *API beschikbaar*, *Gebruiker*, *Incident verversen* and *Statistieken opnieuw synchroniseren*.

### Vehicle names from Brandbase
- Call signs in the P2000 alert (`235331` = `23-5331`) are looked up on Brandbase and shown as short names such as `TST Echt`, `HV Echt` or `OvD`.
- Brandbase is queried politely: only regions from your own incidents, at most once a week per region, 15 seconds between requests, cached across restarts.
- *Own vehicle names* in Configure are now optional exceptions, and they take precedence over Brandbase.
- Numbers without a name are listed in `onbekende_voertuignummers`.

### Upgrade
- Your existing setup is converted automatically into one function.
  - Entity IDs, history and statistics stay the same.
  - The account entities move to a new account device.
  - An untouched built-in vehicle list is replaced by Brandbase; a changed list is kept as your own exceptions.
- Requires Home Assistant 2025.8 or newer (unchanged). Also compatible with the device registry changes in Home Assistant 2026.x.

## 1.4.3

### New
- **How is a turnout counted?** (setup and Configure):
  - *Turnout confirmed in the app* (default, crew members).
  - *Standby duty* for OvD and other standby duties that don't confirm their turnout in the app: every alarm received while on duty counts as a turnout, unless declined. The function comes from the assignment or the skills on your response.
  - Changing the setting rebuilds the statistics automatically.
- `historie_samenvatting` lists the status combinations of your responses (`jouw_statussen`). Download diagnostics shows how recorded incidents were counted.

### Fixes
- `historie_samenvatting` now refreshes while the sync runs (it stayed on the first value).

## 1.4.2

### Fixes
- History sync stopped after the first page. The API returns at most 50 incidents per page, and a page with fewer items than requested was treated as the last one. The sync now continues until an empty page. Accounts that can see incidents of many groups (e.g. an OvD) now get their full history.
- `historie_samenvatting` updates after every page, so progress is visible while the sync runs.

After updating, press **Statistieken opnieuw synchroniseren** once.

## 1.4.1

### Fixes
- A response was not recognised as a turnout while Brandweerrooster still had `reported_status: unknown`, which is the case until attendance is filled in afterwards. The alarm response (`status`: `acknowledged`, `rejected`, `expired`) is now used until the attendance (`dispatched`, `shown_up`, `no_show`) is known. *Mijn opkomst* shows the same effective status.
- History sync now fetches incident details when the incident list does not include responses or group/task ids, instead of skipping those incidents.

### New
- *Uitrukken totaal* has a `historie_samenvatting` attribute that explains the last history sync: incidents seen, relevant, with your response, and a few group/task ids of skipped incidents. The same information is in **Download diagnostics**.
- *Laatste incident* `adres` also uses the API `address` object.

After updating, press **Statistieken opnieuw synchroniseren** once.

## 1.4.0

Requires Home Assistant 2025.8 or newer.

### Everything in the UI
- New **options flow**: change station, groups, tasks, FireServiceRota sensor, minimum crew size, the Facebook template and vehicle names without removing the integration.
- The Facebook template is edited in the UI. A customised `/config/brandweerrooster/facebook_template.yaml` is imported once; the file is no longer used.
- Vehicle names (P2000 number → name) are configurable in the UI instead of hard-coded for Limburg-Noord.
- **Re-authentication flow**: when the password changes Home Assistant asks for the new one instead of failing.
- The FireServiceRota incident sensor is selectable; a **Repair** issue appears when it is missing.

### Reliability fixes
- Statistics were deleted when an incident could only be shown from FireServiceRota data (e.g. during a rate-limit). Fallback data never changes statistics anymore.
- Month/year counters now roll over at midnight instead of on the next incident.
- Incident timestamps are converted to local time, so incidents around midnight at the end of a month count in the right month.
- *API beschikbaar* now reflects the actual last API call (it was always on).
- Crew enrichment runs for up to 20 minutes on a slowing schedule (was 25 seconds) and stops once the data is complete and stable.
- A nightly catch-up picks up incidents missed while Home Assistant was offline.
- The history sync pauses on rate-limits and resumes automatically (honours `Retry-After`), with throttling between detail requests.
- Incidents the account cannot see (HTTP 4xx) are ignored instead of shown from fallback data; incidents for other stations are not fetched again on every FireServiceRota update.
- Concurrent requests refresh an expired token only once; server errors are no longer reported as invalid credentials.
- `fireservicerota` is declared as `after_dependencies`, so it loads first.

### New
- Sensors: *Laatste alarmering*, *Afstand tot incident*, *Uitrukken vorige maand*, *Opkomstpercentage dit jaar*, *Laatste uitruk*.
- Binary sensor *Bezetting compleet* (commander + driver + minimum crew size).
- `geo_location` entity so the incident appears on the map.
- Buttons *Incident verversen* and *Statistieken opnieuw synchroniseren*.
- Actions `brandweerrooster.generate_message` (returns the message), `refresh_incident`, `resync_statistics`.
- Statistics per function, category, classification and time of day; declined alarms are recorded for the response rate. Existing installations re-sync history once in the background to fill these.
- Event data now includes `classificatie`, `categorie`, `bericht` and `afstand_km`.
- `{categorie}` template placeholder.
- Three automation blueprints installed automatically: notification, night alarm, dispatch message to phone.
- Download diagnostics (redacted) replaces the *API diagnose laatste incident* sensor.

### Privacy
- Crew names and response lists are excluded from the recorder database.
- The user sensor no longer exposes e-mail, phone or other personal fields.

### Other
- Entity names are translated (Dutch/English); existing entity IDs are unchanged.
- Uses `entry.runtime_data`, a shared base entity and an explicit coordinator config entry.
- Test suite (pytest-homeassistant-custom-component) added and run in CI.
- Individual `RELEASE_*.md` files replaced by this changelog.

### Breaking changes
- The *API diagnose laatste incident* sensor was removed; use **Download diagnostics**. You can delete the orphaned entity.
- The unused event type `other_incident` was removed.
- *Ingezet personeel* now counts unique people (a person with two functions counts once).

## 1.3.9
- Fixed migration of the built-in Facebook template so existing default installations get the `{classificatie}` heading.

## 1.3.8
- New `{classificatie}` placeholder (e.g. `Woningbrand`, `Buitenbrand`).

## 1.3.7
- Assigned crew is derived only from `incident_skill_assignments`; responses only enrich assigned people. Stable role ordering.

## 1.3.5 / 1.3.4 / 1.3.3
- Config-entry-only schema, manifest ordering, brand assets, HACS and Hassfest workflows.

## 1.3.2
- Short retry window to pick up crew assignments after a new incident.

## 1.3.1
- Picks up the current incident when FireServiceRota loads after this integration.

## 1.3.0
- Event entity for new incidents; latitude/longitude on the latest incident.

## 1.2.0
- Configurable Facebook dispatch template.

## 1.1.9
- The public station name no longer uses the config-entry title.
