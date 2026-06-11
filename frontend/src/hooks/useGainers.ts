import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market, Period } from "../types";

// Radar: 10-min stale (backend cache is 12 h), keep in memory 2 h
const RADAR_STALE = 10 * 60 * 1000;
const RADAR_GC = 2 * 60 * 60 * 1000;

// Dip scan: 30-min client stale (backend caches 60 min)
export function useDips(market: Market) {
  return useQuery({
    queryKey: ["dips", market],
    queryFn: () => api.getDips(market),
    staleTime: 30 * 60 * 1000,
    gcTime: 2 * 60 * 60 * 1000,
    retry: 2,
  });
}

// Value Recovery scan: 1-h client stale (backend caches 2 h)
export function useValueRecovery(market: Market) {
  return useQuery({
    queryKey: ["value-recovery", market],
    queryFn: () => api.getValueRecovery(market),
    staleTime: 60 * 60 * 1000,
    gcTime: 3 * 60 * 60 * 1000,
    retry: 2,
  });
}

// Note: DETAIL_STALE / DETAIL_GC are reused for the analysis hook too.

// Gainers list: 5-min stale (backend cache is 30 min), keep in memory 2 hours
const GAINERS_STALE = 5 * 60 * 1000;
const GAINERS_GC = 2 * 60 * 60 * 1000;

// Analysis: 30-min stale, keep in memory 6 hours so switching stocks doesn't
// lose a previously loaded analysis — user can come back instantly from cache.
const DETAIL_STALE = 30 * 60 * 1000;
const DETAIL_GC = 6 * 60 * 60 * 1000;

export function useGainers(market: Market, period: Period = "1d") {
  return useQuery({
    queryKey: ["gainers", market, period],
    queryFn: () => api.getGainers(market, period),
    staleTime: GAINERS_STALE,
    gcTime: GAINERS_GC,
    retry: 2,
  });
}

export function useGainerDetail(market: Market, ticker: string | null) {
  return useQuery({
    queryKey: ["gainer-detail", market, ticker],
    queryFn: ({ signal }) => api.getGainerDetail(market, ticker!, { signal }),
    enabled: ticker !== null,
    staleTime: DETAIL_STALE,
    gcTime: DETAIL_GC,
    retry: 1,
  });
}

/**
 * Slow AI hook — fetches analysis + 30-day prediction (~10-15 s cold).
 * Always fires in parallel with useGainerDetail so the panel appears faster.
 * Cached 6 h — switching to another stock and coming back is instant.
 */
export function useGainerAnalysis(market: Market, ticker: string | null) {
  return useQuery({
    queryKey: ["gainer-analysis", market, ticker],
    queryFn: ({ signal }) => api.getGainerAnalysis(market, ticker!, { signal }),
    enabled: ticker !== null,
    staleTime: DETAIL_STALE,   // 30 min
    gcTime: DETAIL_GC,         // 6 hours in memory
    retry: 1,
  });
}

/**
 * Force-refresh a stock's AI analysis, bypassing both the React Query
 * in-memory cache and the server-side 24 h cache.
 * On success, writes the fresh result back into the React Query cache
 * so the UI re-renders immediately without a page reload.
 */
export function useRefreshAnalysis(market: Market, ticker: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.getGainerAnalysis(market, ticker!, { refresh: true }),
    onSuccess: (data) => {
      // Overwrite the cached entry — AnalysisPanel re-renders with quarterly data
      queryClient.setQueryData(["gainer-analysis", market, ticker], data);
    },
  });
}

/** OHLCV price history for candlestick chart. Cached 30 min. */
export function usePriceHistory(market: Market, ticker: string | null, period = "3mo") {
  return useQuery({
    queryKey: ["price-history", market, ticker, period],
    queryFn: () => api.getPriceHistory(market, ticker!, period),
    enabled: ticker !== null,
    staleTime: 30 * 60 * 1000,
    gcTime: 2 * 60 * 60 * 1000,
    retry: 1,
  });
}

/**
 * Catalyst radar — structural themes from today's news.
 * Cold call hits Gemini (~10-15 s); after that cached 12 h server-side.
 */
export function useRadar(market: Market) {
  return useQuery({
    queryKey: ["radar", market],
    queryFn: () => api.getRadar(market),
    staleTime: RADAR_STALE,
    gcTime: RADAR_GC,
    retry: 1,
  });
}

/**
 * Catalyst Scanner — top movers with confirmed catalysts + momentum scores.
 * Cold path: screener + volume history + news + AI verdict (~12-18 s).
 * Cached 30 min server-side; 5-min stale client-side.
 */
export function useCatalystScan(market: Market) {
  return useQuery({
    queryKey: ["catalyst-scan", market],
    queryFn: () => api.getCatalystScan(market),
    staleTime: 5 * 60 * 1000,   // 5 min client stale
    gcTime: 60 * 60 * 1000,     // 1 h in memory
    retry: 1,
  });
}

/**
 * Growth Triggers research note — institutional-style analysis with specific
 * business levers, P&L timelines, and conviction tags.
 *
 * Lazy-loaded: only fires when `enabled` is true (i.e. when the user opens
 * the Growth Triggers tab). Cold path: grounded Gemini (~15-25 s).
 * Cached 24 h server-side; 20-min stale client-side.
 */
export function useGrowthTriggers(
  market: Market,
  ticker: string | null,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: ["growth-triggers", market, ticker],
    queryFn: ({ signal }) => api.getGrowthTriggers(market, ticker!, { signal }),
    enabled: ticker !== null && (options.enabled ?? false),
    staleTime: 20 * 60 * 1000,   // 20 min client stale (server caches 24 h)
    gcTime: 24 * 60 * 60 * 1000, // keep in memory all day
    retry: 1,
  });
}
