"""Steg 7: plausibilitetssjekker etter steg 5.

1. Befolkning i rutenettet mot SSBs offisielle tall (tabell 06913, 1.1.2025)
2. Arbeidsplasser i BRREG mot befolkningen (andel)
3. «God tilgang» per fylke mot SSBs analyse fra 2024 (Oslo ≈ 1 % og Innlandet ≈ 48 % uten godt tilbud)
4. Karakterer for kjente steder (sentrum skal få A, spredtbygde strøk F eller G)
5. Kollektivreisetider fra R5 mot Entur Journey Planner for 10 reiser (median over 07:00–07:50)

Kjøres fra prosjektroten:  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/07_sjekk.py
Punkt 5 kjøres bare med --entur (bruker ET-Client-Name fra .env og R5 for region sør).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from pyproj import Transformer  # noqa: E402

from config import CACHE, GANGHASTIGHET_KMT, MAKS_GANGTID, REFERANSE_HVERDAG  # noqa: E402
from showcase_shared.env import entur_client_name  # noqa: E402
from showcase_shared.ssb_grid import ssbid_from_xy  # noqa: E402

SSB_BEFOLKNING_2025 = 5_594_340  # SSB tabell 06913, befolkning 1. januar 2025
SSB_UTEN_GODT_TILBUD = {"03": 0.01, "34": 0.48}  # SSB-artikkel 2024: andel husholdninger uten godt tilbud
STEDER = {
    "Oslo S": (59.9111, 10.7528), "Bergen sentrum": (60.3929, 5.3245), "Trondheim torg": (63.4305, 10.3951),
    "Tromsø sentrum": (69.6496, 18.9560), "Lillehammer": (61.1153, 10.4662), "Karasjok": (69.4719, 25.5112),
    "Lom": (61.8380, 8.5680), "Hasvik": (70.4870, 22.1500),
}
REISER = [
    ("Oslo S", "Blindern", (59.9111, 10.7528), (59.9399, 10.7224)),
    ("Oslo S", "Lillestrøm", (59.9111, 10.7528), (59.9534, 11.0450)),
    ("Oslo S", "Drammen", (59.9111, 10.7528), (59.7400, 10.2045)),
    ("Grünerløkka", "Majorstuen", (59.9233, 10.7590), (59.9296, 10.7150)),
    ("Bergen sentrum", "Haukeland", (60.3929, 5.3245), (60.3734, 5.3593)),
    ("Bergen sentrum", "Åsane", (60.3929, 5.3245), (60.4668, 5.3266)),
    ("Stavanger", "Sandnes", (58.9700, 5.7331), (58.8524, 5.7352)),
    ("Kristiansand", "Vennesla", (58.1467, 7.9956), (58.2694, 7.9737)),
    ("Hamar", "Lillehammer", (60.7945, 11.0680), (61.1153, 10.4662)),
    ("Fredrikstad", "Sarpsborg", (59.2181, 10.9298), (59.2839, 11.1096)),
]
TO_25833 = Transformer.from_crs(4326, 25833, always_xy=True)
JP = "https://api.entur.io/journey-planner/v3/graphql"
JP_QUERY = """query ($from: Location!, $to: Location!, $time: DateTime!) {
  trip(from: $from, to: $to, dateTime: $time, numTripPatterns: 3) { tripPatterns { expectedStartTime expectedEndTime duration } }
}"""


def rute_for(lat: float, lon: float) -> int:
    x, y = TO_25833.transform(lon, lat)
    return int(ssbid_from_xy(x, y))


def nærmeste_befolkede(ruter: pd.DataFrame, lat: float, lon: float) -> pd.Series:
    x, y = TO_25833.transform(lon, lat)
    i = int(np.argmin((ruter.x - x) ** 2 + (ruter.y - y) ** 2))
    return ruter.iloc[i]


def jp_median(fra, til, client: str) -> float | None:
    """Median av (ankomst − ønsket avreise) for avreise hvert 10. minutt 07:00–07:50, som R5s avgangsvindu."""
    verdier = []
    for minutt in range(0, 60, 10):
        start = dt.datetime.combine(REFERANSE_HVERDAG, dt.time(7, minutt)).astimezone()
        body = {"query": JP_QUERY, "variables": {
            "from": {"coordinates": {"latitude": fra[0], "longitude": fra[1]}},
            "to": {"coordinates": {"latitude": til[0], "longitude": til[1]}},
            "time": start.isoformat(),
        }}
        r = requests.post(JP, json=body, headers={"ET-Client-Name": client}, timeout=60)
        r.raise_for_status()
        patterns = r.json()["data"]["trip"]["tripPatterns"]
        if patterns:
            ankomst = min(dt.datetime.fromisoformat(p["expectedEndTime"]) for p in patterns)
            verdier.append((ankomst - start).total_seconds() / 60)
    return float(np.median(verdier)) if verdier else None


def main() -> None:
    opts = argparse.ArgumentParser()
    opts.add_argument("--entur", action="store_true", help="sammenlign R5 med Entur Journey Planner")
    args = opts.parse_args()
    ruter = pd.read_parquet(CACHE / "indikatorer_ruter.parquet")
    rapport: dict = {}

    bef = int(ruter.befolkning.sum())
    rapport["befolkning"] = {"rutenett": bef, "ssb_1_1_2025": SSB_BEFOLKNING_2025, "andel": round(bef / SSB_BEFOLKNING_2025, 4)}
    maal = pd.read_parquet(CACHE / "maal.parquet")
    rapport["arbeidsplasser"] = {"brreg": int(maal.jobber.sum()), "per_innbygger": round(float(maal.jobber.sum()) / bef, 3)}

    god = ruter.groupby("fylkesnummer").apply(lambda g: float(np.average(g.god_tilgang, weights=g.befolkning)))
    rapport["uten_god_tilgang"] = {
        f: {"atlas": round(1 - god[f], 3), "ssb_2024": SSB_UTEN_GODT_TILBUD.get(f)} for f in god.index
    }
    rapport["uten_god_tilgang"]["norge"] = {"atlas": round(1 - float(np.average(ruter.god_tilgang, weights=ruter.befolkning)), 3), "ssb_2024": 0.25}

    steder = {}
    for navn, (lat, lon) in STEDER.items():
        r = nærmeste_befolkede(ruter, lat, lon)
        steder[navn] = {"mf": round(float(r.mf_morgen), 1), "karakter_dk": r.karakter_dk_morgen, "kk": round(float(r.kk_morgen), 1), "tv": round(float(r.tv_morgen), 1)}
    rapport["steder"] = steder

    if args.entur:
        rapport["r5_mot_entur"] = sammenlign_entur()

    (CACHE / "sjekk_rapport.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(rapport, ensure_ascii=False, indent=2, default=str))


def sammenlign_entur() -> list[dict]:
    """R5 (median over 07:00–08:00) mot Entur Journey Planner for de samme reisene."""
    import os

    from showcase_shared.env import configure_java

    os.environ["JAVA_HOME"] = str(configure_java())
    sys.argv = [sys.argv[0], "--max-memory", "24G"]
    import geopandas as gpd
    import r5py

    network = r5py.TransportNetwork(CACHE / "regioner" / "sor.osm.pbf", [CACHE / "regioner" / "sor_gtfs.zip"])
    punkter = pd.DataFrame([(i, *p) for i, (_, _, a, b) in enumerate(REISER) for p in (a, b)], columns=["reise", "lat", "lon"])
    punkter["id"] = range(len(punkter))
    gdf = gpd.GeoDataFrame({"id": punkter.id}, geometry=gpd.points_from_xy(punkter.lon, punkter.lat), crs=4326)
    ttm = r5py.TravelTimeMatrix(
        network, origins=gdf, destinations=gdf,
        departure=dt.datetime.combine(REFERANSE_HVERDAG, dt.time(7, 0)), departure_time_window=dt.timedelta(minutes=60),
        transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK], max_time=dt.timedelta(minutes=180),
        max_time_walking=dt.timedelta(minutes=MAKS_GANGTID), speed_walking=GANGHASTIGHET_KMT,
    )
    client = entur_client_name()
    out = []
    for i, (fra, til, a, b) in enumerate(REISER):
        r5 = ttm[(ttm.from_id == 2 * i) & (ttm.to_id == 2 * i + 1)].travel_time
        r5_min = float(r5.iloc[0]) if len(r5) and pd.notna(r5.iloc[0]) else None
        jp = jp_median(a, b, client)
        avvik = round((r5_min - jp) / jp, 3) if r5_min and jp else None
        out.append({"reise": f"{fra} → {til}", "r5_min": r5_min, "entur_min": jp, "avvik": avvik})
    return out


if __name__ == "__main__":
    main()
    if "--entur" in sys.argv or any("--entur" in a for a in sys.argv):
        import os

        os._exit(0)
