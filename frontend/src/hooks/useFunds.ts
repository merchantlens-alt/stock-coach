import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market, RiskProfile } from "../types";

// Fund scan: 30-min client stale (backend caches 6 h). `category` undefined = whole universe.
export function useFundScan(market: Market, category?: string) {
  return useQuery({
    queryKey: ["funds", "scan", market, category ?? "all"],
    queryFn: () => api.getFundScan(market, category),
    staleTime: 30 * 60 * 1000,
    gcTime: 3 * 60 * 60 * 1000,
    retry: 2,
  });
}

// Model portfolio: keyed by market + risk flavour.
export function useModelPortfolio(market: Market, risk: RiskProfile) {
  return useQuery({
    queryKey: ["funds", "model", market, risk],
    queryFn: () => api.getModelPortfolio(market, risk),
    staleTime: 30 * 60 * 1000,
    gcTime: 3 * 60 * 60 * 1000,
    retry: 2,
  });
}
