# v1.1.8

## Fix: kazerne als afzender en rate-limit fallback

Deze release lost twee problemen op:

- Het gegenereerde uitrukbericht gebruikt de geselecteerde Brandweerrooster-hoofdgroep als kazerne. Bijvoorbeeld `Echt TS` wordt `Brandweer Echt uitgerukt`. Dit is generiek en werkt voor andere kazernes.
- Wanneer Brandweerrooster tijdelijk rate-limited is, gebruikt de integratie de actuele gegevens van `sensor.incidents` als fallback. Hierdoor verschijnt niet onnodig `Geen uitruk`.

### GitHub commit

```text
fix: use station name and keep incident during API rate limits
```
