// MET Locationforecast 2.0. Nettlesere skal gå via en cachende proxy som setter User-Agent
// (se vilkårene på api.met.no); her bygges bare URL-en, med maks fire desimaler som MET krever.

export const MET_BASE = "https://api.met.no/weatherapi";

/** MET avviser koordinater med mer enn fire desimaler. */
export function roundCoordinate(value: number, decimals = 4): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

export function locationforecastUrl(lat: number, lon: number, variant: "compact" | "complete" = "compact", base = MET_BASE) {
  return `${base}/locationforecast/2.0/${variant}?lat=${roundCoordinate(lat)}&lon=${roundCoordinate(lon)}`;
}

export function nowcastUrl(lat: number, lon: number, base = MET_BASE) {
  return `${base}/nowcast/2.0/complete?lat=${roundCoordinate(lat)}&lon=${roundCoordinate(lon)}`;
}
