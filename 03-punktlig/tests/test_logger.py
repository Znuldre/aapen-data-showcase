"""Tester for Punktlig-loggerens parser, tilstand og lagring (uten nettverk).

Kjøres fra prosjektroten:  .venv/Scripts/python.exe -I -m pytest 03-punktlig/tests
"""

from __future__ import annotations

import datetime as dt
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logger"))

import duckdb  # noqa: E402

from lager import Lager  # noqa: E402
from siri import les_et, sekunder  # noqa: E402
from tilstand import Tilstand  # noqa: E402


def t(s: str) -> int:
    return int(dt.datetime.fromisoformat(s).timestamp())


ENTUR = b"""<?xml version="1.0" encoding="UTF-8"?>
<Siri xmlns="http://www.siri.org.uk/siri" version="2.0"><ServiceDelivery><EstimatedTimetableDelivery>
<EstimatedJourneyVersionFrame>
 <EstimatedVehicleJourney>
  <LineRef>RUT:Line:5</LineRef><DirectionRef>2</DirectionRef>
  <FramedVehicleJourneyRef><DataFrameRef>2026-10-23</DataFrameRef>
   <DatedVehicleJourneyRef>RUT:ServiceJourney:abc</DatedVehicleJourneyRef></FramedVehicleJourneyRef>
  <OperatorRef>RUT:Operator:210</OperatorRef><DataSource>RUT</DataSource>
  <RecordedCalls>
   <RecordedCall><StopPointRef>NSR:Quay:1</StopPointRef><Order>1</Order><StopPointName>Vestli</StopPointName>
    <AimedDepartureTime>2026-10-23T19:13:00+02:00</AimedDepartureTime>
    <ActualDepartureTime>2026-10-23T19:14:30.123456789+02:00</ActualDepartureTime></RecordedCall>
  </RecordedCalls>
  <EstimatedCalls>
   <EstimatedCall><StopPointRef>NSR:Quay:2</StopPointRef><Order>2</Order>
    <AimedArrivalTime>2026-10-23T19:20:00+02:00</AimedArrivalTime>
    <ExpectedArrivalTime>2026-10-23T19:21:00+02:00</ExpectedArrivalTime>
    <ArrivalStatus>delayed</ArrivalStatus></EstimatedCall>
   <EstimatedCall><StopPointRef>NSR:Quay:3</StopPointRef><Order>3</Order>
    <AimedArrivalTime>2026-10-23T19:25:00+02:00</AimedArrivalTime>
    <ArrivalStatus>cancelled</ArrivalStatus></EstimatedCall>
  </EstimatedCalls>
 </EstimatedVehicleJourney>
 <EstimatedVehicleJourney>
  <LineRef>VYG:Line:R21</LineRef><DirectionRef>0</DirectionRef>
  <DatedVehicleJourneyRef>VYG:DatedServiceJourney:1114</DatedVehicleJourneyRef>
  <Cancellation>true</Cancellation><VehicleMode>rail</VehicleMode><DataSource>VYG</DataSource>
  <EstimatedCalls>
   <EstimatedCall><StopPointRef>NSR:Quay:333</StopPointRef><Order>1</Order>
    <AimedDepartureTime>2026-10-24T00:24:00+02:00</AimedDepartureTime></EstimatedCall>
  </EstimatedCalls>
 </EstimatedVehicleJourney>
</EstimatedJourneyVersionFrame></EstimatedTimetableDelivery></ServiceDelivery></Siri>"""

BANENOR = """<Siri xmlns="http://www.siri.org.uk/siri"><ServiceDelivery><MoreData>false</MoreData>
<EstimatedTimetableDelivery><EstimatedJourneyVersionFrame>
 <EstimatedVehicleJourney>
  <LineRef>-</LineRef><DirectionRef>TND</DirectionRef><DatedVehicleJourneyRef>49702:2026-10-23</DatedVehicleJourneyRef>
  <VehicleMode>rail</VehicleMode><OperatorRef>CN</OperatorRef><ServiceFeatureRef>freightTrain</ServiceFeatureRef>
  <RecordedCalls><RecordedCall><StopPointRef>OSL</StopPointRef><StopPointName>Oslo S</StopPointName>
   <AimedDepartureTime>2026-10-23T18:15:00+02:00</AimedDepartureTime>
   <ActualDepartureTime>2026-10-23T18:18:09+02:00</ActualDepartureTime></RecordedCall></RecordedCalls>
  <EstimatedCalls><EstimatedCall><StopPointRef>LLS</StopPointRef><StopPointName>Lillestrøm</StopPointName>
   <AimedArrivalTime>2026-10-23T18:30:00+02:00</AimedArrivalTime>
   <ExpectedArrivalTime>2026-10-23T18:33:00+02:00</ExpectedArrivalTime></EstimatedCall></EstimatedCalls>
 </EstimatedVehicleJourney>
</EstimatedJourneyVersionFrame></EstimatedTimetableDelivery></ServiceDelivery></Siri>""".encode("utf-8")


