"""Steg 3: startpunkter – befolkede 250 m-ruter med kommune, grunnkrets, tettsted og snittalder.

Kommune og grunnkrets settes fra adresseregisteret (flest adresser i ruten avgjør). Ruter uten
adresser får grunnkretsen som inneholder rutens midtpunkt. Snittalder hentes fra 1 km-ruten.

Kjøres etter steg 2:  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/03_opphav.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb  # noqa: E402
import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import pyogrio  # noqa: E402
from pyproj import Transformer  # noqa: E402

from config import CACHE, RAW  # noqa: E402
from showcase_shared.ssb_grid import centroid_from_ssbid, parent_ssbid  # noqa: E402

G250 = f"/vsizip/{(RAW / 'ssb-rutenett-250m' / 'rutenett250m_2025.zip').as_posix()}/Befolkning_0000_Norge_25833_BefolkningsstatistikkRutenett250m2025_GML.gml"
G1KM = f"/vsizip/{(RAW / 'ssb-rutenett-1km' / 'rutenett1km_2025.zip').as_posix()}/Befolkning_0000_Norge_25833_BefolkningsstatistikkRutenett1km2025_GML.gml"
GRUNNKRETSER = f"/vsizip/{(RAW / 'grunnkretser' / 'grunnkretser_25833_geojson.zip').as_posix()}/Basisdata_0000_Norge_25833_Grunnkrets_GeoJSON.geojson"
SSBID_SQL = "(CAST(floor(x / 250) * 250 AS BIGINT) + 2000000) * 10000000 + CAST(floor(y / 250) * 250 AS BIGINT)"


def main() -> None:
    ruter = pyogrio.read_dataframe(G250, columns=["ssbid250m", "popTot"], read_geometry=False)
    ruter = ruter.rename(columns={"ssbid250m": "ssbid", "popTot": "befolkning"}).astype({"ssbid": "int64"})
    x, y = centroid_from_ssbid(ruter.ssbid.to_numpy())
    ruter["x"], ruter["y"] = x, y
    ruter["lon"], ruter["lat"] = Transformer.from_crs(25833, 4326, always_xy=True).transform(x, y)

    # Kommune, grunnkrets og tettsted fra adressene i ruten
    con = duckdb.connect()
    fra_adresser = con.execute(f"""
        SELECT ssbid, arg_max(grunnkretsnummer, n) AS grunnkretsnummer, arg_max(knr, n) AS kommunenummer,
               max(tettsted) AS i_tettsted
        FROM (
          SELECT {SSBID_SQL} AS ssbid, grunnkretsnummer, knr, count(*) AS n,
                 bool_or(coalesce(tettstednummer, '') <> '') AS tettsted
          FROM read_parquet('{(CACHE / "adresser.parquet").as_posix()}')
          GROUP BY ALL
        ) GROUP BY ssbid
    """).df()
    ruter = ruter.merge(fra_adresser, on="ssbid", how="left")

    # Ruter uten adresser: grunnkretsen som inneholder midtpunktet
    mangler = ruter.grunnkretsnummer.isna()
    if mangler.any():
        kretser = pyogrio.read_dataframe(GRUNNKRETSER, columns=["grunnkretsnummer", "kommunenummer"])
        pts = gpd.GeoDataFrame(ruter.loc[mangler, ["ssbid"]], geometry=gpd.points_from_xy(ruter.x[mangler], ruter.y[mangler]), crs=25833)
        treff = gpd.sjoin(pts, kretser.to_crs(25833), how="left", predicate="within").drop_duplicates("ssbid").set_index("ssbid")
        ruter.loc[mangler, "grunnkretsnummer"] = ruter.loc[mangler, "ssbid"].map(treff.grunnkretsnummer)
        ruter.loc[mangler, "kommunenummer"] = ruter.loc[mangler, "ssbid"].map(treff.kommunenummer)
    ruter["i_tettsted"] = ruter.i_tettsted.fillna(False).astype(bool)
    ruter["fylkesnummer"] = ruter.kommunenummer.str[:2]

    # Snittalder fra 1 km-ruten (SSB skjuler den der få bor)
    km = pyogrio.read_dataframe(G1KM, columns=["ssbid1000M", "popAve"], read_geometry=False)
    km = km.rename(columns={"ssbid1000M": "ssbid_1km", "popAve": "snittalder_1km"}).astype({"ssbid_1km": "int64"})
    ruter["ssbid_1km"] = parent_ssbid(ruter.ssbid.to_numpy())
    ruter = ruter.merge(km, on="ssbid_1km", how="left")

    ruter.to_parquet(CACHE / "opphav.parquet")
    rapport = {
        "ruter": len(ruter),
        "befolkning": int(ruter.befolkning.sum()),
        "uten_kommune": int(ruter.kommunenummer.isna().sum()),
        "kommuner": int(ruter.kommunenummer.nunique()),
        "grunnkretser": int(ruter.grunnkretsnummer.nunique()),
        "andel_befolkning_i_tettsted": round(float(ruter.befolkning[ruter.i_tettsted].sum() / ruter.befolkning.sum()), 4),
        "befolkning_per_fylke": {k: int(v) for k, v in ruter.groupby("fylkesnummer").befolkning.sum().items()},
    }
    (CACHE / "opphav_rapport.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rapport, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
