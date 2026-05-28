import type { GainerDetail, GainersListResponse, Market, StockAnalysisResponse } from "../types";

const BASE_URL = "/api";

interface FetchOptions {
  signal?: AbortSignal;
  refresh?: boolean;
  method?: string;
}

async function fetchJSON<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { signal, method } = options;
  const resp = await fetch(`${BASE_URL}${path}`, { signal, method });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  getGainers: (market: Market, options: FetchOptions = {}): Promise<GainersListResponse> =>
    fetchJSON(`/gainers/${market}${options.refresh ? "?refresh=true" : ""}`, options),

  getGainerDetail: (market: Market, ticker: string, options: FetchOptions = {}): Promise<GainerDetail> =>
    fetchJSON(`/gainers/${market}/${ticker}${options.refresh ? "?refresh=true" : ""}`, options),

  /** Slow AI endpoint (~10-15 s cold). Fetch in parallel with getGainerDetail. */
  getGainerAnalysis: (market: Market, ticker: string, options: FetchOptions = {}): Promise<StockAnalysisResponse> =>
    fetchJSON(`/gainers/${market}/${ticker}/analyse${options.refresh ? "?refresh=true" : ""}`, options),

  invalidateCache: (market: Market, ticker: string): Promise<{ status: string }> =>
    fetchJSON(`/gainers/${market}/${ticker}/cache`, { method: "DELETE" }),
};
