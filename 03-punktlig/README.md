# 03 – Punktlig

**Spørsmål:** Hvor punktlig er kollektivtrafikken per linje, holdeplass og time – og hvor mye flytter været punktligheten?

- **Kobling:** sanntidsdata fra Entur (alle operatører med sanntid) og Bane NOR (alle tog), senere vær fra MET.
- **Mål:** andel stoppkall innen 3 min (buss, trikk, T-bane, båt) og 5 min (tog), median og 90-persentil for forsinkelse, kanselleringer.
- **Beslutning:** hvor og når tiltak mot forsinkelser gir mest, og hvor sårbar trafikken er for vær.

## Status

v0.1, 23. oktober 2026: loggeren samler data **fra og med 23.10.2026 kl. 20:52**. Norge har ikke noe åpent historisk punktlighetsarkiv (Bane NOR publiserer bare månedlige PDF-er), og sanntidsdata kan ikke hentes i ettertid. Historikken vokser derfor bare mens loggeren kjører, og hull kan ikke fylles igjen.

Fra 24.10.2026 kl. 10:22 henter loggeren Enturs data som Avro i stedet for XML. Det gir de samme dataene for under en fjerdedel av nettverksbruken og en tredjedel av CPU-tiden (se [Nettverk og CPU](#nettverk-og-cpu)).

## Mappestruktur

```
logger/config.py               kilder, format, intervaller, stier og terskler (begrunnelsene står i kommentarene)
logger/logger.py               selve loggeren (hovedløkke, polling, pen avslutning)
logger/siri.py                 strømmende parser for SIRI ET i XML fra Entur og Bane NOR
logger/siri_avro.py            dekoder for Enturs SIRI ET i Avro, i ren Python
logger/SiriRecord.avsc         Avro-skjemaet Entur bruker (fra siri-avro-model)
logger/sammenlign_format.py    henter XML og Avro samtidig og sjekker at dataene er like
logger/tilstand.py             siste kjente tilstand per tur og hvilke stoppkall som er klare til lagring
logger/lager.py                Parquet: staging underveis, sammenslått til én fil per kilde og døgn
logger/linjer.py               linjeregister (modus, linjenummer, navn) fra Entur Journey Planner
logger/kontroll.py             punktlighet per linje siste time
logger/start.ps1               start i bakgrunnen
logger/stopp.ps1               pen stopp
tests/                         tester for parsere, Avro-dekoder, XML-reserve, tilstand og sammenslåing (pytest, uten nettverk)
data/                          innsamlede data, logg og status (gitignored)
```

Testene kjøres med `.venv/Scripts/python.exe -I -m pytest 03-punktlig/tests`.

## Starte og stoppe

Alt kjøres fra prosjektroten og bruker Python-miljøet i `.venv` (se rot-README). Loggeren trenger bare `ENTUR_CLIENT_NAME` i rot-`.env`.

```
powershell -ExecutionPolicy Bypass -File 03-punktlig\logger\start.ps1
powershell -ExecutionPolicy Bypass -File 03-punktlig\logger\stopp.ps1
.venv/Scripts/python.exe -I 03-punktlig/logger/kontroll.py
```

- `start.ps1` starter loggeren i et skjult vindu og venter til den har skrevet `data/logger.pid`. Den nekter å starte en loggerinstans nummer to. Det samme gjør loggeren selv, med en fillås.
- `stopp.ps1` lager `data/logger.stopp`. Loggeren lagrer det som er avklart, slår sammen staging og avslutter, normalt i løpet av noen sekunder. Svarer den ikke innen 3 minutter, blir prosessen avsluttet, og staging slås sammen ved neste start.
- I forgrunnen: `.venv/Scripts/python.exe -I 03-punktlig/logger/logger.py` (Ctrl+C avslutter pent). `--en-runde` henter én gang fra hver kilde, lagrer og avslutter.
- Loggeren starter ikke av seg selv etter omstart av maskinen. Vil du det, kan `start.ps1` legges inn som en planlagt oppgave ved pålogging, for eksempel med `schtasks /Create /TN Punktlig-logger /SC ONLOGON /TR "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File <full sti>\03-punktlig\logger\start.ps1"`.
- Status: `kontroll.py` viser først om loggeren kjører, når hver kilde sist svarte, i hvilket format, hvor mye som er hentet og hvor mye CPU hvert kall bruker. Detaljene står i `data/logger.log` (roteres ved 5 MB) og `data/status.json`.
- Format: Entur hentes som Avro (`ENTUR_FORMAT` i `config.py`, sett `"xml"` for å gå tilbake). Har svaret et annet skjemafingeravtrykk enn `SiriRecord.avsc`, henter loggeren samme runde som XML og bruker XML i 6 timer før den prøver Avro igjen (`ENTUR_AVRO_PAUSE`). Det står i loggen og i `kontroll.py`. Svarer Entur med XML selv om loggeren ber om Avro, leses XML-en. Har Entur endret skjemaet, lager du ny `SiriRecord.avsc` fra [siri-avro-model](https://github.com/entur/siri-avro-model) (for eksempel med `avro-tools idl2schemata` på `src/main/avro`). Kjør så `.venv/Scripts/python.exe -I 03-punktlig/logger/sammenlign_format.py`, som henter begge formatene samtidig og sjekker at dataene er like.

Loggeren kan stoppes og startes når som helst. Den fortsetter uten duplikater: hvert stoppkall har en nøkkel, og sammenslåingen beholder siste versjon. Turer som blir ferdige mens loggeren står, mangler i dataene.

## Kilder

Verifisert 23.–24. oktober 2026. Alle kall til Entur sender `ET-Client-Name` fra `.env`.

| Kilde | Endepunkt | Hva vi bruker | Hentes | Lisens |
|---|---|---|---|---|
| Entur sanntid, SIRI Lite ET | `https://api.entur.io/realtime/v1/rest/et?maxSize=50000` med `Accept: application/avro` | alle turer med sanntid i hele landet: planlagte, forventede og faktiske tider per stopp, kanselleringer | hvert 7,5 min (7–37 MB Avro, tilsvarer 27–157 MB XML) | NLOD 2.0 |
| Bane NOR SIRI ET | `https://siri.banenor.no/jbv/et/EstimatedTimetable.xml?PreviewInterval=PT30M` | alle tog som går nå eller starter innen 30 min, også godstog, med faktiske tider målt i infrastrukturen | hvert 3. min (≈ 1,6 MB) | NLOD (Bane NOR) |
| Entur Journey Planner v3 | `https://api.entur.io/journey-planner/v3/graphql` (`lines`) | modus, linjenummer og navn for ≈ 4 700 linjer | én gang i døgnet | NLOD 2.0 |

Navngivelse: «Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Entur og Bane NOR.»

### Det vi fant ut, og som styrer oppsettet

- **Enturs SIRI Lite ET er ukomprimert.** GTFS-RT kommer gzip-et, men SIRI-svarene gjør ikke det, verken som XML, JSON eller Avro. Hvert kall gir hele landet, også kommende turer, og størrelsen følger trafikken gjennom døgnet: fra ≈ 2 900 turer og 27 MB XML kl. 04 til ≈ 11 100 turer og 157 MB XML kl. 10 (fredag–lørdag 23.–24.10). `previewIntervalMinutes` og `excludedDatasetIds` ignoreres av det offentlige endepunktet, så flyene fra Avinor (AVI) filtreres bort lokalt.
- **Avro gir de samme dataene for under en fjerdedel av nettverket.** Med `Accept: application/avro` er svaret 23,8–23,9 % av XML-størrelsen for samme øyeblikk (tre målinger lørdag formiddag, 36–38 MB mot 150–159 MB). Formatet er Avros «single-object encoding»: `C3 01`, 8 byte fingeravtrykk av skjemaet (CRC-64-AVRO av skjemaets kanoniske form) og så én `SiriRecord`. Skjemaet er `SiriRecord` fra Enturs [siri-avro-model](https://github.com/entur/siri-avro-model), og fingeravtrykket av IDL-en der (`dda132770abb5f30`) stemmer med svarene. Tider er UTC-strenger (`…Z`), og koder står med store bokstaver (`CANCELLED`, `RAIL`). `siri_avro.py` dekoder det i ren Python uten ekstra pakker.
- **Avro bygger på SIRI 2.1, XML-svaret på SIRI 2.0.** Den eneste forskjellen som betyr noe her: registrerte kall (`RecordedCall`) har `ArrivalStatus` og `DepartureStatus` bare i Avro. I et øyeblikksbilde hadde 17 av 29 448 registrerte kall `CANCELLED`, alle med faktiske tider og `Cancellation` usann. Dekoderen ser bort fra status i registrerte kall, slik at dataene blir som med XML. `Extensions`, som bare finnes i XML, inneholder hos Entur bare `StopsAtAirport`.
- **XML og Avro gir identiske data.** `sammenlign_format.py` henter begge formatene med 0,2 sekunders mellomrom og sammenligner turene parserne gir. Kl. 09:51, 10:10 og 10:30 lørdag var det 10 272, 10 663 og 11 367 turer med 249 632, 256 023 og 263 967 stoppkall. Alle turnøkler, linjer, tider og kanselleringer var like, unntatt i 9, 7 og 7 turer som Entur hadde oppdatert mellom de to uttrekkene. Det var nøyaktig de turene som hadde ulik `RecordedAtTime` i de to svarene.
- **Inkrementelle kall med `requestorId` lønner seg ikke.** Entur glemmer økten etter mindre enn 3 minutter uten kall, og med ett kall i minuttet kommer ≈ 1 600 endrede turer per kall (≈ 28 MB). Det blir ≈ 1,7 GB i timen, mot ≈ 650 MB med et fullt uttrekk hvert 7,5. minutt (målt med XML fredag kveld).
- **Ferdige turer blir liggende i ≈ 10 minutter** etter siste stopp hos Entur (median 5 og 90 % innen 9,5 min i et øyeblikksbilde). Hvert 7,5. minutt fanger derfor siste kjente tilstand for alle turer. Hos Bane NOR blir ferdige tog liggende i minst 15 minutter.
- **Bane NORs `PreviewInterval` virker.** `PT30M` gir 1,6 MB mot 10 MB uten filter, og alle tog som allerede går er med. Svaret er ikke komprimert.
- **GTFS-RT dugde ikke som hovedkilde.** Trip updates (1,1 MB gzip for hele landet) har bare forsinkelse, ikke planlagt tid, og skiller ikke faktiske tider fra prognoser. Skyss mangler helt, og Ruter ser ut til å være kappet ved 1 000 turer.
- **Kvoter:** SIRI Lite tillater 5 kall i minuttet per `ET-Client-Name` (`rate-limit-allowed: 5`) og ett kall per 100 ms (`spike-arrest-allowed`). Loggeren bruker 8 kall i timen.
- **Kildene stemmer med hverandre.** Første kveld var det 208 stoppkall på 57 tog med samme tognummer og rutetid i begge kildene. Ankomstforsinkelsen hos Entur (VYG) og Bane NOR avvek med median 0 s, og 98 % lå innen 30 s.
- **Intervallet mister ikke sluttilstander.** For turer som ble ferdige første kveld, er siste stopp registrert som passert for 90–97 % av turene hos Ruter, Skyss, AtB, Kolumbus, FRAM og Agder. Det er minst like høyt som for ferdige turer i et enkelt øyeblikksbilde av feeden. Der siste stopp mangler, er det fordi operatøren ikke melder det: Østfold registrerer det nesten aldri, og Bane NOR lar det ofte bli stående som prognose.

### Dekning

Første driftskveld kom det sanntid fra 22 av Enturs kodeområder: Ruter (RUT), Skyss (SKY), VOT (Vestfold), Kolumbus (KOL), AtB (ATB), Agder Kollektivtrafikk (AKT), FRAM (MOR), Svipper (TRO), Innlandstrafikk (INN), Brakar (BRA), Nordland fylkeskommune (NOR), Østfold kollektivtrafikk (OST), Vy (VYG), Snelandia (FIN), Flybussen Connect (NBU), Bane NOR (BNR), FlixBus (FLI), Go-Ahead (GOA), Flytoget (FLT), Torghatten Sør (BFO), Fjord Line (FJL) og Farte (TEL). For de store bussoperatørene har 93–100 % av stoppkallene faktisk tid. Holdeplassnavn mangler i feeden for blant annet SKY, AKT, TRO, BRA, NOR, OST, FIN og NBU, men NSR-ID-en er alltid med.

## Datamodell

Én rad per **stoppkall**, altså en turs besøk på en holdeplass, med siste kjente verdi. Nøkkelen er `(kilde, dato, tur_id, rekkefolge)`. Tider er UTC.

| Kolonne | Type | Innhold |
|---|---|---|
| `kilde` | tekst | `entur` eller `banenor` |
| `dato` | dato | driftsdøgnet turen tilhører (nattruter etter midnatt hører til dagen før) |
| `datasett` | tekst | Enturs kodeområde (RUT, SKY, ATB, VYG …); `BNR` for Bane NOR |
| `operator` | tekst | operatør (Entur: `RUT:Operator:210`; Bane NOR: `VY`, `GAG`, `SJN`, `CN` …) |
| `linje` | tekst | Entur: `RUT:Line:31`; Bane NOR: `L2`, `R21` (tom for godstog) |
| `linjenummer` | tekst | det publikum ser: `31`, `5`, `L2`, `FLY1` |
| `modus` | tekst | `bus`, `tram`, `metro`, `rail`, `water`, `coach` … (feedens VehicleMode, ellers linjeregisteret) |
| `kategori` | tekst | Bane NOR: `passengerTrain` eller `freightTrain`; tom for Entur |
| `tur_id` | tekst | Entur: ServiceJourney-ID (samme som `trip_id` i GTFS); Bane NOR: tognummer |
| `retning` | tekst | DirectionRef |
| `rekkefolge` | heltall | stoppets nummer i turen (Entur: Order; Bane NOR: posisjon) |
| `holdeplass` | tekst | Entur: NSR-quay (`NSR:Quay:10508`); Bane NOR: stasjonskode (`OSL`) |
| `holdeplass_navn` | tekst | navnet i feeden (mangler for noen Entur-operatører, blant annet Skyss) |
| `planlagt_ankomst`, `planlagt_avgang` | tidspunkt | rutetid |
| `forventet_ankomst`, `forventet_avgang` | tidspunkt | siste prognose |
| `faktisk_ankomst`, `faktisk_avgang` | tidspunkt | målt tid, når kilden har den |
| `forsinkelse_ankomst_s`, `forsinkelse_avgang_s` | heltall | (faktisk, ellers forventet) − planlagt, i sekunder |
| `kansellert` | sann/usann | stoppet eller hele turen er innstilt |
| `registrert` | sann/usann | kjøretøyet har passert (RecordedCall i SIRI) |
| `ekstratur` | sann/usann | turen er ikke i ruteplanen (for eksempel buss for tog) |
| `observert` | tidspunkt | når loggeren mottok denne versjonen |

Regler:

- Et stoppkall lagres når det er **avklart**: kjøretøyet har passert, eller beste kjente tid ligger mer enn 2 minutter bak oss. Prognoser for stopp som ennå ikke er passert, lagres ikke. Endres et lagret stoppkall senere, lagres det på nytt, og sammenslåingen beholder raden med senest `observert`.
- Noen operatører sender aldri registrerte kall. Da er `faktisk_*` tom, og forsinkelsen bygger på siste prognose. `kontroll.py` viser hvor stor andel som har faktisk tid.
- Kildedataene har enkelte meningsløse verdier (for eksempel −70 timer). Analyser bør se bort fra forsinkelser over ±3 timer, slik `kontroll.py` gjør.
- Tog finnes i begge kildene: VYG, FLT, GOA og BNR hos Entur bygger på Bane NORs data. Bruk Bane NOR for tog (stasjonskoder, godstog og målte tider fra infrastrukturen) og Entur for resten, slik `kontroll.py` gjør som standard.
- Bare turer med sanntid er med. Linjer uten sanntid hos operatøren finnes ikke i dataene.

## Lagring

```
data/stoppkall/<kilde>/<dato>.parquet          én fil per kilde og driftsdøgn (zstd), én rad per stoppkall
data/staging/<kilde>/<dato>/<ms>.parquet        ferske rader, skrives hvert 2. minutt, slås sammen hver time
data/ref/linjer.parquet                         linjeregisteret
data/logger.log, status.json, logger.pid       logg, status og prosess-ID
```

Les alt med DuckDB, for eksempel `SELECT * FROM read_parquet('03-punktlig/data/stoppkall/*/*.parquet', union_by_name = true)`. Ta med `data/staging/*/*/*.parquet` for den siste timen, og behold raden med senest `observert` per nøkkel.

**Anslått lagringsbehov: ≈ 20–25 MB per døgn, under 10 GB i året.** Målt fredag 23.10 kl. 20:55–21:55 kom det 50 600 stoppkall fra Entur (3 318 turer) og 970 fra Bane NOR (179 tog). I de ferdige daglige filene tar en rad 13,5 byte (Entur) og 23 byte (Bane NOR). Antar vi at kveldstimen har 3–4 % av døgnets trafikk, blir et hverdagsdøgn 1,3–1,7 millioner stoppkall. Andelen er ikke målt, så anslaget bør sjekkes mot det første hele døgnet. Staging-filene slettes ved hver sammenslåing, og loggen roteres ved 5 MB (høyst 20 MB).

### Nettverk og CPU

Enturs uttrekk står for nesten alt nettverksbruket, og størrelsen følger trafikken gjennom døgnet. Med XML var det 7,5 GB fra fredag 20:52 til lørdag 10:20 (109 uttrekk), fra 27 MB per uttrekk kl. 04 til 157 MB kl. 10. Timene 11–19 ble aldri hentet som XML, så tallet for et helt døgn er et anslag: 17–19 GB med XML, ikke 14–15 GB som først antatt. Avro er ≈ 24 % av XML for samme øyeblikk, og det samme døgnet blir 4–4,5 GB. Bane NOR bruker ≈ 0,7 GB per døgn. `kontroll.py` viser målt snitt per kall siden start og et døgnanslag ut fra det. Vil du ned, kan du øke `ENTUR_INTERVALL` i `config.py`. Over ≈ 9 minutter mister du ferdige turer.

CPU per Entur-uttrekk ble målt lørdag 24.10 kl. 10–10:20, med 10 700–11 100 turer (154–158 MB XML, 37 MB Avro) og loggerens lave prioritet (BELOW_NORMAL). «Full maskin» er 16 travle prosesser med normal prioritet, én per logisk kjerne, slik R5 belaster maskinen. Hver måling kjørte i egen prosess.

| Per uttrekk | XML | Avro |
|---|---|---|
| Parsing, rolig maskin | 1,58 CPU-s | 0,58 CPU-s |
| Hele uttrekket (nedlasting, parsing, tilstand), rolig maskin | 2,20 CPU-s på 15,6 s | 0,78 CPU-s på 5,3 s |
| Parsing, full maskin | 2,77 CPU-s på 218 s | 0,95 CPU-s på 76 s |
| Hele uttrekket, full maskin | 24,6 s nedlasting og 91,9 s parsing¹ | 0,91 CPU-s på 24 s |

¹ Driftsloggerens uttrekk kl. 10:18–10:20, mens lastmålingen pågikk. CPU-tiden ble ikke logget før byttet.

Avro-dekoderen er ren Python, men bruker en tredjedel av CPU-tiden til XML-parseren, og nedlastingen koster også mindre. På full maskin får loggeren bare restene av CPU-en: parsingen tar da 1–4 minutter i stedet for 1–2 sekunder, og samme arbeid koster 60–75 % flere CPU-sekunder (hyperthreading og lavere klokkefrekvens). Veggtiden under last varierer mye fra gang til gang, fordi loggeren bare kommer til når Windows løfter en utsultet tråd. CPU-tiden er det stabile målet. Hele loggeren brukte 10 CPU-sekunder i timen med Avro, målt lørdag kl. 10:29–10:58 med fire Entur-uttrekk på 0,77–0,86 CPU-s hver. Timens sammenslåing (noen sekunder) kommer i tillegg. Loggeren logger CPU-tiden for hvert uttrekk, og `kontroll.py` viser snittet. Med ≈ 12 000 turer i minnet brukte den 193 MB minne, med en topp på 273 MB. Et Avro-svar holdes helt i minnet mens det leses (inntil ≈ 40 MB, et øyeblikk), mens XML leses strømmende. Loggeren kjører med lav prioritet (BELOW_NORMAL), så lange beregninger som R5 i `01-mobilitetsatlas` ikke merker den. Bare sammenslåingen (noen sekunder i timen, én tråd) får normal prioritet, fordi DuckDB sulter helt ut på lav prioritet når CPU-en er full: 10–14 s mot 0,6 s for en triviell spørring.

## Kontrollskriptet

`kontroll.py` regner punktlighet for vinduet 70–10 minutter før nå. Vinduet slutter 10 minutter før nå fordi et stoppkall lagres først når det er passert. Punktlig betyr forsinkelse innen 3 min for buss, trikk, T-bane, båt og øvrige moduser, og innen 5 min for tog. Tog måles på ankomst, alt annet på avgang. Kansellerte stopp telles for seg, og godstog holdes utenfor. Valg: `--kilde entur|banenor`, `--modus metro,tram`, `--datasett RUT`, `--linje 5`, `--minutter 120`, `--topp 30`, `--godstog`.

Første fullt observerte time, fredag 23. oktober (utdrag):

```
Punktlighet 23.10 20:53–21:53 (60 min, slutter 10 min før nå). Punktlig: tog innen 5 min, øvrige innen 3 min.
Tog fra Bane NOR, øvrige moduser fra Entur. Godstog er holdt utenfor.

Kilde    Modus        Linjer  Stoppkall  Punktlige For tidlig  Median     P90 Kansellert Faktisk tid
entur    buss            574     46 724     71,2 %      2,5 %   +1:47   +5:31        304      96,0 %
entur    T-bane            5      1 316     98,6 %      0,0 %   +0:36   +1:56          0      93,7 %
entur    trikk             7      1 212     76,6 %      0,3 %   +1:37   +4:05          0      96,1 %
banenor  tog              28        964     54,3 %      2,3 %   +4:01  +21:08        304      52,4 %
entur    båt             130        519     87,1 %      6,0 %   +0:20   +4:01         15      70,9 %

Per linje (inntil 5 per modus med minst 20 stoppkall, flest kall først):
Kilde    Modus         Linje Hvem     Navn                                     Kall  Punktlige  Median     P90 Kans.
banenor  tog              L1 VY       Spikkestad-Oslo S-Lillestrøm              210     58,6 %   +3:08  +35:04   124
banenor  tog              L2 VY       Stabekk-Oslo S-Ski                        124     25,9 %  +12:57  +46:27    57
banenor  tog              L5 GAG      Jærbanen                                   61     96,7 %   +2:00   +4:02     0
entur    T-bane            5 RUT      Sognsvann - Vestli                        344     99,7 %   +0:54   +2:05     0
entur    trikk            12 RUT      Kjelsås - Majorstuen o/ løkka og Aker     243     78,2 %   +1:49   +3:51     0
```

Togene var preget av omfattende forstyrrelser rundt Oslo S den kvelden (Bane NORs avviksfeed hadde 242 avvik der). Enturs togdata viste det samme: L1 hadde 11,9 % punktlige og 89 innstilte stopp mellom 19:48 og 20:48.

Den første timen etter at loggeren er startet, er tallene skjeve. Første uttrekk inneholder bare turer som fortsatt går eller nettopp er ferdige, og forsinkede turer blir værende lenger. De blir derfor overrepresentert, og punktligheten ser for dårlig ut til loggeren har gått en time.

## Veien videre

- Vær: koble timesobservasjoner fra MET (Frost) ved nærmeste stasjon til hver holdeplass, og se på punktlighet mot nedbør, snø, vind og temperatur.
- Holdeplasser: koordinater og navn fra Nasjonalt stoppestedsregister (NSR) for kart og for operatører som mangler navn i feeden.
- Aggregater per linje, holdeplass og time som DuckDB-visninger eller små Parquet-filer for en web-app.
