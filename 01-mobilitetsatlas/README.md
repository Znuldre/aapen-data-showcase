# 01 – Mobilitetsatlas Norge (arbeidstittel)

**Spørsmål:** Hvor fritt kan du dekke hverdagens behov uten bil – og hvor godt konkurrerer kollektivtilbudet med bilen?

- **Kobling:** reisetider med kollektiv og bil (Entur + OpenStreetMap), befolkning på 250 m-rutenett (SSB) og hverdagsmål (BRREG og Udir).
- **Mål:** mobilitetsfrihet A–G per 250 m-rute, grunnkrets, kommune og fylke.
- **Beslutning:** hvor kollektivtilbudet bør styrkes, og for hvem.

Strukturen følger [Danmarks Mobilitetsatlas](https://mobilitetsatlas.dk/) (Beta Mobility), med norske tilpasninger. Se [METODE.md](METODE.md).

## Status

v0.1 «Kollektiv», oktober 2026. Alle tre tidsvinduene er beregnet for hele landet og vises i appen: hverdag 07–08, hverdag 19–20 og lørdag 10–11.

## Hovedtall, hverdag 07–08

- **Norge samlet:** mobilitetsfrihet 51,2 (C). Kollektiv kvalitet er 70,9 og transportvalgfrihet 31,4. Gini mellom rutene er 0,28.
- **Befolkningen per karakter (DK-skala):** A 32 %, B 23 %, C 10 %, D 11 %, E 5 %, F 5 % og G 14 %.
- **Kommunene:** 6 av 357 får A: Oslo 75,9, Stavanger 74,4, Trondheim 74,3, Bergen 73,2, Bærum 72,5 og Lørenskog 71,0. 151 kommuner får G, og de fleste av dem er små distriktskommuner.
- **God tilgang (SSB-definisjon):** 80 % av befolkningen. SSBs analyse fra 2024 fant 75 % av husholdningene.
- **EUs transport performance:** Stavanger 37 %, Trondheim 32 %, Bergen 31 %, Oslo 28 % og Sandnes 28 %.

Om kvelden og på lørdag faller Norge samlet til 44,1 (D) og 44,0 (D). I snitt har folk 24 ulike avganger i timen nær der de bor om morgenen, 15 om kvelden og 13 på lørdag.

Kontrollene står i METODE.md. Rutenettet dekker 99,85 % av befolkningen, og 8 av 10 reisetider fra R5 ligger innenfor ±10 % av Entur Journey Planner.

## Mappestruktur

```
pipeline/   steg 01–07 (Python) og config.py med alle parametere
data/raw    nedlastede kilder (gitignored), med proveniens.jsonl
data/cache  mellomresultater (gitignored)
web/        Vite + React + MapLibre; data eksporteres til web/public/data
METODE.md   full metodebeskrivelse, vises også i appen
```

## Kjøre pipelinen

Krav: Python 3.12-miljøet i `.venv` (se rot-README) og en JDK 21 med `JAVA_HOME` satt i `.env`. Kjør alt fra prosjektroten, slik at stiene til libosmium blir ASCII.

```
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/01_hent.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/02_mal.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/03_opphav.py
```

Reisetider beregnes per region (`sor`, `midt`, `nordland`, `nord`). For hver region kjøres kollektiv for hvert tidsvindu (`morgen`, `kveld`, `lordag`) og bil én gang:

```
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/04_reisetider.py --region sor --modus kollektiv --vindu morgen
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/04_reisetider.py --region sor --modus bil
```

`04_alle.py` kjører alle regioner og vinduer i riktig rekkefølge, hopper over ferdige kjøringer og logger til `data/cache/logg/`:

```
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/04_alle.py
```

Steg 4 lagrer hver batch for seg og fortsetter der det slapp hvis det avbrytes. På en Ryzen 7 9800X3D (16 tråder, 31 GB RAM) tar ett kollektivvindu for hele landet 6,5–8 timer, og Sør-Norge står for nesten alt. Bil tar 1 t 45 min. Deretter:

```
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/05_indikatorer.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/06_eksport.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/07_sjekk.py --entur
```

`07_sjekk.py` sammenligner med SSB-totalene, og med `--entur` også med Entur Journey Planner.

## Kjøre web-appen

```
npm install
npm run dev:atlas
```

Åpne http://localhost:5173. Live-avganger i «ditt tall» krever `ENTUR_CLIENT_NAME` i `.env`.
