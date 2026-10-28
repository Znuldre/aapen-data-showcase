// Kartverkets adresse-API (ws.geonorge.no/adresser/v1): fritekstsøk og nærmeste adresse.

import { fetchJson, type FetchJsonOptions } from "../http/fetchJson";

const BASE = "https://ws.geonorge.no/adresser/v1";

export interface Address {
  text: string;
  postnummer: string;
  poststed: string;
  kommunenummer: string;
  kommunenavn: string;
  lat: number;
  lon: number;
}

interface ApiAddress {
  adressetekst: string;
  postnummer: string;
  poststed: string;
  kommunenummer: string;
  kommunenavn: string;
  representasjonspunkt: { lat: number; lon: number };
}

const toAddress = (a: ApiAddress): Address => ({
  text: a.adressetekst,
  postnummer: a.postnummer,
  poststed: a.poststed,
  kommunenummer: a.kommunenummer,
  kommunenavn: a.kommunenavn,
  lat: a.representasjonspunkt.lat,
  lon: a.representasjonspunkt.lon,
});

export async function searchAddresses(text: string, limit = 8, options: FetchJsonOptions = {}): Promise<Address[]> {
  const url = `${BASE}/sok?sok=${encodeURIComponent(text)}&fuzzy=true&treffPerSide=${limit}&utkoordsys=4326`;
  const result = await fetchJson<{ adresser: ApiAddress[] }>(url, { cacheTtlMs: 60_000, ...options });
  return result.adresser.map(toAddress);
}

export async function nearestAddress(lat: number, lon: number, options: FetchJsonOptions = {}): Promise<Address | null> {
  const url = `${BASE}/punktsok?lat=${lat}&lon=${lon}&radius=200&treffPerSide=1&utkoordsys=4326`;
  const result = await fetchJson<{ adresser: ApiAddress[] }>(url, { cacheTtlMs: 60_000, ...options });
  return result.adresser[0] ? toAddress(result.adresser[0]) : null;
}
