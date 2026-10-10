# Lovac na akcije — internetska baza

Obrada javnih službenih cjenika Plodina, Eurospina, Lidla, SPAR-a, Studenca, Tommyja i Konzuma za podržane poslovnice u Istri. Paket je izvor podataka za zasebnu Android aplikaciju. Uključuju se samo poslovnice iz službenih datoteka: Studenac trenutačno Buzet i Funtana, Tommy Tar/Pula/Rovinj, Konzum dnevni paginirani popis za Istru. To nije popis svih fizičkih trgovina.

## Aktivacija

1. Postavi ove datoteke u novi GitHub repozitorij na grani `main`.
2. U Settings → Pages odaberi Build and deployment → Source → GitHub Actions.
3. U Actions pokreni Dnevno osvjezavanje cijena → Run workflow.
4. Nakon uspješne objave otvori Pages adresu i provjeri `manifest.json` i `status.json`.
5. U Android aplikaciji pod Izvor podataka spremi punu HTTPS adresu manifesta.

GitHub Pages na besplatnom planu traži javni repozitorij. Kod obrade u ovom paketu tada je javno vidljiv. Android projekt nije dio paketa. Izvorni CSV arhivi i cijela SQLite baza ne spremaju se u Git povijest; Actions objavljuje pripremljenu bazu i status u Pages artefaktu.

## Dnevno ažuriranje

Naredba `python cloud-run.py` prvo provjeri izvore, izradi kompletan katalog i provjeri SHA-256, raspakiravanje i SQLite integritet. Neuspjeli lanci zadržavaju posljednji ispravan cjenik iz cachea. Kod prvog pokretanja svi podržani lanci moraju imati ispravan cjenik. Ako priprema zakaže, korak objave se ne izvršava pa postojeća Pages objava ostaje.

Raspored je 08:17 UTC, odnosno 10:17 ljeti i 09:17 zimi u Hrvatskoj. GitHub može odgoditi raspored; javnim repozitorijima bez aktivnosti 60 dana isključuje zakazane workflowe. Provjeri Actions i po potrebi ponovno uključi raspored. To nije servis s jamstvom dostupnosti. Za pouzdano stalno pokretanje može se kasnije prijeći na VPS.

Cache čuva samo aktivne CSV cjenike i do tri posljednje komprimirane baze. GitHub može ukloniti cache; tada je potrebno ponovno uspješno preuzeti sve podržane izvore. Nikad se ne objavljuje nepotpuna početna baza. Status pojedinog lanca i stvarni datum cjenika dostupni su u `status.json`.

## Lokalna provjera

Potrebni su Python 3.14 i standardna knjižnica, bez dodatnih paketa:

```
python -m unittest test_osvjezi.py test_hosting.py test_trgovci.py test_usporedba.py
python cloud-run.py
```

Dokumentacija: https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
Raspored: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
