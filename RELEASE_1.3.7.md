# Brandweerrooster API v1.3.7

## Fix: authoritative assigned personnel

- The crew/personnel list is now explicitly derived only from `incident_skill_assignments`.
- `incident_responses` is used only as an enrichment lookup for people who are already assigned.
- A response record can no longer add a person to the crew or determine their function.
- Added stable operational role ordering: Bevelvoerder, Chauffeur, Manschappen, Aspirant, then other/custom skills.
- Kept the API diagnostic sensor from 1.3.6 for verification.
- No API endpoint or authentication behavior was changed.

## Expected result for incident 3010161

- Bevelvoerder: Peter Beckers
- Chauffeur: Thijs Smeets
- Manschappen: Kevin Senssen, Mike Richter, Jordy Rijks, Twan Schoenmakers
- Aspirant: Luuk Tummers
