"""Steg 1: henter alle kilder og logger proveniens (kilde, lisens, dato og sjekksum).

Kjøres fra prosjektroten:  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/01_hent.py
Filer som allerede finnes, lastes ikke ned på nytt, men proveniensen logges likevel.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# -I tar bort skriptmappen fra sys.path; legg til pipeline-mappen (vår egen kode) eksplisitt
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

from config import GRUNNKRETSER_UUID, KILDER, KLASS_KOMMUNER, NBR_API, NSR_API, PROVENANCE_LOG, RAW  # noqa: E402
from showcase_shared.provenance import download  # noqa: E402


def hent_filer() -> None:
    for key, kilde in KILDER.items():
        download(kilde["url"], RAW / key / kilde["fil"], log=PROVENANCE_LOG, source=kilde["navn"], license=kilde["lisens"])


def hent_grunnkretser() -> None:
    """Geonorge leverer grunnkretsene via en bestilling som returnerer en nedlastingslenke."""
    dest = RAW / "grunnkretser" / "grunnkretser_25833_geojson.zip"
    url = "https://nedlasting.geonorge.no/api/order"
    if not dest.exists():
        order = {
            "orderLines": [{
                "metadataUuid": GRUNNKRETSER_UUID,
                "areas": [{"code": "0000", "name": "Hele landet", "type": "landsdekkende"}],
                "projections": [{"code": "25833"}],
                "formats": [{"name": "GeoJSON "}],
            }]
        }
        files = requests.post(url, json=order, timeout=60).json()["files"]
        url = files[0]["downloadUrl"]
    download(url, dest, log=PROVENANCE_LOG, source="SSB/Kartverket – statistiske enheter grunnkretser", license="NLOD 2.0")


def _get(session: requests.Session, url: str):
    for attempt in range(4):
        try:
            r = session.get(url, headers={"Accept": "application/json"}, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 3:
                raise
    return None


def hent_udir(register: str, api: str, er_relevant) -> None:
    """Henter aktive enheter per kommune fra Udir og detaljer (koordinater, elev- og barnetall)."""
    dest = RAW / "udir" / f"{register}.jsonl"
    if dest.exists():
        print(f"[fantes] Udir {register}: {dest.name}")
        return
    session = requests.Session()
    kommuner = [c["code"] for c in _get(session, KLASS_KOMMUNER)["codes"] if c["code"] != "9999"]
    kandidater: list[str] = []
    for nr in kommuner:
        liste = _get(session, f"{api}/enheter/kommune/{nr}")
        enheter = liste["EnhetListe"] if isinstance(liste, dict) else liste
        kandidater += [e["Organisasjonsnummer"] for e in enheter if er_relevant(e)]
    kandidater = sorted(set(kandidater))
    with ThreadPoolExecutor(max_workers=4) as pool:
        detaljer = list(pool.map(lambda orgnr: _get(session, f"{api}/enhet/{orgnr}"), kandidater))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        for d in detaljer:
            if d:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    download(f"{api}/enheter", dest, log=PROVENANCE_LOG, source=f"Udir – {register.upper()} (aktive enheter med detaljer)", license="NLOD 2.0")
    print(f"Udir {register}: {len(kandidater)} enheter")


if __name__ == "__main__":
    hent_filer()
    hent_grunnkretser()
    hent_udir(
        "nsr", NSR_API,
        lambda e: e.get("ErAktiv") and e.get("ErSkole") and (e.get("ErGrunnskole") or e.get("ErVideregaaendeSkole")),
    )
    hent_udir("nbr", NBR_API, lambda e: e.get("ErAktiv") and e.get("ErBarnehage"))
