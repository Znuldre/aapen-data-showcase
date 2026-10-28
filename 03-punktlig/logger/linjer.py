"""Linjeregister fra Entur Journey Planner: modus, linjenummer og navn per linje.

Enturs SIRI ET har VehicleMode bare for noen operatører (Ruter mangler det helt), så modus og
linjenummer fylles fra registeret. Hele landet er ≈ 4 700 linjer i ett GraphQL-kall (≈ 0,1 MB).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests

log = logging.getLogger("punktlig")

SPORRING = "{ lines { id publicCode name transportMode transportSubmode authority { name } } }"
SKJEMA = pa.schema([
    ("linje", pa.string()), ("linjenummer", pa.string()), ("navn", pa.string()),
    ("modus", pa.string()), ("undermodus", pa.string()), ("myndighet", pa.string()),
    ("hentet", pa.timestamp("s", tz="UTC")),
])


def hent(url: str, okt: requests.Session) -> pa.Table:
    r = okt.post(url, json={"query": SPORRING}, timeout=60)
    r.raise_for_status()
    svar = r.json()
    if "errors" in svar:
        raise RuntimeError(f"Journey Planner svarte med feil: {svar['errors'][:1]}")
    linjer = svar["data"]["lines"]
    naa = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    return pa.Table.from_pylist([{
        "linje": l["id"], "linjenummer": l.get("publicCode"), "navn": l.get("name"),
        "modus": l.get("transportMode"), "undermodus": l.get("transportSubmode"),
        "myndighet": (l.get("authority") or {}).get("name"), "hentet": naa,
    } for l in linjer], schema=SKJEMA)


class Linjeregister:
    def __init__(self, sti: Path, url: str, okt: requests.Session):
        self.sti, self.url, self.okt = sti, url, okt
        self.linjer: dict[str, tuple[str | None, str | None]] = {}  # linje -> (linjenummer, modus)
        self.hentet = 0.0

    def oppdater(self, maks_alder: float) -> None:
        """Henter registeret på nytt hvis filen er eldre enn `maks_alder` sekunder; ellers leses filen."""
        try:
            alder = time.time() - self.sti.stat().st_mtime if self.sti.exists() else float("inf")
            if alder > maks_alder:
                tabell = hent(self.url, self.okt)
                self.sti.parent.mkdir(parents=True, exist_ok=True)
                delvis = self.sti.with_name(self.sti.name + ".part")
                pq.write_table(tabell, delvis, compression="zstd")
                os.replace(delvis, self.sti)
                log.info("Linjeregister hentet: %d linjer", tabell.num_rows)
            else:
                tabell = pq.read_table(self.sti)
            d = tabell.to_pydict()
            self.linjer = {
                l: (n, m) for l, n, m in zip(d["linje"], d["linjenummer"], d["modus"])
            }
            self.hentet = time.time()
        except Exception:  # loggeren klarer seg uten registeret; modus fylles da bare fra feeden
            log.exception("Kunne ikke oppdatere linjeregisteret")
            self.hentet = time.time() - maks_alder + 3600  # nytt forsøk om en time

    def fyll(self, tur) -> None:
        """Fyller modus og linjenummer på en Entur-tur der feeden mangler dem."""
        if tur.linje and (tur.modus is None or tur.linjenummer is None):
            nummer, modus = self.linjer.get(tur.linje, (None, None))
            tur.linjenummer = tur.linjenummer or nummer
            tur.modus = tur.modus or modus
