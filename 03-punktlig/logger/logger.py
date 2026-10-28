"""Punktlig-loggeren: samler sanntidsdata om punktlighet fra Entur og Bane NOR, fra nå av.

Norge har ikke noe åpent historisk punktlighetsarkiv, så historikken må bygges ved å logge
sanntidsdata løpende. Loggeren henter
- Enturs SIRI Lite ET (alle operatører i landet unntatt fly) hvert 7,5. minutt, som Avro med XML som
  reserve, og
- Bane NORs SIRI ET (alle tog, også godstog, med faktiske tider fra infrastrukturen) hvert 3. minutt,
og lagrer siste kjente verdi per stoppkall i daglige Parquet-filer under 03-punktlig/data/.
Hvorfor disse intervallene og formatene er valgt, står i config.py.

Kjøres fra prosjektroten, i forgrunnen (Ctrl+C avslutter pent):
    .venv/Scripts/python.exe -I 03-punktlig/logger/logger.py
I bakgrunnen startes og stoppes den med start.ps1 og stopp.ps1 i samme mappe.
--en-runde henter én gang fra hver kilde, lagrer og avslutter (til testing).
"""

from __future__ import annotations

import os

# pyarrow drar inn numpy, og OpenBLAS binder ellers ≈ 0,5 GB minne og 16 tråder som aldri brukes
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import json
import logging
import logging.handlers
import shutil
import signal
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import config as C  # noqa: E402
from lager import Lager  # noqa: E402
from linjer import Linjeregister  # noqa: E402
from showcase_shared.env import entur_client_name  # noqa: E402
from siri import les_et  # noqa: E402
from siri_avro import MAGI, UkjentSkjema, les_et_avro  # noqa: E402
from tilstand import Tilstand  # noqa: E402

log = logging.getLogger("punktlig")
VERSJON = "0.1"


class Kilde:
    navn = ""
    intervall = 60

    def __init__(self, okt: requests.Session):
        self.okt = okt
        self.tilstand = Tilstand(C.AVKLART_ETTER, C.GLEM_FERDIG_ETTER, C.GLEM_ETTER)
        self.neste = 0.0
        self.feil_pa_rad = 0
        self.status: dict = {"kall": 0, "feil": 0, "byte_nett": 0, "byte_svar": 0, "cpu_s": 0.0, "rader": 0}

    def url_og_parametre(self) -> tuple[str, dict]:
        raise NotImplementedError

    def poll(self, registre: Linjeregister) -> None:
        self.hent(registre, "xml")

    def hent(self, registre: Linjeregister, format_: str) -> None:
        """Henter ett uttrekk i `format_` ("xml" eller "avro") og oppdaterer tilstanden."""
        url, parametre = self.url_og_parametre()
        hoder = {"Accept": "application/avro"} if format_ == "avro" else {}
        t0 = time.perf_counter()
        cpu0 = time.process_time()
        C.TMP.mkdir(parents=True, exist_ok=True)
        # Svaret lastes ned helt før parsing, så en treg parser (lav prioritet) ikke holder forbindelsen
        with tempfile.SpooledTemporaryFile(max_size=32 << 20, dir=C.TMP) as buf:
            with self.okt.get(url, params=parametre, headers=hoder, stream=True, timeout=(15, 180)) as r:
                if r.status_code == 429:
                    raise Hastighetsgrense(r.headers.get("rate-limit-expiry-time", ""))
                if format_ == "avro" and r.status_code in (406, 415):
                    raise UkjentSkjema(f"HTTP {r.status_code} på Accept: application/avro")
                r.raise_for_status()
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, buf, 1 << 20)
                nett = r.raw.tell()
            storrelse = buf.tell()
            buf.seek(0)
            avro = buf.read(len(MAGI)) == MAGI  # svaret selv avgjør formatet, ikke hva vi ba om
            buf.seek(0)
            t1 = time.perf_counter()
            info: dict = {}
            naa = int(time.time())
            turer = 0
            for tur in (les_et_avro if avro else les_et)(buf, self.navn, info):
                if self.navn == "entur":
                    if tur.datasett in C.ENTUR_UTELAT:
                        continue
                    registre.fyll(tur)
                self.tilstand.oppdater(tur, naa)
                turer += 1
        self.etter_svar(r, info)
        self.feil_pa_rad = 0
        cpu = time.process_time() - cpu0
        s = self.status
        s.update(kall=s["kall"] + 1, byte_nett=s["byte_nett"] + nett, byte_svar=s["byte_svar"] + storrelse,
                 cpu_s=round(s["cpu_s"] + cpu, 2), format="avro" if avro else "xml",
                 sist_ok=naa, sist_turer=turer, turer_i_minne=len(self.tilstand))
        log.info("%s: %d turer, %.1f MB %s (%.2f MB over nett), hentet på %.1f s, lest på %.1f s, CPU %.2f s; "
                 "%d turer i minnet", self.navn, turer, storrelse / 1e6, "Avro" if avro else "XML", nett / 1e6,
                 t1 - t0, time.perf_counter() - t1, cpu, len(self.tilstand))

    def etter_svar(self, r: requests.Response, info: dict) -> None:
        self.neste = time.time() + self.intervall

    def ved_feil(self, feil: Exception) -> None:
        self.feil_pa_rad += 1
        self.status["feil"] += 1
        self.status["siste_feil"] = f"{time.strftime('%Y-%m-%d %H:%M:%S')}: {feil}"[:300]
        if isinstance(feil, Hastighetsgrense):
            vent = 65
        else:  # raskt nytt forsøk, så et kort brudd ikke gir hull: 30 s, 60 s, 120 s … opp til intervallet
            vent = min(30 * 2 ** (self.feil_pa_rad - 1), max(self.intervall, 300))
        self.neste = time.time() + vent
        log.warning("%s: %s – nytt forsøk om %d s", self.navn, feil, vent)


