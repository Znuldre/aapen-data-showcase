"""Nedlasting med proveniens: kilde, lisens, tidspunkt, HTTP-headere, størrelse og SHA-256.

Hver nedlasting får én linje i en JSONL-logg, slik at alle tall i produktene kan spores
tilbake til en bestemt fil fra en bestemt kilde.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import requests

KEPT_HEADERS = ("Last-Modified", "ETag", "Content-Length", "Content-Type")


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _headers_from_file(path: Path) -> dict[str, str]:
    """Leser headere lagret av `curl -D` (brukes for filer lastet ned utenfor pipelinen)."""
    found: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() in {h.lower() for h in KEPT_HEADERS}:
                found[key.strip()] = value.strip()
    return found


def download(
    url: str,
    dest: Path,
    *,
    log: Path,
    source: str,
    license: str,
    method: str = "GET",
    json_body: dict | None = None,
    headers: dict[str, str] | None = None,
    force: bool = False,
) -> Path:
    """Laster ned `url` til `dest` (hopper over hvis filen finnes) og logger proveniens."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    status = "fantes"
    http: dict[str, str] = _headers_from_file(dest.parent / "headers.txt")
    if force or not dest.exists():
        tmp = dest.with_name(dest.name + ".part")
        with requests.request(method, url, json=json_body, headers=headers, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for block in r.iter_content(1 << 20):
                    f.write(block)
            http = {k: r.headers[k] for k in KEPT_HEADERS if k in r.headers}
        tmp.replace(dest)
        status = "lastet ned"
    record = {
        "kilde": source,
        "url": url,
        "fil": dest.name,
        "lisens": license,
        "registrert": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "bytes": dest.stat().st_size,
        "sha256": sha256(dest),
        "http": http,
    }
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[{status}] {source}: {dest.name} ({record['bytes'] / 1e6:.1f} MB)")
    return dest
