import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market, Period } from "../types";

// Radar: 10-min stale (backend cache is 12 h), keep in memory 2 h
const RADAR_STALE = 10 * 60 * 1000;
const RADAR_GC = 2 * 60 * 60 * 1000;

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
