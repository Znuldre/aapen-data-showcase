"""Lagring i Parquet: små staging-filer underveis, sammenslått til én fil per kilde og driftsdøgn.

Loggeren skriver ferske rader til staging/<kilde>/<dato>/<ms>.parquet. Sammenslåingen leser den
daglige filen og alle staging-filene, beholder raden med senest `observert` per stoppkall
(kilde, dato, tur_id, rekkefolge) og erstatter den daglige filen atomisk. Staging-filer slettes
først etterpå, så et avbrudd midt i gir i verste fall rader som slås sammen på nytt – aldri duplikater.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from collections import defaultdict
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger("punktlig")

TID = pa.timestamp("s", tz="UTC")
KOLONNER = [
    ("kilde", pa.string()),  # entur | banenor
    ("dato", pa.date32()),  # driftsdøgn
    ("datasett", pa.string()),  # Entur-kodeområde (RUT, VYG, …); BNR for Bane NOR
    ("operator", pa.string()),
    ("linje", pa.string()),  # Entur: RUT:Line:31; Bane NOR: L2, R21 (tom for godstog)
    ("linjenummer", pa.string()),  # det publikum ser: 31, L2, FLY1
    ("modus", pa.string()),  # bus, tram, metro, rail, water, coach, …
    ("kategori", pa.string()),  # Bane NOR: passengerTrain | freightTrain
    ("tur_id", pa.string()),  # Entur: ServiceJourney-ID; Bane NOR: tognummer
    ("retning", pa.string()),
    ("rekkefolge", pa.int16()),
    ("holdeplass", pa.string()),  # Entur: NSR:Quay:…; Bane NOR: stasjonskode
    ("holdeplass_navn", pa.string()),
    ("planlagt_ankomst", TID),
    ("planlagt_avgang", TID),
    ("forventet_ankomst", TID),  # siste prognose
    ("forventet_avgang", TID),
    ("faktisk_ankomst", TID),
    ("faktisk_avgang", TID),
    ("forsinkelse_ankomst_s", pa.int32()),  # (faktisk ellers forventet) − planlagt
    ("forsinkelse_avgang_s", pa.int32()),
    ("kansellert", pa.bool_()),
    ("registrert", pa.bool_()),  # kjøretøyet har passert (RecordedCall)
    ("ekstratur", pa.bool_()),
    ("observert", TID),  # når loggeren mottok denne versjonen
]
SKJEMA = pa.schema(KOLONNER)
NOKKEL = "kilde, dato, tur_id, rekkefolge"


def tabell(rader: list[tuple]) -> pa.Table:
    kolonner = list(zip(*rader))
    arrays = []
    for (navn, type_), verdier in zip(KOLONNER, kolonner):
        if type_ == pa.date32():
            arrays.append(pa.array([dt.date.fromisoformat(v) for v in verdier], type=type_))
        else:
            arrays.append(pa.array(verdier, type=type_))
    return pa.Table.from_arrays(arrays, schema=SKJEMA)


def _sql_liste(filer: list[Path]) -> str:
    return "[" + ", ".join("'" + p.as_posix().replace("'", "''") + "'" for p in filer) + "]"


class Lager:
    def __init__(self, stoppkall: Path, staging: Path, tmp: Path):
        self.stoppkall, self.staging, self.tmp = stoppkall, staging, tmp

    def skriv(self, kilde: str, rader: list[tuple]) -> int:
        """Skriver rader til én staging-fil per driftsdøgn. Returnerer antall rader."""
        per_dato: dict[str, list[tuple]] = defaultdict(list)
        for r in rader:
            per_dato[r[1]].append(r)
        for dato, rr in per_dato.items():
            mappe = self.staging / kilde / dato
            mappe.mkdir(parents=True, exist_ok=True)
            navn = f"{time.time_ns() // 1_000_000}.parquet"
            delvis = mappe / (navn + ".part")
            pq.write_table(tabell(rr), delvis, compression="zstd")
            os.replace(delvis, mappe / navn)
        return len(rader)

    def ventende(self) -> int:
        """Antall staging-filer som ikke er slått sammen ennå."""
        return sum(1 for _ in self.staging.glob("*/*/*.parquet")) if self.staging.exists() else 0

    def komprimer_alle(self) -> int:
        """Slår sammen all staging som venter. Returnerer antall rader i filene som ble skrevet."""
        totalt = 0
        if not self.staging.exists():
            return 0
        for kildemappe in sorted(p for p in self.staging.iterdir() if p.is_dir()):
            for datomappe in sorted(p for p in kildemappe.iterdir() if p.is_dir()):
                try:
                    totalt += self.komprimer(kildemappe.name, datomappe.name)
                except Exception:  # én feil skal ikke stoppe loggeren; staging blir liggende til neste forsøk
                    log.exception("Sammenslåing feilet for %s %s", kildemappe.name, datomappe.name)
        return totalt

    def komprimer(self, kilde: str, dato: str) -> int:
        mappe = self.staging / kilde / dato
        filer = sorted(mappe.glob("*.parquet"))
        if not filer:
            _fjern_tom(mappe)
            return 0
        maal = self.stoppkall / kilde / f"{dato}.parquet"
        maal.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)
        ny = maal.with_name(maal.name + ".ny")
        kilder = filer + ([maal] if maal.exists() else [])
        t0 = time.perf_counter()
        con = duckdb.connect(config={
            "threads": 1, "memory_limit": "512MB", "temp_directory": self.tmp.as_posix(),
            "preserve_insertion_order": False,
        })
        try:
            con.execute("SET enable_progress_bar = false")
            con.execute(f"""
                COPY (
                    SELECT * FROM read_parquet({_sql_liste(kilder)}, union_by_name = true)
                    QUALIFY row_number() OVER (PARTITION BY {NOKKEL} ORDER BY observert DESC) = 1
                    ORDER BY datasett, linje, tur_id, rekkefolge
                ) TO '{ny.as_posix()}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 200000)
            """)
            rader = con.execute(f"SELECT count(*) FROM read_parquet('{ny.as_posix()}')").fetchone()[0]
        finally:
            con.close()
        try:
            os.replace(ny, maal)
        except PermissionError:  # filen er åpen i en annen prosess (Windows); prøv igjen neste gang
            ny.unlink(missing_ok=True)
            log.warning("%s er i bruk; sammenslåing utsatt", maal.name)
            return 0
        for f in filer:
            try:
                f.unlink()
            except OSError:
                pass  # blir slått sammen på nytt neste gang, uten duplikater
        _fjern_tom(mappe)
        log.info("Slo sammen %s %s: %d staging-filer -> %d rader (%.1f MB) på %.1f s",
                 kilde, dato, len(filer), rader, maal.stat().st_size / 1e6, time.perf_counter() - t0)
        return rader


def _fjern_tom(mappe: Path) -> None:
    try:
        mappe.rmdir()
    except OSError:
        pass
