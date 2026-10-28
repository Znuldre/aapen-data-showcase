import { useEffect, useState } from "react";

import { load, type KommuneProfil, type Meta, type Skala, type Vindu } from "../data";
import { bands, fmt, grade, pct } from "../scales";
import { Bar, GradeBadge, GradeDistribution, Lorenz } from "./Bits";

const num = (v: unknown) => (v === null || v === undefined ? 0 : Number(v));

interface KommuneProps {
  meta: Meta;
  kommune: Record<string, unknown>;
  vindu: Vindu;
  skala: Skala;
}

export function KommunePanel({ meta, kommune, vindu, skala }: KommuneProps) {
  const [profil, setProfil] = useState<KommuneProfil | null>(null);
  const knr = String(kommune.kommunenummer);
  const fylke = meta.fylker.find((f) => f.nr === knr.slice(0, 2));

  useEffect(() => {
    load<Record<string, KommuneProfil>>("kommuner_profiler.json").then((p) => setProfil(p[knr] ?? null));
  }, [knr]);

  const mf = num(kommune[`mf_${vindu}`]);
  const sammenlign = (felt: string) => [
    ...(fylke ? [{ label: fylke.navn, value: num(fylke[`${felt}_${vindu}`]) }] : []),
    { label: "Norge", value: num(meta.norge[`${felt}_${vindu}`]) },
  ];

  return (
    <section className="panel" aria-label={`Kommuneprofil for ${kommune.navn}`}>
      <p className="eyebrow">Kommune {knr} · {fylke?.navn}</p>
      <h2>{String(kommune.navn)}</h2>
      <p className="meta-line">{fmt(num(kommune.befolkning))} innbyggere · befolkningsvektet snitt</p>
      <GradeBadge letter={grade(mf, bands(meta, "mf", skala))} score={mf} label="Mobilitetsfrihet" />
      <Bar label="Kollektiv kvalitet" value={num(kommune[`kk_${vindu}`])} compare={sammenlign("kk")} />
      <Bar label="Transportvalgfrihet" value={num(kommune[`tv_${vindu}`])} compare={sammenlign("tv")} />
      <p>
        <strong>{pct(num(kommune.andel_god_tilgang))}</strong> bor med god tilgang til kollektivtransport (holdeplass innen 500 m med minst én avgang i timen 07–19, SSB-definisjon). Norge: {pct(num(meta.norge.andel_god_tilgang))}.
      </p>
      {profil && (
        <>
          <h3>Fordeling i kommunen</h3>
          <p className="hint">Andel innbyggere per karakter, hverdag morgen, DK-skala.</p>
          <GradeDistribution andeler={profil.andeler} />
          <Lorenz points={profil.lorenz} gini={num(kommune.gini_morgen)} />
          <div className="two-col">
            <div>
              <h4>Svakest</h4>
              <ol className="kretser">
                {profil.svakest.map(([nr, navn, v]) => <li key={nr}>{navn} <span>{fmt(v, 1)}</span></li>)}
              </ol>
            </div>
            <div>
              <h4>Sterkest</h4>
              <ol className="kretser">
                {profil.sterkest.map(([nr, navn, v]) => <li key={nr}>{navn} <span>{fmt(v, 1)}</span></li>)}
              </ol>
            </div>
          </div>
          <p className="hint">Grunnkretser med minst 50 innbyggere, mobilitetsfrihet hverdag morgen.</p>
        </>
      )}
    </section>
  );
}

export function GrunnkretsPanel({ meta, props, vindu, skala }: { meta: Meta; props: Record<string, unknown>; vindu: Vindu; skala: Skala }) {
  const mf = num(props[`mf_${vindu}`]);
  return (
    <section className="panel" aria-label="Grunnkrets">
      <p className="eyebrow">Grunnkrets {String(props.grunnkretsnummer)}</p>
      <h2>{String(props.grunnkretsnavn)}</h2>
      <p className="meta-line">{fmt(num(props.befolkning))} innbyggere</p>
      <GradeBadge letter={grade(mf, bands(meta, "mf", skala))} score={mf} label="Mobilitetsfrihet" />
      <Bar label="Kollektiv kvalitet" value={num(props[`kk_${vindu}`])} />
      <Bar label="Transportvalgfrihet" value={num(props[`tv_${vindu}`])} />
      <p>
        {fmt(num(props[`avganger_${vindu}`]), 0)} ulike avganger i timen i snitt · {pct(num(props.andel_god_tilgang))} med god tilgang (SSB-definisjon).
      </p>
      <p className="hint">Zoom videre inn for å se 250 m-rutene, eller søk opp en adresse.</p>
    </section>
  );
}

export function NorgePanel({ meta, vindu, skala }: { meta: Meta; vindu: Vindu; skala: Skala }) {
  const b = bands(meta, "mf", skala);
  const fylker = [...meta.fylker].sort((a, c) => num(c[`mf_${vindu}`]) - num(a[`mf_${vindu}`]));
  return (
    <section className="panel" aria-label="Norge samlet">
      <p className="eyebrow">Norge samlet · {meta.tidsvinduer[vindu].navn}</p>
      <h2>Hvor fritt kan du bevege deg uten bil?</h2>
      <GradeBadge letter={grade(num(meta.norge[`mf_${vindu}`]), b)} score={num(meta.norge[`mf_${vindu}`])} label="Mobilitetsfrihet, Norge" />
      <p>
        {fmt(num(meta.norge.befolkning))} innbyggere i 250 m-ruter. <strong>{pct(num(meta.norge.andel_god_tilgang))}</strong> bor med god tilgang til kollektivtransport (SSB-definisjon). Klikk på en kommune, eller søk opp en adresse for å få ditt eget tall.
      </p>
      <table className="fylker">
        <thead>
          <tr><th scope="col">Fylke</th><th scope="col">MF</th><th scope="col">God tilgang</th></tr>
        </thead>
        <tbody>
          {fylker.map((f) => (
            <tr key={f.nr}>
              <th scope="row">{f.navn}</th>
              <td><span className="mini-grade" data-grade={grade(num(f[`mf_${vindu}`]), b) ?? ""}>{grade(num(f[`mf_${vindu}`]), b)}</span> {fmt(num(f[`mf_${vindu}`]), 1)}</td>
              <td>{pct(f.andel_god_tilgang)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {meta.transport_performance && meta.transport_performance.length > 0 && (
        <>
          <h3>EUs «transport performance» i bysentrene</h3>
          <p className="hint">
            Hvor stor andel av befolkningen innen 7,5 km du når med kollektiv på 30 minutter (hverdag 07–08), etter EU-kommisjonens metode. Bysentre etter DEGURBA på 1 km-rutenett.
          </p>
          <table className="fylker">
            <thead>
              <tr><th scope="col">Bysenter</th><th scope="col">Innbyggere</th><th scope="col">Andel nådd</th></tr>
            </thead>
            <tbody>
              {meta.transport_performance.map((t) => (
                <tr key={t.bysenter}>
                  <th scope="row">{t.navn}</th>
                  <td>{fmt(t.befolkning)}</td>
                  <td>{pct(t.transport_performance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
