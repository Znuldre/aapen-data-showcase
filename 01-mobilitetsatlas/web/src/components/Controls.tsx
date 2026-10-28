import { GRADE_COLORS } from "@showcase/shared/ui";

import { vinduer, type Indikator, type Meta, type Skala, type Vindu } from "../data";
import { bands, INDIKATORFORKLARING, INDIKATORNAVN, KN_FARGER, KN_NAVN } from "../scales";

interface Props {
  meta: Meta;
  indikator: Indikator;
  vindu: Vindu;
  skala: Skala;
  onIndikator: (i: Indikator) => void;
  onVindu: (v: Vindu) => void;
  onSkala: (s: Skala) => void;
}

function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <fieldset className="segmented">
      <legend>{label}</legend>
      <div role="radiogroup" aria-label={label}>
        {options.map(([v, text]) => (
          <button key={v} type="button" role="radio" aria-checked={v === value} className={v === value ? "on" : ""} onClick={() => onChange(v)}>
            {text}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function Controls({ meta, indikator, vindu, skala, onIndikator, onVindu, onSkala }: Props) {
  const b = bands(meta, indikator, skala);
  return (
    <section className="controls" aria-label="Kartvalg">
      <Segmented
        label="Indikator"
        value={indikator}
        options={(["mf", "kk", "tv", "kn"] as Indikator[]).map((i) => [i, INDIKATORNAVN[i]])}
        onChange={onIndikator}
      />
      <p className="hint">{INDIKATORFORKLARING[indikator]}</p>
      <Segmented label="Tidsvindu" value={vindu} options={vinduer(meta).map((v) => [v, meta.tidsvinduer[v].navn])} onChange={onVindu} />
      {indikator === "mf" && (
        <Segmented
          label="Skala"
          value={skala}
          options={[["dk", "DK-skala"], ["no", "NO-skala"]]}
          onChange={onSkala}
        />
      )}
      <div className="legend" aria-label="Tegnforklaring">
        {indikator === "kn"
          ? KN_NAVN.map((navn, i) => (
              <span key={navn} className="legend-item">
                <i style={{ background: KN_FARGER[i] }} />
                {navn}
              </span>
            ))
          : b.map(([letter, lower], i) => (
              <span key={letter} className="legend-item">
                <i style={{ background: GRADE_COLORS[letter] }} />
                <b>{letter}</b> {Math.round(lower)}–{i === 0 ? 100 : Math.round(b[i - 1][1])}
              </span>
            ))}
      </div>
    </section>
  );
}
