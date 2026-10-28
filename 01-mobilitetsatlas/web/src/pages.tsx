import { marked } from "marked";

import metode from "../../METODE.md?raw";

import type { Meta } from "./data";
import { fmt } from "./scales";

export function MethodPage() {
  // METODE.md er vårt eget innhold i repoet, ikke brukerinput
  return <article className="page prose" dangerouslySetInnerHTML={{ __html: marked.parse(metode, { async: false }) as string }} />;
}

const NEDLASTINGER = [
  ["kommuner.csv", "Indikatorer per kommune (357 kommuner)"],
  ["grunnkretser.csv", "Indikatorer per grunnkrets"],
  ["ruter.csv.gz", "Indikatorer per befolket 250 m-rute (gzip)"],
] as const;

export function DataPage({ meta }: { meta: Meta }) {
  return (
    <article className="page">
      <h1>Data og kilder</h1>
      <p>
        Versjon {meta.versjon}, generert {new Date(meta.generert).toLocaleString("nb-NO")}. Referansedager i rutetabellen: hverdag {meta.referansedager.hverdag}, lørdag {meta.referansedager.lordag}.
      </p>
      <h2>Last ned</h2>
      <ul>
        {NEDLASTINGER.map(([fil, tekst]) => (
          <li key={fil}>
            <a href={`${import.meta.env.BASE_URL}data/nedlasting/${fil}`} download>{fil}</a> – {tekst}
          </li>
        ))}
      </ul>
      <p className="hint">
        Lisensen for nedlastingene er ikke endelig avklart. Arbeidsplasser, tjenester, skoler og barnehager kommer fra offentlige registre (NLOD), mens gatenettet for reisetidene er fra OpenStreetMap (ODbL).
      </p>
      <h2>Kilder</h2>
      <div className="table-scroll">
        <table className="sources">
          <thead>
            <tr><th scope="col">Kilde</th><th scope="col">Lisens</th><th scope="col">Fil</th><th scope="col">Størrelse</th><th scope="col">Registrert</th><th scope="col">SHA-256</th></tr>
          </thead>
          <tbody>
            {meta.kilder.map((k) => (
              <tr key={k.kilde}>
                <th scope="row"><a href={k.url}>{k.kilde}</a></th>
                <td>{k.lisens}</td>
                <td>{k.fil}</td>
                <td>{fmt(k.bytes / 1e6, 1)} MB</td>
                <td>{k.http?.["Last-Modified"] ?? new Date(k.registrert).toLocaleDateString("nb-NO")}</td>
                <td><code title={k.sha256}>{k.sha256.slice(0, 12)}…</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Inspirert av <a href="https://mobilitetsatlas.dk/">Danmarks Mobilitetsatlas</a> (Beta Mobility, CC BY-SA 4.0). Strukturen i indikatoren følger den danske metoden; parameterne er våre egne og står i metodebeskrivelsen.
      </p>
    </article>
  );
}