def test_sekunder_kutter_desimaler_og_forstaar_soner():
    assert sekunder("2026-10-23T19:14:30.123456789+02:00") == t("2026-10-23T19:14:30+02:00")
    assert sekunder("2026-10-23T17:14:30Z") == t("2026-10-23T19:14:30+02:00")
    assert sekunder(None) is None


def test_entur_tur_og_kall():
    turer = list(les_et(io.BytesIO(ENTUR), "entur"))
    assert len(turer) == 2
    a, b = turer
    assert (a.dato, a.tur_id, a.datasett, a.linje, a.modus) == ("2026-10-23", "RUT:ServiceJourney:abc", "RUT", "RUT:Line:5", None)
    forste, andre, tredje = a.kall
    assert forste.registrert and forste.faktisk_avg == t("2026-10-23T19:14:30+02:00")
    assert not andre.registrert and andre.forventet_ank - andre.planlagt_ank == 60
    assert tredje.kansellert and not andre.kansellert
    # Uten FramedVehicleJourneyRef: driftsdøgn fra første planlagte tid; innstilt tur gir innstilte kall
    assert (b.dato, b.tur_id, b.modus, b.kansellert) == ("2026-10-24", "VYG:DatedServiceJourney:1114", "rail", True)
    assert all(k.kansellert for k in b.kall)


def test_banenor_tognummer_posisjon_og_godstog():
    info: dict = {}
    (tur,) = list(les_et(io.BytesIO(BANENOR), "banenor", info))
    assert info["mer_data"] is False
    assert (tur.tur_id, tur.dato, tur.datasett, tur.linje, tur.kategori) == ("49702", "2026-10-23", "BNR", None, "freightTrain")
    assert [k.rekkefolge for k in tur.kall] == [1, 2]
    assert tur.kall[1].navn == "Lillestrøm"


def test_tilstand_lagrer_bare_avklarte_kall_og_endringer():
    (tur, _) = list(les_et(io.BytesIO(ENTUR), "entur"))
    st = Tilstand(avklart_etter=120, glem_ferdig_etter=1800, glem_etter=6 * 3600)
    naa = t("2026-10-23T19:19:00+02:00")
    st.oppdater(tur, naa)
    rader = st.sveip(naa)
    assert [r[10] for r in rader] == [1]  # bare det registrerte kallet; de andre ligger frem i tid
    assert rader[0][20] == 90  # forsinkelse ved avgang i sekunder
    assert st.sveip(naa) == []  # ingenting nytt
    senere = t("2026-10-23T19:40:00+02:00")
    assert sorted(r[10] for r in st.sveip(senere)) == [2, 3]  # nå er resten avklart
    tur.kall[0].faktisk_avg += 30  # korrigert faktisk tid lagres på nytt
    assert [r[10] for r in st.sveip(senere)] == [1]


def test_sammenslaaing_gir_en_rad_per_stoppkall_med_siste_versjon(tmp_path):
    (tur, _) = list(les_et(io.BytesIO(ENTUR), "entur"))
    st = Tilstand(120, 1800, 6 * 3600)
    st.oppdater(tur, 0)
    sent = t("2026-10-23T20:00:00+02:00")
    rader = st.sveip(sent, observert=sent)
    lager = Lager(tmp_path / "stoppkall", tmp_path / "staging", tmp_path / "tmp")
    lager.skriv("entur", rader)
    endret = [r[:20] + (999,) + r[21:-1] + (sent + 60,) for r in rader]  # nyere versjon av samme kall
    lager.skriv("entur", endret)
    assert lager.komprimer_alle() == 3
    assert lager.komprimer_alle() == 0  # ingenting å gjøre, og ingen duplikater ved ny kjøring
    fil = (tmp_path / "stoppkall" / "entur" / "2026-10-23.parquet").as_posix()
    n, unike, siste = duckdb.connect().execute(
        f"SELECT count(*), count(DISTINCT rekkefolge), min(forsinkelse_avgang_s) FROM '{fil}'").fetchone()
    assert (n, unike, siste) == (3, 3, 999)
