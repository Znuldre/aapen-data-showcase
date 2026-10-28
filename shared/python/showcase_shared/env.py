"""Leser .env i prosjektroten og gir tilgang til identifikasjon og Java-oppsett."""

from __future__ import annotations

import os
from pathlib import Path

# shared/python/showcase_shared/env.py -> prosjektroten
ROOT = Path(__file__).resolve().parents[3]


def load_env(path: Path | None = None) -> dict[str, str]:
    """Leser KEY=VALUE-linjer og fyller inn miljøvariabler som ikke allerede er satt."""
    path = path or ROOT / ".env"
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    for key, value in values.items():
        if value and not os.environ.get(key):
            os.environ[key] = value
    return values


def entur_client_name() -> str:
    """Entur krever ET-Client-Name på formen <organisasjon>-<applikasjon> i alle kall."""
    load_env()
    name = os.environ.get("ENTUR_CLIENT_NAME", "").strip()
    if not name:
        raise RuntimeError("ENTUR_CLIENT_NAME mangler i .env (format: <organisasjon>-<applikasjon>)")
    return name


def configure_java() -> Path:
    """r5py starter JVM-en ved import, så JAVA_HOME må være satt før `import r5py`."""
    load_env()
    java_home = os.environ.get("JAVA_HOME", "").strip()
    if not java_home:
        raise RuntimeError("JAVA_HOME mangler i .env – r5py trenger en JDK (versjon 21 eller nyere)")
    path = Path(java_home)
    if not (path / "bin").exists():
        raise RuntimeError(f"JAVA_HOME peker ikke på en JDK: {path}")
    return path
