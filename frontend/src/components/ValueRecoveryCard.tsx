/**
 * ValueRecoveryCard — displays one value recovery candidate.
 *
 * Visual hierarchy (top → bottom):
 *  1. Quality badge (strong = teal, emerging = amber) + sector
 *  2. Ticker + name · Price + today's change
 *  3. P/E comparison bar: trailing P/E → forward P/E (showing contraction)
 *  4. Signal chips (up to 4 most important inflection signals)
 *  5. Recovery thesis one-liner
 *  6. Analyst target + upside (if available)
 */

import { TrendingDown, TrendingUp } from "lucide-react";
import type { RecoverySignal, ValueRecoveryStock } from "../types";

interface Props {
  stock: ValueRecoveryStock;
  isSelected: boolean;
  isLoading: boolean;
  onClick: () => void;
  onPrefetch?: () => void;
}

function fmt(price: number, currency: string): string {
  if (price >= 10_000) return `${currency}${(price / 1000).toFixed(1)}K`;
  if (price >= 1_000)  return `${currency}${price.toFixed(0)}`;
  return `${currency}${price.toFixed(2)}`;
}

const SIGNAL_LABEL: Record<RecoverySignal, string> = {
  eps_growing:     "EPS Growing",
  revenue_growing: "Rev Growing",
  pe_contracting:  "P/E ↓",
  strong_roe:      "Strong ROE",
  low_debt:        "Low Debt",
  profitable:      "Profitable",
  analyst_bullish: "Analyst Buy",
  rdcf_mispriced:  "rDCF Gap",
};

// Priority order: show the most compelling signals first
const SIGNAL_PRIORITY: RecoverySignal[] = [
  "rdcf_mispriced",
  "pe_contracting",
  "eps_growing",
  "revenue_growing",
  "analyst_bullish",
  "strong_roe",
  "profitable",
  "low_debt",
];

const CONSENSUS_STYLE: Record<string, string> = {
  strong_buy: "bg-green-100 text-green-700 border-green-200",
  buy:        "bg-emerald-50 text-emerald-700 border-emerald-200",
  outperform: "bg-teal-50 text-teal-700 border-teal-200",
  overweight: "bg-teal-50 text-teal-700 border-teal-200",
  hold:       "bg-gray-100 text-gray-500 border-gray-200",
  neutral:    "bg-gray-100 text-gray-500 border-gray-200",
};
const CONSENSUS_LABEL: Record<string, string> = {
  strong_buy: "Strong Buy",
  buy:        "Buy",
  outperform: "Outperform",
  overweight: "Overweight",
  hold:       "Hold",
  neutral:    "Hold",
};

