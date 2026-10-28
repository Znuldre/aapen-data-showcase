# Research og beslutningsgrunnlag

Sammendrag av miljøsjekken, API-gjennomgangen og researchen som ligger bak porteføljen (oktober 2026).

## Ledetråd

Research viste at Norge har mange tjenester som bruker én kilde (Yr, hvakosterstrommen.no, Sjekktrafikken, Varsom, Proff, Finn Nabolag), men nesten ingen som **kobler** transport, vær, demografi og næringsliv på fin geografi. Hver prototype skal derfor ha **én kobling, ett mål og én beslutning** – ikke bare flere lag på et kart.

## Miljøsjekk

- **Maskin:** Node 24, npm 11, Python 3.14 (pipelines bruker 3.12 via uv), git 2.52, Temurin JDK 21. 31 GB RAM, 16 tråder.
- **MCP:** 74 av 75 allemannsdata-servere svarer (remote, uten nøkler). `norgesbank` feilet. Røyktestet: Entur, MET, Frost, SSB, BRREG, Geonorge, NVE naturfare, NGU og Vegvesen.
- **Allemannsdata REST:** `https://allemannsdata.com/wiki/api/v1/kilder/{kilde}/{operasjon}?…` gir hver MCP-operasjon som åpen JSON (77 kilder, CORS `*`, uten nøkkel).
- **Fallgruver:**
  - BRREG bruker SN2025-koder (restaurant = `56.110`, dagligvare = `47.110`).
  - `firmafakta.finn_selskaper_i_omrade` plasserer bedrifter på postnummerets midtpunkt.
  - Varsom-snøskredvarsel publiseres først fra desember.

## Entur

- Ingen nøkkel, men `ET-Client-Name: <organisasjon>-<applikasjon>` er påkrevd i alle kall (også WebSocket). Lisens NLOD.
- CORS `*` på Journey Planner, Geocoder, Mobility, Vehicle Positions og Stop Place. Kvotene gjelder per klientnavn (Journey Planner: 500 reisesøk i minuttet).
- Journey Planner v3: gange, sykkel, bil og utleiesykkel/-sparkesykkel, med etappegeometri, høydeprofil og CO₂ per etappe. Ikke noe isokron- eller mange-til-mange-API.
- Vehicle Positions: WebSocket-abonnement (`graphql-transport-ws`) med forsinkelse, retning og belegg.
- Emissions Calculator (beta) sammenligner transportformer i ett kall.
- Geocoder v1/v2 ble utfaset 12.06.2026; bruk v3.
- «prdudisapi» (takstavstander) og Timetable Import Info har lav verdi for sluttbrukere.
- Nattlig nasjonal GTFS (≈ 540 MB) og NeTEx. Åpen historikk for sanntidsdata er ikke bekreftet.

## MET / Yr

- Identifiserende `User-Agent` med kontaktinfo, maks 4 desimaler, respekter `Expires` og `If-Modified-Since`. Over 20 kall i sekundet krever avtale. Lisens CC BY 4.0 + NLOD.
- Vilkårene ber nettlesere gå via en cachende proxy, og localhost-opphav kan bli strupet.
- Nowcast 2.0 (5 min, to timer), MetAlerts 2.0, Sunrise 3.0, Oceanforecast og Textforecast.
- `tiles.yr.no` (beta) har kartfliser for radar/nowcast, nedbør, temperatur, vind og skydekke (CORS `*`).
- Widgets: `https://www.yr.no/nb/innhold/{id}/{meteogram.svg|table.html|card.html}`.

## Kart og geodata

- Bakgrunnskart: OpenFreeMap (vektor, uten nøkkel) og Kartverket topo/gråtone (`cache.kartverket.no`, CC BY 4.0).
- Terreng: Mapterhorn (Kartverket 1 m DTM).
- Grenser: Kartverket Kommuneinfo og Geonorge grunnkretser. SSB KLASS 131 har 357 kommuner per 1.1.2026.
- SSB befolkning på rutenett: 250 m (totalt) og 1 km (kjønn og snittalder), siste årgang 1.1.2025.

## Research: eksisterende produkter

- **Norge og Norden (23 gjennomgått):** nærmest kommer Oslo Live (stablede lag via allemannsdata), Movai.no (Entur + Yr, tidlig fase) og SSBs analyse av kollektivtilgang fra 2024 (1 av 4 husholdninger mangler godt tilbud). Ingen kuraterer en levende showcase.
- **Internasjonalt (20 gjennomgått), sju mønstre:**
  1. ett spørsmål, ett kart (Chronotrains, PTAL)
  2. et personlig tall (Walk Score)
  3. logg strømmen og «selg fortiden» (Rijden de Treinen)
  4. spill av en dag
  5. fusjon av to kilder til én beslutning
  6. profilsider med sammenligning mot nivået over
  7. eie kilden og åpne resultatet
- **AI + åpne data (15 gjennomgått):** synlig, verifisert spørring mot API-er virker (IMF StatGPT, Data Commons, data.gouv.fr MCP). Frie chatboter feiler (NYC MyCity). Ikke valgt i første runde.
- **HuggingFace:** lite strukturert norsk data. Nyttigst: én dag med Entur-posisjoner (`knuthp/entur_vm`), vegbilder med embeddings og norske modeller (nb-whisper, nb-sbert, NorMistral).
- **Danmarks Mobilitetsatlas (Beta Mobility):** mobilitetsfrihet = 0,5 × kollektiv kvalitet + 0,5 × transportvalgfrihet, med A–G per punkt. Vekter, kurvekonstant og terskler er ikke publisert.

## Idékatalog

| Idé | Status |
|---|---|
| Mobilitetsatlas Norge (Kollektivnivå som første tema) | Valgt – produkt 01 |
| Regnbyen, Punktlig, Tørrskodd, Norge på N timer, Etableringskartet, Uværskartet | Valgt – produkt 02–07 |
| Spør Norge (kildesporet AI-agent) | Ikke valgt i første runde |
| Stedsrøntgen, Kommer jeg over fjellet?, Norge i bevegelse, Solsøkeren | Nedprioritert |
