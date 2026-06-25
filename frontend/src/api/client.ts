import type { AddPortfolioEntryRequest, AdvisorEvaluateRequest, AdvisorEvaluateResponse, CompareRequest, CompareResponse, ConvictionRequest, ConvictionResponse, FundScanResponse, GainerDetail, GrowthTriggersReport, InvestorProfile, Market, ModelPortfolioResponse, PortfolioEntry, PortfolioPricesResponse, PortfolioSummary, PortfolioXrayResponse, PriceHistory, RiskProfile, StockAnalysisResponse, XrayRequest } from "../types";

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

  /** Get personalised Buy/Pass verdict for a stock or fund. */
  evaluateAdvisor: (body: AdvisorEvaluateRequest): Promise<AdvisorEvaluateResponse> =>
    fetchJSON("/advisor/evaluate", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
};
