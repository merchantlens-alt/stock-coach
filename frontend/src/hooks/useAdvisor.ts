import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AdvisorEvaluateRequest, AdvisorEvaluateResponse, InvestorProfile, Market } from "../types";

export function useInvestorProfile() {
  return useQuery({
    queryKey: ["investor-profile"],
    queryFn: () => api.getInvestorProfile(),
    retry: false,           // 404 = no profile set — don't retry
    staleTime: 5 * 60_000, // treat as fresh for 5 min
  });
}

export function useSaveProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: InvestorProfile) => api.saveInvestorProfile(profile),
    onSuccess: (saved) => {
      queryClient.setQueryData(["investor-profile"], saved);
      // Invalidate all advisor verdicts — profile changed, old verdicts are stale.
      queryClient.invalidateQueries({ queryKey: ["advisor"] });
    },
  });
}

export function useAdvisorVerdict(
  assetType: "stock" | "fund",
  ticker: string,
  market: Market,
  name?: string,
  context?: Record<string, unknown>,
  enabled = true,
) {
  return useQuery<AdvisorEvaluateResponse>({
    queryKey: ["advisor", assetType, market, ticker],
    queryFn: () => {
      const req: AdvisorEvaluateRequest = {
        asset_type: assetType,
        ticker,
        market,
        name,
        context: context ?? {},
      };
      return api.evaluateAdvisor(req);
    },
    enabled: enabled && !!ticker,
    retry: false,           // 404 = no profile — don't spam the server
    staleTime: 6 * 60 * 60_000,  // matches backend 6h cache
  });
}
