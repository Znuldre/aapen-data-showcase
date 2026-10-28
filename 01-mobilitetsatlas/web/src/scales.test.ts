import { GRADE_COLORS } from "@showcase/shared/ui";
import { describe, expect, it } from "vitest";

import type { Band, Meta } from "./data";
import { fillColor, grade, knLevel } from "./scales";

const DK: Band[] = [["A", 70], ["B", 55], ["C", 45], ["D", 30], ["E", 22], ["F", 15], ["G", 0]];

describe("karakterer", () => {
  it("følger DK-grensene, og en score på grensen får den høyeste karakteren", () => {
    expect(grade(100, DK)).toBe("A");
    expect(grade(70, DK)).toBe("A");
    expect(grade(69.9, DK)).toBe("B");
    expect(grade(15, DK)).toBe("F");
    expect(grade(14.9, DK)).toBe("G");
    expect(grade(0, DK)).toBe("G");
  });

  it("gir null for manglende verdier", () => {
    expect(grade(null, DK)).toBeNull();
    expect(grade(Number.NaN, DK)).toBeNull();
  });
});

describe("fargeuttrykk", () => {
  it("slår sammen like terskler, og den høyeste karakteren vinner som i grade()", () => {
    const like: Band[] = [["A", 60], ["B", 40], ["C", 20], ["D", 0], ["E", 0], ["F", 0], ["G", 0]];
    const meta = { skalaer: { dk: DK, no: like } } as unknown as Meta;
    const step = (fillColor(meta, "mf", "morgen", "no", "flate") as unknown[])[3] as unknown[];
    const terskler = step.slice(3).filter((_, i) => i % 2 === 0);
    expect(terskler).toEqual([0, 20, 40, 60]);
    expect(step[4]).toBe(GRADE_COLORS[grade(0, like)!]);
  });
});

describe("kollektivnivå", () => {
  it("teller grensene som er nådd", () => {
    const grenser = [1, 2, 4, 8, 16, 32];
    expect(knLevel(0, grenser)).toBe(0);
    expect(knLevel(1, grenser)).toBe(1);
    expect(knLevel(3, grenser)).toBe(2);
    expect(knLevel(31, grenser)).toBe(5);
    expect(knLevel(100, grenser)).toBe(6);
  });
});
