import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market } from "../types";

// Note: DETAIL_STALE / DETAIL_GC are reused for the analysis hook too.

// Gainers list: 5-min stale (backend cache is 30 min), keep in memory 2 hours
const GAINERS_STALE = 5 * 60 * 1000;
const GAINERS_GC = 2 * 60 * 60 * 1000;

// Analysis: 30-min stale, keep in memory 6 hours so switching stocks doesn't
// lose a previously loaded analysis — user can come back instantly from cache.
const DETAIL_STALE = 30 * 60 * 1000;
const DETAIL_GC = 6 * 60 * 60 * 1000;

export function useGainers(market: Market) {
  return useQuery({
    queryKey: ["gainers", market],
    queryFn: () => api.getGainers(market),
    staleTime: GAINERS_STALE,
    gcTime: GAINERS_GC,
    retry: 2,
  });
}

export function useGainerDetail(market: Market, ticker: string | null) {
  return useQuery({
    queryKey: ["gainer-detail", market, ticker],
    queryFn: () => api.getGainerDetail(market, ticker!),
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
    queryFn: () => api.getGainerAnalysis(market, ticker!),
    enabled: ticker !== null,
    staleTime: DETAIL_STALE,   // 30 min
    gcTime: DETAIL_GC,         // 6 hours in memory
    retry: 1,
  });
}
