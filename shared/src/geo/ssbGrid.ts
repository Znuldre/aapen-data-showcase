// Geonøkkelen: SSBs statistiske rutenett (EPSG:25833) og overgang til lengde-/breddegrad.
// Rute-ID = (x + 2 000 000) · 10^7 + y, der (x, y) er nedre venstre hjørne i UTM sone 33.

import proj4 from "proj4";

const UTM33 = "+proj=utm +zone=33 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs";
const WGS84 = "EPSG:4326";
const X_OFFSET = 2_000_000;
const Y_FACTOR = 10_000_000;

export function lonLatToUtm33(lon: number, lat: number): [number, number] {
  return proj4(WGS84, UTM33, [lon, lat]) as [number, number];
}

export function utm33ToLonLat(x: number, y: number): [number, number] {
  return proj4(UTM33, WGS84, [x, y]) as [number, number];
}

export function ssbidFromXY(x: number, y: number, size = 250): number {
  const x0 = Math.floor(x / size) * size;
  const y0 = Math.floor(y / size) * size;
  return (x0 + X_OFFSET) * Y_FACTOR + y0;
}

export function xyFromSsbid(ssbid: number): [number, number] {
  const x0 = Math.floor(ssbid / Y_FACTOR) - X_OFFSET;
  const y0 = ssbid % Y_FACTOR;
  return [x0, y0];
}

export function ssbidFromLonLat(lon: number, lat: number, size = 250): number {
  const [x, y] = lonLatToUtm33(lon, lat);
  return ssbidFromXY(x, y, size);
}

/** Rutens hjørner som en lukket ring i lengde-/breddegrad (for kartvisning). */
export function cellPolygon(ssbid: number, size = 250): [number, number][] {
  const [x0, y0] = xyFromSsbid(ssbid);
  return [
    utm33ToLonLat(x0, y0),
    utm33ToLonLat(x0 + size, y0),
    utm33ToLonLat(x0 + size, y0 + size),
    utm33ToLonLat(x0, y0 + size),
    utm33ToLonLat(x0, y0),
  ];
}
