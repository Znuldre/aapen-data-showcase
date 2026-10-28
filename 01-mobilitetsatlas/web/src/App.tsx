import { useEffect, useMemo, useState } from "react";

import { ssbidFromLonLat, type Address } from "@showcase/shared";

import { AddressSearch } from "./components/AddressSearch";
import { GrunnkretsPanel, KommunePanel, NorgePanel } from "./components/AreaPanels";
import { CellCard } from "./components/CellCard";
import { Controls } from "./components/Controls";
import { MapView, type Selection } from "./components/MapView";
import { load, type Indikator, type Meta, type Skala, type Vindu } from "./data";
import { DataPage, MethodPage } from "./pages";

type Side = "kart" | "metode" | "data";

const sideFraHash = (): Side => (location.hash === "#/metode" ? "metode" : location.hash === "#/data" ? "data" : "kart");

interface KommuneFeatures {
  features: { properties: Record<string, unknown> }[];
}

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [feil, setFeil] = useState<string | null>(null);
  const [side, setSide] = useState<Side>(sideFraHash);
  const [indikator, setIndikator] = useState<Indikator>("mf");
  const [vindu, setVindu] = useState<Vindu>("morgen");
  const [skala, setSkala] = useState<Skala>("dk");
  const [selection, setSelection] = useState<Selection>(null);
  const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; zoom: number } | null>(null);
  const [kommuner, setKommuner] = useState<Record<string, Record<string, unknown>>>({});

  useEffect(() => {
    load<Meta>("meta.json").then(setMeta).catch((e: Error) => setFeil(e.message));
    load<KommuneFeatures>("kommuner.geojson")
      .then((fc) => setKommuner(Object.fromEntries(fc.features.map((f) => [String(f.properties.kommunenummer), f.properties]))))
      .catch(() => undefined);
    const onHash = () => setSide(sideFraHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const velgAdresse = (a: Address) => {
    setFlyTo({ lon: a.lon, lat: a.lat, zoom: 14 });
    setSelection({ type: "rute", ssbid: ssbidFromLonLat(a.lon, a.lat), knr: a.kommunenummer, lonlat: [a.lon, a.lat], adresse: `${a.text}, ${a.poststed}` });
  };

  const panel = useMemo(() => {
    if (!meta) return null;
    if (selection?.type === "rute") return <CellCard meta={meta} sel={selection} vindu={vindu} skala={skala} kommune={kommuner[selection.knr]} />;
    if (selection?.type === "kommune" && kommuner[selection.knr]) return <KommunePanel meta={meta} kommune={kommuner[selection.knr]} vindu={vindu} skala={skala} />;
    if (selection?.type === "grunnkrets") return <GrunnkretsPanel meta={meta} props={selection.props} vindu={vindu} skala={skala} />;
    return <NorgePanel meta={meta} vindu={vindu} skala={skala} />;
  }, [meta, selection, vindu, skala, kommuner]);

  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          Mobilitetsatlas Norge <span>v0.1 · Kollektiv</span>
        </a>
        <nav aria-label="Hovedmeny">
          <a href="#/" aria-current={side === "kart" ? "page" : undefined}>Kart</a>
          <a href="#/metode" aria-current={side === "metode" ? "page" : undefined}>Metode</a>
          <a href="#/data" aria-current={side === "data" ? "page" : undefined}>Data og kilder</a>
        </nav>
      </header>
      {feil && <main className="page"><p className="error">{feil}</p></main>}
      {meta && side === "metode" && <main><MethodPage /></main>}
      {meta && side === "data" && <main><DataPage meta={meta} /></main>}
      {meta && side === "kart" && (
        <main className="atlas">
          <aside className="sidebar">
            <AddressSearch onPick={velgAdresse} />
            <Controls meta={meta} indikator={indikator} vindu={vindu} skala={skala} onIndikator={setIndikator} onVindu={setVindu} onSkala={setSkala} />
            {selection && (
              <button type="button" className="link" onClick={() => setSelection(null)}>
                ← Tilbake til Norge samlet
              </button>
            )}
            {panel}
          </aside>
          <MapView meta={meta} indikator={indikator} vindu={vindu} skala={skala} selection={selection} onSelect={setSelection} flyTo={flyTo} />
        </main>
      )}
    </div>
  );
}
