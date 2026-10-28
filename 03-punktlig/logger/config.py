"""Parametere for Punktlig-loggeren: kilder, pollefrekvens, stier og punktlighetsterskler."""

from __future__ import annotations

from pathlib import Path

PRODUKT = Path(__file__).resolve().parents[1]  # 03-punktlig/
DATA = PRODUKT / "data"
STOPPKALL = DATA / "stoppkall"  # daglige Parquet-filer: stoppkall/<kilde>/<dato>.parquet
STAGING = DATA / "staging"  # ferske rader før sammenslåing: staging/<kilde>/<dato>/<ms>.parquet
REF = DATA / "ref"
LINJER = REF / "linjer.parquet"
TMP = DATA / "tmp"  # DuckDB kan skrive mellomresultater hit ved sammenslåing
LOGG = DATA / "logger.log"
STATUS = DATA / "status.json"
LAAS = DATA / "logger.lock"
PID = DATA / "logger.pid"
STOPPFIL = DATA / "logger.stopp"  # finnes filen, avslutter loggeren pent (se stopp.ps1)

# Entur: SIRI Lite ET sendes ukomprimert, og hvert kall gir hele landet: 28–150 MB XML etter tid på
# døgnet (≈ 2 900–10 300 turer, også kommende turer resten av døgnet). Inkrementelle kall med
# requestorId lønner seg ikke: Entur glemmer økten etter under 3 min uten kall, og ett kall i minuttet
# ga ≈ 28 MB XML hver gang (fredag kveld: ≈ 1,7 GB/t mot ≈ 650 MB/t med fulle uttrekk). Ferdige turer
# ligger i ≈ 10 min etter siste stopp, så et fullt uttrekk hvert 7,5. minutt fanger siste kjente
# tilstand for alle turer. previewIntervalMinutes og excludedDatasetIds ignoreres av det offentlige
# endepunktet (testet oktober 2026).
ENTUR_ET = "https://api.entur.io/realtime/v1/rest/et"
ENTUR_JP = "https://api.entur.io/journey-planner/v3/graphql"
ENTUR_INTERVALL = 450  # sekunder; grensen er 5 kall i minuttet per ET-Client-Name
ENTUR_MAKS = 50_000  # maxSize; uten den kuttes svaret ved 1 500 turer
ENTUR_UTELAT = {"AVI"}  # Avinor (fly) er ikke kollektivtrafikk her; filtreres bort lokalt

# Format for Enturs uttrekk: "avro" eller "xml". Avro (Accept: application/avro) er ≈ 24 % av
# XML-størrelsen for samme øyeblikk og gir de samme dataene (siri_avro.py, målt oktober 2026).
# Dekoderen er ren Python og bruker en tredjedel av CPU-tiden til XML-parseren. Har svaret et annet
# skjemafingeravtrykk enn SiriRecord.avsc, hentes samme runde som XML, og XML brukes deretter i
# ENTUR_AVRO_PAUSE sekunder før Avro prøves igjen.
ENTUR_FORMAT = "avro"
ENTUR_AVRO_PAUSE = 6 * 3600

# Bane NOR: hele svaret hentes hver gang. PreviewInterval tar med tog som går nå og tog som
# starter innen 30 min (≈ 1,6 MB mot ≈ 10 MB uten filter). Ferdige tog ligger i svaret i
# minst ≈ 15 min, så hvert 3. minutt fanger siste faktiske ankomst med god margin.
BANENOR_ET = "https://siri.banenor.no/jbv/et/EstimatedTimetable.xml"
BANENOR_INTERVALL = 180
BANENOR_FORHANDSVISNING = "PT30M"

SVEIP_INTERVALL = 60  # hvor ofte avklarte stoppkall plukkes ut for lagring
SKRIV_INTERVALL = 120  # hvor ofte ferske rader skrives til staging
KOMPRIMER_INTERVALL = 3600  # hvor ofte staging slås sammen til daglige filer
LINJER_INTERVALL = 24 * 3600  # linjeregisteret (modus og linjenummer) hentes på nytt hvert døgn
AVKLART_ETTER = 120  # et stoppkall regnes som passert 2 min etter beste kjente tid
GLEM_FERDIG_ETTER = 1800  # ferdige turer slippes fra minnet etter 30 min uten oppdatering
GLEM_ETTER = 6 * 3600  # turer som ikke har vært med i et svar på 6 timer, slippes uansett

# Punktlighet: andel stoppkall innen terskelen (sekunder forsinket)
TERSKEL_TOG = 300
TERSKEL_ANNET = 180
