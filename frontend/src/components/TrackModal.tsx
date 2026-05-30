import { useState } from "react";
import { ArrowDown, ArrowUp, BookmarkPlus, Loader2, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market, PortfolioEntry, PortfolioEntryType } from "../types";

interface TrackModalProps {
  ticker: string;
  stockName: string;
  market: Market;
  currentPrice: number;
  aiPredictedChangePct?: number | null;
  aiConfidence?: number | null;
  catalystType?: string | null;
  aiOutlook?: string | null;
  onClose: () => void;
  onSaved: (entry: PortfolioEntry) => void;
}

export function TrackModal({
  ticker,
  stockName,
  market,
  currentPrice,
  aiPredictedChangePct,
  aiConfidence,
  catalystType,
  aiOutlook,
  onClose,
  onSaved,
}: TrackModalProps) {
  const currency = market === "india" ? "₹" : "$";
  const queryClient = useQueryClient();

  const [entryType, setEntryType] = useState<PortfolioEntryType>("watchlist");
  const [purchaseAvg, setPurchaseAvg] = useState("");
  const [shares, setShares] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setError(null);
    if (entryType === "holding" && !purchaseAvg) {
      setError("Please enter your average buy price.");
      return;
    }
    setLoading(true);
    try {
      const entry = await api.addPortfolioEntry({
        ticker,
        market,
        type: entryType,
        entry_price: currentPrice,
        stock_name: stockName,
        ...(entryType === "holding" && purchaseAvg
          ? { purchase_avg: parseFloat(purchaseAvg) }
          : {}),
        ...(shares ? { shares: parseFloat(shares) } : {}),
        ...(aiPredictedChangePct != null
          ? { ai_predicted_change_pct: aiPredictedChangePct }
          : {}),
        ...(aiConfidence != null ? { ai_confidence: aiConfidence } : {}),
        ...(catalystType != null ? { catalyst_type: catalystType } : {}),
        ...(aiOutlook != null ? { ai_outlook: aiOutlook } : {}),
      });
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      onSaved(entry);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  const isPositive =
    aiPredictedChangePct != null && aiPredictedChangePct >= 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-white rounded-t-2xl sm:rounded-2xl w-full sm:max-w-sm mx-0 sm:mx-4 p-5 space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-bold text-gray-900">{ticker}</span>
            </div>
            <p className="text-sm text-gray-500 truncate mt-0.5">{stockName}</p>
          </div>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-7 h-7 rounded-full hover:bg-gray-100 text-gray-400 shrink-0"
          >
            <X size={15} />
          </button>
        </div>

        {/* Entry price */}
        <div className="rounded-xl border border-gray-100 bg-gray-50 px-3 py-2.5">
          <span className="text-xs text-gray-500">Tracking from </span>
          <span className="text-sm font-bold text-gray-900">
            {currency}{currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        {/* AI prediction summary */}
        {aiPredictedChangePct != null && (
          <div
            className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 ${
              isPositive
                ? "bg-green-50 border-green-200"
                : "bg-red-50 border-red-200"
            }`}
          >
            {isPositive ? (
              <ArrowUp size={14} className="text-green-600 shrink-0" />
            ) : (
              <ArrowDown size={14} className="text-red-500 shrink-0" />
            )}
            <div className="text-xs leading-snug">
              <span
                className={`font-bold ${
                  isPositive ? "text-green-700" : "text-red-600"
                }`}
              >
                AI: {isPositive ? "+" : ""}
                {aiPredictedChangePct.toFixed(1)}% predicted
              </span>
              {aiConfidence != null && (
                <span className="text-gray-500 ml-1">
                  · {Math.round(aiConfidence * 100)}% confidence
                </span>
              )}
            </div>
          </div>
        )}

        {/* Type toggle */}
        <div>
          <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-2">
            Track as
          </p>
          <div className="flex gap-2">
            {(["holding", "watchlist"] as PortfolioEntryType[]).map((t) => (
              <button
                key={t}
                onClick={() => setEntryType(t)}
                className={[
                  "flex-1 py-2 text-sm font-semibold rounded-xl border transition-all capitalize",
                  entryType === t
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50",
                ].join(" ")}
              >
                {t === "holding" ? "Holding" : "Watchlist"}
              </button>
            ))}
          </div>
        </div>

        {/* Conditional inputs */}
        {entryType === "holding" ? (
          <div className="space-y-3">
            <div>
              <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wide block mb-1">
                Your avg buy price <span className="text-red-400">*</span>
              </label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={purchaseAvg}
                onChange={(e) => setPurchaseAvg(e.target.value)}
                placeholder="482.50"
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              />
            </div>
            <div>
              <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wide block mb-1">
                Shares held{" "}
                <span className="font-normal normal-case text-gray-400">
                  (optional)
                </span>
              </label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={shares}
                onChange={(e) => setShares(e.target.value)}
                placeholder="100"
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              />
            </div>
          </div>
        ) : (
          <div>
            <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wide block mb-1">
              Hypothetical shares{" "}
              <span className="font-normal normal-case text-gray-400">
                (optional)
              </span>
            </label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={shares}
              onChange={(e) => setShares(e.target.value)}
              placeholder="100"
              className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
            />
          </div>
        )}

        {/* Error */}
        {error && (
          <p className="text-xs text-red-500 font-medium">{error}</p>
        )}

        {/* CTA */}
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl px-4 py-2.5 text-sm disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <BookmarkPlus size={14} />
          )}
          {loading ? "Saving…" : "Start tracking →"}
        </button>
      </div>
    </div>
  );
}
