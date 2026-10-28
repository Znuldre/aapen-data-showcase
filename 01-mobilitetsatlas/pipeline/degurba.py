"""Bysentre etter EUs DEGURBA på SSBs 1 km-rutenett.

Et bysenter er en sammenhengende klynge (kant mot kant) av 1 km-ruter med minst 1 500 innbyggere
per km², med minst 50 000 innbyggere til sammen. Hull fylles og kanter jevnes ut ved at ruter med
minst fem av åtte naboer i klyngen legges til, gjentatt til ingenting endrer seg (som i DEGURBA).
Brukes for EUs «transport performance».
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyogrio
from scipy import ndimage

from config import BYSENTER_MIN_BEFOLKNING, BYSENTER_TETTHET, RAW
from showcase_shared.ssb_grid import xy_from_ssbid

G1KM = f"/vsizip/{(RAW / 'ssb-rutenett-1km' / 'rutenett1km_2025.zip').as_posix()}/Befolkning_0000_Norge_25833_BefolkningsstatistikkRutenett1km2025_GML.gml"


def ruter_1km() -> pd.DataFrame:
    """Befolkede 1 km-ruter med midtpunkt i EPSG:25833 og lengde-/breddegrad."""
    from pyproj import Transformer

    km = pyogrio.read_dataframe(G1KM, layer="BefolkningPåRuter1km", columns=["ssbid1000M", "popTot"], read_geometry=False)
    km = km.rename(columns={"ssbid1000M": "ssbid_1km", "popTot": "befolkning"}).astype({"ssbid_1km": "int64"})
    x0, y0 = xy_from_ssbid(km.ssbid_1km.to_numpy())
    km["x"], km["y"] = x0 + 500.0, y0 + 500.0
    km["lon"], km["lat"] = Transformer.from_crs(25833, 4326, always_xy=True).transform(km.x.to_numpy(), km.y.to_numpy())
    return km


def bysentre(km: pd.DataFrame) -> pd.Series:
    """Bysenter-ID per 1 km-rute (0 = ikke bysenter)."""
    ix = ((km.x - 500) // 1000).astype(int).to_numpy()
    iy = ((km.y - 500) // 1000).astype(int).to_numpy()
    ix0, iy0 = ix.min(), iy.min()
    grid = np.zeros((iy.max() - iy0 + 1, ix.max() - ix0 + 1), dtype=bool)
    tett = km.befolkning.to_numpy() >= BYSENTER_TETTHET
    grid[iy[tett] - iy0, ix[tett] - ix0] = True
    labels, _ = ndimage.label(grid)  # kant mot kant (4-naboskap)
    klynge = labels[iy - iy0, ix - ix0]
    klynge[~tett] = 0
    befolkning = pd.Series(km.befolkning.to_numpy()).groupby(klynge).sum()
    store = befolkning[(befolkning.index > 0) & (befolkning >= BYSENTER_MIN_BEFOLKNING)].index
    # Fyll hull og jevn ut kanter: legg til ruter med minst 5 av 8 naboer i samme bysenter
    senter = np.where(np.isin(labels, store), labels, 0)
    naboer = np.ones((3, 3), dtype=int)
    naboer[1, 1] = 0
    while True:
        endret = False
        for lab in store:
            maske = senter == lab
            antall = ndimage.convolve(maske.astype(int), naboer, mode="constant")
            nye = (antall >= 5) & (senter == 0)
            if nye.any():
                senter[nye] = lab
                endret = True
        if not endret:
            break
    return pd.Series(senter[iy - iy0, ix - ix0], index=km.index, name="bysenter")
