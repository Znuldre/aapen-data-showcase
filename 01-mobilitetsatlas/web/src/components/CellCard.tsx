import { useEffect, useMemo, useState } from "react";

import { nearbyDepartures, utm33ToLonLat, xyFromSsbid, type NearbyDeparture } from "@showcase/shared";

import { indexOf, KATEGORIER, load, row, type Kategori, type Kolonner, type Meta, type Skala, type Vindu } from "../data";
import { bands, fmt, grade, KN_NAVN, knLevel } from "../scales";
import { Bar, GradeBadge } from "./Bits";
import type { Selection } from "./MapView";

type RuteValg = Extract<Selection, { type: "rute" }>;
type Rad = Record<string, number | string | null>;

interface Props {
  meta: Meta;
  sel: RuteValg;
  vindu: Vindu;
  skala: Skala;
  kommune?: Record<string, unknown>;
}

const num = (v: unknown) => (v === null || v === undefined ? 0 : Number(v));
const ENTUR_CLIENT_NAME = import.meta.env.ENTUR_CLIENT_NAME as string | undefined;

function nearestIndex(data: Kolonner, ssbid: number): { index: number; distance: number } {
  const [x, y] = xyFromSsbid(ssbid);
  let best = { index: -1, distance: Infinity };
  (data.ssbid as number[]).forEach((id, i) => {
    const [cx, cy] = xyFromSsbid(id);
    const d = Math.hypot(cx - x, cy - y);
    if (d < best.distance) best = { index: i, distance: d };
  });
  return best;
}

