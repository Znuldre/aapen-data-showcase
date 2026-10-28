"""Strømmende parser for SIRI 2.0 Estimated Timetable (ET) fra Entur og Bane NOR.

Hver EstimatedVehicleJourney blir én `Tur` med en liste `Kall` (stoppkall). XML-en leses med
iterparse og ryddes underveis, så Enturs fulle uttrekk (≈ 90 MB XML) går med lite minne.
Tider holdes som Unix-sekunder (UTC); brøkdeler av sekunder kuttes.

Forskjeller mellom kildene:
- Entur: turen identifiseres av FramedVehicleJourneyRef (driftsdøgn + ServiceJourney-ID), ellers
  DatedVehicleJourneyRef eller EstimatedVehicleJourneyCode (ekstraturer). Holdeplass er NSR-quay,
  rekkefølgen står i Order. VehicleMode mangler for mange operatører og fylles fra linjeregisteret.
- Bane NOR: DatedVehicleJourneyRef er «<tognummer>:<driftsdøgn>», holdeplass er stasjonskode (OSL),
  Order finnes ikke (posisjonen i stoppsekvensen brukes), og ServiceFeatureRef skiller person- og godstog.
"""

from __future__ import annotations

import datetime as dt
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import IO, Iterator
from zoneinfo import ZoneInfo

NS = "{http://www.siri.org.uk/siri}"
OSLO = ZoneInfo("Europe/Oslo")

# SIRI VehicleMode -> transportMode slik Entur Journey Planner bruker det
MODUS = {
    "bus": "bus", "coach": "coach", "tram": "tram", "metro": "metro", "underground": "metro",
    "rail": "rail", "ferry": "water", "water": "water", "air": "air",
}

EVJ = NS + "EstimatedVehicleJourney"
MORE_DATA = NS + "MoreData"
LINE_REF = NS + "LineRef"
DIRECTION_REF = NS + "DirectionRef"
FRAMED = NS + "FramedVehicleJourneyRef"
DATA_FRAME_REF = NS + "DataFrameRef"
DATED_VJ_REF = NS + "DatedVehicleJourneyRef"
EVJ_CODE = NS + "EstimatedVehicleJourneyCode"
CANCELLATION = NS + "Cancellation"
EXTRA = NS + "ExtraJourney"
VEHICLE_MODE = NS + "VehicleMode"
PUBLISHED_LINE_NAME = NS + "PublishedLineName"
OPERATOR_REF = NS + "OperatorRef"
DATA_SOURCE = NS + "DataSource"
SERVICE_FEATURE = NS + "ServiceFeatureRef"
RECORDED_CALLS = NS + "RecordedCalls"
ESTIMATED_CALLS = NS + "EstimatedCalls"
STOP_POINT_REF = NS + "StopPointRef"
STOP_POINT_NAME = NS + "StopPointName"
ORDER = NS + "Order"
AIMED_ARR = NS + "AimedArrivalTime"
AIMED_DEP = NS + "AimedDepartureTime"
EXPECTED_ARR = NS + "ExpectedArrivalTime"
EXPECTED_DEP = NS + "ExpectedDepartureTime"
ACTUAL_ARR = NS + "ActualArrivalTime"
ACTUAL_DEP = NS + "ActualDepartureTime"
ARR_STATUS = NS + "ArrivalStatus"
DEP_STATUS = NS + "DepartureStatus"
EXTENSIONS = NS + "Extensions"


@dataclass(slots=True)
class Kall:
    rekkefolge: int
    holdeplass: str
    navn: str | None
    planlagt_ank: int | None
    planlagt_avg: int | None
    forventet_ank: int | None
    forventet_avg: int | None
    faktisk_ank: int | None
    faktisk_avg: int | None
    kansellert: bool
    registrert: bool  # ligger i RecordedCalls: kjøretøyet har passert

    def beste_tid(self) -> int | None:
        """Seneste kjente tidspunkt for kallet (faktisk, ellers forventet, ellers planlagt)."""
        avg = self.faktisk_avg or self.forventet_avg or self.planlagt_avg
        ank = self.faktisk_ank or self.forventet_ank or self.planlagt_ank
        return max(avg or 0, ank or 0) or None


@dataclass(slots=True)
class Tur:
    kilde: str
    dato: str  # driftsdøgn, YYYY-MM-DD
    tur_id: str
    datasett: str | None
    operator: str | None
    linje: str | None
    linjenummer: str | None
    modus: str | None
    kategori: str | None
    retning: str | None
    ekstratur: bool
    kansellert: bool
    kall: list[Kall]

    @property
    def nokkel(self) -> str:
        return f"{self.dato}|{self.tur_id}"


_TIDER: dict[str, int] = {}


def tid_fra_iso(s: str) -> int:
    """ISO 8601 med sone (2026-10-23T20:37:10.682+02:00 eller …Z) -> Unix-sekunder, uten buffer."""
    if len(s) > 19 and s[19] == ".":  # opptil ni desimaler forekommer; fromisoformat tåler seks
        j = 20
        while j < len(s) and s[j].isdigit():
            j += 1
        s = s[:19] + s[j:]
    return int(dt.datetime.fromisoformat(s).timestamp())


def sekunder(tekst: str | None) -> int | None:
    """ISO 8601 med sone -> Unix-sekunder, med hurtigbuffer."""
    if not tekst:
        return None
    verdi = _TIDER.get(tekst)
    if verdi is None:
        verdi = tid_fra_iso(tekst)
        if len(_TIDER) > 50_000:  # liten buffer holder: planlagte tider gjentas mye innen samme svar
            _TIDER.clear()
        _TIDER[tekst] = verdi
    return verdi


