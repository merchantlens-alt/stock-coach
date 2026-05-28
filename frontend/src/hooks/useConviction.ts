import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ConvictionResponse, Market } from "../types";

/**
 * Mutation hook for conviction thesis analysis.
 * Uses useMutation (not useQuery) because:
 *  - The request is user-triggered (form submit)
 *  - The payload is a POST body, not a URL param
 *  - We want to control when it fires (not automatically)
 */
export function useConvictionAnalysis() {
  return useMutation<ConvictionResponse, Error, { belief: string; market: Market }>({
    mutationFn: ({ belief, market }) => api.analyseConviction({ belief, market }),
  });
}
