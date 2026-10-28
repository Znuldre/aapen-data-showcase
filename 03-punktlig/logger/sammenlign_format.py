"""Henter Enturs SIRI ET som XML og Avro på samme øyeblikk og sammenligner turene parserne gir.

Sjekker Avro-dekoderen (siri_avro.py) mot XML-parseren (siri.py), for eksempel etter et nytt
SiriRecord.avsc. De to kallene startes med 0,2 s mellomrom (Enturs spike arrest tillater ett kall per
100 ms) og bruker 2 av 5 kall i minuttet. Turer Entur har oppdatert mellom de to uttrekkene, har ulik
RecordedAtTime og regnes som forklart. Alle andre avvik er feil, og da avslutter skriptet med kode 1.

Kjøres fra prosjektroten:
    .venv/Scripts/python.exe -I 03-punktlig/logger/sammenlign_format.py
    .venv/Scripts/python.exe -I 03-punktlig/logger/sammenlign_format.py --xml svar.xml --avro svar.avro
--behold <mappe> lagrer de nedlastede svarene der.
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # se logger.py

import argparse
import shutil
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import astuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import config as C  # noqa: E402
import siri_avro as A  # noqa: E402
from showcase_shared.env import entur_client_name  # noqa: E402
from siri import NS, les_et, tid_fra_iso  # noqa: E402


def hent(url: str, hoder: dict, sti: Path, ut: dict) -> None:
    with requests.get(url, params={"maxSize": C.ENTUR_MAKS}, headers=hoder, stream=True, timeout=(15, 180)) as r:
        r.raise_for_status()
        with open(sti, "wb") as f:
            shutil.copyfileobj(r.raw, f, 1 << 20)
    ut[sti.name] = time.time()


def hent_begge(mappe: Path) -> tuple[Path, Path]:
    felles = {"ET-Client-Name": entur_client_name(), "User-Agent": "aapendata-showcase-punktlig/sammenlign"}
    xml, avro = mappe / "et.xml", mappe / "et.avro"
    ferdig: dict = {}
    traader = [
        threading.Thread(target=hent, args=(C.ENTUR_ET, felles, xml, ferdig)),
        threading.Thread(target=hent, args=(C.ENTUR_ET, {**felles, "Accept": "application/avro"}, avro, ferdig)),
    ]
    traader[0].start()
    time.sleep(0.2)
    traader[1].start()
    for t in traader:
        t.join()
    if len(ferdig) != 2:
        raise SystemExit("Nedlastingen feilet (se feilmeldingen over)")
    return xml, avro


def registrert_xml(sti: Path) -> dict[str, set[float]]:
    """tur_id -> RecordedAtTime (Unix-sekunder med desimaler) per EstimatedVehicleJourney i XML-en."""
    ut: dict[str, set[float]] = {}
    for _, el in ET.iterparse(sti, events=("end",)):
        if el.tag == NS + "EstimatedVehicleJourney":
            framed = el.find(NS + "FramedVehicleJourneyRef")
            tur_id = (framed.findtext(NS + "DatedVehicleJourneyRef") if framed is not None else None) \
                or el.findtext(NS + "DatedVehicleJourneyRef") or el.findtext(NS + "EstimatedVehicleJourneyCode")
            ut.setdefault(tur_id, set()).add(_tid(el.findtext(NS + "RecordedAtTime")))
            el.clear()
    return ut


def registrert_avro(sti: Path) -> dict[str, set[float]]:
    """Det samme fra Avro: leser de første feltene i hver EstimatedVehicleJourneyRecord og hopper over resten."""
    d = sti.read_bytes()
    hopp_resten = [h for _, h in A._RECORDS["EstimatedVehicleJourneyRecord"][6:]]
    ut: dict[str, set[float]] = {}
    p = A._hopp_streng(d, 10)  # SiriRecord.version
    if not d[p]:  # ingen serviceDelivery
        return ut
    p += 1
    for _ in range(3):
        p = A._hopp_tekst(d, p)
    p += 2 if d[p] else 1  # moreData
    n, p = A._antall(d, p)
    while n:
        for _ in range(n):
            p = A._hopp_tekst(d, A._hopp_tekst(d, p))
            m, p = A._antall(d, p)
            while m:
                for _ in range(m):
                    p = A._hopp_tekst(d, p)
                    k, p = A._antall(d, p)
                    while k:
                        for _ in range(k):
                            registrert, p = A._tekst(d, p)  # recordedAtTime
                            p = A._hopp_tekst(d, A._hopp_tekst(d, p))  # lineRef, directionRef
                            dated, p = A._tekst(d, p)
                            framed = None
                            if d[p]:
                                p = A._hopp_tekst(d, p + 1)
                                framed, p = A._tekst(d, p)
                            else:
                                p += 1
                            kode, p = A._tekst(d, p)
                            for h in hopp_resten:
                                p = h(d, p)
                            ut.setdefault(framed or dated or kode, set()).add(_tid(registrert))
                        k, p = A._antall(d, p)
                m, p = A._antall(d, p)
        n, p = A._antall(d, p)
    return ut


def _tid(tekst: str | None) -> float | None:
    """RecordedAtTime med desimaler (XML har opptil ni, Avro seks; begge kuttes til mikrosekunder)."""
    if not tekst:
        return None
    hel = tid_fra_iso(tekst)
    desimaler = tekst[20:].split("+")[0].split("-")[0].rstrip("Z") if len(tekst) > 19 and tekst[19] == "." else ""
    return hel + int(desimaler[:6].ljust(6, "0")) / 1e6


def les(funksjon, sti: Path) -> tuple[list, float]:
    t0 = time.process_time()
    with open(sti, "rb") as f:
        turer = list(funksjon(f, "entur"))
    return turer, time.process_time() - t0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xml", type=Path, help="XML-svar hentet på samme tid som --avro (ellers hentes begge nå)")
    ap.add_argument("--avro", type=Path)
    ap.add_argument("--behold", type=Path, help="mappe der nedlastede svar lagres")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        if args.xml and args.avro:
            xml, avro = args.xml, args.avro
        else:
            mappe = args.behold or Path(tmp)
            mappe.mkdir(parents=True, exist_ok=True)
            print(f"Henter XML og Avro samtidig ({time.strftime('%d.%m %H:%M:%S')}) ...")
            xml, avro = hent_begge(mappe)
        x, cpu_x = les(les_et, xml)
        a, cpu_a = les(A.les_et_avro, avro)
        kall_x, kall_a = sum(len(t.kall) for t in x), sum(len(t.kall) for t in a)
        print(f"XML : {xml.stat().st_size / 1e6:6.1f} MB, {len(x)} turer, {kall_x} kall, lest på {cpu_x:.2f} CPU-s")
        print(f"Avro: {avro.stat().st_size / 1e6:6.1f} MB, {len(a)} turer, {kall_a} kall, lest på {cpu_a:.2f} CPU-s "
              f"({100 * avro.stat().st_size / xml.stat().st_size:.1f} % av XML)")
        dx, da = {t.nokkel: t for t in x}, {t.nokkel: t for t in a}
        bare_x, bare_a = set(dx) - set(da), set(da) - set(dx)
        felles = set(dx) & set(da)
        ulike = sorted(k for k in felles if astuple(dx[k]) != astuple(da[k]))
        print(f"Turer i begge: {len(felles)}, identiske: {len(felles) - len(ulike)}, ulike: {len(ulike)}, "
              f"bare i XML: {len(bare_x)}, bare i Avro: {len(bare_a)}")
        if not (ulike or bare_x or bare_a):
            print("Helt like.")
            return 0
        rx, ra = registrert_xml(xml), registrert_avro(avro)
        uforklart: list[tuple[str, Counter]] = []
        for k in ulike + sorted(bare_x) + sorted(bare_a):
            tur = dx.get(k) or da[k]
            if rx.get(tur.tur_id) == ra.get(tur.tur_id):
                felt = Counter()
                if k in dx and k in da:
                    felt.update(f for f in tur.__slots__ if f != "kall" and getattr(dx[k], f) != getattr(da[k], f))
                    for kx, ka in zip(dx[k].kall, da[k].kall):
                        felt.update(f for f in kx.__slots__ if getattr(kx, f) != getattr(ka, f))
                    if len(dx[k].kall) != len(da[k].kall):
                        felt["antall kall"] += 1
                else:
                    felt["bare i XML" if k in dx else "bare i Avro"] += 1
                uforklart.append((k, felt))
        forklart = len(ulike) + len(bare_x) + len(bare_a) - len(uforklart)
        print(f"Forklart av ulik RecordedAtTime (oppdatert mellom uttrekkene): {forklart}; uforklart: {len(uforklart)}")
        for k, felt in uforklart[:20]:
            print(f"  {k}: {dict(felt)}")
        return 1 if uforklart else 0


if __name__ == "__main__":
    sys.exit(main())
