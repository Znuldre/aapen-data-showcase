import { GRADE_COLORS } from "@showcase/shared/ui";

import { fmt } from "../scales";

export function GradeBadge({ letter, score, label }: { letter: string | null; score?: number | null; label?: string }) {
  return (
    <div className="grade" aria-label={`${label ?? "Karakter"} ${letter ?? "mangler"}`}>
      <span className="grade-letter" style={{ background: letter ? GRADE_COLORS[letter] : "var(--muted)" }}>
        {letter ?? "–"}
      </span>
      {score !== undefined && (
        <span className="grade-score">
          {fmt(score, 1)}
          <small> av 100</small>
        </span>
      )}
    </div>
  );
}

export function Bar({ label, value, max = 100, compare }: { label: string; value: number | null; max?: number; compare?: { label: string; value: number }[] }) {
  const w = value === null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="bar">
      <div className="bar-head">
        <span>{label}</span>
        <strong>{fmt(value, 1)}</strong>
      </div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${w}%` }} />
        {compare?.map((c) => (
          <span key={c.label} className="bar-mark" style={{ left: `${Math.min(100, (c.value / max) * 100)}%` }} title={`${c.label}: ${fmt(c.value, 1)}`} />
        ))}
      </div>
      {compare && (
        <div className="bar-compare">
          {compare.map((c) => (
            <span key={c.label}>
              {c.label}: {fmt(c.value, 1)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function Lorenz({ points, gini }: { points: number[]; gini: number }) {
  const n = points.length - 1;
  const path = points.map((y, i) => `${i === 0 ? "M" : "L"}${(i / n) * 100},${100 - y * 100}`).join(" ");
  return (
    <figure className="lorenz">
      <svg viewBox="-8 -4 116 116" role="img" aria-label={`Lorenzkurve, Gini ${fmt(gini, 2)}`}>
        <line x1="0" y1="100" x2="100" y2="0" className="lorenz-equal" />
        <path d={`${path} L100,100 L0,100 Z`} className="lorenz-area" />
        <path d={path} className="lorenz-line" />
        <line x1="0" y1="100" x2="100" y2="100" className="axis" />
        <line x1="0" y1="0" x2="0" y2="100" className="axis" />
        <text x="50" y="112" textAnchor="middle">andel av befolkningen</text>
      </svg>
      <figcaption>
        Gini {fmt(gini, 2)} – jo lenger kurven ligger under diagonalen, jo skjevere er mobilitetsfriheten fordelt innad i kommunen.
      </figcaption>
    </figure>
  );
}

export function GradeDistribution({ andeler }: { andeler: Record<string, number> }) {
  return (
    <div className="distribution" role="img" aria-label="Andel av befolkningen per karakter">
      {"ABCDEFG".split("").map((letter) =>
        andeler[letter] > 0 ? (
          <span key={letter} style={{ width: `${andeler[letter] * 100}%`, background: GRADE_COLORS[letter] }} title={`${letter}: ${fmt(andeler[letter] * 100, 0)} %`}>
            {andeler[letter] > 0.07 ? letter : ""}
          </span>
        ) : null,
      )}
    </div>
  );
}