export function ValueRecoveryCard({ stock, isSelected, isLoading, onClick, onPrefetch }: Props) {
  const currency  = stock.market === "india" ? "₹" : "$";
  const isStrong  = stock.recovery_quality === "strong";

  // Sort signals by priority, show top 4
  const sortedSignals = SIGNAL_PRIORITY
    .filter(s => stock.signals.includes(s))
    .slice(0, 4);

  const consensus      = stock.analyst_consensus?.toLowerCase().replace(/[\s-]/g, "_") ?? null;
  const consensusStyle = consensus ? (CONSENSUS_STYLE[consensus] ?? "bg-gray-100 text-gray-500 border-gray-200") : null;
  const consensusLabel = consensus ? (CONSENSUS_LABEL[consensus] ?? stock.analyst_consensus) : null;

  return (
    <button
      onClick={onClick}
      onMouseEnter={onPrefetch}
      className={[
        "w-full text-left rounded-xl border transition-all duration-150 overflow-hidden",
        "hover:shadow-md",
        isSelected
          ? "border-teal-400 bg-teal-50 shadow-md ring-1 ring-teal-300"
          : isStrong
          ? "border-teal-200 bg-white hover:border-teal-400"
          : "border-amber-200 bg-white hover:border-amber-400",
        isLoading ? "opacity-70 cursor-wait" : "cursor-pointer",
      ].join(" ")}
    >
      {/* Quality banner */}
      <div className={`flex items-center gap-1.5 px-3.5 py-1.5 border-b ${
        isStrong
          ? "bg-teal-50 border-teal-100"
          : "bg-amber-50 border-amber-100"
      }`}>
        <span className="text-xs">{isStrong ? "♻️" : "📈"}</span>
        <span className={`text-[10px] font-bold uppercase tracking-wide ${
          isStrong ? "text-teal-700" : "text-amber-700"
        }`}>
          {isStrong ? "Value Recovery" : "Emerging"} · Score {stock.recovery_score.toFixed(0)}/100
        </span>
        {stock.sector && (
          <span className="ml-auto text-[10px] text-gray-400 truncate max-w-[100px]">{stock.sector}</span>
        )}
      </div>

      <div className="px-3.5 py-3 space-y-2.5">
        {/* Row 1: Ticker + price */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-bold text-gray-900 text-sm">{stock.ticker}</span>
              <span className="text-[10px] text-gray-400 truncate max-w-[160px]">{stock.name}</span>
            </div>
            <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
              <span className="font-semibold text-gray-800">{fmt(stock.price, currency)}</span>
              <span className={`flex items-center gap-0.5 font-medium ${
                stock.change_pct_1d < 0 ? "text-red-500" : "text-green-600"
              }`}>
                {stock.change_pct_1d < 0 ? <TrendingDown size={10} /> : <TrendingUp size={10} />}
                {stock.change_pct_1d >= 0 ? "+" : ""}{stock.change_pct_1d.toFixed(1)}% today
              </span>
            </div>
          </div>

          {/* P/E badge */}
          {stock.pe_ratio != null && (
            <div className="shrink-0 text-right">
              <div className="text-sm font-bold text-gray-900">
                {stock.pe_ratio.toFixed(1)}×
              </div>
              <div className="text-[10px] text-gray-400">trailing P/E</div>
            </div>
          )}
        </div>

        {/* P/E contraction indicator */}
        {stock.pe_ratio != null && stock.forward_pe != null && stock.pe_contraction_pct != null && (
          <div>
            <div className="flex items-center justify-between text-[9px] text-gray-400 mb-1">
              <span>Forward P/E {stock.forward_pe.toFixed(1)}×</span>
              <span className="text-teal-600 font-semibold">
                ↓ {stock.pe_contraction_pct.toFixed(0)}% contraction
              </span>
              <span>Trailing {stock.pe_ratio.toFixed(1)}×</span>
            </div>
            {/* Bar shows how far forward PE has contracted from trailing */}
            <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-teal-400 to-teal-600"
                style={{ width: `${Math.min((stock.forward_pe / stock.pe_ratio) * 100, 100)}%` }}
              />
            </div>
          </div>
        )}

        {/* Signal chips */}
        {sortedSignals.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {sortedSignals.map(sig => (
              <span
                key={sig}
                className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                  sig === "rdcf_mispriced"
                    ? "bg-purple-50 text-purple-700 border-purple-200"
                    : sig === "pe_contracting"
                    ? "bg-teal-50 text-teal-700 border-teal-200"
                    : sig === "eps_growing" || sig === "revenue_growing"
                    ? "bg-green-50 text-green-700 border-green-200"
                    : sig === "analyst_bullish"
                    ? "bg-indigo-50 text-indigo-600 border-indigo-200"
                    : "bg-gray-50 text-gray-600 border-gray-200"
                }`}
              >
                {SIGNAL_LABEL[sig]}
              </span>
            ))}
            {stock.signals.length > 4 && (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-gray-50 text-gray-400 border-gray-200">
                +{stock.signals.length - 4} more
              </span>
            )}
          </div>
        )}

        {/* Recovery thesis */}
        <p className="text-[10px] text-gray-500 leading-relaxed line-clamp-2">
          {stock.recovery_thesis}
        </p>

        {/* Analyst consensus + upside */}
        <div className="flex items-center gap-2 flex-wrap">
          {consensusStyle && consensusLabel && (
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${consensusStyle}`}>
              {consensusLabel}
            </span>
          )}
          {stock.analyst_target != null && stock.upside_to_target != null && stock.upside_to_target > 0 && (
            <span className="flex items-center gap-1 text-[10px] text-gray-600">
              <TrendingUp size={10} className="text-indigo-500 shrink-0" />
              <span className="font-semibold text-gray-900">{fmt(stock.analyst_target, currency)}</span>
              <span className="text-green-600 font-semibold">
                +{stock.upside_to_target.toFixed(1)}%
              </span>
              <span className="text-gray-400">12m target</span>
            </span>
          )}
        </div>

        {/* Reverse DCF row — market implied growth vs actual */}
        {stock.implied_growth_pct != null && stock.earnings_growth_yoy != null && (
          <div className="flex items-center gap-1.5 text-[10px] text-gray-500 bg-purple-50 rounded-lg px-2 py-1">
            <span className="text-purple-500">◈</span>
            <span>Market pricing</span>
            <span className="font-semibold text-gray-700">{stock.implied_growth_pct.toFixed(0)}% EPS growth</span>
            <span>·</span>
            <span>Actual</span>
            <span className={`font-semibold ${stock.earnings_growth_yoy > stock.implied_growth_pct / 100 ? "text-green-600" : "text-red-500"}`}>
              {stock.earnings_growth_yoy >= 0 ? "+" : ""}{(stock.earnings_growth_yoy * 100).toFixed(0)}%
            </span>
          </div>
        )}

        {/* Loading indicator */}
        {isLoading && (
          <div className="flex items-center gap-1.5 text-xs text-teal-600">
            <span className="w-2 h-2 rounded-full bg-teal-500 animate-pulse" />
            Analysing with AI…
          </div>
        )}
      </div>
    </button>
  );
}
