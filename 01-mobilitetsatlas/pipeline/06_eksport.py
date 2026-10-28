"""Steg 6: eksport til web-appen (web/public/data) og nedlastbare CSV-filer.

  meta.json                 parametere, skalaer, landstall, fylker og kilder med sjekksum
  kommuner.geojson          forenklede kommunegrenser med indikatorer
  kommuner_profiler.json    Lorenzkurve, karakterfordeling og svakeste/sterkeste grunnkretser
  grunnkretser/{fylke}.geojson
  ruter/{fylke}.json        250 m-ruter, kolonnevis, for kartet
  detaljer/{kommune}.json   alt per rute i kommunen, for «ditt tall» og følsomhetsvisningen
  nedlasting/*.csv          kommuner, grunnkretser og ruter

Kjøres etter steg 5:  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/06_eksport.py
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyogrio  # noqa: E402
import requests  # noqa: E402

from config import (  # noqa: E402
    CACHE, GANGAVSTAND_HOY_KAPASITET, GANGAVSTAND_LAV_KAPASITET, KATEGORIER, KOLLEKTIVNIVAA_GRENSER,
    LAV_SAMLET_REKKEVIDDE, MAKS_REISETID, PROVENANCE_LOG, PUBLIC, RAW, REFERANSE_HVERDAG, REFERANSE_LORDAG, TIDSVINDUER,
)

GRUNNKRETSER = f"/vsizip/{(RAW / 'grunnkretser' / 'grunnkretser_25833_geojson.zip').as_posix()}/Basisdata_0000_Norge_25833_Grunnkrets_GeoJSON.geojson"
KLASS = "https://data.ssb.no/api/klass/v1/classifications/{id}/codesAt?date=2026-01-01"
VINDUSNAVN = {"morgen": "Hverdag 07–08", "kveld": "Hverdag 19–20", "lordag": "Lørdag 10–11"}
KATEGORINAVN = {
    "jobber": "Arbeidsplasser", "dagligvare": "Dagligvare", "skole": "Skoler",
    "barnehage": "Barnehager", "helse": "Helse", "tjenester": "Tjenester",
}


def klass_navn(klass_id: int) -> dict[str, str]:
    fil = RAW / "klass" / f"{klass_id}.json"
    if not fil.exists():
        fil.parent.mkdir(parents=True, exist_ok=True)
        fil.write_text(requests.get(KLASS.format(id=klass_id), headers={"Accept": "application/json"}, timeout=60).text, encoding="utf-8")
    return {c["code"]: c["name"] for c in json.loads(fil.read_text(encoding="utf-8"))["codes"]}


def avrund(df: pd.DataFrame, kolonner: list[str], desimaler: int = 1) -> pd.DataFrame:
    out = df.copy()
    for c in kolonner:
        if c in out:
            out[c] = out[c].astype(float).round(desimaler)
    return out


def indikator_kolonner(vinduer: list[str]) -> list[str]:
    return [f"{m}_{v}" for v in vinduer for m in ("mf", "kk", "tv", "avganger")]


def skriv_geojson(gdf, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pyogrio.write_dataframe(gdf, path, driver="GeoJSON", layer_options={"COORDINATE_PRECISION": 5, "RFC7946": "YES"})


def kolonnevis(df: pd.DataFrame) -> dict:
    """Kolonnevis JSON; NaN blir null. (pandas 3 bruker egne strengtyper, så sjekk via pandas.api.)"""
    out = {}
    for c in df.columns:
        v = df[c]
        if pd.api.types.is_bool_dtype(v.dtype):
            out[c] = v.astype(int).tolist()
        elif pd.api.types.is_float_dtype(v.dtype):
            out[c] = [None if np.isnan(x) else x for x in v.astype("float64").tolist()]
        elif pd.api.types.is_integer_dtype(v.dtype):
            out[c] = v.astype("int64").tolist()
        else:
            out[c] = v.astype(object).where(v.notna(), None).tolist()
    return out


def main() -> None:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)
    kommunenavn, fylkesnavn = klass_navn(131), klass_navn(104)
    meta_ind = json.loads((CACHE / "indikatorer_meta.json").read_text(encoding="utf-8"))
    vinduer = meta_ind["vinduer"]
    ruter = pd.read_parquet(CACHE / "indikatorer_ruter.parquet")
    kommuner = pd.read_parquet(CACHE / "indikatorer_kommune.parquet")
    kretser = pd.read_parquet(CACHE / "indikatorer_grunnkrets.parquet")
    fylker = pd.read_parquet(CACHE / "indikatorer_fylke.parquet")
    hoved = indikator_kolonner(vinduer)
    karakterer = [f"karakter_{s}_{v}" for v in vinduer for s in ("dk", "no")]
    andeler = ["andel_god_tilgang", "andel_naer_holdeplass"]

    # Grenser: grunnkretser fra Geonorge, kommuner som sammenslåtte grunnkretser
    gk = pyogrio.read_dataframe(GRUNNKRETSER, columns=["grunnkretsnummer", "grunnkretsnavn", "kommunenummer"])
    gk_navn = dict(zip(gk.grunnkretsnummer, gk.grunnkretsnavn))
    kommune_geo = gk.dissolve(by="kommunenummer", as_index=False)[["kommunenummer", "geometry"]]
    kommune_geo["geometry"] = kommune_geo.geometry.simplify(150)
    k = kommune_geo.merge(kommuner, on="kommunenummer", how="left")
    k["navn"] = k.kommunenummer.map(kommunenavn)
    k["fylkesnummer"] = k.kommunenummer.str[:2]
    k = avrund(k, hoved + ["gini_morgen"], 2)
    k = avrund(k, andeler + [c for c in k.columns if c.startswith("andel_")], 3)
    skriv_geojson(
        k[["kommunenummer", "navn", "fylkesnummer", "befolkning", *hoved, *karakterer, *andeler, "gini_morgen", "geometry"]].to_crs(4326),
        PUBLIC / "kommuner.geojson",
    )

    # Kommuneprofiler: Lorenzkurve, karakterfordeling, svakeste og sterkeste grunnkretser
    kretser["navn"] = kretser.grunnkretsnummer.map(gk_navn)
    kretser["kommunenummer"] = kretser.grunnkretsnummer.str[:4]
    profiler = {}
    for _, rad in kommuner.iterrows():
        knr = rad.kommunenummer
        egne = kretser[(kretser.kommunenummer == knr) & (kretser.befolkning >= 50)].sort_values("mf_morgen")
        liste = lambda d: [[r.grunnkretsnummer, r.navn, round(float(r.mf_morgen), 1), int(r.befolkning)] for r in d.itertuples()]
        profiler[knr] = {
            "lorenz": rad.lorenz_morgen.tolist() if hasattr(rad.lorenz_morgen, "tolist") else list(rad.lorenz_morgen),
            "andeler": {letter: round(float(rad[f"andel_{letter}"]), 4) for letter in "ABCDEFG"},
            "svakest": liste(egne.head(5)),
            "sterkest": liste(egne.tail(5).iloc[::-1]),
        }
    (PUBLIC / "kommuner_profiler.json").write_text(json.dumps(profiler, ensure_ascii=False), encoding="utf-8")

    # Grunnkretser per fylke
    gk_geo = gk.merge(kretser.drop(columns=["navn", "kommunenummer"]), on="grunnkretsnummer", how="inner")
    gk_geo["geometry"] = gk_geo.geometry.simplify(40)
    gk_geo = avrund(gk_geo, hoved, 1)
    for fnr, del_gk in gk_geo.groupby(gk_geo.kommunenummer.str[:2]):
        skriv_geojson(
            del_gk[["grunnkretsnummer", "grunnkretsnavn", "kommunenummer", "befolkning", *hoved, *karakterer, "andel_god_tilgang", "geometry"]].to_crs(4326),
            PUBLIC / "grunnkretser" / f"{fnr}.geojson",
        )

    # 250 m-ruter per fylke (kart) og detaljer per kommune
    kart = ["ssbid", "befolkning", "kommunenummer", *hoved, *[f"kn_{v}" for v in vinduer]]
    for fnr, del_r in ruter.groupby("fylkesnummer"):
        d = avrund(del_r[kart], hoved, 1)
        (PUBLIC / "ruter").mkdir(exist_ok=True)
        (PUBLIC / "ruter" / f"{fnr}.json").write_text(json.dumps(kolonnevis(d), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    detalj_kolonner = (
        ["ssbid", "grunnkretsnummer", "befolkning", "god_tilgang", "naer_holdeplass", "snittalder_1km"]
        + [c for c in ruter.columns if c.startswith(("metning_", "rekkevidde_", "kol_", "bil_", "avganger_"))]
    )
    (PUBLIC / "detaljer").mkdir(exist_ok=True)
    for knr, del_r in ruter.groupby("kommunenummer"):
        d = avrund(del_r[detalj_kolonner], [c for c in detalj_kolonner if c.startswith(("metning_",))], 3)
        d = avrund(d, [c for c in detalj_kolonner if c.startswith(("rekkevidde_",))], 1)
        d = avrund(d, [c for c in detalj_kolonner if c.startswith(("kol_", "bil_", "avganger_"))], 0)
        (PUBLIC / "detaljer" / f"{knr}.json").write_text(json.dumps(kolonnevis(d), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Nedlastinger
    ned = PUBLIC / "nedlasting"
    ned.mkdir()
    kommuner.assign(navn=kommuner.kommunenummer.map(kommunenavn)).drop(columns=["lorenz_morgen"]).to_csv(ned / "kommuner.csv", index=False)
    kretser.to_csv(ned / "grunnkretser.csv", index=False)
    with gzip.open(ned / "ruter.csv.gz", "wt", encoding="utf-8") as f:
        ruter[["ssbid", "kommunenummer", "grunnkretsnummer", "befolkning", *hoved, *[f"kn_{v}" for v in vinduer], *karakterer, "god_tilgang"]].to_csv(f, index=False)

    # Meta: parametere, skalaer, landstall, fylker og kilder
    fylke_bbox = ruter.groupby("fylkesnummer").agg(x0=("lon", "min"), y0=("lat", "min"), x1=("lon", "max"), y1=("lat", "max"))
    kilder = [json.loads(line) for line in open(PROVENANCE_LOG, encoding="utf-8")]
    siste = {}
    for kilde in kilder:
        siste[kilde["kilde"]] = kilde
    meta = {
        "versjon": "0.1.0",
        "generert": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "referansedager": {"hverdag": REFERANSE_HVERDAG.isoformat(), "lordag": REFERANSE_LORDAG.isoformat()},
        "tidsvinduer": {v: {"navn": VINDUSNAVN[v], "dato": d.isoformat(), "start": s.strftime("%H:%M"), "minutter": m} for v, (d, s, m) in TIDSVINDUER.items() if v in vinduer},
        "kategorier": {k: {**p, "navn": KATEGORINAVN[k]} for k, p in KATEGORIER.items()},
        "parametere": {
            "maks_reisetid": MAKS_REISETID, "lav_samlet_rekkevidde": LAV_SAMLET_REKKEVIDDE,
            "gangavstand_lav_kapasitet": GANGAVSTAND_LAV_KAPASITET, "gangavstand_hoy_kapasitet": GANGAVSTAND_HOY_KAPASITET,
            "kollektivnivaa_grenser": list(KOLLEKTIVNIVAA_GRENSER),
        },
        "skalaer": {"dk": meta_ind["dk_skala"], "no": meta_ind["no_skala"]},
        "norge": meta_ind["norge"],
        "transport_performance": [
            {**d, "navn": kommunenavn.get(d["kommunenummer"], d["kommunenummer"])} for d in meta_ind.get("transport_performance", [])
        ],
        "fylker": [
            {
                "nr": r.fylkesnummer, "navn": fylkesnavn.get(r.fylkesnummer, r.fylkesnummer), "befolkning": int(r.befolkning),
                "bbox": [round(float(v), 4) for v in fylke_bbox.loc[r.fylkesnummer]],
                **{c: round(float(getattr(r, c)), 2) for c in hoved}, **{c: getattr(r, c) for c in karakterer},
                "andel_god_tilgang": round(float(r.andel_god_tilgang), 4), "gini_morgen": round(float(r.gini_morgen), 4),
            }
            for r in fylker.itertuples()
        ],
        "kilder": [
            {k: v for k, v in kilde.items() if k in ("kilde", "url", "fil", "lisens", "registrert", "bytes", "sha256", "http")}
            for kilde in siste.values()
        ],
    }
    (PUBLIC / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    total = sum(f.stat().st_size for f in PUBLIC.rglob("*") if f.is_file())
    print(f"Eksportert til {PUBLIC} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