class Hastighetsgrense(Exception):
    def __str__(self) -> str:
        return f"HTTP 429 (hastighetsgrense) {self.args[0] if self.args else ''}".strip()


class Entur(Kilde):
    navn = "entur"
    intervall = C.ENTUR_INTERVALL

    def __init__(self, okt: requests.Session):
        super().__init__(okt)
        self.avro_pause_til = 0.0

    def url_og_parametre(self) -> tuple[str, dict]:
        return C.ENTUR_ET, {"maxSize": C.ENTUR_MAKS}

    def poll(self, registre: Linjeregister) -> None:
        if C.ENTUR_FORMAT != "avro" or time.time() < self.avro_pause_til:
            self.hent(registre, "xml")
            return
        try:
            self.hent(registre, "avro")
        except UkjentSkjema as feil:
            # Entur har trolig endret Avro-skjemaet. Ingen turer er lest ennå, så samme runde hentes
            # som XML (to kall i samme minutt er godt innenfor kvoten), og XML brukes en stund.
            self.avro_pause_til = time.time() + C.ENTUR_AVRO_PAUSE
            self.status["avro_reserve"] = f"{time.strftime('%Y-%m-%d %H:%M:%S')}: {feil}"[:300]
            log.warning("entur: kan ikke lese Avro-svaret (%s); henter XML nå og de neste %.0f timene",
                        feil, C.ENTUR_AVRO_PAUSE / 3600)
            self.hent(registre, "xml")

    def etter_svar(self, r: requests.Response, info: dict) -> None:
        self.status["rate_limit_ledig"] = r.headers.get("rate-limit-available")
        if info.get("mer_data"):
            log.warning("entur: svaret ble kuttet ved maxSize=%d (MoreData); øk ENTUR_MAKS", C.ENTUR_MAKS)
        super().etter_svar(r, info)


class BaneNor(Kilde):
    navn = "banenor"
    intervall = C.BANENOR_INTERVALL

    def url_og_parametre(self) -> tuple[str, dict]:
        return C.BANENOR_ET, {"PreviewInterval": C.BANENOR_FORHANDSVISNING}


class Laas:
    """Hindrer at to loggere kjører samtidig (låsen slippes automatisk hvis prosessen dør)."""

    def __init__(self, sti: Path):
        self.sti = sti
        self.fil = None

    def ta(self) -> bool:
        self.fil = open(self.sti, "a+b")
        try:
            self.fil.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fil.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fil, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.fil.close()
            return False


def sett_opp_logging() -> None:
    C.DATA.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fil = logging.handlers.RotatingFileHandler(C.LOGG, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fil.setFormatter(fmt)
    log.addHandler(fil)
    if sys.stderr is not None:  # uten konsoll (pythonw) finnes ingen stderr
        konsoll = logging.StreamHandler()
        konsoll.setFormatter(fmt)
        log.addHandler(konsoll)
    log.setLevel(logging.INFO)
    sys.excepthook = lambda *exc: log.critical("Uventet feil", exc_info=exc)


def sett_prioritet(lav: bool) -> None:
    """Lav prioritet gjør at lange beregninger (R5) ikke merker loggeren."""
    try:
        import psutil
        p = psutil.Process()
        if os.name == "nt":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if lav else psutil.NORMAL_PRIORITY_CLASS)
        else:
            p.nice(10 if lav else 0)
    except Exception:
        log.warning("Kunne ikke endre prosessprioriteten", exc_info=True)


@contextmanager
def normal_prioritet():
    """Sammenslåing med DuckDB sulter helt ut på lav prioritet når CPU-en er full (10 s mot 0,6 s),
    så den får kortvarig normal prioritet. Den tar noen sekunder i timen på én tråd."""
    sett_prioritet(False)
    try:
        yield
    finally:
        sett_prioritet(True)


