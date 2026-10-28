// Typer og lasting av data eksportert av pipeline-steg 6 (public/data).

export type Vindu = "morgen" | "kveld" | "lordag";
export type Indikator = "mf" | "kk" | "tv" | "kn";
export type Skala = "dk" | "no";
export type Band = [string, number];

export const VINDUER: Vindu[] = ["morgen", "kveld", "lordag"];

/** Tidsvinduene som faktisk er beregnet (morgen finnes alltid). */
export const vinduer = (meta: Meta): Vindu[] => VINDUER.filter((v) => v in meta.tidsvinduer);
export const KATEGORIER = ["jobber", "dagligvare", "skole", "barnehage", "helse", "tjenester"] as const;
export type Kategori = (typeof KATEGORIER)[number];

export interface Fylke {
  nr: string;
  navn: string;
  befolkning: number;
  bbox: [number, number, number, number];
  andel_god_tilgang: number;
  gini_morgen: number;
  [key: string]: unknown;
}

export interface Kilde {
  kilde: string;
  url: string;
  fil: string;
  lisens: string;
  registrert: string;
  bytes: number;
  sha256: string;
  http?: Record<string, string>;
}

export interface Meta {
  versjon: string;
  generert: string;
  referansedager: { hverdag: string; lordag: string };
  tidsvinduer: Record<Vindu, { navn: string; dato: string; start: string; minutter: number }>;
  kategorier: Record<Kategori, { vekt: number; halveringstid: number; maal: number; navn: string }>;
  parametere: {
    maks_reisetid: number;
    lav_samlet_rekkevidde: number;
    gangavstand_lav_kapasitet: number;
    gangavstand_hoy_kapasitet: number;
    kollektivnivaa_grenser: number[];
  };
  skalaer: { dk: Band[]; no: Band[] };
  norge: Record<string, number | string>;
  transport_performance?: TransportPerformance[];
  fylker: Fylke[];
  kilder: Kilde[];
}

/** EUs «transport performance» for et bysenter (DEGURBA): nådd innen 30 min / bosatt innen 7,5 km. */
export interface TransportPerformance {
  bysenter: number;
  navn: string;
  kommunenummer: string;
  befolkning: number;
  transport_performance: number;
  naadd_30_min: number;
  innen_7_5_km: number;
}

export interface KommuneProfil {
  lorenz: number[];
  andeler: Record<string, number>;
  svakest: [string, string, number, number][];
  sterkest: [string, string, number, number][];
}

export type Kolonner = Record<string, (number | string | null)[]>;

const cache = new Map<string, Promise<unknown>>();

export function load<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    cache.set(
      path,
      fetch(`${import.meta.env.BASE_URL}data/${path}`).then((r) => {
        if (!r.ok) throw new Error(`Fant ikke data/${path} (HTTP ${r.status}). Er pipelinen kjørt?`);
        return r.json();
      }),
    );
  }
  return cache.get(path) as Promise<T>;
}

/** Slår opp én rad i kolonnevise data. */
export function row(data: Kolonner, index: number): Record<string, number | string | null> {
  const out: Record<string, number | string | null> = {};
  for (const [key, values] of Object.entries(data)) out[key] = values[index];
  return out;
}

export function indexOf(data: Kolonner, ssbid: number): number {
  return (data.ssbid as number[]).indexOf(ssbid);
}
