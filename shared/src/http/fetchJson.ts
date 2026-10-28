// Felles fetch for alle API-klientene: tidsavbrudd, retry med backoff, minnecache og ETag.

export interface FetchJsonOptions {
  method?: "GET" | "POST";
  headers?: Record<string, string>;
  body?: unknown;
  /** Antall nye forsøk ved 429 og 5xx (standard 2). */
  retries?: number;
  timeoutMs?: number;
  /** Hvor lenge et svar kan gjenbrukes fra minnecachen (0 = ingen cache). */
  cacheTtlMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

interface CacheEntry {
  expires: number;
  etag?: string;
  data: unknown;
}

const cache = new Map<string, CacheEntry>();

export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly url: string,
  ) {
    super(`HTTP ${status} fra ${url}`);
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function clearCache(): void {
  cache.clear();
}

export async function fetchJson<T>(url: string, options: FetchJsonOptions = {}): Promise<T> {
  const { method = "GET", headers = {}, body, retries = 2, timeoutMs = 20_000, cacheTtlMs = 0, signal } = options;
  const doFetch = options.fetchImpl ?? fetch;
  const key = method === "GET" ? url : `${url}#${JSON.stringify(body)}`;
  const cached = cache.get(key);
  if (cached && cached.expires > Date.now()) return cached.data as T;

  for (let attempt = 0; ; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    signal?.addEventListener("abort", () => controller.abort(), { once: true });
    try {
      const response = await doFetch(url, {
        method,
        headers: {
          Accept: "application/json",
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
          ...(cached?.etag ? { "If-None-Match": cached.etag } : {}),
          ...headers,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      if (response.status === 304 && cached) {
        cached.expires = Date.now() + cacheTtlMs;
        return cached.data as T;
      }
      if ((response.status === 429 || response.status >= 500) && attempt < retries) {
        const retryAfter = Number(response.headers.get("Retry-After"));
        await sleep(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 500 * 2 ** attempt);
        continue;
      }
      if (!response.ok) throw new HttpError(response.status, url);
      const data = (await response.json()) as T;
      if (cacheTtlMs > 0) {
        cache.set(key, { expires: Date.now() + cacheTtlMs, etag: response.headers.get("ETag") ?? undefined, data });
      }
      return data;
    } finally {
      clearTimeout(timer);
    }
  }
}
