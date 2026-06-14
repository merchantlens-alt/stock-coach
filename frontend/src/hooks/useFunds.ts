import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market, RiskProfile } from "../types";

// Fund scan: NAVs change once daily, so stay fresh for 12 h (backend caches 24 h).
export function useFundScan(market: Market, category?: string) {
  return useQuery({
    queryKey: ["funds", "scan", market, category ?? "all"],
    queryFn: () => api.getFundScan(market, category),
    staleTime: 12 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
    retry: 2,
  });
}

// Model portfolio: a long-term call — keep it stable for the day (backend holds 3 days).
// keepPreviousData ⇒ switching risk keeps the current portfolio on screen (just the
// weights update) instead of flashing a loading state.
export function useModelPortfolio(market: Market, risk: RiskProfile) {
  return useQuery({
    queryKey: ["funds", "model", market, risk],
    queryFn: () => api.getModelPortfolio(market, risk),
    placeholderData: keepPreviousData,
    staleTime: 12 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
    retry: 2,
  });
}
