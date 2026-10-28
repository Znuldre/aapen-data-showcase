"""Steg 5: indikatorer per 250 m-rute og aggregering til grunnkrets, kommune, fylke og land.

Per rute og tidsvindu:
  kollektiv kvalitet (KK)  = 100 · Σ vekt · metning(reisetidsvektet antall mål / mål for full score)
  transportvalgfrihet (TV) = 100 · min(1, 2·R_kollektiv / (R_kollektiv + R_bil)), nedskalert når
                             samlet rekkevidde er lav (R = Σ vekt · rekkevidde / mål, uten metning)
  mobilitetsfrihet (MF)    = 0,5 · KK + 0,5 · TV, med A–G på DK-skala og NO-skala
I tillegg kollektivnivå (ulike avganger i timen innen gangavstand) og «god tilgang» som i SSBs
analyse fra 2024 (minst én avgang i timen 07–19 innen 500 m, eller 1 km for tog/T-bane/båt).

Kjøres etter steg 4:  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/05_indikatorer.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from pyproj import Transformer  # noqa: E402

from config import (  # noqa: E402
    CACHE, GANGAVSTAND_HOY_KAPASITET, GANGAVSTAND_LAV_KAPASITET, GOD_TILGANG_VINDU, KATEGORIER,
    KOLLEKTIVNIVAA_GRENSER, LAV_SAMLET_REKKEVIDDE, REGIONER, TIDSVINDUER, TP_RADIUS_KM,
)
from showcase_shared import gtfs  # noqa: E402
from showcase_shared.indicators import DK_BANDS, band, gini, lorenz, saturate, transport_choice, weighted_quantile_bands  # noqa: E402

UT = CACHE / "tilgjengelighet"
TO_25833 = Transformer.from_crs(4326, 25833, always_xy=True)


DELVIS = "--delvis" in sys.argv  # bruk ferdige batcher fra pågående kjøringer (bare for testing av appen)


def les_rekkevidde(modus: str, vindu: str) -> pd.DataFrame:
    """Rekkevidde fra alle regioner som er beregnet; manglende regioner gir 0 (og en advarsel)."""
    deler = []
    for region in REGIONER:
        fil = UT / f"{region}_{modus}_{vindu}.parquet"
        batcher = sorted((UT / fil.stem).glob("batch_*.parquet"))
        if fil.exists():
            deler.append(pd.read_parquet(fil))
        elif DELVIS and batcher:
            print(f"DELVIS: bruker {len(batcher)} batcher for {fil.stem}")
            deler.extend(pd.read_parquet(b) for b in batcher)
        else:
            print(f"ADVARSEL: mangler {fil.name} – rutene i region {region} får 0 for {modus}/{vindu}")
    if not deler:
        if DELVIS:
            print(f"DELVIS: ingen data for {modus}/{vindu} – alle får 0")
            return pd.DataFrame(columns=["ssbid"]).set_index("ssbid")
        raise FileNotFoundError(f"Ingen reisetider for {modus}/{vindu}. Kjør steg 4 først.")
    return pd.concat(deler).drop_duplicates("ssbid").set_index("ssbid")


def nabo_holdeplasser(con: duckdb.DuckDBPyConnection, ruter: pd.DataFrame) -> None:
    """Par (rute, holdeplass) innen 1 km, via 1 km-bøtter (rute × 9 nabobøtter)."""
    stops = con.execute(
        "SELECT stop_id, TRY_CAST(stop_lon AS DOUBLE) AS lon, TRY_CAST(stop_lat AS DOUBLE) AS lat FROM stops"
    ).df().dropna(subset=["lon", "lat"])
    stops["x"], stops["y"] = TO_25833.transform(stops.lon.to_numpy(), stops.lat.to_numpy())
    con.register("stops_xy", stops[["stop_id", "x", "y"]])
    con.register("ruter_xy", ruter[["ssbid", "x", "y"]])
    r = GANGAVSTAND_HOY_KAPASITET
    con.execute(f"""
        CREATE OR REPLACE TABLE rute_holdeplass AS
        WITH q AS (SELECT stop_id, x, y, CAST(floor(x / {r}) AS INTEGER) AS gx, CAST(floor(y / {r}) AS INTEGER) AS gy FROM stops_xy),
             c AS (SELECT ssbid, x, y, CAST(floor(x / {r}) AS INTEGER) + dx AS gx, CAST(floor(y / {r}) AS INTEGER) + dy AS gy
                   FROM ruter_xy, (SELECT unnest([-1, 0, 1]) AS dx), (SELECT unnest([-1, 0, 1]) AS dy))
        SELECT c.ssbid, q.stop_id, sqrt(pow(c.x - q.x, 2) + pow(c.y - q.y, 2)) AS avstand
        FROM c JOIN q ON c.gx = q.gx AND c.gy = q.gy
        WHERE pow(c.x - q.x, 2) + pow(c.y - q.y, 2) <= {r * r}
    """)


def ulike_avganger(con: duckdb.DuckDBPyConnection, date, start, minutes) -> pd.Series:
    """Ulike turer per rute i vinduet fra holdeplasser innen gangavstand for turens kapasitet."""
    con.register("stop_trips", gtfs.stop_trips(con, date, start, minutes))
    df = con.execute(f"""
        SELECT rh.ssbid, count(DISTINCT st.trip_id) AS avganger
        FROM rute_holdeplass rh JOIN stop_trips st USING (stop_id)
        WHERE rh.avstand <= CASE WHEN st.hoy_kapasitet THEN {GANGAVSTAND_HOY_KAPASITET} ELSE {GANGAVSTAND_LAV_KAPASITET} END
        GROUP BY rh.ssbid
    """).df()
    con.unregister("stop_trips")
    return df.set_index("ssbid").avganger


def nivaa(avganger: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.asarray(KOLLEKTIVNIVAA_GRENSER), avganger, side="right")


def vektet(df: pd.DataFrame, kolonner: list[str], gruppe: str) -> pd.DataFrame:
    w = df.befolkning
    out = df[kolonner].mul(w, axis=0).groupby(df[gruppe]).sum().div(w.groupby(df[gruppe]).sum(), axis=0)
    out["befolkning"] = w.groupby(df[gruppe]).sum()
    return out


def transport_performance(ruter: pd.DataFrame) -> list[dict]:
    """EUs «transport performance» per bysenter: nådd innen 30 min / bosatt innen 7,5 km."""
    filer = [UT / f"{r}_tp_morgen.parquet" for r in REGIONER]
    deler = [pd.read_parquet(f) for f in filer if f.exists()]
    if not deler or all(d.empty for d in deler):
        print("ADVARSEL: mangler transport performance (kjør steg 4 med --modus tp)")
        return []
    from scipy.spatial import cKDTree

    import degurba

    tp = pd.concat(deler)
    km = degurba.ruter_1km()
    tre = cKDTree(km[["x", "y"]].to_numpy())
    pos = km.set_index("ssbid_1km")[["x", "y"]].reindex(tp.ssbid_1km).to_numpy()
    naboer = tre.query_ball_point(pos, r=TP_RADIUS_KM * 1000)
    bef = km.befolkning.to_numpy()
    tp["innen_radius"] = [bef[n].sum() for n in naboer]
    tp["tp"] = tp.nadd_30 / tp.innen_radius
    # Navn: kommunen der flest i bysenteret bor
    kommune = ruter.groupby("ssbid_1km").apply(lambda g: g.kommunenummer.iloc[g.befolkning.argmax()])
    tp["kommunenummer"] = tp.ssbid_1km.map(kommune)
    out = []
    for senter, g in tp.groupby("bysenter"):
        w = g.befolkning
        out.append({
            "bysenter": int(senter),
            "kommunenummer": g.kommunenummer[w.idxmax()] if w.idxmax() in g.index else g.kommunenummer.mode().iat[0],
            "befolkning": int(w.sum()),
            "transport_performance": round(float(np.average(g.tp, weights=w)), 4),
            "naadd_30_min": int(round(float(np.average(g.nadd_30, weights=w)))),
            "innen_7_5_km": int(round(float(np.average(g.innen_radius, weights=w)))),
        })
    return sorted(out, key=lambda d: -d["befolkning"])


def beregnede_vinduer() -> list[str]:
    """Tidsvinduene der kollektiv er beregnet for minst én region (morgen må alltid finnes)."""
    def finnes(r: str, v: str) -> bool:
        navn = f"{r}_kollektiv_{v}"
        return (UT / f"{navn}.parquet").exists() or (DELVIS and any((UT / navn).glob("batch_*.parquet")))

    vinduer = [v for v in TIDSVINDUER if any(finnes(r, v) for r in REGIONER)]
    if "morgen" not in vinduer:
        raise FileNotFoundError("Mangler kollektiv/morgen – kjør steg 4 først.")
    return vinduer


def main() -> None:
    global TIDSVINDUER
    TIDSVINDUER = {v: TIDSVINDUER[v] for v in beregnede_vinduer()}
    print("Tidsvinduer med data:", ", ".join(TIDSVINDUER))
    ruter = pd.read_parquet(CACHE / "opphav.parquet")
    kategorier = list(KATEGORIER)
    vekt = {k: KATEGORIER[k]["vekt"] for k in kategorier}
    maal = {k: KATEGORIER[k]["maal"] for k in kategorier}

    forventet = kategorier + [f"{k}_{g}" for k in kategorier for g in (30, 60, 90)]
    bil = les_rekkevidde("bil", "statisk").reindex(ruter.ssbid).reindex(columns=forventet).fillna(0.0)
    r_bil = sum(vekt[k] * bil[k].to_numpy() / maal[k] for k in kategorier)
    # Kolonnene samles og legges til på én gang; hundrevis av enkeltinnsettinger fragmenterer DataFrame-en
    nye: dict[str, np.ndarray] = {}
    for k in kategorier:
        nye[f"rekkevidde_bil_{k}"] = bil[k].to_numpy()
        for g in (30, 60, 90):
            nye[f"bil_{k}_{g}"] = bil[f"{k}_{g}"].to_numpy()

    for vindu in TIDSVINDUER:
        kol = les_rekkevidde("kollektiv", vindu).reindex(ruter.ssbid).reindex(columns=forventet).fillna(0.0)
        metning = {k: saturate(kol[k].to_numpy(), maal[k]) for k in kategorier}
        kk = 100 * sum(vekt[k] * metning[k] for k in kategorier)
        r_kol = sum(vekt[k] * kol[k].to_numpy() / maal[k] for k in kategorier)
        tv = transport_choice(r_kol, r_bil, LAV_SAMLET_REKKEVIDDE)
        nye[f"kk_{vindu}"], nye[f"tv_{vindu}"], nye[f"mf_{vindu}"] = kk, tv, 0.5 * kk + 0.5 * tv
        for k in kategorier:
            nye[f"metning_{k}_{vindu}"] = metning[k]
            nye[f"rekkevidde_kol_{k}_{vindu}"] = kol[k].to_numpy()
            for g in (30, 60, 90):
                nye[f"kol_{k}_{g}_{vindu}"] = kol[f"{k}_{g}"].to_numpy()
    ruter = pd.concat([ruter, pd.DataFrame(nye, index=ruter.index)], axis=1)

    con = gtfs.connect(CACHE / "gtfs")
    nabo_holdeplasser(con, ruter)
    for vindu, (date, start, minutes) in TIDSVINDUER.items():
        ruter[f"avganger_{vindu}"] = ruter.ssbid.map(ulike_avganger(con, date, start, minutes)).fillna(0).to_numpy()
        ruter[f"kn_{vindu}"] = nivaa(ruter[f"avganger_{vindu}"].to_numpy())
    dagtid = ruter.ssbid.map(ulike_avganger(con, *GOD_TILGANG_VINDU)).fillna(0).to_numpy()
    ruter["naer_holdeplass"] = dagtid >= 1
    ruter["god_tilgang"] = dagtid >= GOD_TILGANG_VINDU[2] / 60  # minst én avgang i timen i snitt

    # Karakterer: DK-skala, og NO-skala fra befolkningsvektede persentiler av morgen-MF
    no_bands = weighted_quantile_bands(ruter.mf_morgen.to_numpy(), ruter.befolkning.to_numpy())
    for vindu in TIDSVINDUER:
        ruter[f"karakter_dk_{vindu}"] = band(ruter[f"mf_{vindu}"].to_numpy(), DK_BANDS)
        ruter[f"karakter_no_{vindu}"] = band(ruter[f"mf_{vindu}"].to_numpy(), no_bands)
    ruter.to_parquet(CACHE / "indikatorer_ruter.parquet")

    # Aggregering (befolkningsvektet)
    hoved = [f"{m}_{v}" for v in TIDSVINDUER for m in ("mf", "kk", "tv", "avganger")]
    ruter["andel_god_tilgang"] = ruter.god_tilgang.astype(float)
    ruter["andel_naer_holdeplass"] = ruter.naer_holdeplass.astype(float)
    for letter, _ in DK_BANDS:
        ruter[f"andel_{letter}"] = (ruter.karakter_dk_morgen == letter).astype(float)
    kolonner = hoved + ["andel_god_tilgang", "andel_naer_holdeplass"] + [f"andel_{letter}" for letter, _ in DK_BANDS]
    nivaaer = {"grunnkrets": "grunnkretsnummer", "kommune": "kommunenummer", "fylke": "fylkesnummer"}
    meta: dict = {"dk_skala": DK_BANDS, "no_skala": no_bands, "vinduer": list(TIDSVINDUER)}
    for navn, gruppe in nivaaer.items():
        agg = vektet(ruter, kolonner, gruppe)
        for vindu in TIDSVINDUER:
            agg[f"karakter_dk_{vindu}"] = band(agg[f"mf_{vindu}"].to_numpy(), DK_BANDS)
            agg[f"karakter_no_{vindu}"] = band(agg[f"mf_{vindu}"].to_numpy(), no_bands)
        if navn != "grunnkrets":
            grupper = ruter.groupby(gruppe)
            agg["gini_morgen"] = grupper.apply(lambda g: gini(g.mf_morgen, g.befolkning))
            if navn == "kommune":
                agg["lorenz_morgen"] = grupper.apply(lambda g: [round(float(v), 4) for v in lorenz(g.mf_morgen, g.befolkning)[1]])
        agg.reset_index().to_parquet(CACHE / f"indikatorer_{navn}.parquet")

    meta["transport_performance"] = transport_performance(ruter)

    w = ruter.befolkning
    meta["norge"] = {c: float((ruter[c] * w).sum() / w.sum()) for c in kolonner}
    meta["norge"]["befolkning"] = int(w.sum())
    meta["norge"]["gini_morgen"] = gini(ruter.mf_morgen, w)
    meta["norge"]["karakter_dk_morgen"] = str(band([meta["norge"]["mf_morgen"]], DK_BANDS)[0])
    (CACHE / "indikatorer_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in meta["norge"].items()}, ensure_ascii=False, indent=2))
    print("NO-skala (nedre grenser):", [(letter, round(v, 1)) for letter, v in no_bands])


if __name__ == "__main__":
    main()
