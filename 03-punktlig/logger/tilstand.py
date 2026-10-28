"""Siste kjente tilstand per tur, og utvalget av stoppkall som er klare til å lagres.

Et stoppkall lagres først når det er avklart: kjøretøyet har passert (RecordedCall), eller beste
kjente tid ligger mer enn AVKLART_ETTER sekunder bak oss. Endres et lagret kall senere (f.eks. en
korrigert faktisk tid), lagres det på nytt; sammenslåingen beholder raden med senest `observert`.
Slik blir det én rad per stoppkall med siste kjente verdi, uten prognosehistorikk.
"""

from __future__ import annotations

from siri import Kall, Tur


def _forsinkelse(faktisk: int | None, forventet: int | None, planlagt: int | None) -> int | None:
    tid = faktisk or forventet
    return tid - planlagt if tid and planlagt else None


def rad(tur: Tur, k: Kall, observert: int) -> tuple:
    """Én rad i samme rekkefølge som lager.KOLONNER."""
    return (
        tur.kilde, tur.dato, tur.datasett, tur.operator, tur.linje, tur.linjenummer, tur.modus,
        tur.kategori, tur.tur_id, tur.retning, k.rekkefolge, k.holdeplass, k.navn,
        k.planlagt_ank, k.planlagt_avg, k.forventet_ank, k.forventet_avg, k.faktisk_ank, k.faktisk_avg,
        _forsinkelse(k.faktisk_ank, k.forventet_ank, k.planlagt_ank),
        _forsinkelse(k.faktisk_avg, k.forventet_avg, k.planlagt_avg),
        k.kansellert, k.registrert, tur.ekstratur, observert,
    )


def _signatur(tur: Tur, k: Kall) -> int:
    return hash((
        k.holdeplass, k.forventet_ank, k.forventet_avg, k.faktisk_ank, k.faktisk_avg,
        k.kansellert, k.registrert, tur.modus, tur.linjenummer,
    ))


class Tilstand:
    """Turene én kilde har meldt, med hva som allerede er lagret per stoppkall."""

    def __init__(self, avklart_etter: int, glem_ferdig_etter: int, glem_etter: int):
        self.avklart_etter = avklart_etter
        self.glem_ferdig_etter = glem_ferdig_etter
        self.glem_etter = glem_etter
        self.turer: dict[str, Tur] = {}
        self.sett: dict[str, int] = {}  # sist meldt (Unix-sekunder)
        self.skrevet: dict[str, dict[int, int]] = {}  # rekkefølge -> signatur av lagret rad

    def __len__(self) -> int:
        return len(self.turer)

    def oppdater(self, tur: Tur, naa: int) -> None:
        nokkel = tur.nokkel
        self.turer[nokkel] = tur
        self.sett[nokkel] = naa
        self.skrevet.setdefault(nokkel, {})

    def sveip(self, naa: int, observert: int | None = None) -> list[tuple]:
        """Rader for avklarte stoppkall som er nye eller endret siden sist; glemmer gamle turer."""
        observert = observert or naa
        grense = naa - self.avklart_etter
        rader: list[tuple] = []
        for nokkel in list(self.turer):
            tur = self.turer[nokkel]
            skrevet = self.skrevet[nokkel]
            siste = 0
            for k in tur.kall:
                tid = k.beste_tid() or 0
                siste = max(siste, tid)
                if not (k.registrert or (tid and tid < grense)):
                    continue
                sig = _signatur(tur, k)
                if skrevet.get(k.rekkefolge) != sig:
                    rader.append(rad(tur, k, observert))
                    skrevet[k.rekkefolge] = sig
            stille = naa - self.sett[nokkel]
            if (stille > self.glem_ferdig_etter and siste < naa - self.glem_ferdig_etter) or stille > self.glem_etter:
                del self.turer[nokkel], self.sett[nokkel], self.skrevet[nokkel]
        return rader

    def antall_kall(self) -> int:
        return sum(len(t.kall) for t in self.turer.values())
