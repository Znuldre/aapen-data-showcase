"""GTFS med DuckDB: aktive tjenester på en dato, redusert feed for R5 og avganger per holdeplass.

Enturs nasjonale feed er stor (stop_times ≈ 0,8 GB, shapes ≈ 2,4 GB). R5 trenger bare
turene som går på referansedagene, så vi lager en redusert feed uten shapes.
"""

from __future__ import annotations

import datetime as dt
import shutil
import zipfile
from pathlib import Path

import duckdb

FILES = (
    "agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
    "calendar.txt", "calendar_dates.txt", "transfers.txt", "feed_info.txt",
)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# Utvidede rutetyper (Entur): https://developers.google.com/transit/gtfs/reference/extended-route-types
AIR = (1100, 1199)
HIGH_CAPACITY = ((100, 199), (2, 2), (400, 405), (1, 1), (1000, 1099), (4, 4))  # tog, T-bane, båt/ferje


def extract(zip_path: Path, dest_dir: Path) -> Path:
    """Pakker ut filene vi trenger (ikke shapes.txt) til en egen mappe."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for name in FILES:
            if name in z.namelist() and not (dest_dir / name).exists():
                with z.open(name) as src, open(dest_dir / name, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    return dest_dir


def connect(gtfs_dir: Path, con: duckdb.DuckDBPyConnection | None = None) -> duckdb.DuckDBPyConnection:
    """Lager én visning per GTFS-fil; alle kolonner leses som tekst for å bevare ID-er."""
    con = con or duckdb.connect()
    for name in FILES:
        path = gtfs_dir / name
        if path.exists():
            con.execute(
                f"CREATE OR REPLACE VIEW {path.stem} AS "
                # Sitattegn settes eksplisitt: de første radene har ingen sitater, så autodeteksjon bommer
                f"SELECT * FROM read_csv('{path.as_posix()}', header=true, all_varchar=true, quote='\"', escape='\"')"
            )
    return con


def active_services_sql(date: dt.date) -> str:
    d = date.strftime("%Y%m%d")
    day = WEEKDAYS[date.weekday()]
    return f"""
        (SELECT service_id FROM calendar
          WHERE start_date <= '{d}' AND end_date >= '{d}' AND {day} = '1'
         EXCEPT SELECT service_id FROM calendar_dates WHERE date = '{d}' AND exception_type = '2')
        UNION SELECT service_id FROM calendar_dates WHERE date = '{d}' AND exception_type = '1'
    """


def reduce_feed(
    gtfs_dir: Path,
    dest_zip: Path,
    dates: list[dt.date],
    drop_air: bool = True,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, int]:
    """Skriver en GTFS med bare turene som går på `dates` (og uten fly hvis `drop_air`).

    Med `bbox` (min_lon, min_lat, max_lon, max_lat) beholdes bare stoppene inne i området, og
    turer med færre enn to gjenværende stopp fjernes. Turer som krysser grensen kuttes der.
    """
    con = connect(gtfs_dir)
    services = " UNION ".join(f"({active_services_sql(d)})" for d in dates)
    air = f"AND NOT (CAST(r.route_type AS INTEGER) BETWEEN {AIR[0]} AND {AIR[1]})" if drop_air else ""
    con.execute(f"CREATE TEMP TABLE svc AS {services}")
    con.execute(
        f"CREATE TEMP TABLE t_trips AS SELECT t.* FROM trips t JOIN routes r USING (route_id) "
        f"WHERE t.service_id IN (SELECT service_id FROM svc) {air}"
    )
    inside = ""
    if bbox:
        x0, y0, x1, y1 = bbox
        inside = (
            "AND stop_id IN (SELECT stop_id FROM stops WHERE "
            f"CAST(stop_lon AS DOUBLE) BETWEEN {x0} AND {x1} AND CAST(stop_lat AS DOUBLE) BETWEEN {y0} AND {y1})"
        )
    con.execute(f"CREATE TEMP TABLE t_stop_times AS SELECT * FROM stop_times WHERE trip_id IN (SELECT trip_id FROM t_trips) {inside}")
    # R5 godtar tider opp til 72:00:00; flerdagers seilinger (Hurtigruten) kuttes der
    con.execute(
        "DELETE FROM t_stop_times WHERE TRY_CAST(split_part(arrival_time, ':', 1) AS INTEGER) >= 72 "
        "OR TRY_CAST(split_part(departure_time, ':', 1) AS INTEGER) >= 72"
    )
    con.execute("DELETE FROM t_stop_times WHERE trip_id IN (SELECT trip_id FROM t_stop_times GROUP BY trip_id HAVING count(*) < 2)")
    con.execute("DELETE FROM t_trips WHERE trip_id NOT IN (SELECT DISTINCT trip_id FROM t_stop_times)")
    con.execute(
        "CREATE TEMP TABLE t_stops AS SELECT * FROM stops WHERE stop_id IN (SELECT DISTINCT stop_id FROM t_stop_times) "
        "OR stop_id IN (SELECT DISTINCT parent_station FROM stops WHERE stop_id IN (SELECT DISTINCT stop_id FROM t_stop_times))"
    )
    con.execute("CREATE TEMP TABLE t_routes AS SELECT * FROM routes WHERE route_id IN (SELECT DISTINCT route_id FROM t_trips)")
    con.execute("CREATE TEMP TABLE t_agency AS SELECT * FROM agency WHERE agency_id IN (SELECT DISTINCT agency_id FROM t_routes)")
    con.execute("CREATE TEMP TABLE t_calendar AS SELECT * FROM calendar WHERE service_id IN (SELECT service_id FROM svc)")
    con.execute("CREATE TEMP TABLE t_calendar_dates AS SELECT * FROM calendar_dates WHERE service_id IN (SELECT service_id FROM svc)")
    # Tom transfer_type betyr «0 – anbefalt overgang» i GTFS-spesifikasjonen, men R5 krever en verdi
    con.execute(
        "CREATE TEMP TABLE t_transfers AS SELECT * REPLACE (coalesce(nullif(transfer_type, ''), '0') AS transfer_type) "
        "FROM transfers WHERE from_stop_id IN (SELECT stop_id FROM t_stops) AND to_stop_id IN (SELECT stop_id FROM t_stops)"
    )
    tmp = dest_zip.parent / (dest_zip.stem + "_csv")
    tmp.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for table in ("agency", "stops", "routes", "trips", "stop_times", "calendar", "calendar_dates", "transfers"):
        out = tmp / f"{table}.txt"
        con.execute(f"COPY t_{table} TO '{out.as_posix()}' (HEADER, DELIMITER ',')")
        counts[table] = con.execute(f"SELECT count(*) FROM t_{table}").fetchone()[0]
    shutil.copy(gtfs_dir / "feed_info.txt", tmp / "feed_info.txt")
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(tmp.iterdir()):
            z.write(f, f.name)
    shutil.rmtree(tmp)
    return counts


def stop_trips(con: duckdb.DuckDBPyConnection, date: dt.date, start: dt.time, minutes: int):
    """Par (holdeplass, tur) med avgang i vinduet, og om turen har høy kapasitet (tog, T-bane, båt)."""
    lo = start.hour * 3600 + start.minute * 60
    hi = lo + minutes * 60
    high = " OR ".join(f"CAST(r.route_type AS INTEGER) BETWEEN {a} AND {b}" for a, b in HIGH_CAPACITY)
    return con.execute(f"""
        WITH st AS (
          SELECT trip_id, stop_id, pickup_type,
                 CAST(split_part(departure_time, ':', 1) AS INTEGER) * 3600
               + CAST(split_part(departure_time, ':', 2) AS INTEGER) * 60
               + CAST(split_part(departure_time, ':', 3) AS INTEGER) AS dep_s
          FROM stop_times WHERE departure_time IS NOT NULL AND departure_time <> ''
        )
        SELECT DISTINCT st.stop_id, st.trip_id, ({high}) AS hoy_kapasitet
        FROM st JOIN trips t USING (trip_id) JOIN routes r USING (route_id)
        WHERE t.service_id IN ({active_services_sql(date)})
          AND st.dep_s >= {lo} AND st.dep_s < {hi}
          AND coalesce(st.pickup_type, '0') <> '1'
          AND NOT (CAST(r.route_type AS INTEGER) BETWEEN {AIR[0]} AND {AIR[1]})
    """).df()


def departures_per_stop(con: duckdb.DuckDBPyConnection, date: dt.date, start: dt.time, minutes: int):
    """Antall avganger per holdeplass (quay) i vinduet, med rutetype og kapasitetsklasse."""
    lo = start.hour * 3600 + start.minute * 60
    hi = lo + minutes * 60
    high = " OR ".join(f"CAST(r.route_type AS INTEGER) BETWEEN {a} AND {b}" for a, b in HIGH_CAPACITY)
    return con.execute(f"""
        WITH st AS (
          SELECT trip_id, stop_id, pickup_type,
                 CAST(split_part(departure_time, ':', 1) AS INTEGER) * 3600
               + CAST(split_part(departure_time, ':', 2) AS INTEGER) * 60
               + CAST(split_part(departure_time, ':', 3) AS INTEGER) AS dep_s
          FROM stop_times WHERE departure_time IS NOT NULL AND departure_time <> ''
        )
        SELECT st.stop_id,
               count(DISTINCT st.trip_id) AS avganger,
               bool_or({high}) AS hoy_kapasitet,
               min(CAST(r.route_type AS INTEGER)) AS rutetype
        FROM st
        JOIN trips t USING (trip_id)
        JOIN routes r USING (route_id)
        WHERE t.service_id IN ({active_services_sql(date)})
          AND st.dep_s >= {lo} AND st.dep_s < {hi}
          AND coalesce(st.pickup_type, '0') <> '1'
          AND NOT (CAST(r.route_type AS INTEGER) BETWEEN {AIR[0]} AND {AIR[1]})
        GROUP BY st.stop_id
    """).df()
