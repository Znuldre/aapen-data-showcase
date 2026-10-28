import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { cellPolygon } from "@showcase/shared";
import { BASEMAPS } from "@showcase/shared/ui";

import { load, VINDUER, type Indikator, type Kolonner, type Meta, type Skala, type Vindu } from "../data";
import { fillColor, fmt, grade, bands, INDIKATORNAVN } from "../scales";

export type Selection =
  | { type: "kommune"; knr: string }
  | { type: "grunnkrets"; props: Record<string, unknown> }
  | { type: "rute"; ssbid: number; knr: string; lonlat?: [number, number]; adresse?: string }
  | null;

interface Feature {
  type: "Feature";
  geometry: { type: string; coordinates: unknown };
  properties: Record<string, unknown>;
}
interface FeatureCollection {
  type: "FeatureCollection";
  features: Feature[];
}

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

// MapLibre 6 finner workeren relativt til modulen, men Vite skriver om filen så den ikke kan kjøre
// som worker. Workeren kopieres derfor uendret til public/ (npm run kopier-worker).
maplibregl.setWorkerUrl(`${import.meta.env.BASE_URL}maplibre-gl-worker.mjs`);
const ZOOM_GRUNNKRETS = 9;
const ZOOM_RUTER = 11.5;

interface Props {
  meta: Meta;
  indikator: Indikator;
  vindu: Vindu;
  skala: Skala;
  selection: Selection;
  onSelect: (s: Selection) => void;
  flyTo: { lon: number; lat: number; zoom: number } | null;
}

function ruterTilFeatures(data: Kolonner): Feature[] {
  const ids = data.ssbid as number[];
  return ids.map((ssbid, i) => {
    const properties: Record<string, unknown> = { ssbid, befolkning: data.befolkning[i], kommunenummer: data.kommunenummer[i] };
    for (const v of VINDUER) for (const m of ["mf", "kk", "tv", "kn", "avganger"]) {
      // Kolonner for tidsvinduer som ikke er beregnet finnes ikke i filen
      const col = data[`${m}_${v}`];
      if (col) properties[`${m}_${v}`] = col[i];
    }
    return { type: "Feature", geometry: { type: "Polygon", coordinates: [cellPolygon(ssbid)] }, properties };
  });
}