def _kall(el: ET.Element, registrert: bool, posisjon: int, bruk_order: bool) -> Kall | None:
    rekkefolge = holdeplass = navn = None
    pa = pd = ea = ed = aa = ad = None
    kansellert = False
    for c in el:
        t = c.tag
        if t == STOP_POINT_REF:
            holdeplass = c.text
        elif t == ORDER:
            rekkefolge = int(c.text)
        elif t == STOP_POINT_NAME:
            navn = c.text
        elif t == AIMED_ARR:
            pa = sekunder(c.text)
        elif t == AIMED_DEP:
            pd = sekunder(c.text)
        elif t == EXPECTED_ARR:
            ea = sekunder(c.text)
        elif t == EXPECTED_DEP:
            ed = sekunder(c.text)
        elif t == ACTUAL_ARR:
            aa = sekunder(c.text)
        elif t == ACTUAL_DEP:
            ad = sekunder(c.text)
        elif t == CANCELLATION:
            kansellert = kansellert or c.text == "true"
        elif t == ARR_STATUS or t == DEP_STATUS:
            kansellert = kansellert or c.text == "cancelled"
        elif t == EXTENSIONS:  # Bane NOR kan legge kansellering av enkeltstopp i en utvidelse
            kansellert = kansellert or c.findtext(".//" + CANCELLATION) == "true"
    if not holdeplass:
        return None
    return Kall(
        rekkefolge if bruk_order and rekkefolge is not None else posisjon,
        sys.intern(holdeplass), sys.intern(navn) if navn else None,
        pa, pd, ea, ed, aa, ad, kansellert, registrert,
    )


def _lokal_dato(kall: list[Kall]) -> str | None:
    for k in kall:
        t = k.planlagt_avg or k.planlagt_ank
        if t:
            return dt.datetime.fromtimestamp(t, OSLO).date().isoformat()
    return None


def _tur(el: ET.Element, kilde: str) -> Tur | None:
    banenor = kilde == "banenor"
    linje = retning = datasett = operator = modus = linjenummer = kategori = None
    dato = framed = dated = kode = None
    kansellert = ekstratur = False
    kall: list[Kall] = []
    for c in el:
        t = c.tag
        if t == RECORDED_CALLS or t == ESTIMATED_CALLS:
            registrert = t == RECORDED_CALLS
            for x in c:
                k = _kall(x, registrert, len(kall) + 1, not banenor)
                if k is not None:
                    kall.append(k)
        elif t == LINE_REF:
            linje = c.text
        elif t == DIRECTION_REF:
            retning = c.text
        elif t == FRAMED:
            dato = c.findtext(DATA_FRAME_REF)
            framed = c.findtext(DATED_VJ_REF)
        elif t == DATED_VJ_REF:
            dated = c.text
        elif t == EVJ_CODE:
            kode = c.text
        elif t == CANCELLATION:
            kansellert = c.text == "true"
        elif t == EXTRA:
            ekstratur = c.text == "true"
        elif t == VEHICLE_MODE:
            modus = MODUS.get(c.text, c.text)
        elif t == PUBLISHED_LINE_NAME:
            linjenummer = c.text
        elif t == OPERATOR_REF:
            operator = c.text
        elif t == DATA_SOURCE:
            datasett = c.text
        elif t == SERVICE_FEATURE:
            kategori = c.text
    return lag_tur(
        kilde, kall, linje=linje, retning=retning, dato=dato, framed=framed, dated=dated, kode=kode,
        kansellert=kansellert, ekstratur=ekstratur, modus=modus, linjenummer=linjenummer,
        operator=operator, datasett=datasett, kategori=kategori,
    )


def lag_tur(
    kilde: str, kall: list[Kall], *, linje: str | None, retning: str | None, dato: str | None,
    framed: str | None, dated: str | None, kode: str | None, kansellert: bool, ekstratur: bool,
    modus: str | None, linjenummer: str | None, operator: str | None, datasett: str | None,
    kategori: str | None,
) -> Tur | None:
    """Felles for XML og Avro (siri_avro.py): turnøkkel og driftsdøgn per kilde, og en innstilt tur
    gir innstilte kall. Gir None for turer uten stoppkall, nøkkel eller driftsdøgn."""
    if not kall:
        return None
    if kilde == "banenor":
        # «3597:2026-10-23» -> tognummer 3597 på driftsdøgnet 2026-10-23
        nummer, _, dag = (dated or "").partition(":")
        tur_id, dato = nummer or None, dag or None
        datasett = "BNR"
        if linje == "-":  # godstog har ingen linje
            linje = None
        linjenummer = linje
        modus = modus or "rail"
    else:
        tur_id = framed or dated or kode
        kategori = None
    if not tur_id:
        return None
    dato = dato or _lokal_dato(kall)
    if not dato:
        return None
    if kansellert:
        for k in kall:
            k.kansellert = True
    return Tur(
        kilde, dato, tur_id, datasett, operator, linje, linjenummer, modus, kategori, retning,
        ekstratur, kansellert, kall,
    )


def les_et(strom: IO[bytes], kilde: str, info: dict | None = None) -> Iterator[Tur]:
    """Leser et SIRI ET-svar og gir én Tur per EstimatedVehicleJourney.

    `info["mer_data"]` settes til True hvis svaret sier at det finnes mer (MoreData).
    """
    for _, el in ET.iterparse(strom, events=("end",)):
        if el.tag == EVJ:
            tur = _tur(el, kilde)
            el.clear()
            if tur is not None:
                yield tur
        elif el.tag == MORE_DATA and info is not None:
            info["mer_data"] = (el.text or "").strip() == "true"
