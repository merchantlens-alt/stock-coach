import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market } from "../types";

const GAINERS_STALE_TIME = 5 * 60 * 1000; // 5 min — backend cache is 30 min

export function useGainers(market: Market) {
  return useQuery({
    queryKey: ["gainers", market],
    queryFn: () => api.getGainers(market),
    staleTime: GAINERS_STALE_TIME,
    retry: 2,
  });
}

export function useGainerDetail(market: Market, ticker: string | null) {
  return useQuery({
    queryKey: ["gainer-detail", market, ticker],
    queryFn: () => api.getGainerDetail(market, ticker!),
    enabled: ticker !== null,
    staleTime: 30 * 60 * 1000, // 30 min — analysis is expensive
    retry: 1,
  });
}