export function MapView({ meta, indikator, vindu, skala, selection, onSelect, flyTo }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [laster, setLaster] = useState(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const styleRef = useRef({ indikator, vindu, skala });
  styleRef.current = { indikator, vindu, skala };

  useEffect(() => {
    // Lastestatus per kartinstans (React StrictMode monterer komponenten to ganger i utvikling)
    const loaded = { grunnkretser: new Map<string, Feature[]>(), ruter: new Map<string, Feature[]>() };
    let aktiv = true;
    const map = new maplibregl.Map({
      container: container.current!,
      style: BASEMAPS[0].style as string,
      bounds: [[4.5, 57.9], [31.2, 71.2]],
      fitBoundsOptions: { padding: 20 },
      attributionControl: { compact: true, customAttribution: "Entur · SSB · BRREG · Kartverket · Udir · OSM" },
    });
    mapRef.current = map;
    if (import.meta.env.DEV) (window as unknown as { atlasKart: maplibregl.Map }).atlasKart = map; // for testing i utvikling
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "tooltip" });

    map.on("load", async () => {
      const kommuner = await load<FeatureCollection>("kommuner.geojson");
      map.addSource("kommuner", { type: "geojson", data: kommuner as never });
      map.addSource("grunnkretser", { type: "geojson", data: EMPTY as never });
      map.addSource("ruter", { type: "geojson", data: EMPTY as never });
      map.addSource("valgt", { type: "geojson", data: EMPTY as never });
      const { indikator: i, vindu: v, skala: s } = styleRef.current;
      map.addLayer({ id: "kommuner-fill", type: "fill", source: "kommuner", maxzoom: ZOOM_GRUNNKRETS,
        paint: { "fill-color": fillColor(meta, i, v, s, "flate") as ExpressionSpecification, "fill-opacity": 0.78 } });
      map.addLayer({ id: "kommuner-line", type: "line", source: "kommuner",
        paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.3, 9, 1.2], "line-opacity": 0.8 } });
      map.addLayer({ id: "grunnkretser-fill", type: "fill", source: "grunnkretser", minzoom: ZOOM_GRUNNKRETS, maxzoom: ZOOM_RUTER,
        paint: { "fill-color": fillColor(meta, i, v, s, "flate") as ExpressionSpecification, "fill-opacity": 0.72 } });
      map.addLayer({ id: "grunnkretser-line", type: "line", source: "grunnkretser", minzoom: ZOOM_GRUNNKRETS,
        paint: { "line-color": "#ffffff", "line-width": 0.4, "line-opacity": 0.7 } });
      map.addLayer({ id: "ruter-fill", type: "fill", source: "ruter", minzoom: ZOOM_RUTER,
        paint: { "fill-color": fillColor(meta, i, v, s, "rute") as ExpressionSpecification, "fill-opacity": 0.75 } });
      map.addLayer({ id: "valgt-line", type: "line", source: "valgt", paint: { "line-color": "#111111", "line-width": 2.5 } });
      setReady(true);
      void lastFylker();
    });

    const tooltip = (e: MapLayerMouseEvent, layer: string) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as Record<string, number | string>;
      const { indikator: i, vindu: v, skala: s } = styleRef.current;
      const value = i === "kn" ? Number(p[`avganger_${v}`]) : Number(p[`${i}_${v}`]);
      const navn = layer === "kommuner-fill" ? p.navn : layer === "grunnkretser-fill" ? p.grunnkretsnavn : `${fmt(Number(p.befolkning))} innbyggere`;
      const karakter = i === "kn" ? "" : ` · ${grade(value, bands(meta, i, s)) ?? "–"}`;
      const enhet = i === "kn" ? " avganger/t" : "";
      map.getCanvas().style.cursor = "pointer";
      popup.setLngLat(e.lngLat).setHTML(`<strong>${navn}</strong><br>${INDIKATORNAVN[i]}: ${fmt(value, i === "kn" ? 0 : 1)}${enhet}${karakter}`).addTo(map);
    };
    for (const layer of ["kommuner-fill", "grunnkretser-fill", "ruter-fill"]) {
      map.on("mousemove", layer, (e) => tooltip(e, layer));
      map.on("mouseleave", layer, () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      });
    }
    map.on("click", (e) => {
      const hits = map.queryRenderedFeatures(e.point, { layers: ["ruter-fill", "grunnkretser-fill", "kommuner-fill"].filter((l) => map.getLayer(l)) });
      const f = hits[0];
      if (!f) return;
      const p = f.properties as Record<string, unknown>;
      if (f.layer.id === "ruter-fill") onSelectRef.current({ type: "rute", ssbid: Number(p.ssbid), knr: String(p.kommunenummer), lonlat: [e.lngLat.lng, e.lngLat.lat] });
      else if (f.layer.id === "grunnkretser-fill") onSelectRef.current({ type: "grunnkrets", props: p });
      else onSelectRef.current({ type: "kommune", knr: String(p.kommunenummer) });
    });

    // Last grunnkretser og ruter for fylkene i kartutsnittet
    const lastFylker = async () => {
      const zoom = map.getZoom();
      // Kildene legges til etter at kartstilen er lastet; før det er det ingenting å fylle
      if (zoom < ZOOM_GRUNNKRETS || !map.getSource("grunnkretser")) return;
      const b = map.getBounds();
      const synlige = meta.fylker.filter(({ bbox: [x0, y0, x1, y1] }) => x1 >= b.getWest() && x0 <= b.getEast() && y1 >= b.getSouth() && y0 <= b.getNorth());
      const jobber: Promise<void>[] = [];
      for (const { nr } of synlige) {
        if (!loaded.grunnkretser.has(nr)) {
          loaded.grunnkretser.set(nr, []);
          jobber.push(load<FeatureCollection>(`grunnkretser/${nr}.geojson`).then((fc) => void loaded.grunnkretser.set(nr, fc.features)));
        }
        if (zoom >= ZOOM_RUTER - 0.5 && !loaded.ruter.has(nr)) {
          loaded.ruter.set(nr, []);
          jobber.push(load<Kolonner>(`ruter/${nr}.json`).then((d) => void loaded.ruter.set(nr, ruterTilFeatures(d))));
        }
      }
      if (!jobber.length) return;
      setLaster(true);
      await Promise.all(jobber);
      if (!aktiv) return;
      (map.getSource("grunnkretser") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: [...loaded.grunnkretser.values()].flat() } as never);
      (map.getSource("ruter") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: [...loaded.ruter.values()].flat() } as never);
      setLaster(false);
    };
    map.on("moveend", () => void lastFylker());
    return () => {
      aktiv = false;
      map.remove();
    };
  }, [meta]);

  // Ny farge når indikator, tidsvindu eller skala endres
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.setPaintProperty("kommuner-fill", "fill-color", fillColor(meta, indikator, vindu, skala, "flate"));
    map.setPaintProperty("grunnkretser-fill", "fill-color", fillColor(meta, indikator, vindu, skala, "flate"));
    map.setPaintProperty("ruter-fill", "fill-color", fillColor(meta, indikator, vindu, skala, "rute"));
  }, [ready, meta, indikator, vindu, skala]);

  // Marker valgt kommune eller rute
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const source = map.getSource("valgt") as GeoJSONSource;
    if (selection?.type === "rute") {
      source.setData({ type: "Feature", geometry: { type: "Polygon", coordinates: [cellPolygon(selection.ssbid)] }, properties: {} } as never);
    } else if (selection?.type === "kommune") {
      load<FeatureCollection>("kommuner.geojson").then((fc) => {
        const f = fc.features.find((x) => x.properties.kommunenummer === selection.knr);
        source.setData((f ?? EMPTY) as never);
      });
    } else {
      source.setData(EMPTY as never);
    }
  }, [ready, selection]);

  useEffect(() => {
    if (flyTo && mapRef.current) mapRef.current.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: flyTo.zoom, speed: 1.6 });
  }, [flyTo]);

  return (
    <div className="map-wrap">
      <div ref={container} className="map" aria-label="Kart over mobilitetsfrihet" />
      {laster && <div className="map-status">Laster detaljer …</div>}
    </div>
  );
}
