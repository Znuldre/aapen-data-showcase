"""Felles konfigurasjon for pipelinen til Mobilitetsatlas Norge.

Alle parametere som påvirker resultatene står her og dokumenteres i METODE.md.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# Windows-konsollen bruker cp1252 når utdata sendes videre; tving UTF-8 for æøå, ≈ og ²
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PRODUCT = Path(__file__).resolve().parents[1]
DATA = PRODUCT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
PUBLIC = PRODUCT / "web" / "public" / "data"
PROVENANCE_LOG = RAW / "proveniens.jsonl"

# Referansedager i rutetabellen: vanlig tirsdag og lørdag i november uten helligdager
REFERANSE_HVERDAG = dt.date(2026, 11, 10)
REFERANSE_LORDAG = dt.date(2026, 11, 14)

# Avgangsvinduer: medianreisetid over alle avgangsminutter i vinduet (DK-sammenlignbart: morgen)
TIDSVINDUER: dict[str, tuple[dt.date, dt.time, int]] = {
    "morgen": (REFERANSE_HVERDAG, dt.time(7, 0), 60),
    "kveld": (REFERANSE_HVERDAG, dt.time(19, 0), 60),
    "lordag": (REFERANSE_LORDAG, dt.time(10, 0), 60),
}
MAKS_REISETID = 90  # minutter, som i DK
# Gange er tilbringer til kollektiv (og direkte gange til nære mål): maks 15 min per etappe,
# 4,8 km/t (80 m/min, som TfL PTAL). Uten maks gangtid tillater R5 90 minutters gange,
# og kostnaden vokser med kvadratet av gangradiusen (holdeplasser per mål).
MAKS_GANGTID = 15
GANGHASTIGHET_KMT = 4.8

# R5 godtar maks 975 000 km² gatenett per nettverk. Norge deles i tre regioner; startrutene i
# kjernefylkene beregnes mot alle mål innenfor kjernen pluss en buffer, slik at reiser over
# regiongrensene innen 90 minutter kommer med.
REGIONER: dict[str, tuple[str, ...]] = {
    "sor": ("03", "11", "31", "32", "33", "34", "39", "40", "42", "46"),
    "midt": ("15", "50"),
    "nordland": ("18",),
    "nord": ("55", "56"),
}
REGION_BUFFER_KM = 150

# Hverdagsmål: vekt i kollektiv kvalitet, halveringstid for reisetidsvekten (min)
# og målet for full score (reisetidsvektet antall som gir 95 % metning)
KATEGORIER: dict[str, dict[str, float]] = {
    "jobber": {"vekt": 0.30, "halveringstid": 30, "maal": 100_000},
    "dagligvare": {"vekt": 0.15, "halveringstid": 10, "maal": 3},
    "skole": {"vekt": 0.15, "halveringstid": 15, "maal": 3},
    "barnehage": {"vekt": 0.10, "halveringstid": 10, "maal": 5},
    "helse": {"vekt": 0.15, "halveringstid": 20, "maal": 5},
    "tjenester": {"vekt": 0.15, "halveringstid": 20, "maal": 5},
}

# EUs «transport performance» (Poelman, Dijkstra & Ackermans 2020): befolkning nådd innen 30 min
# med kollektiv, delt på befolkning innen 7,5 km, for bysentre (DEGURBA på 1 km-rutenett)
TP_MAKS_REISETID = 30
TP_RADIUS_KM = 7.5
BYSENTER_TETTHET = 1500  # innbyggere per km²
BYSENTER_MIN_BEFOLKNING = 50_000

# Transportvalgfrihet skaleres ned når samlet normalisert rekkevidde (kollektiv + bil) er under
# denne verdien, slik at to like dårlige alternativer ikke ser ut som frihet. 1,0 betyr å nå målet
# i alle kategorier; 5 tilsvarer omtrent 25-persentilen i befolkningen (hverdag morgen, 2026).
LAV_SAMLET_REKKEVIDDE = 5.0

# Kollektivnivå: ulike avganger i timen innen gangavstand (500 m for buss og trikk, 1 km for
# tog, T-bane og båt, som i FNs bærekraftsmål 11.2.1). Nedre grenser for nivå 1–6.
GANGAVSTAND_LAV_KAPASITET = 500
GANGAVSTAND_HOY_KAPASITET = 1000
KOLLEKTIVNIVAA_GRENSER = (1, 2, 4, 8, 16, 32)
# «God tilgang» som i SSBs analyse fra 2024: minst én avgang i timen i snitt, her 07–19 på hverdag
GOD_TILGANG_VINDU = (REFERANSE_HVERDAG, dt.time(7, 0), 12 * 60)

KILDER: dict[str, dict[str, str]] = {
    "entur-gtfs": {
        "navn": "Entur – nasjonal rutetabell (GTFS)",
        "url": "https://storage.googleapis.com/marduk-production/outbound/gtfs/rb_norway-aggregated-gtfs.zip",
        "fil": "rb_norway-aggregated-gtfs.zip",
        "lisens": "NLOD 2.0",
    },
    "osm": {
        "navn": "OpenStreetMap Norge (Geofabrik)",
        "url": "https://download.geofabrik.de/europe/norway-latest.osm.pbf",
        "fil": "norway-latest.osm.pbf",
        "lisens": "ODbL 1.0",
    },
    "ssb-rutenett-250m": {
        "navn": "SSB – befolkning på rutenett 250 m, 2025",
        "url": "https://nedlasting.geonorge.no/geonorge/Befolkning/BefolkningsstatistikkRutenett250m2025/GML/Befolkning_0000_Norge_25833_BefolkningsstatistikkRutenett250m2025_GML.zip",
        "fil": "rutenett250m_2025.zip",
        "lisens": "NLOD 2.0 / CC BY 4.0 (SSB)",
    },
    "ssb-rutenett-1km": {
        "navn": "SSB – befolkning på rutenett 1 km, 2025",
        "url": "https://nedlasting.geonorge.no/geonorge/Befolkning/BefolkningsstatistikkRutenett1km2025/GML/Befolkning_0000_Norge_25833_BefolkningsstatistikkRutenett1km2025_GML.zip",
        "fil": "rutenett1km_2025.zip",
        "lisens": "NLOD 2.0 / CC BY 4.0 (SSB)",
    },
    "brreg-underenheter": {
        "navn": "Brønnøysundregistrene – alle underenheter (CSV)",
        "url": "https://data.brreg.no/enhetsregisteret/api/underenheter/lastned/csv",
        "fil": "underenheter.csv.gz",
        "lisens": "NLOD 2.0",
    },
    "kartverket-adresser": {
        "navn": "Kartverket – Matrikkelen adresser (CSV, EPSG:25833)",
        "url": "https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenAdresse/CSV/Basisdata_0000_Norge_25833_MatrikkelenAdresse_CSV.zip",
        "fil": "adresser_25833.zip",
        "lisens": "CC BY 4.0 (Kartverket)",
    },
}

GRUNNKRETSER_UUID = "51d279f8-e2be-4f5e-9f72-1a53f7535ec1"
KLASS_KOMMUNER = "https://data.ssb.no/api/klass/v1/classifications/131/codesAt?date=2026-01-01"
NSR_API = "https://data-nsr.udir.no/v4"
NBR_API = "https://data-nbr.udir.no/v4"
