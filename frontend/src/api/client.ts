import type { GainerDetail, GainersListResponse, Market } from "../types";

const BASE_URL = "/api";

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, options);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  getGainers: (market: Market, refresh = false): Promise<GainersListResponse> =>
    fetchJSON(`/gainers/${market}${refresh ? "?refresh=true" : ""}`),

  getGainerDetail: (market: Market, ticker: string, refresh = false): Promise<GainerDetail> =>
    fetchJSON(`/gainers/${market}/${ticker}${refresh ? "?refresh=true" : ""}`),

  invalidateCache: (market: Market, ticker: string): Promise<{ status: string }> =>
    fetchJSON(`/gainers/${market}/${ticker}/cache`, { method: "DELETE" }),
};
