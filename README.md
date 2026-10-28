# Åpen data-showcase

Prototyper som kobler norske åpne data – kollektivtrafikk, vær, statistikk, næringsliv og kart – til **én kobling, ett mål og én beslutning** per produkt. Hvert produkt ligger i sin egen mappe, og felles kode ligger i `shared/`.

## Produkter

| Mappe | Produkt | Status |
|---|---|---|
| `01-mobilitetsatlas` | Mobilitetsatlas Norge (arbeidstittel): mobilitetsfrihet A–G for hele Norge | v0.1 «Kollektiv»: tre tidsvinduer for hele landet |
| `02-regnbyen` | Regnbyen: hvor mye flytter været syklingen? | Planlagt |
| `03-punktlig` | Punktlig: punktlighet og vær-stress i kollektivtrafikken | Loggeren samler data fra 23.10.2026, analyse og app gjenstår |
| `04-torrskodd` | Tørrskodd: gå nå eller vent – regn langs reisen | Planlagt |
| `05-norge-pa-n-timer` | Norge på N timer: hvor langt når du kollektivt? | Planlagt |
| `06-etableringskartet` | Etableringskartet: nedslagsfelt og konkurrenter | Planlagt |
| `07-uvaerskartet` | Uværskartet: hvem og hva rammes av farevarsler? | Planlagt |

Mobilitetsatlaset ligger på https://znuldre.github.io/aapen-data-showcase/ og virker på mobil, nettbrett og PC.

## Struktur

```
shared/            felles kode: TypeScript-SDK (@showcase/shared) og Python-pakke (showcase_shared)
01-…/              ett produkt per mappe, med egen pipeline, data og web-app
docs/research.md   miljøsjekk, API-notater, research og idékatalog
```

## Kom i gang

1. Kopier `.env.example` til `.env` og fyll inn `ENTUR_CLIENT_NAME` (formatet er `<organisasjon>-<applikasjon>`).
2. Installer Node-pakker: `npm install`
3. Lag Python-miljøet for pipelinene (Python 3.12 via [uv](https://docs.astral.sh/uv/)):
   ```
   uv venv --python 3.12 .venv
   uv pip install --python .venv/Scripts/python.exe -e "shared/python[test,routing]"
   ```
4. Installer en JDK 21 for r5py og sett `JAVA_HOME` i `.env`.

Se `01-mobilitetsatlas/README.md` for pipeline og web-app.

## Kilder og lisenser

| Kilde | Lisens |
|---|---|
| Entur (rutetabell, reiseplanlegger) | NLOD 2.0 |
| Statistisk sentralbyrå | CC BY 4.0 / NLOD 2.0 |
| Brønnøysundregistrene | NLOD 2.0 |
| Kartverket / Geonorge | CC BY 4.0 |
| Utdanningsdirektoratet (NSR, NBR) | NLOD 2.0 |
| OpenStreetMap | ODbL 1.0 |
| MET Norway / Yr | CC BY 4.0 + NLOD 2.0 |
| allemannsdata.com (MCP og REST) | Følger hver enkelt kilde |

Mobilitetsatlaset er inspirert av [Danmarks Mobilitetsatlas](https://mobilitetsatlas.dk/) (Beta Mobility, CC BY-SA 4.0).
