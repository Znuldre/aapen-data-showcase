"""Parallell bruk av R5 via r5py: én TravelTimeComputer per startpunkt, i en trådpool.

r5py.TravelTimeMatrix går gjennom startpunktene ett om gangen og bygger en DataFrame for hvert,
og bruker derfor bare én kjerne. R5-nettverket er skrivebeskyttet under beregningen, og JPype
slipper GIL-en i Java-kall, så flere tråder kan regne samtidig mot samme nettverk.

Importeres først etter at r5py er importert (JVM-en må være startet).
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import jpype
import numpy as np
import shapely

MAX_INT32 = 2**31 - 1


def travel_times_parallel(
    network,
    base_task,
    lons: np.ndarray,
    lats: np.ndarray,
    consumer: Callable[[int, np.ndarray], None],
    threads: int = 14,
) -> None:
    """Kaller `consumer(i, reisetider)` for hvert startpunkt i; NaN betyr ikke nådd innen maks tid.

    `base_task` er en r5py.r5.RegionalTask med mål og reiseparametere satt. Reisetidene er i
    minutter og i samme rekkefølge som målene i oppgaven.
    """
    computer = jpype.JClass("com.conveyal.r5.analyst.TravelTimeComputer")

    def run(i: int) -> None:
        task = copy.copy(base_task)
        task.origin = shapely.Point(float(lons[i]), float(lats[i]))
        result = computer(task, network).computeTravelTimes()
        times = np.asarray(result.travelTimes.getValues()[0], dtype="float64")
        times[times >= MAX_INT32] = np.nan
        consumer(i, times)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        for _ in pool.map(run, range(len(lons))):
            pass
