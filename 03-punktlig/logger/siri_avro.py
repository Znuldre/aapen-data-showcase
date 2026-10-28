"""Dekoder for Enturs SIRI ET i Avro (`Accept: application/avro`), i ren Python uten ekstra pakker.

Avro-svaret er ≈ en fjerdedel av XML-svaret for samme øyeblikk, og ingen av dem komprimeres, så Avro
sparer det meste av nettverksbruken. Formatet er Avros «single-object encoding»: C3 01, 8 byte
fingeravtrykk av skjemaet og så én SiriRecord i Avros binærformat. Fingeravtrykket er CRC-64-AVRO av
skjemaets Parsing Canonical Form, little-endian.

Skjemaet står i SiriRecord.avsc ved siden av denne filen. Det er SiriRecord fra Enturs siri-avro-model
(github.com/entur/siri-avro-model, src/main/avro), som Anshar koder svaret med. Fingeravtrykket regnes
ut fra filen ved import og sammenlignes med hvert svar. Stemmer det ikke, har Entur endret skjemaet:
les_et_avro kaster da UkjentSkjema før noe er lest, og loggeren henter XML i stedet. Ved nytt skjema:
lag SiriRecord.avsc fra den nye IDL-en (for eksempel med `avro-tools idl2schemata`), og rett
dekoderen hvis FELT under ikke lenger stemmer. Det sjekkes ved import.

Dekoderen gir de samme Tur- og Kall-objektene som siri.les_et; README forteller hvordan det er
sammenlignet. Bare feltene loggeren bruker, blir Python-verdier, resten hoppes over. Avro-svaret
skiller seg fra XML-svaret ved at tider er UTC (…Z), koder står med store bokstaver (CANCELLED, RAIL)
og Extensions mangler.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Callable, Iterator

from siri import MODUS, Kall, Tur, lag_tur, tid_fra_iso

SKJEMAFIL = Path(__file__).with_name("SiriRecord.avsc")
MAGI = b"\xc3\x01"  # Avro single-object encoding, versjon 1
PRIMITIVE = {"null", "boolean", "int", "long", "float", "double", "bytes", "string"}

# Feltene i rekkefølgen dekoderen under leser dem. Sjekkes mot SiriRecord.avsc ved import, så et
# skjema som flytter, legger til eller fjerner felt her, gir XML i stedet for feil data.
FELT = {
    "SiriRecord": (
        "version", "serviceDelivery", "serviceRequest", "subscriptionRequest", "subscriptionResponse",
        "terminateSubscriptionRequest", "terminateSubscriptionResponse", "heartbeatNotification",
    ),
    "ServiceDeliveryRecord": (
        "responseTimestamp", "producerRef", "requestMessageRef", "moreData", "estimatedTimetableDeliveries",
        "situationExchangeDeliveries", "vehicleMonitoringDeliveries",
    ),
    "EstimatedTimetableDeliveryRecord": ("version", "responseTimestamp", "estimatedJourneyVersionFrames"),
    "EstimatedJourneyVersionFrameRecord": ("recordedAtTime", "estimatedVehicleJourneys"),
    "EstimatedVehicleJourneyRecord": (
        "recordedAtTime", "lineRef", "directionRef", "datedVehicleJourneyRef", "framedVehicleJourneyRef",
        "estimatedVehicleJourneyCode", "extraJourney", "cancellation", "journeyPatternRef", "vehicleModes",
        "routeRef", "publishedLineNames", "destinationDisplayAtOrigins", "groupOfLinesRef", "externalLineRef",
        "originNames", "originRef", "destinationNames", "destinationRef", "operatorRef",
        "originAimedDepartureTime", "destinationAimedArrivalTime", "vehicleFeatureRefs", "productCategoryRef",
        "serviceFeatureRefs", "monitored", "predictionInaccurate", "dataSource", "occupancy", "blockRef",
        "vehicleJourneyRef", "additionalVehicleJourneyRef", "vehicleRef", "recordedCalls", "estimatedCalls",
        "isCompleteStopSequence",
    ),
    "FramedVehicleJourneyRefRecord": ("dataFrameRef", "datedVehicleJourneyRef"),
    "TranslatedStringRecord": ("value", "language"),
    "RecordedCallRecord": (
        "stopPointRef", "order", "stopPointNames", "extraCall", "cancellation", "predictionInaccurate",
        "occupancy", "requestStop", "destinationDisplays", "aimedArrivalTime", "expectedArrivalTime",
        "actualArrivalTime", "arrivalPlatformName", "arrivalStatus", "arrivalBoardingActivity",
        "arrivalStopAssignments", "aimedDepartureTime", "expectedDepartureTime", "actualDepartureTime",
        "departurePlatformName", "departureStatus", "departureBoardingActivity", "departureStopAssignments",
        "recordedDepartureOccupancies", "recordedDepartureCapacities",
    ),
    "EstimatedCallRecord": (
        "stopPointRef", "order", "stopPointNames", "extraCall", "cancellation", "predictionInaccurate",
        "occupancy", "requestStop", "destinationDisplays", "aimedArrivalTime", "expectedArrivalTime",
        "arrivalPlatformName", "arrivalStatus", "arrivalBoardingActivity", "arrivalStopAssignments",
        "aimedDepartureTime", "expectedDepartureTime", "departurePlatformName", "departureStatus",
        "departureBoardingActivity", "departureStopAssignments", "expectedDepartureOccupancies",
        "expectedDepartureCapacities",
    ),
}


class UkjentSkjema(ValueError):
    """Svaret er ikke Avro med skjemaet i SiriRecord.avsc (eller skjemafilen passer ikke med dekoderen)."""


# --- Skjemaet: Parsing Canonical Form og fingeravtrykk ---------------------------------------------

def _fullt_navn(skjema: dict, ns: str) -> tuple[str, str]:
    """(fullt navn, navnerommet typene inni arver) for en navngitt type."""
    navn = skjema["name"]
    if "." in navn:
        return navn, navn.rpartition(".")[0]
    ns = skjema.get("namespace", ns)
    return (f"{ns}.{navn}" if ns else navn), ns


def kanonisk_form(skjema, ns: str = "") -> str:
    """Avros Parsing Canonical Form: fulle navn, bare det som styrer lesingen, ingen mellomrom."""
    if isinstance(skjema, str):
        full = skjema if skjema in PRIMITIVE or "." in skjema or not ns else f"{ns}.{skjema}"
        return json.dumps(full, ensure_ascii=False)
    if isinstance(skjema, list):
        return "[" + ",".join(kanonisk_form(s, ns) for s in skjema) + "]"
    t = skjema["type"]
    if t in ("record", "enum", "fixed"):
        full, ns = _fullt_navn(skjema, ns)
        hode = '{"name":' + json.dumps(full, ensure_ascii=False) + ',"type":"' + t + '"'
        if t == "record":
            felt = ",".join(
                '{"name":' + json.dumps(f["name"], ensure_ascii=False) + ',"type":' + kanonisk_form(f["type"], ns) + "}"
                for f in skjema["fields"]
            )
            return hode + ',"fields":[' + felt + "]}"
        if t == "enum":
            return hode + ',"symbols":' + json.dumps(skjema["symbols"], ensure_ascii=False, separators=(",", ":")) + "}"
        return hode + ',"size":' + str(int(skjema["size"])) + "}"
    if t == "array":
        return '{"type":"array","items":' + kanonisk_form(skjema["items"], ns) + "}"
    if t == "map":
        return '{"type":"map","values":' + kanonisk_form(skjema["values"], ns) + "}"
    return kanonisk_form(t, ns)  # {"type": "string", …} er bare "string"


_CRC_TOM = 0xC15D213AA4D7A795  # CRC-64-AVRO-polynomet, og fingeravtrykket av tom tekst
_CRC: list[int] = []
for _i in range(256):
    _fp = _i
    for _ in range(8):
        _fp = (_fp >> 1) ^ (_CRC_TOM & -(_fp & 1))
    _CRC.append(_fp)


def fingeravtrykk(form: str) -> bytes:
    """CRC-64-AVRO av en Parsing Canonical Form, som de 8 bytene etter C3 01 i svaret."""
    fp = _CRC_TOM
    for b in form.encode("utf-8"):
        fp = (fp >> 8) ^ _CRC[(fp ^ b) & 0xFF]
    return fp.to_bytes(8, "little")


# --- Lesing av Avros binærformat ---------------------------------------------------------------------
# Alle funksjonene tar (data, posisjon) og gir posisjonen etter verdien. int og long er zigzag-varint,
# en streng er lengde + UTF-8, en union er grennummer + verdi (null/verdi gir én byte: 0 eller 2), og
# et array er blokker med antall elementer, avsluttet av 0.

def _lang(d: bytes, p: int) -> tuple[int, int]:
    b = d[p]
    if b < 0x80:
        return (b >> 1) ^ -(b & 1), p + 1
    n = b & 0x7F
    skift = 7
    p += 1
    while True:
        b = d[p]
        p += 1
        n |= (b & 0x7F) << skift
        if b < 0x80:
            return (n >> 1) ^ -(n & 1), p
        skift += 7


def _antall(d: bytes, p: int) -> tuple[int, int]:
    """Antall elementer i neste array-blokk (0 = slutt på arrayet)."""
    n, p = _lang(d, p)
    if n < 0:  # negativt antall: blokken oppgir også bytestørrelsen, som vi ikke trenger
        _, p = _lang(d, p)
        n = -n
    return n, p


def _tekst(d: bytes, p: int) -> tuple[str | None, int]:
    """Valgfri streng (union null/string)."""
    if not d[p]:
        return None, p + 1
    n = d[p + 1]
    if n < 0x80:
        p += 2
        n >>= 1
    else:
        n, p = _lang(d, p + 1)
    return d[p:p + n].decode(), p + n


def _hopp_tekst(d: bytes, p: int) -> int:
    if not d[p]:
        return p + 1
    n = d[p + 1]
    if n < 0x80:
        return p + 2 + (n >> 1)
    n, p = _lang(d, p + 1)
    return p + n


def _hopp_streng(d: bytes, p: int) -> int:
    n, p = _lang(d, p)
    return p + n


def _sann(d: bytes, p: int) -> tuple[bool, int]:
    """Valgfri boolean (union null/boolean); null blir False, som "true"-sjekken i XML-parseren."""
    if not d[p]:
        return False, p + 1
    return d[p + 1] == 1, p + 2


_TIDER: dict[bytes, int] = {}


def _tid(d: bytes, p: int) -> tuple[int | None, int]:
    """Valgfri tidsstreng (ISO 8601) -> Unix-sekunder, med hurtigbuffer på de rå bytene."""
    if not d[p]:
        return None, p + 1
    n = d[p + 1]
    if n < 0x80:
        p += 2
        n >>= 1
    else:
        n, p = _lang(d, p + 1)
    if not n:  # tom streng, som siri.sekunder("")
        return None, p
    raa = d[p:p + n]
    verdi = _TIDER.get(raa)
    if verdi is None:
        if len(raa) < n:  # utsnitt forbi slutten blir bare kortere; et avkortet svar skal gi feil
            raise IndexError
        verdi = tid_fra_iso(raa.decode())
        if len(_TIDER) > 50_000:  # se siri.sekunder
            _TIDER.clear()
        _TIDER[raa] = verdi
    return verdi, p + n


def _siste_tekst(d: bytes, p: int) -> tuple[str | None, int]:
    """array<string> -> siste element; XML-parseren beholder også siste forekomst."""
    siste = None
    n, p = _antall(d, p)
    while n:
        for _ in range(n):
            n_ = d[p]
            if n_ < 0x80:
                p += 1
                n_ >>= 1
            else:
                n_, p = _lang(d, p)
            siste = d[p:p + n_].decode()
            p += n_
        n, p = _antall(d, p)
    return siste, p


def _siste_oversatt(d: bytes, p: int) -> tuple[str | None, int]:
    """array<TranslatedStringRecord> -> value i siste element (PublishedLineName, StopPointName)."""
    siste = None
    n, p = _antall(d, p)
    while n:
        for _ in range(n):
            siste, p = _tekst(d, p)  # value
            p = _hopp_tekst(d, p)  # language
        n, p = _antall(d, p)
    return siste, p


# --- Generisk overhopping, laget fra skjemaet ---------------------------------------------------------

Hopper = Callable[[bytes, int], int]
_ENKLE: dict[str, Hopper] = {
    "null": lambda d, p: p, "boolean": lambda d, p: p + 1, "int": lambda d, p: _lang(d, p)[1],
    "long": lambda d, p: _lang(d, p)[1], "float": lambda d, p: p + 4, "double": lambda d, p: p + 8,
    "string": _hopp_streng, "bytes": _hopp_streng,
}


def _hopper(typ, ns: str, navngitt: dict[str, Hopper], records: dict) -> Hopper:
    """Funksjon som hopper over én verdi av typen. Navngitte typer står definert før de brukes
    (slik Avro skriver skjemaer), og hver record legges i `records` som [(feltnavn, hopper)]."""
    if isinstance(typ, str):
        if typ in _ENKLE:
            return _ENKLE[typ]
        return navngitt[typ if "." in typ or not ns else f"{ns}.{typ}"]
    if isinstance(typ, list):
        grener = [_hopper(t, ns, navngitt, records) for t in typ]
        if len(typ) == 2 and typ[0] == "null":
            verdi = grener[1]
            return lambda d, p: verdi(d, p + 1) if d[p] else p + 1

        def union(d: bytes, p: int) -> int:
            i, p = _lang(d, p)
            return grener[i](d, p)
        return union
    t = typ["type"]
    if t == "record":
        full, ns = _fullt_navn(typ, ns)
        felt: list[Hopper] = []

        def record(d: bytes, p: int) -> int:
            for f in felt:
                p = f(d, p)
            return p
        navngitt[full] = record
        felt.extend(_hopper(f["type"], ns, navngitt, records) for f in typ["fields"])
        records[full.rpartition(".")[2]] = list(zip((f["name"] for f in typ["fields"]), felt))
        return record
    if t in ("enum", "fixed"):
        full, _ = _fullt_navn(typ, ns)
        storrelse = int(typ.get("size", 0))
        navngitt[full] = _ENKLE["long"] if t == "enum" else (lambda d, p: p + storrelse)
        return navngitt[full]
    if t in ("array", "map"):
        element = _hopper(typ["items"] if t == "array" else typ["values"], ns, navngitt, records)
        er_map = t == "map"

        def blokker(d: bytes, p: int) -> int:
            n, p = _lang(d, p)
            while n:
                if n < 0:  # blokken oppgir bytestørrelsen: hopp rett over
                    storrelse, p = _lang(d, p)
                    p += storrelse
                else:
                    for _ in range(n):
                        if er_map:
                            p = _hopp_streng(d, p)
                        p = element(d, p)
                n, p = _lang(d, p)
            return p
        return blokker
    return _hopper(t, ns, navngitt, records)


_SKJEMA = json.loads(SKJEMAFIL.read_text(encoding="utf-8"))
FINGERAVTRYKK = fingeravtrykk(kanonisk_form(_SKJEMA))
_RECORDS: dict[str, list[tuple[str, Hopper]]] = {}  # kortnavn -> [(feltnavn, hopper)]
_hopper(_SKJEMA, "", {}, _RECORDS)


def _sjekk_felt() -> str | None:
    for record, forventet in FELT.items():
        faktisk = tuple(navn for navn, _ in _RECORDS.get(record, []))
        if faktisk != forventet:
            return f"{SKJEMAFIL.name} passer ikke med dekoderen: feltene i {record} er {faktisk}"
    return None


SKJEMAFEIL = _sjekk_felt()  # er den satt, kaster les_et_avro UkjentSkjema, og loggeren bruker XML
_HOPP = {(r, navn): h for r, felt in _RECORDS.items() for navn, h in felt}
_hopp_oversatte = _HOPP.get(("EstimatedVehicleJourneyRecord", "originNames"))  # array<TranslatedStringRecord>
_hopp_tekster = _HOPP.get(("EstimatedVehicleJourneyRecord", "vehicleFeatureRefs"))  # array<string>
_hopp_rammer = _HOPP.get(("EstimatedVehicleJourneyRecord", "additionalVehicleJourneyRef"))
_hopp_tilordninger = _HOPP.get(("RecordedCallRecord", "arrivalStopAssignments"))
_hopp_belegg = _HOPP.get(("RecordedCallRecord", "recordedDepartureOccupancies"))
_hopp_kapasitet = _HOPP.get(("RecordedCallRecord", "recordedDepartureCapacities"))
_hopp_sx_vm = [_HOPP.get(("ServiceDeliveryRecord", f)) for f in FELT["ServiceDeliveryRecord"][5:]]
_hopp_resten = [_HOPP.get(("SiriRecord", f)) for f in FELT["SiriRecord"][2:]]


# --- Dekoderen -----------------------------------------------------------------------------------------

def _kall(d: bytes, p: int, kall: list[Kall], registrert: bool) -> int:
    """Leser et array med RecordedCallRecord (registrert) eller EstimatedCallRecord og legger
    stoppkallene til i `kall` etter samme regler som siri._kall.

    Avro bygger på SIRI 2.1 og har ArrivalStatus/DepartureStatus også i RecordedCall. XML-svaret er
    SIRI 2.0, der RecordedCall ikke har dem, så de brukes bare for kommende kall. Da blir dataene
    like som med XML. (Et øyeblikksbilde hadde 17 registrerte kall med CANCELLED, alle med faktiske tider.)
    """
    # Dette er den varme løkka (≈ 250 000 kall per uttrekk). De fleste feltene er null eller tomme
    # (én byte 0), så det sjekkes før funksjonskall: `f(d, p) if d[p] else p + 1`.
    n, p = _antall(d, p)
    while n:
        for _ in range(n):
            holdeplass, p = _tekst(d, p)  # stopPointRef
            if d[p]:  # order (int, nesten alltid under 64 og dermed én byte)
                b = d[p + 1]
                if b < 0x80:
                    rekkefolge = (b >> 1) ^ -(b & 1)
                    p += 2
                else:
                    rekkefolge, p = _lang(d, p + 1)
            else:
                rekkefolge = None
                p += 1
            navn, p = _siste_oversatt(d, p) if d[p] else (None, p + 1)  # stopPointNames
            p += 2 if d[p] else 1  # extraCall
            if d[p]:  # cancellation
                kansellert = d[p + 1] == 1
                p += 2
            else:
                kansellert = False
                p += 1
            p += 2 if d[p] else 1  # predictionInaccurate
            p = _hopp_tekst(d, p) if d[p] else p + 1  # occupancy
            p += 2 if d[p] else 1  # requestStop
            p = _hopp_oversatte(d, p) if d[p] else p + 1  # destinationDisplays
            pa, p = _tid(d, p)  # aimedArrivalTime
            ea, p = _tid(d, p)  # expectedArrivalTime
            if registrert:
                aa, p = _tid(d, p)  # actualArrivalTime
            else:
                aa = None
            p = _hopp_tekst(d, p) if d[p] else p + 1  # arrivalPlatformName
            if d[p]:  # arrivalStatus
                status, p = _tekst(d, p)
                kansellert = kansellert or (status == "CANCELLED" and not registrert)
            else:
                p += 1
            p = _hopp_tekst(d, p) if d[p] else p + 1  # arrivalBoardingActivity
            p = _hopp_tilordninger(d, p) if d[p] else p + 1  # arrivalStopAssignments
            pd, p = _tid(d, p)  # aimedDepartureTime
            ed, p = _tid(d, p)  # expectedDepartureTime
            if registrert:
                ad, p = _tid(d, p)  # actualDepartureTime
            else:
                ad = None
            p = _hopp_tekst(d, p) if d[p] else p + 1  # departurePlatformName
            if d[p]:  # departureStatus
                status, p = _tekst(d, p)
                kansellert = kansellert or (status == "CANCELLED" and not registrert)
            else:
                p += 1
            p = _hopp_tekst(d, p) if d[p] else p + 1  # departureBoardingActivity
            p = _hopp_tilordninger(d, p) if d[p] else p + 1  # departureStopAssignments
            p = _hopp_belegg(d, p) if d[p] else p + 1  # recorded-/expectedDepartureOccupancies
            p = _hopp_kapasitet(d, p) if d[p] else p + 1  # recorded-/expectedDepartureCapacities
            if holdeplass:
                kall.append(Kall(
                    rekkefolge if rekkefolge is not None else len(kall) + 1,
                    sys.intern(holdeplass), sys.intern(navn) if navn else None,
                    pa, pd, ea, ed, aa, ad, kansellert, registrert,
                ))
        n, p = _antall(d, p)
    return p


def _tur(d: bytes, p: int, kilde: str) -> tuple[Tur | None, int]:
    """Leser én EstimatedVehicleJourneyRecord."""
    p = _hopp_tekst(d, p)  # recordedAtTime
    linje, p = _tekst(d, p)  # lineRef
    retning, p = _tekst(d, p)  # directionRef
    dated, p = _tekst(d, p)  # datedVehicleJourneyRef
    if d[p]:  # framedVehicleJourneyRef
        dato, p = _tekst(d, p + 1)  # dataFrameRef
        framed, p = _tekst(d, p)  # datedVehicleJourneyRef
    else:
        dato = framed = None
        p += 1
    kode, p = _tekst(d, p)  # estimatedVehicleJourneyCode
    ekstratur, p = _sann(d, p)  # extraJourney
    kansellert, p = _sann(d, p)  # cancellation
    p = _hopp_tekst(d, p)  # journeyPatternRef
    modus, p = _siste_tekst(d, p)  # vehicleModes
    if modus is not None:
        modus = modus.lower()  # RAIL -> rail, som VehicleMode i XML
        modus = MODUS.get(modus, modus)
    p = _hopp_tekst(d, p)  # routeRef
    linjenummer, p = _siste_oversatt(d, p)  # publishedLineNames
    p = _hopp_oversatte(d, p)  # destinationDisplayAtOrigins
    p = _hopp_tekst(d, p)  # groupOfLinesRef
    p = _hopp_tekst(d, p)  # externalLineRef
    p = _hopp_oversatte(d, p)  # originNames
    p = _hopp_tekst(d, p)  # originRef
    p = _hopp_oversatte(d, p)  # destinationNames
    p = _hopp_tekst(d, p)  # destinationRef
    operator, p = _tekst(d, p)  # operatorRef
    p = _hopp_tekst(d, p)  # originAimedDepartureTime
    p = _hopp_tekst(d, p)  # destinationAimedArrivalTime
    p = _hopp_tekster(d, p)  # vehicleFeatureRefs
    p = _hopp_tekst(d, p)  # productCategoryRef
    kategori, p = _siste_tekst(d, p)  # serviceFeatureRefs
    p += 2 if d[p] else 1  # monitored
    p += 2 if d[p] else 1  # predictionInaccurate
    datasett, p = _tekst(d, p)  # dataSource
    p = _hopp_tekst(d, p)  # occupancy
    p = _hopp_tekst(d, p)  # blockRef
    p = _hopp_tekst(d, p)  # vehicleJourneyRef
    p = _hopp_rammer(d, p)  # additionalVehicleJourneyRef
    p = _hopp_tekst(d, p)  # vehicleRef
    kall: list[Kall] = []
    p = _kall(d, p, kall, True)  # recordedCalls
    p = _kall(d, p, kall, False)  # estimatedCalls
    p += 2 if d[p] else 1  # isCompleteStopSequence
    tur = lag_tur(
        kilde, kall, linje=linje, retning=retning, dato=dato, framed=framed, dated=dated, kode=kode,
        kansellert=kansellert, ekstratur=ekstratur, modus=modus, linjenummer=linjenummer,
        operator=operator, datasett=datasett, kategori=kategori,
    )
    return tur, p


def _siri(d: bytes, p: int, kilde: str, info: dict | None) -> Iterator[Tur]:
    p = _hopp_streng(d, p)  # SiriRecord.version
    if d[p]:  # serviceDelivery
        p += 1
        p = _hopp_tekst(d, p)  # responseTimestamp
        p = _hopp_tekst(d, p)  # producerRef
        p = _hopp_tekst(d, p)  # requestMessageRef
        if d[p]:  # moreData
            if info is not None:
                info["mer_data"] = d[p + 1] == 1
            p += 2
        else:
            p += 1
        n, p = _antall(d, p)  # estimatedTimetableDeliveries
        while n:
            for _ in range(n):
                p = _hopp_tekst(d, p)  # version
                p = _hopp_tekst(d, p)  # responseTimestamp
                m, p = _antall(d, p)  # estimatedJourneyVersionFrames
                while m:
                    for _ in range(m):
                        p = _hopp_tekst(d, p)  # recordedAtTime
                        k, p = _antall(d, p)  # estimatedVehicleJourneys
                        while k:
                            for _ in range(k):
                                tur, p = _tur(d, p, kilde)
                                if tur is not None:
                                    yield tur
                            k, p = _antall(d, p)
                    m, p = _antall(d, p)
            n, p = _antall(d, p)
        for hopp in _hopp_sx_vm:  # situationExchangeDeliveries, vehicleMonitoringDeliveries
            p = hopp(d, p)
    else:
        p += 1
    for hopp in _hopp_resten:  # serviceRequest, subscriptionRequest, …
        p = hopp(d, p)
    if p != len(d):
        raise ValueError(f"Avro-svaret har {len(d) - p} byte etter SiriRecord")


def les_et_avro(strom: IO[bytes], kilde: str = "entur", info: dict | None = None) -> Iterator[Tur]:
    """Leser et Avro-svar fra Enturs SIRI Lite ET og gir én Tur per EstimatedVehicleJourney, som
    siri.les_et. Kaster UkjentSkjema før første tur hvis svaret har et annet skjema enn SiriRecord.avsc."""
    d = strom.read()
    if SKJEMAFEIL:
        raise UkjentSkjema(SKJEMAFEIL)
    if d[:2] != MAGI or len(d) < 10:
        raise UkjentSkjema(f"svaret er ikke Avro single-object encoding (begynner med {d[:10]!r})")
    if d[2:10] != FINGERAVTRYKK:
        raise UkjentSkjema(f"ukjent skjemafingeravtrykk {d[2:10].hex()}, {SKJEMAFIL.name} har {FINGERAVTRYKK.hex()}")
    try:
        yield from _siri(d, 10, kilde, info)
    except IndexError:
        raise ValueError(f"Avro-svaret slutter midt i en verdi etter {len(d)} byte (avkortet?)") from None
