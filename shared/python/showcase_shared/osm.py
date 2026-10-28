"""Klipping av OSM-data til regioner for R5.

R5 godtar et gatenett med utstrekning på inntil 975 000 km², mens Norge er rundt det dobbelte.
Vi klipper derfor ut alle ways som er relevante for ruting (veier, ferjer, plattformer) og
som overlapper regionens avgrensning, og tar med alle nodene de bruker. Relasjoner
(svingrestriksjoner) tas ikke med.

Klippingen går i to pass i stedet for via osmium.BackReferenceWriter, som på Windows prøver å
slette en midlertidig fil som fortsatt er åpen.
"""

from __future__ import annotations

import os
from pathlib import Path

import osmium

ROUTING_KEYS = ("highway", "route", "public_transport", "railway")


def _ascii_path(path: Path) -> str:
    """libosmium åpner filer med smale (ANSI) stier på Windows og feiler på tegn som «Å».
    En relativ sti fra arbeidsmappen (prosjektroten) er ren ASCII."""
    for candidate in (os.path.relpath(path), str(path)):
        if candidate.isascii():
            return candidate
    raise RuntimeError(f"Stien må være ASCII for libosmium – kjør fra prosjektroten: {path}")


def clip_regions(pbf: Path, regions: dict[str, tuple[float, float, float, float]], out_dir: Path) -> dict[str, Path]:
    """Skriver én PBF per region (min_lon, min_lat, max_lon, max_lat); eksisterende filer gjenbrukes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    outs = {name: out_dir / f"{name}.osm.pbf" for name in regions}
    todo = {name: bbox for name, bbox in regions.items() if not outs[name].exists()}
    if not todo:
        return outs

    # Pass 1: ways som overlapper regionen, og hvilke noder de trenger
    trackers = {name: osmium.IdTracker() for name in todo}
    way_files = {name: out_dir / f"{name}.ways.osm.pbf" for name in todo}
    way_writers = {name: osmium.SimpleWriter(_ascii_path(way_files[name]), overwrite=True) for name in todo}
    processor = (
        osmium.FileProcessor(_ascii_path(pbf), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter(*ROUTING_KEYS))
    )
    try:
        for way in processor:
            lons, lats = [], []
            for node in way.nodes:
                if node.location.valid():
                    lons.append(node.lon)
                    lats.append(node.lat)
            if not lons:
                continue
            w_min_lon, w_max_lon, w_min_lat, w_max_lat = min(lons), max(lons), min(lats), max(lats)
            for name, (x0, y0, x1, y1) in todo.items():
                if w_max_lon >= x0 and w_min_lon <= x1 and w_max_lat >= y0 and w_min_lat <= y1:
                    way_writers[name].add_way(way)
                    trackers[name].add_references(way)
    finally:
        for writer in way_writers.values():
            writer.close()

    # Pass 2: nodene (i C++ via filter og WriteHandler), deretter waysene, i én fil
    for name in todo:
        tmp = out_dir / f"{name}.tmp.osm.pbf"
        handler = osmium.WriteHandler(_ascii_path(tmp))
        try:
            osmium.apply(_ascii_path(pbf), osmium.filter.EntityFilter(osmium.osm.NODE), trackers[name].id_filter(), handler)
            osmium.apply(_ascii_path(way_files[name]), handler)
        finally:
            handler.close()
        tmp.replace(outs[name])
        way_files[name].unlink()
    return outs
