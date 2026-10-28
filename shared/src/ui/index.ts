// Felles kartoppsett og A–G-farger. Fargene går fra grønt (A) til rødt (G) og har nok
// kontrast mot både lyst og mørkt bakgrunnskart.

export const GRADE_COLORS: Record<string, string> = {
  A: "#1a9850",
  B: "#66bd63",
  C: "#a6d96a",
  D: "#fee08b",
  E: "#fdae61",
  F: "#f46d43",
  G: "#d73027",
};

export const GRADES = ["A", "B", "C", "D", "E", "F", "G"] as const;
export type Grade = (typeof GRADES)[number];

export interface Basemap {
  id: string;
  label: string;
  style: string | object;
  attribution: string;
}

const kartverketRaster = (layer: string, label: string): Basemap => ({
  id: `kartverket-${layer}`,
  label,
  attribution: "© Kartverket",
  style: {
    version: 8,
    sources: {
      kartverket: {
        type: "raster",
        tiles: [`https://cache.kartverket.no/v1/wmts/1.0.0/${layer}/default/webmercator/{z}/{y}/{x}.png`],
        tileSize: 256,
        attribution: "© Kartverket",
        maxzoom: 18,
      },
    },
    layers: [{ id: "kartverket", type: "raster", source: "kartverket" }],
  },
});

export const BASEMAPS: Basemap[] = [
  {
    id: "openfreemap-positron",
    label: "Lyst (OpenFreeMap)",
    style: "https://tiles.openfreemap.org/styles/positron",
    attribution: "© OpenMapTiles © OpenStreetMap-bidragsytere",
  },
  kartverketRaster("topograatone", "Gråtone (Kartverket)"),
  kartverketRaster("topo", "Topografisk (Kartverket)"),
];
