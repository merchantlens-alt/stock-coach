import type { AddPortfolioEntryRequest, AdvisorEvaluateRequest, AdvisorEvaluateResponse, AllocationPlanResponse, CompareRequest, CompareResponse, ConvictionRequest, ConvictionResponse, FundScanResponse, GainerDetail, GrowthTriggersReport, InvestorProfile, Market, ModelPortfolioResponse, PortfolioEntry, PortfolioPricesResponse, PortfolioSummary, PortfolioXrayResponse, PriceHistory, RiskProfile, StockAnalysisResponse, XrayRequest } from "../types";

const BASE_URL = "/api";
const TOKEN_KEY = "sc_token";

// Module-level token store — avoids repeated localStorage reads per request
let _token: string | null = null;

try { _token = localStorage.getItem(TOKEN_KEY); } catch { /* SSR safety */ }

export const authToken = {
  get: () => _token,
  set: (t: string) => { _token = t; try { localStorage.setItem(TOKEN_KEY, t); } catch { /**/ } },
  clear: () => { _token = null; try { localStorage.removeItem(TOKEN_KEY); } catch { /**/ } },
};

// App.tsx subscribes to this to force a re-render on 401
const _unauthListeners: Array<() => void> = [];
export function onUnauthenticated(cb: () => void) { _unauthListeners.push(cb); }
function _notifyUnauth() { _unauthListeners.forEach(fn => fn()); }

interface FetchOptions {
  signal?: AbortSignal;
  refresh?: boolean;
  method?: string;
  body?: string;
  headers?: Record<string, string>;
}

async function fetchJSON<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { signal, method, body, headers } = options;
  const mergedHeaders: Record<string, string> = { ...headers };
  if (_token) mergedHeaders["Authorization"] = `Bearer ${_token}`;
  const resp = await fetch(`${BASE_URL}${path}`, {
    signal, method, body,
    headers: mergedHeaders,
  });
  if (resp.status === 401) {
    authToken.clear();
    _notifyUnauth();
    throw new Error("Session expired. Please log in again.");
  }
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody.detail ?? `Request failed: ${resp.status}`);
  }
  // 204 No Content (e.g. DELETE) has no body — return undefined rather than
  // letting resp.json() throw a SyntaxError on the empty stream.
  if (resp.status === 204) {
    return undefined as unknown as T;
  }
  return resp.json() as Promise<T>;
}

export const api = {
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

  /** OHLCV candlestick data. Cached 30 min. */
  getPriceHistory: (market: Market, ticker: string, period = "3mo"): Promise<PriceHistory> =>
    fetchJSON(`/gainers/${market}/${ticker}/history?period=${period}`),

  /** Growth Triggers research note. Cached 24 h. Cold: ~15-25 s (grounded AI). */
  getGrowthTriggers: (market: Market, ticker: string, options: FetchOptions = {}): Promise<GrowthTriggersReport> =>
    fetchJSON(`/gainers/${market}/${ticker}/growth-triggers${options.refresh ? "?refresh=true" : ""}`, options),

  getPortfolio: (): Promise<PortfolioSummary> =>
    fetchJSON("/portfolio"),

  addPortfolioEntry: (body: AddPortfolioEntryRequest): Promise<PortfolioEntry> =>
    fetchJSON("/portfolio", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),

  deletePortfolioEntry: (id: string): Promise<void> =>
    fetchJSON(`/portfolio/${id}`, { method: "DELETE" }),

  resolvePortfolioEntry: (id: string, actualPrice: number): Promise<PortfolioEntry> =>
    fetchJSON(`/portfolio/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ actual_price: actualPrice }),
      headers: { "Content-Type": "application/json" },
    }),

  markExpiredPortfolio: (): Promise<{ marked_expired: number }> =>
    fetchJSON("/portfolio/resolve-expired", { method: "POST" }),

  /**
   * Batch-fetch current market prices for a list of portfolio tickers.
   * Tickers missing from the response simply have no live price available.
   */
  getPortfolioPrices: (tickers: string[], market: Market): Promise<PortfolioPricesResponse> =>
    fetchJSON(`/portfolio/prices?tickers=${tickers.join(",")}&market=${market}`),

  /** Fund scanner — India mutual funds or US ETFs with metrics + entry verdict. Cached 6 h. */
  getFundScan: (market: Market = "india", category?: string, options: FetchOptions = {}): Promise<FundScanResponse> => {
    const params = new URLSearchParams({ market });
    if (category) params.set("category", category);
    if (options.refresh) params.set("refresh", "true");
    return fetchJSON(`/funds/scan?${params.toString()}`, options);
  },

  /** Generic 5-fund model portfolio for a self-selected market + risk level. Cached 6 h. */
  getModelPortfolio: (market: Market = "india", risk: RiskProfile = "balanced", options: FetchOptions = {}): Promise<ModelPortfolioResponse> => {
    const params = new URLSearchParams({ market, risk });
    if (options.refresh) params.set("refresh", "true");
    return fetchJSON(`/funds/model-portfolio?${params.toString()}`, options);
  },

  /** SIP backtest: your funds vs the model portfolio over trailing 1/3/5 years. */
  compareFunds: (body: CompareRequest): Promise<CompareResponse> =>
    fetchJSON("/funds/compare", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),

  /** Portfolio X-ray: allocation, US sector/company look-through, gaps, AI summary. */
  xrayPortfolio: (body: XrayRequest): Promise<PortfolioXrayResponse> =>
    fetchJSON("/funds/xray", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),

  /** Investor profile — returns 404 if not set yet. */
  getInvestorProfile: (): Promise<InvestorProfile> =>
    fetchJSON("/investor-profile"),

  /** Save / update investor profile. */
  saveInvestorProfile: (profile: InvestorProfile): Promise<InvestorProfile> =>
    fetchJSON("/investor-profile", {
      method: "PUT",
      body: JSON.stringify(profile),
      headers: { "Content-Type": "application/json" },
    }),

  /** AI cross-asset allocation plan based on full investor profile. Cached 24 h. */
  getAllocationPlan: (options: FetchOptions = {}): Promise<AllocationPlanResponse> =>
    fetchJSON(`/advisor/allocation-plan${options.refresh ? "?refresh=true" : ""}`, options),

  /** Get personalised Buy/Pass verdict for a stock or fund. */
  evaluateAdvisor: (body: AdvisorEvaluateRequest): Promise<AdvisorEvaluateResponse> =>
    fetchJSON("/advisor/evaluate", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
};
