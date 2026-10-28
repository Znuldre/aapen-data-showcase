import type { ExpressionSpecification } from "maplibre-gl";

import { GRADE_COLORS } from "@showcase/shared/ui";

import type { Band, Indikator, Meta, Skala, Vindu } from "./data";

export const INDIKATORNAVN: Record<Indikator, string> = {
  mf: "Mobilitetsfrihet",
  kk: "Kollektiv kvalitet",
  tv: "Transportvalgfrihet",
  kn: "Kollektivnivå",
};

export const INDIKATORFORKLARING: Record<Indikator, string> = {
  mf: "Snittet av kollektiv kvalitet og transportvalgfrihet, som i Danmarks Mobilitetsatlas.",
  kk: "Hvor mange hverdagsmål du når med kollektiv, vektet etter reisetid.",
  tv: "Hvor godt kollektiv når like langt som bil. 100 = like mye.",
  kn: "Ulike avganger i timen innen gangavstand (500 m, eller 1 km for tog, T-bane og båt).",
};

export const KN_FARGER = ["#f1eef6", "#d0d1e6", "#a6bddb", "#74a9cf", "#3690c0", "#0570b0", "#034e7b"];
export const KN_NAVN = ["Ingen avganger", "1 i timen", "2–3", "4–7", "8–15", "16–31", "32 eller flere"];
export const MANGLER = "#bdbdbd";

export function bands(meta: Meta, indikator: Indikator, skala: Skala): Band[] {
  // KK og TV vises alltid på DK-skalaen som leseguide; NO-skalaen er kalibrert for mobilitetsfrihet
  return indikator === "mf" ? meta.skalaer[skala] : meta.skalaer.dk;
}

export function grade(score: number | null | undefined, b: Band[]): string | null {
  if (score === null || score === undefined || Number.isNaN(score)) return null;
  for (const [letter, lower] of b) if (score >= lower) return letter;
  return b[b.length - 1][0];
}

export function knLevel(avganger: number, grenser: number[]): number {
  let level = 0;
  for (const g of grenser) if (avganger >= g) level++;
  return level;
}

/** MapLibre-uttrykk som farger et felt etter karakterskalaen eller kollektivnivå. */
export function fillColor(meta: Meta, indikator: Indikator, vindu: Vindu, skala: Skala, level: "flate" | "rute"): ExpressionSpecification {
  return fillColorExpression(meta, indikator, vindu, skala, level) as unknown as ExpressionSpecification;
}

function fillColorExpression(meta: Meta, indikator: Indikator, vindu: Vindu, skala: Skala, level: "flate" | "rute"): unknown[] {
  if (indikator === "kn") {
    const field = level === "rute" ? `kn_${vindu}` : `avganger_${vindu}`;
    const steps: unknown[] = [];
    if (level === "rute") {
      KN_FARGER.slice(1).forEach((c, i) => steps.push(i + 1, c));
    } else {
      meta.parametere.kollektivnivaa_grenser.forEach((g, i) => steps.push(g, KN_FARGER[i + 1]));
    }
    return ["case", ["==", ["get", field], null], MANGLER, ["step", ["get", field], KN_FARGER[0], ...steps]];
  }
  const field = `${indikator}_${vindu}`;
  const ascending = [...bands(meta, indikator, skala)].reverse();
  const steps: unknown[] = [];
  ascending.slice(1).forEach(([letter, lower]) => {
    // MapLibre krever strengt stigende terskler. Like persentiler (f.eks. når mange har 0) slås
    // sammen, og den høyeste karakteren vinner, som i grade().
    if (steps.length && lower <= (steps[steps.length - 2] as number)) steps.splice(-2);
    steps.push(lower, GRADE_COLORS[letter]);
  });
  return ["case", ["==", ["get", field], null], MANGLER, ["step", ["get", field], GRADE_COLORS[ascending[0][0]], ...steps]];
}

export const fmt = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("nb-NO", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "–" : `${(v * 100).toLocaleString("nb-NO", { maximumFractionDigits: digits })} %`;
