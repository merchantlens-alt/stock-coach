import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RiskProfile } from "../types";

// Fund scan: 30-min client stale (backend caches 6 h — NAVs publish once daily).
// `category` undefined = scan the whole curated universe.
export function useFundScan(category?: string) {
  return useQuery({
    queryKey: ["funds", "scan", category ?? "all"],
    queryFn: () => api.getFundScan(category),
    staleTime: 30 * 60 * 1000,
    gcTime: 3 * 60 * 60 * 1000,
    retry: 2,
  });
}

// Model portfolio: same cache profile; keyed by risk flavour.
export function useModelPortfolio(risk: RiskProfile) {
  return useQuery({
    queryKey: ["funds", "model", risk],
    queryFn: () => api.getModelPortfolio(risk),
    staleTime: 30 * 60 * 1000,
    gcTime: 3 * 60 * 60 * 1000,
    retry: 2,
  });
}
