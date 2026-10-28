import { useEffect, useRef, useState } from "react";

import { searchAddresses, type Address } from "@showcase/shared";

export function AddressSearch({ onPick }: { onPick: (a: Address) => void }) {
  const [text, setText] = useState("");
  const [hits, setHits] = useState<Address[]>([]);
  const [open, setOpen] = useState(false);
  const [feil, setFeil] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Teksten settes til valgt adresse etter et valg; da skal det ikke søkes og listen åpnes igjen
  const hoppOver = useRef(false);

  const velg = (a: Address) => {
    hoppOver.current = true;
    setText(`${a.text}, ${a.poststed}`);
    setOpen(false);
    onPick(a);
  };

  useEffect(() => {
    clearTimeout(timer.current);
    if (hoppOver.current) {
      hoppOver.current = false;
      return;
    }
    if (text.trim().length < 3) {
      setHits([]);
      return;
    }
    timer.current = setTimeout(() => {
      searchAddresses(text, 6)
        .then((r) => {
          setHits(r);
          setFeil(null);
          setOpen(true);
        })
        .catch(() => setFeil("Adressesøket svarte ikke. Prøv igjen."));
    }, 250);
    return () => clearTimeout(timer.current);
  }, [text]);

  return (
    <div className="search">
      <label htmlFor="adresse">Finn ditt tall</label>
      <input
        id="adresse"
        type="search"
        placeholder="Skriv en adresse, f.eks. Storgata 1, Tromsø"
        value={text}
        autoComplete="off"
        onChange={(e) => setText(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits[0]) velg(hits[0]);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {feil && <p className="error">{feil}</p>}
      {open && hits.length > 0 && (
        <ul className="search-hits" role="listbox">
          {hits.map((a) => (
            <li key={`${a.text}-${a.postnummer}`}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => velg(a)}>
                {a.text}
                <span>{a.postnummer} {a.poststed} · {a.kommunenavn}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
