"""Tester for Avro-dekoderen (siri_avro.py) og loggerens XML-reserve (uten nettverk).

Avro-svarene lages her med en liten, skjemadrevet koder, så de har samme innhold som XML-fiksturen
i test_logger.py. Kjøres fra prosjektroten:  .venv/Scripts/python.exe -I -m pytest 03-punktlig/tests
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
from dataclasses import astuple
from pathlib import Path

import pytest

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logger"))

import siri_avro  # noqa: E402
from siri import les_et  # noqa: E402
from siri_avro import FINGERAVTRYKK, MAGI, UkjentSkjema, fingeravtrykk, kanonisk_form, les_et_avro  # noqa: E402
from test_logger import ENTUR  # noqa: E402
from test_logger import t as t_  # noqa: E402

SKJEMA = json.loads(siri_avro.SKJEMAFIL.read_text(encoding="utf-8"))


# --- En enkel Avro-koder for testdata -----------------------------------------------------------------

def _varint(n: int) -> bytes:
    n = (n << 1) ^ (n >> 63)  # zigzag
    ut = bytearray()
    while n > 0x7F:
        ut.append(n & 0x7F | 0x80)
        n >>= 7
    ut.append(n)
    return bytes(ut)


def _navngitte(typ, ut: dict) -> dict:
    if isinstance(typ, list):
        for t in typ:
            _navngitte(t, ut)
    elif isinstance(typ, dict):
        if typ["type"] == "record":
            ut[typ["name"]] = typ
            for f in typ["fields"]:
                _navngitte(f["type"], ut)
        elif typ["type"] == "array":
            _navngitte(typ["items"], ut)
    return ut


NAVNGITTE = _navngitte(SKJEMA, {})


def koder(verdi, typ=SKJEMA, blokkstorrelse: bool = False) -> bytes:
    """Koder en dict etter skjemaet. Manglende felt blir null eller tomme arrayer. Med
    `blokkstorrelse` skrives arrayer med negativt antall og bytestørrelse, som spesifikasjonen tillater."""
    if isinstance(typ, str):
        if typ == "null":
            return b""
        if typ == "boolean":
            return b"\x01" if verdi else b"\x00"
        if typ in ("int", "long"):
            return _varint(verdi)
        if typ == "string":
            b = verdi.encode()
            return _varint(len(b)) + b
        if typ == "double":
            return struct.pack("<d", verdi)
        if typ == "float":
            return struct.pack("<f", verdi)
        return koder(verdi, NAVNGITTE[typ], blokkstorrelse)
    if isinstance(typ, list):  # union: null-grenen for None, ellers den andre grenen
        i = 0 if verdi is None else next(i for i, t in enumerate(typ) if t != "null")
        return _varint(i) + koder(verdi, typ[i], blokkstorrelse)
    if typ["type"] == "record":
        verdi = verdi or {}
        ukjente = set(verdi) - {f["name"] for f in typ["fields"]}
        assert not ukjente, ukjente
        return b"".join(
            koder(verdi.get(f["name"], [] if isinstance(f["type"], dict) and f["type"]["type"] == "array" else None),
                  f["type"], blokkstorrelse)
            for f in typ["fields"]
        )
    if typ["type"] == "array":
        if not verdi:
            return b"\x00"
        innhold = b"".join(koder(v, typ["items"], blokkstorrelse) for v in verdi)
        if blokkstorrelse:
            return _varint(-len(verdi)) + _varint(len(innhold)) + innhold + b"\x00"
        return _varint(len(verdi)) + innhold + b"\x00"
    raise ValueError(typ)


def avro_svar(turer: list[dict], **ekstra) -> bytes:
    blokkstorrelse = ekstra.pop("blokkstorrelse", False)
    siri = {"version": "2.1", "serviceDelivery": {
        "responseTimestamp": "2026-10-23T17:30:00.123456Z", "producerRef": "ENT", **ekstra,
        "estimatedTimetableDeliveries": [{"version": "2.1", "estimatedJourneyVersionFrames": [
            {"recordedAtTime": "2026-10-23T17:30:00Z", "estimatedVehicleJourneys": turer},
        ]}],
    }}
    return MAGI + FINGERAVTRYKK + koder(siri, blokkstorrelse=blokkstorrelse)


def navn(tekst: str) -> list[dict]:
    return [{"value": tekst, "language": None}]


# Samme innhold som ENTUR-XML-en i test_logger.py, slik Entur koder det i Avro (UTC-tider, store bokstaver)
ENTUR_TURER = [
    {
        "recordedAtTime": "2026-10-23T17:15:00.5Z", "lineRef": "RUT:Line:5", "directionRef": "2",
        "framedVehicleJourneyRef": {"dataFrameRef": "2026-10-23", "datedVehicleJourneyRef": "RUT:ServiceJourney:abc"},
        "operatorRef": "RUT:Operator:210", "dataSource": "RUT", "monitored": True,
        "recordedCalls": [
            {"stopPointRef": "NSR:Quay:1", "order": 1, "stopPointNames": navn("Vestli"),
             "aimedDepartureTime": "2026-10-23T17:13:00Z", "actualDepartureTime": "2026-10-23T17:14:30.123456789Z"},
        ],
        "estimatedCalls": [
            {"stopPointRef": "NSR:Quay:2", "order": 2, "aimedArrivalTime": "2026-10-23T17:20:00Z",
             "expectedArrivalTime": "2026-10-23T17:21:00Z", "arrivalStatus": "DELAYED"},
            {"stopPointRef": "NSR:Quay:3", "order": 3, "aimedArrivalTime": "2026-10-23T17:25:00Z",
             "arrivalStatus": "CANCELLED"},
        ],
        "isCompleteStopSequence": True,
    },
    {
        "lineRef": "VYG:Line:R21", "directionRef": "0", "datedVehicleJourneyRef": "VYG:DatedServiceJourney:1114",
        "cancellation": True, "vehicleModes": ["RAIL"], "dataSource": "VYG",
        "estimatedCalls": [{"stopPointRef": "NSR:Quay:333", "order": 1, "aimedDepartureTime": "2026-10-23T22:24:00Z"}],
    },
]


# --- Skjema og fingeravtrykk ------------------------------------------------------------------------

def test_crc64_avro_stemmer_med_avros_testverdier():
    def som_long(b: bytes) -> int:
        return int.from_bytes(b, "little", signed=True)
    assert som_long(fingeravtrykk('"null"')) == 7195948357588979594
    assert som_long(fingeravtrykk('"boolean"')) == -6970731678124411036
    assert som_long(fingeravtrykk('"int"')) == 8247732601305521295


def test_kanonisk_form_gir_fulle_navn_og_fjerner_alt_som_ikke_styrer_lesingen():
    skjema = {"type": "record", "name": "Tur", "namespace": "no.test", "doc": "x", "fields": [
        {"name": "id", "type": {"type": "string", "avro.java.string": "String"}, "default": "a"},
        {"name": "neste", "type": ["null", "Tur"], "default": None},
        {"name": "modus", "type": {"type": "enum", "name": "Modus", "symbols": ["BUS", "RAIL"]}},
        {"name": "tider", "type": {"type": "array", "items": "long"}},
    ]}
    assert kanonisk_form(skjema) == (
        '{"name":"no.test.Tur","type":"record","fields":[{"name":"id","type":"string"},'
        '{"name":"neste","type":["null","no.test.Tur"]},'
        '{"name":"modus","type":{"name":"no.test.Modus","type":"enum","symbols":["BUS","RAIL"]}},'
        '{"name":"tider","type":{"type":"array","items":"long"}}]}'
    )


def test_skjemafilen_gir_fingeravtrykket_i_enturs_svar():
    # Fingeravtrykket i alle Avro-svar fra api.entur.io/realtime/v1/rest/et i oktober 2026
    assert FINGERAVTRYKK.hex() == "dda132770abb5f30"
    assert siri_avro.SKJEMAFEIL is None


def test_skjema_som_ikke_passer_med_dekoderen_gir_xml(monkeypatch):
    monkeypatch.setitem(siri_avro.FELT, "TranslatedStringRecord", ("value",))
    feil = siri_avro._sjekk_felt()
    assert "TranslatedStringRecord" in feil
    monkeypatch.setattr(siri_avro, "SKJEMAFEIL", feil)
    with pytest.raises(UkjentSkjema, match="passer ikke"):
        next(les_et_avro(io.BytesIO(avro_svar(ENTUR_TURER)), "entur"))


# --- Dekoderen ---------------------------------------------------------------------------------------

def test_avro_gir_samme_turer_og_kall_som_xml():
    xml = list(les_et(io.BytesIO(ENTUR), "entur"))
    avro = list(les_et_avro(io.BytesIO(avro_svar(ENTUR_TURER)), "entur"))
    assert [astuple(t) for t in avro] == [astuple(t) for t in xml]
    assert avro[1].modus == "rail" and avro[1].dato == "2026-10-24"  # RAIL -> rail; driftsdøgn fra planlagt tid


def test_negative_blokkantall_gir_samme_resultat():
    vanlig = list(les_et_avro(io.BytesIO(avro_svar(ENTUR_TURER)), "entur"))
    med_storrelse = list(les_et_avro(io.BytesIO(avro_svar(ENTUR_TURER, blokkstorrelse=True)), "entur"))
    assert [astuple(t) for t in med_storrelse] == [astuple(t) for t in vanlig]


def test_status_i_registrerte_kall_brukes_ikke_som_i_xml():
    # SIRI 2.0-XML-en har ikke ArrivalStatus i RecordedCall; Avro har det, men det skal ikke telle
    tur = {"datedVehicleJourneyRef": "VYG:DatedServiceJourney:1", "dataSource": "VYG",
           "recordedCalls": [{"stopPointRef": "NSR:Quay:9", "order": 1, "cancellation": False,
                              "aimedArrivalTime": "2026-10-23T17:00:00Z", "actualArrivalTime": "2026-10-23T17:01:00Z",
                              "arrivalStatus": "CANCELLED", "departureStatus": "CANCELLED"}],
           "estimatedCalls": [{"stopPointRef": "NSR:Quay:10", "order": 2, "aimedArrivalTime": "2026-10-23T17:10:00Z",
                               "departureStatus": "CANCELLED"}]}
    (t,) = les_et_avro(io.BytesIO(avro_svar([tur])), "entur")
    assert [k.kansellert for k in t.kall] == [False, True]


def test_lange_verdier_og_felt_som_hoppes_over():
    lang_id = "SKY:ServiceJourney:" + "x" * 200  # lengde over 63 gir flerbyte-varint
    tur = {
        "lineRef": "SKY:Line:1", "directionRef": "1", "estimatedVehicleJourneyCode": lang_id, "dataSource": "SKY",
        "publishedLineNames": navn("1A") + navn("1"), "originNames": navn("Bergen"),
        "additionalVehicleJourneyRef": [{"dataFrameRef": "2026-10-23", "datedVehicleJourneyRef": "x"}],
        "vehicleFeatureRefs": ["lowFloor"], "serviceFeatureRefs": ["schoolBus"],
        "estimatedCalls": [{
            "stopPointRef": "NSR:Quay:4", "order": 300, "stopPointNames": navn("Første") + navn("Siste"),
            "destinationDisplays": navn("Sentrum"), "occupancy": "FULL",
            "aimedDepartureTime": "2026-10-23T18:00:00+02:00", "expectedDepartureTime": "2026-10-23T16:00:30.5Z",
            "arrivalStopAssignments": [{"aimedQuayRef": "NSR:Quay:4", "expectedQuayRef": "NSR:Quay:5"}],
            "expectedDepartureOccupancies": [{"occupancyLevel": "FULL", "occupancyPercentage": 99.5, "onboardCount": 70}],
            "expectedDepartureCapacities": [{"totalCapacity": 80, "seatingCapacity": 40}],
        }],
    }
    info: dict = {}
    (t,) = les_et_avro(io.BytesIO(avro_svar([tur], moreData=True)), "entur", info)
    assert info["mer_data"] is True
    assert (t.tur_id, t.linjenummer, t.kategori) == (lang_id, "1", None)  # siste PublishedLineName, som i XML
    (k,) = t.kall
    assert (k.rekkefolge, k.navn) == (300, "Siste")
    assert k.planlagt_avg == t_("2026-10-23T18:00:00+02:00") and k.forventet_avg - k.planlagt_avg == 30


def test_ukjent_skjema_og_avkortet_svar_gir_tydelige_feil():
    riktig = avro_svar(ENTUR_TURER)
    with pytest.raises(UkjentSkjema, match="fingeravtrykk"):
        next(les_et_avro(io.BytesIO(MAGI + b"\x00" * 8 + riktig[10:]), "entur"))
    with pytest.raises(UkjentSkjema, match="ikke Avro"):
        next(les_et_avro(io.BytesIO(ENTUR), "entur"))
    with pytest.raises(ValueError, match="avkortet"):
        list(les_et_avro(io.BytesIO(riktig[:-40]), "entur"))
    with pytest.raises(ValueError, match="etter SiriRecord"):
        list(les_et_avro(io.BytesIO(riktig + b"\x00"), "entur"))


# --- Loggeren: Avro med XML som reserve -----------------------------------------------------------------

class FalskSvar:
    def __init__(self, innhold: bytes, status: int = 200):
        self.raw = io.BytesIO(innhold)
        self.status_code = status
        self.headers = {"rate-limit-available": "4"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FalskOkt:
    """Svarer med Avro når det bes om Avro, ellers XML, og husker hva som ble bedt om."""

    def __init__(self, avro: bytes, xml: bytes):
        self.avro, self.xml, self.bedt_om = avro, xml, []

    def get(self, url, params=None, headers=None, **_):
        avro = (headers or {}).get("Accept") == "application/avro"
        self.bedt_om.append("avro" if avro else "xml")
        return FalskSvar(self.avro if avro else self.xml)


class IngenLinjer:
    def fyll(self, tur) -> None:
        pass


@pytest.fixture
def logger_modul(tmp_path, monkeypatch):
    import logger
    monkeypatch.setattr(logger.C, "TMP", tmp_path / "tmp")
    monkeypatch.setattr(logger.C, "ENTUR_FORMAT", "avro")
    return logger


def test_loggeren_bruker_avro_naar_skjemaet_stemmer(logger_modul):
    okt = FalskOkt(avro_svar(ENTUR_TURER), ENTUR)
    kilde = logger_modul.Entur(okt)
    kilde.poll(IngenLinjer())
    assert okt.bedt_om == ["avro"]
    assert kilde.status["format"] == "avro" and kilde.status["kall"] == 1 and len(kilde.tilstand) == 2


def test_loggeren_henter_xml_naar_avro_skjemaet_er_ukjent(logger_modul):
    ukjent = MAGI + b"\x01" * 8 + avro_svar(ENTUR_TURER)[10:]
    okt = FalskOkt(ukjent, ENTUR)
    kilde = logger_modul.Entur(okt)
    kilde.poll(IngenLinjer())
    assert okt.bedt_om == ["avro", "xml"]  # samme runde hentes som XML
    assert kilde.status["format"] == "xml" and len(kilde.tilstand) == 2
    assert "0101010101010101" in kilde.status["avro_reserve"]
    kilde.poll(IngenLinjer())  # i pausen etterpå spørres det rett etter XML
    assert okt.bedt_om == ["avro", "xml", "xml"]


def test_loggeren_leser_xml_hvis_entur_svarer_xml_paa_avro(logger_modul):
    okt = FalskOkt(ENTUR, ENTUR)
    kilde = logger_modul.Entur(okt)
    kilde.poll(IngenLinjer())
    assert okt.bedt_om == ["avro"] and kilde.status["format"] == "xml" and len(kilde.tilstand) == 2
