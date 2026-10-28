"""Kjører steg 4 for alle regioner: kollektiv per tidsvindu og bil, én prosess (én JVM) om gangen.

Morgen og bil kjøres først, region for region, slik at de DK-sammenlignbare tallene blir klare
tidligst. Ferdige kjøringer hoppes over, og avbrutte kjøringer fortsetter fra siste lagrede batch.

Kjøres fra prosjektroten:  .venv/Scripts/python.exe -I 01-mobilitetsatlas/pipeline/04_alle.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CACHE, REGIONER, TIDSVINDUER  # noqa: E402

SCRIPT = Path(__file__).with_name("04_reisetider.py")
LOGG = CACHE / "logg"


def jobber() -> list[tuple[str, str, str | None]]:
    # Region for region: morgen og bil først (gir komplett mobilitetsfrihet), deretter kveld og lørdag
    out: list[tuple[str, str, str | None]] = []
    for r in REGIONER:
        out += [(r, "kollektiv", "morgen"), (r, "bil", None)]
    out += [(r, "tp", "morgen") for r in REGIONER]  # EUs transport performance (liten kjøring)
    out += [(r, "kollektiv", v) for v in TIDSVINDUER if v != "morgen" for r in REGIONER]
    return out


def main() -> None:
    # Valgfritt filter, f.eks. --bare kollektiv:morgen eller --bare bil
    bare = sys.argv[sys.argv.index("--bare") + 1] if "--bare" in sys.argv else None
    LOGG.mkdir(parents=True, exist_ok=True)
    for region, modus, vindu in jobber():
        if bare and f"{modus}:{vindu}" != bare and modus != bare:
            continue
        navn = f"{region}_{modus}_{vindu or 'statisk'}"
        if (CACHE / "tilgjengelighet" / f"{navn}.parquet").exists():
            print(f"[ferdig] {navn}")
            continue
        cmd = [sys.executable, "-I", str(SCRIPT), "--region", region, "--modus", modus, *(["--vindu", vindu] if vindu else [])]
        t = time.time()
        print(f"[starter] {navn}", flush=True)
        with open(LOGG / f"{navn}.log", "a", encoding="utf-8") as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=False)
        status = "ok" if result.returncode == 0 else f"feil (kode {result.returncode})"
        print(f"[{status}] {navn} på {(time.time() - t) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
