// Entur: Geocoder v3 og Journey Planner v3. Alle kall må ha ET-Client-Name (<organisasjon>-<applikasjon>).

import { fetchJson, type FetchJsonOptions } from "../http/fetchJson";

const GEOCODER = "https://api.entur.io/geocoder/v3";
const JOURNEY_PLANNER = "https://api.entur.io/journey-planner/v3/graphql";

export interface EnturConfig {
  clientName: string;
  fetchImpl?: typeof fetch;
}

export function enturHeaders(config: EnturConfig): Record<string, string> {
  if (!/^[a-z0-9]+-[a-z0-9-]+$/.test(config.clientName)) {
    throw new Error("ET-Client-Name må ha formen <organisasjon>-<applikasjon> (små bokstaver)");
  }
  return { "ET-Client-Name": config.clientName };
}

export interface GeocoderFeature {
  geometry: { coordinates: [number, number] };
  properties: { id: string; name: string; label?: string; layer?: string; category?: string[] };
}

export async function geocode(config: EnturConfig, text: string, limit = 8, options: FetchJsonOptions = {}) {
  const url = `${GEOCODER}/autocomplete?q=${encodeURIComponent(text)}&limit=${limit}&lang=no`;
  const result = await fetchJson<{ features: GeocoderFeature[] }>(url, {
    ...options,
    headers: enturHeaders(config),
    fetchImpl: config.fetchImpl,
    cacheTtlMs: 60_000,
  });
  return result.features;
}

export async function journeyPlanner<T>(config: EnturConfig, query: string, variables: Record<string, unknown> = {}) {
  const result = await fetchJson<{ data: T; errors?: { message: string }[] }>(JOURNEY_PLANNER, {
    method: "POST",
    body: { query, variables },
    headers: enturHeaders(config),
    fetchImpl: config.fetchImpl,
  });
  if (result.errors?.length) throw new Error(result.errors.map((e) => e.message).join("; "));
  return result.data;
}

export interface NearbyDeparture {
  stopName: string;
  distance: number;
  departures: { line: string; destination: string; expected: string; mode: string }[];
}

const NEARBY_QUERY = `
query ($lat: Float!, $lon: Float!, $maxDistance: Float!) {
  nearest(latitude: $lat, longitude: $lon, maximumDistance: $maxDistance, maximumResults: 5,
          filterByPlaceTypes: [stopPlace], multiModalMode: parent) {
    edges { node { distance place { ... on StopPlace {
      name
      estimatedCalls(numberOfDepartures: 4, timeRange: 3600) {
        expectedDepartureTime
        destinationDisplay { frontText }
        serviceJourney { line { publicCode transportMode } }
      }
    } } } }
  }
}`;

interface NearbyResponse {
  nearest: {
    edges: {
      node: {
        distance: number;
        place: {
          name: string;
          estimatedCalls: {
            expectedDepartureTime: string;
            destinationDisplay: { frontText: string };
            serviceJourney: { line: { publicCode: string | null; transportMode: string } };
          }[];
        } | null;
      };
    }[];
  };
}

/** De nærmeste holdeplassene med avganger den neste timen. */
export async function nearbyDepartures(config: EnturConfig, lat: number, lon: number, maxDistance = 800) {
  const data = await journeyPlanner<NearbyResponse>(config, NEARBY_QUERY, { lat, lon, maxDistance });
  return data.nearest.edges
    .filter((e) => e.node.place)
    .map<NearbyDeparture>((e) => ({
      stopName: e.node.place!.name,
      distance: Math.round(e.node.distance),
      departures: e.node.place!.estimatedCalls.map((c) => ({
        line: c.serviceJourney.line.publicCode ?? "",
        destination: c.destinationDisplay.frontText,
        expected: c.expectedDepartureTime,
        mode: c.serviceJourney.line.transportMode,
      })),
    }));
}
