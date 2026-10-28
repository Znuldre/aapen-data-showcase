"""Tilgjengelighetsindikatorer: reisetidsvekting, metning, transportvalgfrihet, A–G og ulikhet.

Strukturen følger Danmarks Mobilitetsatlas (Beta Mobility): mobilitetsfrihet er snittet av
kollektiv kvalitet og transportvalgfrihet. Parameterne er våre egne og publiseres i METODE.md.
"""

from __future__ import annotations

import numpy as np

# A–G-grenser fra Danmarks Mobilitetsatlas (nedre grense for hver karakter)
DK_BANDS: tuple[tuple[str, float], ...] = (
    ("A", 70), ("B", 55), ("C", 45), ("D", 30), ("E", 22), ("F", 15), ("G", 0),
)


def decay(minutes, half_life: float, max_minutes: float = 90.0):
    """Reisetidsvekt: halveres hver `half_life` minutt, null over `max_minutes`."""
    t = np.asarray(minutes, dtype="float64")
    w = np.power(0.5, t / half_life)
    return np.where((t <= max_minutes) & np.isfinite(t), w, 0.0)


def saturate(reach, target: float):
    """Mettende kurve 1 − e^(−3·x/target): gir 0,95 når rekkevidden når målet."""
    x = np.asarray(reach, dtype="float64")
    return 1.0 - np.exp(-3.0 * x / target)


def transport_choice(reach_pt, reach_car, low_total: float):
    """Transportvalgfrihet (0–100): 100 når kollektiv når like mye som bil.

    100 · (1 − (bil − kollektiv)/(bil + kollektiv)) = 100 · 2·kollektiv/(kollektiv + bil),
    begrenset til 100. Skaleres ned når samlet rekkevidde er under `low_total`,
    slik at to like dårlige alternativer ikke ser ut som frihet.
    """
    pt = np.asarray(reach_pt, dtype="float64")
    car = np.asarray(reach_car, dtype="float64")
    total = pt + car
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(total > 0, 2.0 * pt / total, 0.0)
    scale = np.clip(total / low_total, 0.0, 1.0)
    return 100.0 * np.clip(ratio, 0.0, 1.0) * scale


def band(scores, bands=DK_BANDS):
    """Karakter for hver score; en score lik en grense får den høyeste karakteren."""
    s = np.asarray(scores, dtype="float64")
    out = np.full(s.shape, bands[-1][0], dtype=object)
    for letter, lower in reversed(bands):
        out = np.where(s >= lower, letter, out)
    return out


def weighted_quantile_bands(scores, weights, quantiles=(0.05, 0.15, 0.30, 0.50, 0.70, 0.85)):
    """NO-skala: grenser ved befolkningsvektede persentiler (G nederst, A øverst)."""
    s = np.asarray(scores, dtype="float64")
    w = np.asarray(weights, dtype="float64")
    order = np.argsort(s)
    cum = np.cumsum(w[order]) / w.sum()
    cuts = [float(s[order][np.searchsorted(cum, q)]) for q in quantiles]
    letters = ("G", "F", "E", "D", "C", "B", "A")
    return tuple(zip(reversed(letters), [*reversed(cuts), 0.0][: len(letters)]))


def gini(values, weights=None) -> float:
    """Vektet Gini-koeffisient (0 = helt likt, 1 = maksimalt ulikt)."""
    x = np.asarray(values, dtype="float64")
    w = np.ones_like(x) if weights is None else np.asarray(weights, dtype="float64")
    mask = (w > 0) & np.isfinite(x)
    x, w = x[mask], w[mask]
    if x.size == 0 or x.sum() == 0:
        return 0.0
    order = np.argsort(x)
    x, w = x[order], w[order]
    cw = np.cumsum(w) / w.sum()
    cx = np.cumsum(x * w) / (x * w).sum()
    # Arealet under Lorenzkurven med trapesregelen
    area = np.sum((cx + np.concatenate(([0.0], cx[:-1]))) * np.diff(np.concatenate(([0.0], cw)))) / 2.0
    return float(1.0 - 2.0 * area)


def lorenz(values, weights=None, points: int = 21):
    """Lorenzkurve som (andel befolkning, andel tilgjengelighet) i `points` punkter."""
    x = np.asarray(values, dtype="float64")
    w = np.ones_like(x) if weights is None else np.asarray(weights, dtype="float64")
    order = np.argsort(x)
    x, w = x[order], w[order]
    cw = np.concatenate(([0.0], np.cumsum(w) / w.sum()))
    total = (x * w).sum()
    cx = np.concatenate(([0.0], np.cumsum(x * w) / total)) if total > 0 else cw
    grid = np.linspace(0, 1, points)
    return grid, np.interp(grid, cw, cx)
