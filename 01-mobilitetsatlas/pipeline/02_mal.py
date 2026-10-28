"""Steg 2: hverdagsmål geokodet og summert per 250 m-rute.

- Arbeidsplasser, dagligvare, helse og tjenester: BRREG-underenheter (SN2025-koder),
  geokodet mot Kartverkets adresseregister (gate + husnummer + bokstav i kommunen,
  deretter gate + husnummer, til slutt postnummerets midtpunkt).
- Skoler og barnehager: Udirs registre (NSR og NBR) med koordinater.

Kjøres fra prosjektroten:  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/02_mal.py
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from pyproj import Transformer  # noqa: E402

from config import CACHE, KATEGORIER, RAW  # noqa: E402
from showcase_shared.ssb_grid import centroid_from_ssbid, ssbid_from_xy  # noqa: E402

ADR_ZIP = RAW / "kartverket-adresser" / "adresser_25833.zip"
BRREG = RAW / "brreg-underenheter" / "underenheter.csv.gz"

# SN2025-koder per kategori. Hver adresse teller én gang per kode (et legesenter med åtte
# fastleger er ett sted), slik at kategoriene måler steder og ikke foretak.
NAERINGSKODER = {
    "dagligvare": ("47.110",),                              # dagligvarebutikker
    "helse": ("86.210", "47.730", "86.101", "86.942"),      # allmennlege, apotek, sykehus, helsestasjon
    "tjenester": ("91.111", "84.300"),                      # folkebibliotek, NAV-kontor
}
SSBID_SQL = "(CAST(floor(x / 250) * 250 AS BIGINT) + 2000000) * 10000000 + CAST(floor(y / 250) * 250 AS BIGINT)"
ADR_REGEX = r"^(.*?)\s+(\d+)\s*([A-Za-zÆØÅæøå]?)$"
TO_25833 = Transformer.from_crs(4326, 25833, always_xy=True)
TO_4326 = Transformer.from_crs(25833, 4326, always_xy=True)


def adresser(con: duckdb.DuckDBPyConnection) -> None:
    """Adresseregisteret som parquet (gjenbrukes av steg 3) og oppslagstabeller for geokoding."""
    pq = CACHE / "adresser.parquet"
    if not pq.exists():
        tmp = CACHE / "adresser_csv"
        tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ADR_ZIP) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as src, open(tmp / "adresser.csv", "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
        con.execute(f"""
            COPY (
              SELECT kommunenummer AS knr, lower(trim(adressenavn)) AS gate, nummer AS nr,
                     upper(coalesce(bokstav, '')) AS bokstav, postnummer, adressetype,
                     CAST("Øst" AS DOUBLE) AS x, CAST("Nord" AS DOUBLE) AS y,
                     grunnkretsnummer, tettstednummer
              FROM read_csv('{(tmp / "adresser.csv").as_posix()}', delim=';', header=true, all_varchar=true, quote='"')
            ) TO '{pq.as_posix()}' (FORMAT parquet)
        """)
        shutil.rmtree(tmp)
    con.execute(f"CREATE OR REPLACE VIEW adr AS SELECT *, {SSBID_SQL} AS ssbid FROM read_parquet('{pq.as_posix()}')")
    con.execute("CREATE OR REPLACE TABLE adr_eksakt AS SELECT knr, gate, nr, bokstav, avg(x) AS x, avg(y) AS y FROM adr WHERE adressetype = 'vegadresse' GROUP BY ALL")
    con.execute("CREATE OR REPLACE TABLE adr_husnr AS SELECT knr, gate, nr, avg(x) AS x, avg(y) AS y FROM adr WHERE adressetype = 'vegadresse' GROUP BY ALL")
    con.execute("CREATE OR REPLACE TABLE adr_post AS SELECT postnummer, avg(x) AS x, avg(y) AS y FROM adr GROUP BY ALL")


def brreg(con: duckdb.DuckDBPyConnection) -> dict:
    con.execute(f"""
        CREATE OR REPLACE TABLE u AS
        SELECT organisasjonsnummer AS orgnr, navn, "naeringskode1.kode" AS kode,
               coalesce(TRY_CAST(antallAnsatte AS INTEGER), 0) AS ansatte,
               "beliggenhetsadresse.kommunenummer" AS knr, "beliggenhetsadresse.postnummer" AS postnr,
               trim(list_last(string_split("beliggenhetsadresse.adresse", chr(10)))) AS adr
        FROM read_csv('{BRREG.as_posix()}', header=true, all_varchar=true, quote='"', escape='"')
        WHERE coalesce(nedleggelsesdato, '') = '' AND "beliggenhetsadresse.landkode" = 'NO'
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE geo AS
        WITH p AS (
          SELECT *, lower(trim(regexp_extract(adr, '{ADR_REGEX}', 1))) AS gate,
                 regexp_extract(adr, '{ADR_REGEX}', 2) AS nr,
                 upper(regexp_extract(adr, '{ADR_REGEX}', 3)) AS bokstav
          FROM u
        )
        SELECT p.*, coalesce(e.x, h.x, po.x) AS x, coalesce(e.y, h.y, po.y) AS y,
               CASE WHEN e.x IS NOT NULL THEN 'adresse' WHEN h.x IS NOT NULL THEN 'husnummer'
                    WHEN po.x IS NOT NULL THEN 'postnummer' ELSE 'mangler' END AS treff
        FROM p
        LEFT JOIN adr_eksakt e ON e.knr = p.knr AND e.gate = p.gate AND e.nr = p.nr AND e.bokstav = p.bokstav
        LEFT JOIN adr_husnr h ON h.knr = p.knr AND h.gate = p.gate AND h.nr = p.nr
        LEFT JOIN adr_post po ON po.postnummer = p.postnr
    """)
    con.execute(f"CREATE OR REPLACE TABLE geo AS SELECT *, {SSBID_SQL} AS ssbid FROM geo WHERE x IS NOT NULL")
    rapport = {
        "treff_enheter": dict(con.execute("SELECT treff, count(*) FROM geo GROUP BY 1").fetchall()),
        "treff_ansatte": dict(con.execute("SELECT treff, sum(ansatte) FROM geo GROUP BY 1").fetchall()),
        "mangler": con.execute("SELECT count(*), sum(ansatte) FROM u").fetchone()[0]
        - con.execute("SELECT count(*) FROM geo").fetchone()[0],
    }
    frames = [con.execute("SELECT ssbid, sum(ansatte)::DOUBLE AS jobber FROM geo WHERE ansatte > 0 GROUP BY ssbid").df()]
    for kategori, koder in NAERINGSKODER.items():
        kode_liste = ", ".join(f"'{k}'" for k in koder)
        nav = "AND (kode <> '84.300' OR navn LIKE 'NAV %')"  # bare NAV-kontor under trygdeforvaltning
        frames.append(con.execute(f"""
            SELECT ssbid, count(DISTINCT (kode, round(x), round(y)))::DOUBLE AS {kategori}
            FROM geo WHERE kode IN ({kode_liste}) {nav} GROUP BY ssbid
        """).df())
    rapport["brreg_steder"] = {k: float(f[k].sum()) for f, k in zip(frames, ["jobber", *NAERINGSKODER])}
    out = frames[0]
    for f in frames[1:]:
        out = out.merge(f, on="ssbid", how="outer")
    con.register("brreg_maal", out)
    return rapport


def udir(register: str, kategori: str) -> pd.DataFrame:
    """Skoler (NSR) og barnehager (NBR) med koordinater fra Udir."""
    rows = []
    for line in open(RAW / "udir" / f"{register}.jsonl", encoding="utf-8"):
        d = json.loads(line)
        k = d.get("Koordinat") or {}
        if k.get("Lengdegrad") and k.get("Breddegrad"):
            rows.append((d["Organisasjonsnummer"], k["Lengdegrad"], k["Breddegrad"]))
    df = pd.DataFrame(rows, columns=["orgnr", "lon", "lat"]).drop_duplicates("orgnr")
    x, y = TO_25833.transform(df.lon.to_numpy(), df.lat.to_numpy())
    df["ssbid"] = ssbid_from_xy(x, y)
    return df.groupby("ssbid").size().rename(kategori).astype("float64").reset_index()


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    adresser(con)
    rapport = brreg(con)
    maal = con.execute("SELECT * FROM brreg_maal").df()
    for register, kategori in (("nsr", "skole"), ("nbr", "barnehage")):
        df = udir(register, kategori)
        rapport[f"udir_{kategori}"] = int(df[kategori].sum())
        maal = maal.merge(df, on="ssbid", how="outer")
    maal = maal.fillna(0.0)
    maal = maal[[c for c in ["ssbid", *KATEGORIER]]]
    x, y = centroid_from_ssbid(maal.ssbid.to_numpy())
    maal["lon"], maal["lat"] = TO_4326.transform(x, y)
    maal.to_parquet(CACHE / "maal.parquet")
    rapport["maalruter"] = len(maal)
    rapport["sum_per_kategori"] = {k: float(maal[k].sum()) for k in KATEGORIER}
    (CACHE / "maal_rapport.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(json.dumps(rapport, ensure_ascii=False, indent=2, default=float))


if __name__ == "__main__":
    main()