export function CellCard({ meta, sel, vindu, skala, kommune }: Props) {
  const [data, setData] = useState<{ det: Rad; kart: Rad; avstand: number } | null>(null);
  const [feil, setFeil] = useState<string | null>(null);
  const [vekter, setVekter] = useState<Record<Kategori, number>>(() =>
    Object.fromEntries(KATEGORIER.map((k) => [k, meta.kategorier[k].vekt])) as Record<Kategori, number>,
  );
  const [avganger, setAvganger] = useState<NearbyDeparture[] | null>(null);

  useEffect(() => {
    setData(null);
    setFeil(null);
    Promise.all([load<Kolonner>(`detaljer/${sel.knr}.json`), load<Kolonner>(`ruter/${sel.knr.slice(0, 2)}.json`)])
      .then(([det, kart]) => {
        let i = indexOf(det, sel.ssbid);
        let avstand = 0;
        if (i < 0) ({ index: i, distance: avstand } = nearestIndex(det, sel.ssbid));
        if (i < 0) throw new Error("Fant ingen befolkede ruter i kommunen.");
        const id = det.ssbid[i] as number;
        setData({ det: row(det, i), kart: row(kart, indexOf(kart, id)), avstand });
      })
      .catch((e: Error) => setFeil(e.message));
  }, [sel.ssbid, sel.knr]);

  const lonlat = useMemo<[number, number]>(() => {
    if (sel.lonlat) return sel.lonlat;
    const [x0, y0] = xyFromSsbid(sel.ssbid);
    return utm33ToLonLat(x0 + 125, y0 + 125);
  }, [sel]);

  useEffect(() => {
    setAvganger(null);
    if (!ENTUR_CLIENT_NAME) return;
    nearbyDepartures({ clientName: ENTUR_CLIENT_NAME }, lonlat[1], lonlat[0]).then(setAvganger).catch(() => setAvganger([]));
  }, [lonlat]);

  // Følsomhet: samme formler som pipelinen, med brukerens vekter
  const justert = useMemo(() => {
    if (!data) return null;
    const sum = KATEGORIER.reduce((s, k) => s + vekter[k], 0) || 1;
    const w = (k: Kategori) => vekter[k] / sum;
    const kk = 100 * KATEGORIER.reduce((s, k) => s + w(k) * num(data.det[`metning_${k}_${vindu}`]), 0);
    const rKol = KATEGORIER.reduce((s, k) => s + (w(k) * num(data.det[`rekkevidde_kol_${k}_${vindu}`])) / meta.kategorier[k].maal, 0);
    const rBil = KATEGORIER.reduce((s, k) => s + (w(k) * num(data.det[`rekkevidde_bil_${k}`])) / meta.kategorier[k].maal, 0);
    const total = rKol + rBil;
    const tv = total > 0 ? 100 * Math.min(1, (2 * rKol) / total) * Math.min(1, total / meta.parametere.lav_samlet_rekkevidde) : 0;
    return { kk, tv, mf: 0.5 * kk + 0.5 * tv };
  }, [data, vekter, vindu, meta]);

  if (feil) return <section className="panel"><p className="error">{feil}</p></section>;
  if (!data) return <section className="panel"><p>Laster rute …</p></section>;

  const { det, kart, avstand } = data;
  const mf = num(kart[`mf_${vindu}`]);
  const kk = num(kart[`kk_${vindu}`]);
  const tv = num(kart[`tv_${vindu}`]);
  const avg = num(det[`avganger_${vindu}`]);
  const b = bands(meta, "mf", skala);
  const sammenlign = (felt: string) => [
    ...(kommune ? [{ label: String(kommune.navn), value: num(kommune[`${felt}_${vindu}`]) }] : []),
    { label: "Norge", value: num(meta.norge[`${felt}_${vindu}`]) },
  ];

  return (
    <section className="panel" aria-label="Ditt tall">
      <p className="eyebrow">{sel.adresse ? "Ditt tall" : "Valgt rute (250 × 250 m)"}</p>
      <h2>{sel.adresse ?? `${kommune?.navn ?? ""}`}</h2>
      {avstand > 0 && (
        <p className="note">Ruten har ingen registrerte beboere. Viser nærmeste befolkede rute, {fmt(avstand)} m unna.</p>
      )}
      <p className="meta-line">
        {fmt(num(det.befolkning))} innbyggere i ruten · {String(kommune?.navn ?? "")} · grunnkrets {String(det.grunnkretsnummer ?? "–")}
      </p>
      <GradeBadge letter={grade(mf, b)} score={mf} label="Mobilitetsfrihet" />
      <Bar label="Kollektiv kvalitet" value={kk} compare={sammenlign("kk")} />
      <Bar label="Transportvalgfrihet" value={tv} compare={sammenlign("tv")} />
      <p>
        <strong>Kollektivnivå:</strong> {fmt(avg)} ulike avganger i timen ({KN_NAVN[knLevel(avg, meta.parametere.kollektivnivaa_grenser)].toLowerCase()}).{" "}
        <strong>God tilgang</strong> (SSB-definisjon): {num(det.god_tilgang) ? "ja" : "nei"}.
      </p>

      <h3>Hva du når</h3>
      <div className="table-scroll">
        <table className="reach">
          <thead>
            <tr>
              <th scope="col">Mål</th>
              <th scope="col" colSpan={3}>Kollektiv (30 / 60 / 90 min)</th>
              <th scope="col" colSpan={3}>Bil (30 / 60 / 90 min)</th>
            </tr>
          </thead>
          <tbody>
            {KATEGORIER.map((k) => (
              <tr key={k}>
                <th scope="row">{meta.kategorier[k].navn}</th>
                {[30, 60, 90].map((g) => <td key={`k${g}`}>{fmt(num(det[`kol_${k}_${g}_${vindu}`]))}</td>)}
                {[30, 60, 90].map((g) => <td key={`b${g}`} className="car">{fmt(num(det[`bil_${k}_${g}`]))}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="sensitivity">
        <summary>Juster vektene (følsomhet)</summary>
        <p className="hint">Vektene normaliseres til sum 100 %. Pipelinens standard: {KATEGORIER.map((k) => `${meta.kategorier[k].navn} ${Math.round(meta.kategorier[k].vekt * 100)} %`).join(", ")}.</p>
        {KATEGORIER.map((k) => (
          <label key={k} className="slider">
            <span>{meta.kategorier[k].navn}</span>
            <input type="range" min={0} max={0.6} step={0.05} value={vekter[k]} onChange={(e) => setVekter({ ...vekter, [k]: Number(e.target.value) })} />
            <output>{fmt(vekter[k] * 100)}</output>
          </label>
        ))}
        {justert && (
          <p>
            Med dine vekter: mobilitetsfrihet <strong>{fmt(justert.mf, 1)}</strong> ({grade(justert.mf, b)}), kollektiv kvalitet {fmt(justert.kk, 1)}, transportvalgfrihet {fmt(justert.tv, 1)}.
          </p>
        )}
      </details>

      <h3>Avganger nå</h3>
      {!ENTUR_CLIENT_NAME && <p className="hint">Sett ENTUR_CLIENT_NAME i .env for å vise live-avganger fra Entur.</p>}
      {ENTUR_CLIENT_NAME && avganger === null && <p className="hint">Henter avganger fra Entur …</p>}
      {avganger?.length === 0 && <p className="hint">Ingen holdeplasser med avganger innen 800 m den neste timen.</p>}
      {avganger?.slice(0, 3).map((s) => (
        <div key={s.stopName} className="stop">
          <strong>{s.stopName}</strong> <span className="hint">{fmt(s.distance)} m</span>
          {s.departures.length === 0 && <p className="hint">Ingen avganger den neste timen.</p>}
          <ul>
            {s.departures.map((d) => (
              <li key={`${d.line}-${d.expected}`}>
                <time>{new Date(d.expected).toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" })}</time> {d.line} {d.destination}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
