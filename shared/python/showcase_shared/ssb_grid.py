"""SSBs statistiske rutenett (EPSG:25833): konvertering mellom rute-ID og koordinater.

SSB-ID-en er 14 sifre: (x + 2 000 000) * 10^7 + y, der (x, y) er nedre venstre hjørne
av ruten i UTM sone 33. Forskyvningen holder x positiv også vest i landet.
"""

from __future__ import annotations

import numpy as np

X_OFFSET = 2_000_000
Y_FACTOR = 10_000_000


def ssbid_from_xy(x, y, size: int = 250):
    """Rute-ID for punktet (x, y) i EPSG:25833 og gitt rutestørrelse i meter."""
    x0 = np.floor(np.asarray(x, dtype="float64") / size) * size
    y0 = np.floor(np.asarray(y, dtype="float64") / size) * size
    return ((x0 + X_OFFSET).astype("int64") * Y_FACTOR + y0.astype("int64"))


def xy_from_ssbid(ssbid):
    """Nedre venstre hjørne (x, y) i EPSG:25833 for rute-ID-er."""
    ids = np.asarray(ssbid, dtype="int64")
    return ids // Y_FACTOR - X_OFFSET, ids % Y_FACTOR


def centroid_from_ssbid(ssbid, size: int = 250):
    x0, y0 = xy_from_ssbid(ssbid)
    return x0 + size / 2, y0 + size / 2


def parent_ssbid(ssbid, size: int = 250, parent_size: int = 1000):
    """ID for ruten av størrelse `parent_size` som inneholder ruten."""
    x, y = centroid_from_ssbid(ssbid, size)
    return ssbid_from_xy(x, y, parent_size)
