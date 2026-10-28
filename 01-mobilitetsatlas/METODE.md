# Metode – Mobilitetsatlas Norge v0.1

Atlaset måler **mobilitetsfrihet**: hvor fritt man kan dekke hverdagens behov med kollektivtransport, og hvor godt kollektivtilbudet konkurrerer med bil. Hver befolket 250 m-rute i Norge får en score fra 0 til 100 og en karakter fra A til G. Tall for grunnkretser, kommuner, fylker og hele landet er befolkningsvektede snitt av rutene.

Strukturen følger [Danmarks Mobilitetsatlas](https://mobilitetsatlas.dk/metode) (Beta Mobility). Danmarks atlas publiserer ikke vekter, kurvekonstant eller terskler, så alle parametere her er våre egne. Alle står i denne beskrivelsen og i `pipeline/config.py`.

## Formelen i korte trekk

| Del | Formel |
|---|---|
| Reisetidsvekt | w(t) = 0,5^(t / h) for t ≤ 90 min, ellers 0. h er halveringstiden for kategorien |
| Rekkevidde per kategori | R_k = Σ (antall mål i målruten) · w(reisetid) |
| Metning | s_k = 1 − e^(−3 · R_k / M_k), som gir 0,95 når R_k når målet M_k |
| **Kollektiv kvalitet (KK)** | 100 · Σ v_k · s_k (kollektiv) |
| Normalisert rekkevidde | N = Σ v_k · R_k / M_k (uten metning), for kollektiv og bil |
| **Transportvalgfrihet (TV)** | 100 · min(1, 2 · N_kollektiv / (N_kollektiv + N_bil)) · min(1, (N_kollektiv + N_bil) / 5) |
| **Mobilitetsfrihet (MF)** | 0,5 · KK + 0,5 · TV |

TV er den danske formelen 1 − (bil − kollektiv) / (bil + kollektiv), skrevet om. Den gir 100 når kollektiv når like mye som bil, og 0 når kollektiv ikke når noe. Siste ledd skalerer ned scoren der selv bilen når lite, slik at to like dårlige alternativer ikke ser ut som frihet.

Terskelen 5 betyr at kollektiv og bil til sammen når fem ganger målet for full score. Det tilsvarer omtrent den fjerdedelen av befolkningen med lavest samlet rekkevidde. Den første versjonen brukte 0,5. Da fikk små, avsidesliggende tettsteder høy transportvalgfrihet, fordi bilen der når nesten ikke mer enn det man når til fots:

| Sted | Mobilitetsfrihet med 0,5 | Med 5 |
|---|---|---|
| Karasjok sentrum | 58 (B) | 25 (E) |
| Hasvik | 56 (B) | 22 (F) |

Byene påvirkes ikke.

## Romlig enhet

- **Startpunkter:** SSBs befolkning på 250 m-rutenett per 1.1.2025, med 224 761 befolkede ruter og 5 585 868 innbyggere. Reisen starter i rutens midtpunkt.
- **Kommune og grunnkrets:** satt fra Kartverkets adresseregister (flest adresser i ruten avgjør). Ruter uten adresser får grunnkretsen som inneholder midtpunktet.
- **Til sammenligning:** Danmarks atlas bruker ca. 75 000 punkter og DSTs 100 m-grid.

## Hverdagsmål

Seks kategorier. Danmark har fem; barnehage er et norsk tillegg. Arbeidsplasser, dagligvare, helse og tjenester hentes fra Enhetsregisteret, slik at alle mål kommer fra offentlige registre.

| Kategori | Kilde og definisjon | Vekt | Halveringstid | Mål for full score |
|---|---|---|---|---|
| Arbeidsplasser | BRREG-underenheter, antall ansatte | 30 % | 30 min | 100 000 |
| Dagligvare | BRREG SN2025 `47.110`, ett sted per adresse | 15 % | 10 min | 3 |
| Skoler | Udir NSR: aktive grunnskoler og videregående | 15 % | 15 min | 3 |
| Barnehager | Udir NBR: aktive barnehager | 10 % | 10 min | 5 |
| Helse | BRREG SN2025 `86.210` allmennlege, `47.730` apotek, `86.101` sykehus, `86.942` helsestasjon; ett sted per adresse og kode | 15 % | 20 min | 5 |
| Tjenester | BRREG SN2025 `91.111` folkebibliotek og `84.300` NAV-kontor (navn som starter med «NAV») | 15 % | 20 min | 5 |

«Mål for full score» er reisetidsvektet antall. Tre dagligvarebutikker rett utenfor døren gir altså nesten full score for dagligvare. Det samme gjør flere butikker som ligger lenger unna.

**Geokoding av BRREG-adresser** mot Kartverkets adresseregister:

| Treff | Andel enheter | Andel ansatte |
|---|---|---|
| Gate + husnummer + bokstav | 94,8 % | 91,1 % |
| Gate + husnummer | 1,2 % | 2,9 % |
| Postnummerets midtpunkt | 4,1 % | 5,9 % |

1 155 enheter fikk ingen treff. 96 % av skolene og 95 % av barnehagene har koordinater i Udirs registre. De øvrige er ikke med i v0.1.

Samlet antall arbeidsplasser (3,39 mill.) er høyere enn SSBs sysselsettingstall. BRREG teller arbeidsforhold per underenhet, og én person kan ha flere.

## Reisetider

- **Motor:** r5py 1.1.7 (Conveyal R5 v7.5.1) med Enturs nasjonale GTFS og OpenStreetMap (Geofabrik).
- **Kollektiv:** gange som tilbringer. Vi bruker medianreisetiden over alle avgangsminutter i et vindu på 60 minutter, ikke ett enkelt avgangstidspunkt.
- **Gange:** maks 15 minutter per gangetappe (ca. 1,2 km), med 4,8 km/t (80 m/min, som TfL PTAL). Uten en slik grense tillater R5 opptil 90 minutter gange, og da ville gange telle som kollektivtilgang. Mål innen 15 minutters gange regnes også med direkte, uten kollektiv.
- **Bil:** R5s bilmodus på OSM-veinettet, uten kø og uten svingrestriksjoner. Det gjør bilen litt raskere enn i virkeligheten.
- **Maks reisetid:** 90 minutter for begge, som i Danmark.
- **Referansedager:** tirsdag 10.11.2026 og lørdag 14.11.2026.

| Tidsvindu | Avganger |
|---|---|
| Hverdag morgen (sammenlignbart med Danmark) | 07:00–08:00 |
| Hverdag kveld | 19:00–20:00 |
| Lørdag | 10:00–11:00 |

### Regioner

R5 godtar et gatenett på maks 975 000 km², mens Norge er om lag dobbelt så stort. Beregningen kjøres derfor i fire regioner. Hver region dekker kjernefylkene og en buffer på 150 km, slik at reiser over regiongrensene innen 90 minutter kommer med.

| Region | Kjernefylker |
|---|---|
| Sør | Oslo, Rogaland, Østfold, Akershus, Buskerud, Innlandet, Vestfold, Telemark, Agder, Vestland |
| Midt | Møre og Romsdal, Trøndelag |
| Nordland | Nordland |
| Nord | Troms, Finnmark |

**OSM:** regionene klippes ut med alle veier, ferjestrekninger og plattformer som overlapper området.

**GTFS:** vi beholder turene som går på referansedagene. Fly er tatt ut, fordi R5 ikke regner med innsjekking. Stopp utenfor regionen fjernes, og turer som krysser grensen kuttes der. Tomme `transfer_type`-felt tolkes som 0 (anbefalt overgang), slik GTFS-spesifikasjonen sier.

## Skalaer

- **DK-skala** (som Danmarks Mobilitetsatlas): A 70–100, B 55–70, C 45–55, D 30–45, E 22–30, F 15–22, G 0–15. En score lik en grense får den høyeste karakteren.
- **NO-skala:** grensene er befolkningsvektede persentiler av morgen-MF i Norge, ved 85, 70, 50, 30, 15 og 5 %.
  - A er de 15 % med høyest mobilitetsfrihet, og G er de 5 % med lavest.
  - Samme grenser brukes for alle tidsvinduer, slik at kveld og lørdag kan sammenlignes med morgen.
  - Skalaen viser hvordan nordmenn har det sammenlignet med hverandre. DK-skalaen viser hvordan vi har det sammenlignet med Danmark.

Kollektiv kvalitet og transportvalgfrihet vises alltid med DK-grensene som leseguide.

## Støtteindikatorer

### Kollektivnivå

Antall ulike turer i timen fra holdeplasser innen gangavstand. Gangavstanden er 500 m for buss og trikk og 1 km for tog, T-bane og båt, som i FNs bærekraftsmål 11.2.1. Avstanden er målt i luftlinje fra rutens midtpunkt.

| Nivå | Avganger i timen |
|---|---|
| 0 | ingen |
| 1 | 1 |
| 2 | 2–3 |
| 3 | 4–7 |
| 4 | 8–15 |
| 5 | 16–31 |
| 6 | 32 eller flere |

### God tilgang (SSB-definisjon)

Minst én avgang i timen i snitt 07–19 på hverdag, fra en holdeplass innen 500 m (eller 1 km for tog, T-bane og båt). Definisjonen er nær SSBs analyse fra 2024, som fant at én av fire husholdninger mangler godt kollektivtilbud. Analysene er likevel ikke identiske. SSB måler husholdninger, mens vi måler personer på 250 m-rutenett.

### EUs «transport performance»

Metoden følger EU-kommisjonen (Poelman, Dijkstra & Ackermans 2020). For hver 1 km-rute i et bysenter regner vi befolkningen som nås innen 30 minutter med kollektiv og gange (median, hverdag 07–08). Den deles på befolkningen som bor innen 7,5 km i luftlinje. Bysenteret får et befolkningsvektet snitt.

Bysentre er definert etter EUs DEGURBA på SSBs 1 km-rutenett:
- sammenhengende ruter (kant mot kant) med minst 1 500 innbyggere per km²
- minst 50 000 innbyggere til sammen
- hull fylles ved at ruter med minst fem av åtte naboer i klyngen legges til

Det gir fem bysentre: Oslo, Trondheim, Bergen, Stavanger og Sandnes. Bergen blir lite fordi fjell og fjorder deler opp de tette rutene. EUs egne tall bruker samme definisjon, så tallene kan sammenlignes med europeiske byer.

### Ulikhet

Vi beregner befolkningsvektet Gini-koeffisient og Lorenzkurve for morgen-MF i hver kommune, etter Delbosc & Currie (2011). Gini 0 betyr at alle har samme mobilitetsfrihet.

## Kontroller

| Kontroll | Resultat |
|---|---|
| Befolkning i rutenettet mot SSB (tabell 06913, 1.1.2025) | 5 585 868 av 5 594 340 (99,85 %) |
| Andel uten god tilgang mot SSBs analyse fra 2024 | Norge 20 % (SSB 25 % av husholdningene), Oslo 0,3 % (SSB 1 %), Innlandet 39 % (SSB 48 %) |
| Reisetid fra R5 mot Entur Journey Planner, 10 reiser kl. 07–08 | 8 av 10 innenfor ±10 %. Oslo S–Lillestrøm +33 % og Grünerløkka–Majorstuen −26 % |
| Arbeidsplasser i BRREG | 3,39 mill. (0,61 per innbygger) |
| Stikkprøver, mobilitetsfrihet hverdag morgen | Oslo S 89,3 (A), Bergen sentrum 86,5 (A), Trondheim torg 85,0 (A), Tromsø sentrum 84,9 (A), Lillehammer 68,6 (B), Lom 27,3 (E), Karasjok 25,1 (E), Hasvik 21,9 (F) |
| Reproduserbarhet | En batch regnet på nytt gir nøyaktig samme rekkevidde som første kjøring |

Atlaset finner færre uten god tilgang enn SSB. Én grunn er at vi teller personer og ikke husholdninger. En annen er at gangavstanden måles i luftlinje fra rutens midtpunkt.

Entur sammenlignes med medianen av tidligste ankomst for avreise hvert tiende minutt fra 07:00 til 07:50. R5 bruker medianen over alle avgangsminutter fra 07:00 til 08:00. Avvikene kommer hovedsakelig av ganghastighet, gangveier og hvilke linjer som er raskest for akkurat de tidspunktene.

## Forskjeller fra Danmarks Mobilitetsatlas

- Alle parametere er publisert.
- Oppløsningen er 250 m-ruter for hele landet.
- Det er tre tidsvinduer i stedet for ett.
- Barnehage er med som eget mål.
- Hverdagsmålene kommer fra offentlige registre (BRREG, Udir) i stedet for OpenStreetMap.
- Ferjer inngår i rutetabellen, og fly er tatt ut.
- Det finnes to skalaer: en for sammenligning med Danmark og en kalibrert for Norge.

## Begrensninger

- **Gange:** Gangreiser følger gatenettet, men ikke terrenget. Bakker gjør reisene i praksis lengre, særlig i Bergen og Ålesund. Terreng er planlagt i v0.2.
- **Bil:** Bil regnes uten kø og uten svingrestriksjoner.
- **Rutetabell:** Reisetidene bygger på planlagt rutetabell, ikke sanntid. Pålitelighet kommer som eget tema fra produktet *Punktlig*.
- **Lokalisering:** BRREG-adressen er der foretaket er registrert, ikke nødvendigvis der arbeidet utføres.
- **Avgrensning av kategorier:**
  - Helse omfatter allmennleger, apotek, somatiske sykehus og helsestasjoner, men ikke legevakt som egen kategori.
  - NAV-kontor er avgrenset på navn, så enkelte interne NAV-enheter kan komme med.
- **Lisens:** Lisensen for nedlastbare data er ikke endelig avklart. Gatenettet er fra OSM (ODbL).

## Slik reproduserer du tallene

Kjør fra prosjektroten med Python 3.12-miljøet (`.venv`) og JDK 21:

```
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/01_hent.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/02_mal.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/03_opphav.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/04_reisetider.py --region sor --modus kollektiv --vindu morgen
(… for hver region, kollektiv per vindu og bil)
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/05_indikatorer.py
.venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/06_eksport.py
```

Alle nedlastinger logges med kilde, lisens, tidspunkt og SHA-256 i `data/raw/proveniens.jsonl`. Listen vises på siden «Data og kilder».

## Kilder

- **Entur:** nasjonal rutetabell (GTFS), NLOD 2.0. Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Entur AS.
- **Statistisk sentralbyrå:** befolkning på rutenett 2025 og KLASS-kodelister, CC BY 4.0.
- **Brønnøysundregistrene:** Enhetsregisteret, underenheter, NLOD 2.0.
- **Kartverket / Geonorge:** Matrikkelen adresser og statistiske enheter (grunnkretser), CC BY 4.0.
- **Utdanningsdirektoratet:** Nasjonalt skoleregister og Nasjonalt barnehageregister, NLOD 2.0.
- **OpenStreetMap-bidragsytere:** gatenett, ODbL 1.0.
- **Metodegrunnlag:**
  - Hansen (1959) om tilgjengelighet
  - Danmarks Mobilitetsatlas (Beta Mobility, 2026)
  - UN-Habitat, SDG 11.2.1
  - Delbosc & Currie (2011) om Lorenzkurver for kollektivtransport
