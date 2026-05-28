import type { ConvictionRequest, ConvictionResponse, GainerDetail, GainersListResponse, Market, StockAnalysisResponse } from "../types";

const BASE_URL = "/api";

interface FetchOptions {
  signal?: AbortSignal;
  refresh?: boolean;
  method?: string;
  body?: string;
  headers?: Record<string, string>;
}

async function fetchJSON<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { signal, method, body, headers } = options;
  const resp = await fetch(`${BASE_URL}${path}`, { signal, method, body, headers });
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody.detail ?? `Request failed: ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  getGainers: (market: Market, period = "1d", options: FetchOptions = {}): Promise<GainersListResponse> => {
    const params = new URLSearchParams();
    if (period !== "1d") params.set("period", period);
    if (options.refresh) params.set("refresh", "true");
    const qs = params.toString();
    return fetchJSON(`/gainers/${market}${qs ? `?${qs}` : ""}`, options);
  },

  getGainerDetail: (market: Market, ticker: string, options: FetchOptions = {}): Promise<GainerDetail> =>
    fetchJSON(`/gainers/${market}/${ticker}${options.refresh ? "?refresh=true" : ""}`, options),

  /** Slow AI endpoint (~10-15 s cold). Fetch in parallel with getGainerDetail. */
  getGainerAnalysis: (market: Market, ticker: string, options: FetchOptions = {}): Promise<StockAnalysisResponse> =>
    fetchJSON(`/gainers/${market}/${ticker}/analyse${options.refresh ? "?refresh=true" : ""}`, options),

  invalidateCache: (market: Market, ticker: string): Promise<{ status: string }> =>
    fetchJSON(`/gainers/${market}/${ticker}/cache`, { method: "DELETE" }),

  /** Conviction thesis analysis (~10-15 s cold). Cached 24 h per belief. */
  analyseConviction: (body: ConvictionRequest): Promise<ConvictionResponse> =>
    fetchJSON("/conviction/analyse", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
};
