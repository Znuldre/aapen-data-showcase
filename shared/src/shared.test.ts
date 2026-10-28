import { afterEach, describe, expect, it, vi } from "vitest";

import { enturHeaders, geocode } from "./entur/client";
import { cellPolygon, ssbidFromLonLat, ssbidFromXY, xyFromSsbid } from "./geo/ssbGrid";
import { clearCache, fetchJson, HttpError } from "./http/fetchJson";
import { locationforecastUrl, roundCoordinate } from "./met/locationforecast";

const json = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" }, ...init });

afterEach(() => clearCache());

describe("Geonøkkelen (SSB-rutenett)", () => {
  it("gir samme rute-ID som Python-pipelinen", () => {
    expect(ssbidFromXY(262_400, 6_649_300)).toBe(22622506649250);
    expect(xyFromSsbid(22622506649250)).toEqual([262_250, 6_649_250]);
  });

  it("håndterer negativ x vest i landet (Bergen)", () => {
    const id = ssbidFromXY(-31_200, 6_731_900);
    const [x0, y0] = xyFromSsbid(id);
    expect(x0).toBe(-31_250);
    expect(y0).toBe(6_731_750);
  });

  it("finner ruten for Oslo S fra lengde-/breddegrad, og polygonet omslutter punktet", () => {
    const id = ssbidFromLonLat(10.7528, 59.9111);
    const ring = cellPolygon(id);
    const lons = ring.map(([lon]) => lon);
    const lats = ring.map(([, lat]) => lat);
    expect(Math.min(...lons)).toBeLessThan(10.7528);
    expect(Math.max(...lons)).toBeGreaterThan(10.7528);
    expect(Math.min(...lats)).toBeLessThan(59.9111);
    expect(Math.max(...lats)).toBeGreaterThan(59.9111);
  });
});

describe("Entur-identifikasjon", () => {
  it("setter ET-Client-Name og avviser feil format", () => {
    expect(enturHeaders({ clientName: "aapendata-showcase" })).toEqual({ "ET-Client-Name": "aapendata-showcase" });
    expect(() => enturHeaders({ clientName: "showcase" })).toThrow();
  });

  it("sender headeren med Geocoder-kallet", async () => {
    const fetchImpl = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => json({ features: [] }));
    await geocode({ clientName: "aapendata-showcase", fetchImpl: fetchImpl as unknown as typeof fetch }, "Bergen");
    const init = fetchImpl.mock.calls[0][1]!;
    expect((init.headers as Record<string, string>)["ET-Client-Name"]).toBe("aapendata-showcase");
    expect(String(fetchImpl.mock.calls[0][0])).toContain("/geocoder/v3/autocomplete?q=Bergen");
  });
});

describe("MET-koordinater", () => {
  it("runder til maks fire desimaler", () => {
    expect(roundCoordinate(59.911123456)).toBe(59.9111);
    expect(locationforecastUrl(59.911123456, 10.752849)).toContain("lat=59.9111&lon=10.7528");
  });
});

describe("fetchJson", () => {
  it("prøver på nytt ved 503 og gir opp med HttpError ved 404", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValueOnce(json({ ok: true }));
    await expect(fetchJson("https://example.org/a", { fetchImpl, retries: 1 })).resolves.toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    const notFound = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    await expect(fetchJson("https://example.org/b", { fetchImpl: notFound })).rejects.toBeInstanceOf(HttpError);
  });

  it("gjenbruker svar fra minnecachen innenfor TTL", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ n: 1 }));
    await fetchJson("https://example.org/c", { fetchImpl, cacheTtlMs: 10_000 });
    await fetchJson("https://example.org/c", { fetchImpl, cacheTtlMs: 10_000 });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
