"""Kontroll: punktlighet per linje den siste timen, fra dataene Punktlig-loggeren har samlet.

Punktlig = forsinkelse innenfor terskelen: 3 min for buss, trikk, T-bane, båt og øvrige moduser,
5 min for tog. Tog måles på ankomst (avgang der ankomst mangler), alt annet på avgang. Kansellerte
stoppkall telles for seg, og forsinkelser over ±3 timer regnes som feil i kildedataene og utelates.
Vinduet slutter 10 minutter før nå, fordi et stoppkall lagres først når det er passert.

Kjøres fra prosjektroten:  .venv/Scripts/python.exe -I 03-punktlig/logger/kontroll.py
Eksempler:  --kilde banenor   --modus metro,tram   --datasett RUT   --minutter 120   --topp 30
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # se logger.py

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb  # noqa: E402

import config as C  # noqa: E402

OSLO = ZoneInfo("Europe/Oslo")
MODUSNAVN = {
    "bus": "buss", "coach": "ekspressbuss", "tram": "trikk", "metro": "T-bane", "rail": "tog",
    "water": "båt", "air": "fly", "cableway": "taubane", "funicular": "bane", None: "ukjent",
}
MAKS_AVVIK = 3 * 3600  # større avvik er feil i kildedataene


def tall(x: float | int | None, des: int = 0) -> str:
    if x is None:
        return "–"
    return f"{x:,.{des}f}".replace(",", " ").replace(".", ",")


def prosent(teller: int, nevner: int) -> str:
    return f"{tall(100 * teller / nevner, 1)} %" if nevner else "–"


def min_sek(sek: float | None) -> str:
    if sek is None:
        return "–"
    s = int(round(abs(sek)))
    return f"{'−' if sek < 0 else '+'}{s // 60}:{s % 60:02d}"


def vis_status() -> None:
    try:
        st = json.loads(C.STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Loggeren har ikke skrevet status ennå (data/status.json mangler).")
        return
    kjorer = False
    try:
        import psutil

        pid = int(C.PID.read_text(encoding="utf-8")) if C.PID.exists() else 0
        kjorer = pid > 0 and psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower()
    except Exception:
        pass
    startet = dt.datetime.fromtimestamp(st["startet"], OSLO)
    if kjorer:
        print(f"Loggeren kjører (pid {st['pid']}, startet {startet:%d.%m %H:%M}).")
    else:
        sist = dt.datetime.fromtimestamp(st.get("avsluttet") or st["oppdatert"], OSLO)
        print(f"Loggeren kjører IKKE (sist aktiv {sist:%d.%m %H:%M}). Start den med start.ps1.")
    intervall = {"entur": C.ENTUR_INTERVALL, "banenor": C.BANENOR_INTERVALL}
    for navn, k in st.get("kilder", {}).items():
        sist = f"for {time.time() - k['sist_ok']:.0f} s siden" if k.get("sist_ok") else "aldri"
        feil = f"; {k['feil']} feil, siste: {k['siste_feil']}" if k.get("feil") else ""
        reserve = f"; XML som reserve for Avro: {k['avro_reserve']}" if k.get("avro_reserve") else ""
        formatet = f" ({k['format']})" if k.get("format") else ""
        per_kall = k["byte_nett"] / k["kall"] if k["kall"] else 0
        dogn = per_kall * 86400 / intervall.get(navn, 60) / 1e9
        cpu = f", CPU {tall(k['cpu_s'] / k['kall'], 2)} s per kall" if k["kall"] and "cpu_s" in k else ""
        print(f"  {navn:8} siste svar {sist}{formatet}: {k['kall']} kall, {tall(k['rader'])} rader lagret, "
              f"{per_kall / 1e6:.1f} MB per kall (≈ {tall(dogn, 1)} GB/døgn){cpu}{feil}{reserve}")


def finn_filer(datoer: list[dt.date], kilder: list[str]) -> list[str]:
    filer = []
    for kilde in kilder:
        for d in datoer:
            daglig = C.STOPPKALL / kilde / f"{d.isoformat()}.parquet"
            if daglig.exists():
                filer.append(daglig.as_posix())
            filer += [p.as_posix() for p in sorted((C.STAGING / kilde / d.isoformat()).glob("*.parquet"))]
    return filer


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Punktlighet per linje den siste timen")
    ap.add_argument("--minutter", type=int, default=60, help="vinduets lengde (standard 60)")
    ap.add_argument("--etterslep", type=int, default=10, help="vinduet slutter så mange minutter før nå")
    ap.add_argument("--kilde", default="alle", choices=["alle", "entur", "banenor"],
                    help="alle = tog fra Bane NOR og øvrige moduser fra Entur (standard)")
    ap.add_argument("--modus", help="kommaseparert, f.eks. bus,tram,metro,rail,water")
    ap.add_argument("--datasett", help="Entur-kodeområde, f.eks. RUT, SKY, ATB")
    ap.add_argument("--linje", help="linjenummer slik publikum ser det, f.eks. 5 eller L2")
    ap.add_argument("--topp", type=int, default=10, help="antall linjer per modus (standard 10)")
    ap.add_argument("--min-kall", type=int, default=20, help="minste antall stoppkall for å vise en linje")
    ap.add_argument("--godstog", action="store_true", help="ta med godstog (Bane NOR)")
    args = ap.parse_args()

    vis_status()
    slutt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(minutes=args.etterslep)
    start = slutt - dt.timedelta(minutes=args.minutter)
    lstart, lslutt = start.astimezone(OSLO), slutt.astimezone(OSLO)
    # Driftsdøgnet kan ligge en dag før kalenderdatoen (nattruter), så ta med dagen før
    datoer = [lstart.date() + dt.timedelta(days=i) for i in range(-1, (lslutt.date() - lstart.date()).days + 1)]
    kilder = ["entur", "banenor"] if args.kilde == "alle" else [args.kilde]
    filer = finn_filer(datoer, kilder)
    if not filer:
        print("\nIngen data ennå. Start loggeren (start.ps1) og vent noen minutter.")
        return 1

    vilkar = ["planlagt >= $start", "planlagt < $slutt"]
    parametre: dict = {"start": start, "slutt": slutt, "filer": filer}
    if args.kilde == "alle":  # tog fra Bane NOR, resten fra Entur (unngår å telle tog to ganger)
        vilkar.append("(kilde = 'banenor') = (coalesce(modus, '') = 'rail')")
    if not args.godstog:
        vilkar.append("coalesce(kategori, '') <> 'freightTrain'")
    if args.modus:
        vilkar.append("list_contains($modus, modus)")
        parametre["modus"] = [m.strip() for m in args.modus.split(",")]
    if args.datasett:
        vilkar.append("datasett = $datasett")
        parametre["datasett"] = args.datasett.upper()
    if args.linje:
        vilkar.append("linjenummer = $linje")
        parametre["linje"] = args.linje

    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    con.execute(f"""
        CREATE TEMP TABLE vindu AS
        WITH siste AS (
            SELECT * FROM read_parquet($filer, union_by_name = true)
            QUALIFY row_number() OVER (PARTITION BY kilde, dato, tur_id, rekkefolge ORDER BY observert DESC) = 1
        ), kall AS (
            SELECT *,
                CASE WHEN modus = 'rail' THEN coalesce(planlagt_ankomst, planlagt_avgang)
                     ELSE coalesce(planlagt_avgang, planlagt_ankomst) END AS planlagt,
                CASE WHEN modus = 'rail' THEN coalesce(forsinkelse_ankomst_s, forsinkelse_avgang_s)
                     ELSE coalesce(forsinkelse_avgang_s, forsinkelse_ankomst_s) END AS forsinkelse,
                CASE WHEN modus = 'rail' THEN {C.TERSKEL_TOG} ELSE {C.TERSKEL_ANNET} END AS terskel,
                faktisk_ankomst IS NOT NULL OR faktisk_avgang IS NOT NULL AS har_faktisk
            FROM siste
        )
        SELECT * FROM kall WHERE {' AND '.join(vilkar)}
    """, parametre)
    gyldig = f"NOT kansellert AND abs(forsinkelse) <= {MAKS_AVVIK}"
    maal = f"""
        count(*) AS kall,
        count(*) FILTER (kansellert) AS kansellert,
        count(*) FILTER ({gyldig}) AS malt,
        count(*) FILTER ({gyldig} AND forsinkelse <= terskel) AS punktlig,
        count(*) FILTER ({gyldig} AND forsinkelse < -60) AS tidlig,
        count(*) FILTER (har_faktisk) AS faktisk,
        median(forsinkelse) FILTER ({gyldig}) AS median,
        quantile_cont(forsinkelse, 0.9) FILTER ({gyldig}) AS p90
    """

    print(f"\nPunktlighet {lstart:%d.%m %H:%M}–{lslutt:%H:%M} ({args.minutter} min, slutter {args.etterslep} min "
          f"før nå). Punktlig: tog innen {C.TERSKEL_TOG // 60} min, øvrige innen {C.TERSKEL_ANNET // 60} min.")
    if args.kilde == "alle":
        print("Tog fra Bane NOR, øvrige moduser fra Entur. Godstog er " + ("med." if args.godstog else "holdt utenfor."))

    sammendrag = con.execute(f"""
        SELECT kilde, modus, count(DISTINCT linje), {maal} FROM vindu GROUP BY ALL ORDER BY kall DESC
    """).fetchall()
    if not sammendrag:
        print("\nIngen stoppkall i vinduet.")
        return 1
    print(f"\n{'Kilde':8} {'Modus':12} {'Linjer':>6} {'Stoppkall':>10} {'Punktlige':>10} {'For tidlig':>10} "
          f"{'Median':>7} {'P90':>7} {'Kansellert':>10} {'Faktisk tid':>11}")
    for kilde, modus, linjer, kall, kans, malt, punkt, tidlig, faktisk, med, p90 in sammendrag:
        print(f"{kilde:8} {MODUSNAVN.get(modus, modus):12} {linjer:>6} {tall(kall):>10} {prosent(punkt, malt):>10} "
              f"{prosent(tidlig, malt):>10} {min_sek(med):>7} {min_sek(p90):>7} {tall(kans):>10} "
              f"{prosent(faktisk, kall):>11}")

    navn = "NULL"
    if C.LINJER.exists():
        con.execute("CREATE TEMP TABLE linjer AS SELECT * FROM read_parquet($f)", {"f": C.LINJER.as_posix()})
        navn = """coalesce(
            (SELECT any_value(l.navn) FROM linjer l WHERE l.linje = g.linje),
            (SELECT any_value(l.navn) FROM linjer l
              WHERE g.kilde = 'banenor' AND l.modus = 'rail' AND l.linjenummer = g.nummer))"""
    per_linje = con.execute(f"""
        WITH g AS (
            SELECT kilde, modus, linje, any_value(linjenummer) AS nummer, any_value(datasett) AS datasett,
                   any_value(operator) AS operator, {maal}
            FROM vindu GROUP BY ALL
        )
        SELECT kilde, modus, coalesce(nummer, linje, '?'), datasett, operator, {navn},
               kall, kansellert, malt, punktlig, median, p90
        FROM g WHERE kall >= $min
        QUALIFY row_number() OVER (PARTITION BY kilde, modus ORDER BY kall DESC) <= $topp
        ORDER BY kilde, max(kall) OVER (PARTITION BY kilde, modus) DESC, modus, kall DESC
    """, {"min": args.min_kall, "topp": args.topp}).fetchall()

    print(f"\nPer linje (inntil {args.topp} per modus med minst {args.min_kall} stoppkall, flest kall først):")
    print(f"{'Kilde':8} {'Modus':12} {'Linje':>6} {'Hvem':8} {'Navn':38} {'Kall':>6} {'Punktlige':>10} "
          f"{'Median':>7} {'P90':>7} {'Kans.':>5}")
    forrige = None
    for kilde, modus, nummer, datasett, operator, linjenavn, kall, kans, malt, punkt, med, p90 in per_linje:
        if forrige and forrige != (kilde, modus):
            print()
        forrige = (kilde, modus)
        hvem = datasett if kilde == "entur" else (operator or "")
        print(f"{kilde:8} {MODUSNAVN.get(modus, modus):12} {nummer[:6]:>6} {hvem[:8]:8} {(linjenavn or '')[:38]:38} "
              f"{kall:>6} {prosent(punkt, malt):>10} {min_sek(med):>7} {min_sek(p90):>7} {kans:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