def skriv_status(kilder: list[Kilde], start: float, ekstra: dict) -> None:
    status = {
        "versjon": VERSJON, "pid": os.getpid(), "startet": int(start), "oppdatert": int(time.time()),
        **ekstra, "kilder": {k.navn: k.status for k in kilder},
    }
    delvis = C.STATUS.with_name(C.STATUS.name + ".part")
    try:
        delvis.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(delvis, C.STATUS)
    except OSError:  # status.json er åpen i en annen prosess (Windows); neste skriving tar den igjen
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kilder", default="entur,banenor", help="kommaseparert: entur,banenor")
    ap.add_argument("--en-runde", action="store_true", help="én henting per kilde, lagre og avslutt")
    args = ap.parse_args()

    sett_opp_logging()
    laas = Laas(C.LAAS)
    if not laas.ta():
        log.error("En annen logger kjører allerede (se %s)", C.PID)
        return 1
    C.PID.write_text(str(os.getpid()), encoding="utf-8")
    C.STOPPFIL.unlink(missing_ok=True)
    sett_prioritet(True)

    stopp = {"flagg": False}

    def ved_signal(signum, _frame):
        log.info("Fikk signal %s, avslutter", signum)
        stopp["flagg"] = True

    for navn in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, navn):
            signal.signal(getattr(signal, navn), ved_signal)

    okt = requests.Session()
    okt.headers.update({"User-Agent": f"aapendata-showcase-punktlig/{VERSJON}", "Accept-Encoding": "gzip"})
    entur_okt = requests.Session()
    entur_okt.headers.update({**okt.headers, "ET-Client-Name": entur_client_name()})

    valgt = set(args.kilder.split(","))
    kilder: list[Kilde] = [k for k in (Entur(entur_okt), BaneNor(okt)) if k.navn in valgt]
    lager = Lager(C.STOPPKALL, C.STAGING, C.TMP)
    registre = Linjeregister(C.LINJER, C.ENTUR_JP, entur_okt)
    registre.oppdater(C.LINJER_INTERVALL)

    def komprimer() -> None:
        with normal_prioritet():
            lager.komprimer_alle()

    komprimer()  # rester fra forrige kjøring

    start = time.time()
    buffer: dict[str, list[tuple]] = {k.navn: [] for k in kilder}
    neste_sveip = time.time() + C.SVEIP_INTERVALL
    neste_skriv = time.time() + C.SKRIV_INTERVALL
    neste_komprimering = time.time() + C.KOMPRIMER_INTERVALL
    log.info("Punktlig-logger %s startet (pid %d): %s", VERSJON, os.getpid(), ", ".join(k.navn for k in kilder))

    def sveip() -> None:
        naa = int(time.time())
        for k in kilder:
            rader = k.tilstand.sveip(naa)
            buffer[k.navn].extend(rader)

    def skriv() -> None:
        for k in kilder:
            if buffer[k.navn]:
                n = lager.skriv(k.navn, buffer[k.navn])
                k.status["rader"] += n
                buffer[k.navn] = []
        skriv_status(kilder, start, {"ventende_staging": lager.ventende()})

    while not stopp["flagg"]:
        naa = time.time()
        for k in kilder:
            if naa >= k.neste:
                try:
                    k.poll(registre)
                except Exception as feil:
                    k.ved_feil(feil)
                skriv_status(kilder, start, {})
        if args.en_runde:
            break
        if C.STOPPFIL.exists():
            log.info("Fant %s, avslutter", C.STOPPFIL.name)
            break
        naa = time.time()
        try:  # en feil i lagringen skal ikke stoppe innsamlingen; radene blir liggende til neste forsøk
            if naa >= neste_sveip:
                neste_sveip = naa + C.SVEIP_INTERVALL
                sveip()
            if naa >= neste_skriv:
                neste_skriv = naa + C.SKRIV_INTERVALL
                skriv()
            if naa >= neste_komprimering:
                neste_komprimering = naa + C.KOMPRIMER_INTERVALL
                komprimer()
            if naa - registre.hentet > C.LINJER_INTERVALL:
                registre.oppdater(C.LINJER_INTERVALL)
        except Exception:
            log.exception("Feil under lagring")
        neste = min([k.neste for k in kilder] + [neste_sveip, neste_skriv])
        time.sleep(max(0.2, min(1.0, neste - time.time())))

    # Pen avslutning: lagre det som er avklart, slå sammen og frigjør låsen
    sveip()
    skriv()
    komprimer()
    skriv_status(kilder, start, {"avsluttet": int(time.time())})
    C.PID.unlink(missing_ok=True)
    C.STOPPFIL.unlink(missing_ok=True)
    log.info("Punktlig-logger avsluttet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
