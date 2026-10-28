"""Steg 4: reisetider med r5py (Conveyal R5) og reisetidsvektet rekkevidde per startrute.

For hver startrute (befolket 250 m-rute) beregnes medianreisetiden til alle målruter innen
90 minutter, med kollektiv (gange som tilbringer) per tidsvindu og med bil. Reisetidene
vektes med halveringstiden for hver målkategori og summeres per startrute. Matrisene
kastes etter hver batch, slik at bare rekkevidden lagres.

R5 tillater maks 975 000 km² gatenett, så beregningen kjøres per region (se config.REGIONER).

Kjøres fra prosjektroten:
  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/04_reisetider.py --region sor --test
  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/04_reisetider.py --region sor --modus kollektiv --vindu morgen
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    CACHE, GANGHASTIGHET_KMT, KATEGORIER, MAKS_GANGTID, MAKS_REISETID, RAW, REFERANSE_HVERDAG, REFERANSE_LORDAG, REGION_BUFFER_KM, REGIONER, TIDSVINDUER,
    TP_MAKS_REISETID,
)
from showcase_shared.env import configure_java  # noqa: E402

args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
args.add_argument("--region", choices=list(REGIONER), required=True)
args.add_argument("--test", action="store_true", help="bygg nettverket og beregn én liten matrise")
args.add_argument("--modus", choices=["kollektiv", "bil", "tp"], default="kollektiv", help="tp = EUs transport performance for bysentre")
args.add_argument("--vindu", choices=list(TIDSVINDUER), default="morgen")
args.add_argument("--batch", type=int, default=1000, help="antall startruter per R5-kall")
args.add_argument("--maks-batcher", type=int, default=None, help="stopp etter så mange batcher (for måling)")
args.add_argument("--maks-minne", default="16G", help="maks minne for Java (R5)")
args.add_argument("--traader", type=int, default=14, help="antall parallelle R5-beregninger")
opts = args.parse_args()

# r5py leser sine egne argumenter fra sys.argv og starter JVM-en ved import
os.environ["JAVA_HOME"] = str(configure_java())
sys.argv = [sys.argv[0], "--max-memory", opts.maks_minne]

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import r5py  # noqa: E402
import shapely  # noqa: E402
from r5py.r5.regional_task import RegionalTask  # noqa: E402
from r5py.util.config import Config  # noqa: E402

from showcase_shared.gtfs import extract, reduce_feed  # noqa: E402
from showcase_shared.osm import clip_regions  # noqa: E402
from showcase_shared.r5 import travel_times_parallel  # noqa: E402

OSM = RAW / "osm" / "norway-latest.osm.pbf"
GTFS_FULL = RAW / "entur-gtfs" / "rb_norway-aggregated-gtfs.zip"
REGION_DIR = CACHE / "regioner"
UT = CACHE / "tilgjengelighet"


def region_bboxes(opphav: pd.DataFrame) -> dict[str, tuple[float, float, float, float]]:
    """Kjernefylkenes utstrekning pluss buffer, i lengde-/breddegrad."""
    out = {}
    for name, fylker in REGIONER.items():
        core = opphav[opphav.fylkesnummer.isin(fylker)]
        mid_lat = (core.lat.min() + core.lat.max()) / 2
        dlat = REGION_BUFFER_KM / 111.0
        dlon = REGION_BUFFER_KM / (111.0 * math.cos(math.radians(mid_lat)))
        out[name] = (core.lon.min() - dlon, core.lat.min() - dlat, core.lon.max() + dlon, core.lat.max() + dlat)
    return out


def area_km2(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    return (x1 - x0) * 111.0 * math.cos(math.radians((y0 + y1) / 2)) * (y1 - y0) * 111.0


def fersk_kopi(path: Path) -> None:
    """r5py gjenbruker kopien i sin cache så lenge filnavnet finnes der; slett den hvis kilden er endret."""
    kopi = Config().CACHE_DIR / path.name
    if kopi.exists() and (kopi.stat().st_size != path.stat().st_size or kopi.stat().st_mtime < path.stat().st_mtime):
        kopi.unlink()


def nettverk(region: str, bbox: tuple[float, float, float, float], all_bboxes: dict) -> r5py.TransportNetwork:
    osm = clip_regions(OSM, all_bboxes, REGION_DIR)[region]
    gtfs = REGION_DIR / f"{region}_gtfs.zip"
    if not gtfs.exists():
        reduce_feed(extract(GTFS_FULL, CACHE / "gtfs"), gtfs, [REFERANSE_HVERDAG, REFERANSE_LORDAG], bbox=bbox)
    fersk_kopi(osm)
    fersk_kopi(gtfs)
    t = time.time()
    network = r5py.TransportNetwork(osm, [gtfs])
    print(f"Nettverk {region} klart på {time.time() - t:.0f} s", flush=True)
    return network


def punkter(df: pd.DataFrame, id_col: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"id": df[id_col].to_numpy()}, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")


TESTPUNKTER = {
    "sor": [("Oslo S", 59.9111, 10.7528), ("Blindern", 59.9399, 10.7224), ("Bergen sentrum", 60.3929, 5.3245), ("Lillehammer", 61.1153, 10.4662)],
    "midt": [("Trondheim S", 63.4363, 10.3988), ("Ålesund", 62.4722, 6.1549), ("Steinkjer", 64.0149, 11.4954)],
    "nordland": [("Bodø", 67.2804, 14.4049), ("Mo i Rana", 66.3128, 14.1428), ("Svolvær", 68.2343, 14.5683)],
    "nord": [("Tromsø", 69.6496, 18.9560), ("Harstad", 68.7984, 16.5415), ("Alta", 69.9689, 23.2716)],
}


def test(network: r5py.TransportNetwork, region: str) -> None:
    steder = pd.DataFrame(TESTPUNKTER[region], columns=["navn", "lat", "lon"])
    steder["id"] = range(len(steder))
    pts = punkter(steder, "id")
    date, start, minutes = TIDSVINDUER["morgen"]
    for modes in ([r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK], [r5py.TransportMode.CAR]):
        t = time.time()
        ttm = r5py.TravelTimeMatrix(
            network, origins=pts, destinations=pts,
            departure=dt.datetime.combine(date, start), departure_time_window=dt.timedelta(minutes=minutes),
            transport_modes=modes, max_time=dt.timedelta(minutes=MAKS_REISETID),
            max_time_walking=dt.timedelta(minutes=MAKS_GANGTID), speed_walking=GANGHASTIGHET_KMT,
        )
        print([m.name for m in modes], f"{time.time() - t:.1f} s")
        names = dict(zip(steder.id, steder.navn))
        print(ttm.pivot(index="from_id", columns="to_id", values="travel_time").rename(index=names, columns=names))


def rekkevidde(network, region, bbox, modus, vindu, batch, maks_batcher) -> None:
    opphav = pd.read_parquet(CACHE / "opphav.parquet")
    opphav = opphav[opphav.fylkesnummer.isin(REGIONER[region])]
    x0, y0, x1, y1 = bbox
    maal = pd.read_parquet(CACHE / "maal.parquet")
    maal = maal[maal.lon.between(x0, x1) & maal.lat.between(y0, y1)].reset_index(drop=True)
    kategorier = list(KATEGORIER)
    counts = maal[kategorier].to_numpy(dtype="float64")
    half_lives = np.array([KATEGORIER[k]["halveringstid"] for k in kategorier], dtype="float64")
    destinations = punkter(maal, "ssbid")
    date, start, minutes = TIDSVINDUER[vindu]
    modes = [r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK] if modus == "kollektiv" else [r5py.TransportMode.CAR]
    navn = f"{region}_{modus}_{vindu if modus == 'kollektiv' else 'statisk'}"
    out_dir = UT / navn
    out_dir.mkdir(parents=True, exist_ok=True)
    # Én R5-oppgave med mål og parametere; startpunktet byttes per tråd
    base_task = RegionalTask(
        network, origin=shapely.Point(float(maal.lon.iloc[0]), float(maal.lat.iloc[0])), destinations=destinations,
        departure=dt.datetime.combine(date, start), departure_time_window=dt.timedelta(minutes=minutes),
        transport_modes=modes, max_time=dt.timedelta(minutes=MAKS_REISETID),
        max_time_walking=dt.timedelta(minutes=MAKS_GANGTID), speed_walking=GANGHASTIGHET_KMT,
    )
    # Sorter geografisk slik at hver batch dekker et sammenhengende område
    opphav = opphav.sort_values(["fylkesnummer", "ssbid"]).reset_index(drop=True)
    n_batches = int(np.ceil(len(opphav) / batch))
    print(f"{navn}: {len(opphav):,} startruter, {len(maal):,} målruter, {n_batches} batcher, {opts.traader} tråder", flush=True)
    kolonner = kategorier + [f"{k}_{g}" for k in kategorier for g in (30, 60, 90)] + ["maalruter_naadd"]
    done = 0
    for b in range(n_batches):
        fil = out_dir / f"batch_{b:04d}.parquet"
        if fil.exists():
            continue
        if maks_batcher is not None and done >= maks_batcher:
            print("Stopper etter --maks-batcher")
            return
        t = time.time()
        del_opphav = opphav.iloc[b * batch:(b + 1) * batch]
        out = np.zeros((len(del_opphav), len(kolonner)), dtype="float64")

        def summer(i: int, tt: np.ndarray) -> None:
            # Reisetidsvektet rekkevidde per kategori og antall mål innen 30/60/90 min
            nadd = np.isfinite(tt)
            t_n, c_n = tt[nadd], counts[nadd]
            weights = np.power(0.5, t_n[:, None] / half_lives[None, :])
            out[i, : len(kategorier)] = (weights * c_n).sum(axis=0)
            col = len(kategorier)
            for k in range(len(kategorier)):
                for grense in (30, 60, 90):
                    out[i, col] = c_n[t_n <= grense, k].sum()
                    col += 1
            out[i, col] = nadd.sum()

        travel_times_parallel(network, base_task, del_opphav.lon.to_numpy(), del_opphav.lat.to_numpy(), summer, opts.traader)
        result = pd.DataFrame(out, columns=kolonner)
        result.insert(0, "ssbid", del_opphav.ssbid.to_numpy())
        result.to_parquet(fil)
        done += 1
        print(f"{navn} batch {b + 1}/{n_batches}: {len(del_opphav)} startruter, {time.time() - t:.0f} s", flush=True)
    samlet = pd.concat(pd.read_parquet(f) for f in sorted(out_dir.glob("batch_*.parquet")))
    samlet.to_parquet(UT / f"{navn}.parquet")
    print(f"Ferdig: {len(samlet):,} startruter → {navn}.parquet")


def transport_performance(network, region, bbox) -> None:
    """Befolkning nådd innen 30 min med kollektiv (07–08) fra hver 1 km-rute i bysentrene i regionen."""
    import degurba

    km = degurba.ruter_1km()
    km["bysenter"] = degurba.bysentre(km)
    fylke = pd.read_parquet(CACHE / "opphav.parquet", columns=["ssbid_1km", "fylkesnummer"]).groupby("ssbid_1km").fylkesnummer.agg(lambda f: f.mode().iat[0])
    km["fylkesnummer"] = km.ssbid_1km.map(fylke)
    opphav = km[(km.bysenter > 0) & km.fylkesnummer.isin(REGIONER[region])].reset_index(drop=True)
    x0, y0, x1, y1 = bbox
    maal = km[km.lon.between(x0, x1) & km.lat.between(y0, y1)].reset_index(drop=True)
    navn = f"{region}_tp_morgen"
    if opphav.empty:
        pd.DataFrame(columns=["ssbid_1km", "bysenter", "befolkning", "nadd_30"]).to_parquet(UT / f"{navn}.parquet")
        print(f"{navn}: ingen bysentre i regionen")
        return
    date, start, minutes = TIDSVINDUER["morgen"]
    base_task = RegionalTask(
        network, origin=shapely.Point(float(maal.lon.iloc[0]), float(maal.lat.iloc[0])), destinations=punkter(maal, "ssbid_1km"),
        departure=dt.datetime.combine(date, start), departure_time_window=dt.timedelta(minutes=minutes),
        transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK], max_time=dt.timedelta(minutes=TP_MAKS_REISETID),
        max_time_walking=dt.timedelta(minutes=MAKS_GANGTID), speed_walking=GANGHASTIGHET_KMT,
    )
    befolkning = maal.befolkning.to_numpy(dtype="float64")
    nadd = np.zeros(len(opphav))

    def summer(i: int, tt: np.ndarray) -> None:
        nadd[i] = befolkning[np.isfinite(tt) & (tt <= TP_MAKS_REISETID)].sum()

    t = time.time()
    travel_times_parallel(network, base_task, opphav.lon.to_numpy(), opphav.lat.to_numpy(), summer, opts.traader)
    UT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ssbid_1km": opphav.ssbid_1km, "bysenter": opphav.bysenter, "befolkning": opphav.befolkning, "nadd_30": nadd}).to_parquet(UT / f"{navn}.parquet")
    print(f"{navn}: {len(opphav)} bysenterruter på {time.time() - t:.0f} s")


def main() -> None:
    bboxes = region_bboxes(pd.read_parquet(CACHE / "opphav.parquet", columns=["fylkesnummer", "lon", "lat"]))
    for name, bbox in bboxes.items():
        print(f"Region {name}: {tuple(round(float(v), 2) for v in bbox)} ≈ {area_km2(bbox):,.0f} km²")
    network = nettverk(opts.region, bboxes[opts.region], bboxes)
    if opts.test:
        test(network, opts.region)
    elif opts.modus == "tp":
        transport_performance(network, opts.region, bboxes[opts.region])
    else:
        rekkevidde(network, opts.region, bboxes[opts.region], opts.modus, opts.vindu, opts.batch, opts.maks_batcher)


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except Exception:
        traceback.print_exc()
        exit_code = 1
    finally:
        # JVM-en til r5py holder prosessen i live etter en feil; avslutt hardt
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
