/**
 * ValueRecoveryCard — displays one value recovery candidate.
 *
 * Visual hierarchy (top → bottom):
 *  1. Quality badge (strong = teal, emerging = amber) + sector
 *  2. Ticker + name · Price + today's change
 *  3. P/E comparison bar: trailing P/E → forward P/E (showing contraction)
 *  4. Signal chips (up to 4 most important inflection signals)
 *  5. Recovery thesis one-liner
 *  6. Analyst target + upside / Reverse DCF row
 */

import type { ReactNode } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import type { RecoverySignal, ValueRecoveryStock } from "../types";

interface Props {
  stock: ValueRecoveryStock;
  isSelected: boolean;
  isLoading: boolean;
  onClick: () => void;
  onPrefetch?: () => void;
}

// ── Tooltip component ─────────────────────────────────────────────────────────
// Uses a CSS-only group-hover approach. The parent button must NOT have
// overflow-hidden (banner handles its own clipping via rounded-t-xl).

function Tip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-50 w-56 text-left">
        <span className="block bg-gray-900 text-white text-[10px] leading-relaxed rounded-lg px-2.5 py-2 shadow-xl">
          {text}
        </span>
        <span className="block w-2 h-2 bg-gray-900 rotate-45 mx-auto -mt-1 shrink-0" />
      </span>
    </span>
  );
}

// ── Static data ───────────────────────────────────────────────────────────────

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

const SIGNAL_TOOLTIP: Record<RecoverySignal, string> = {
  eps_growing:
    "EPS grew >8% year-over-year. Rising earnings are the core engine of stock price appreciation over time.",
  revenue_growing:
    "Revenue grew >5% year-over-year. Expanding top line supports future earnings and reduces the risk of margin-driven misses.",
  pe_contracting:
    "Forward P/E is 5%+ below trailing P/E — earnings are growing faster than the stock price is rising. The multiple compresses naturally as earnings catch up, then the stock re-rates.",
  strong_roe:
    "Return on Equity >13% — the company generates strong returns on shareholders' capital. High ROE sustained over time is a hallmark of durable competitive advantage.",
  low_debt:
    "Debt-to-Equity below 0.8× — conservative balance sheet. Low leverage means less financial risk and more flexibility to invest in growth or return capital.",
  profitable:
    "Profit margin >8% — the business converts a meaningful share of revenue into actual profit, reducing the risk of a value trap.",
  analyst_bullish:
    "Wall Street consensus is Buy, Outperform, or Strong Buy. Institutional analysts expect the stock to beat the market over the next 12 months.",
  rdcf_mispriced:
    "Reverse DCF: working backwards from the current PE, the market is implying modest EPS growth. Actual reported growth is 20+ points higher. The market hasn't priced in the real earnings trajectory — that gap is your margin of safety.",
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

// ── Component ─────────────────────────────────────────────────────────────────

export function ValueRecoveryCard({ stock, isSelected, isLoading, onClick, onPrefetch }: Props) {
  const currency = stock.market === "india" ? "₹" : "$";
  const isStrong = stock.recovery_quality === "strong";

  // Sort signals by priority, show top 4
  const sortedSignals = SIGNAL_PRIORITY
    .filter(s => stock.signals.includes(s))
    .slice(0, 4);

  const consensus      = stock.analyst_consensus?.toLowerCase().replace(/[\s-]/g, "_") ?? null;
  const consensusStyle = consensus ? (CONSENSUS_STYLE[consensus] ?? "bg-gray-100 text-gray-500 border-gray-200") : null;
  const consensusLabel = consensus ? (CONSENSUS_LABEL[consensus] ?? stock.analyst_consensus) : null;

  const actualGrowthPct = stock.earnings_growth_yoy != null
    ? stock.earnings_growth_yoy * 100
    : null;
  const rdcfGap = stock.implied_growth_pct != null && actualGrowthPct != null
    ? actualGrowthPct - stock.implied_growth_pct
    : null;

  return (
    // overflow-hidden removed from button — banner handles its own corner clipping.
    // This lets Tip tooltips render outside the card boundary without being clipped.
    <button
      onClick={onClick}
      onMouseEnter={onPrefetch}
      className={[
        "w-full text-left rounded-xl border transition-all duration-150 relative",
        "hover:shadow-md",
        isSelected
          ? "border-teal-400 bg-teal-50 shadow-md ring-1 ring-teal-300"
          : isStrong
          ? "border-teal-200 bg-white hover:border-teal-400"
          : "border-amber-200 bg-white hover:border-amber-400",
        isLoading ? "opacity-70 cursor-wait" : "cursor-pointer",
      ].join(" ")}
    >
      {/* Quality banner — overflow-hidden here clips bg-color to rounded top corners */}
      <div className={`rounded-t-xl overflow-hidden flex items-center gap-1.5 px-3.5 py-1.5 border-b ${
        isStrong
          ? "bg-teal-50 border-teal-100"
          : "bg-amber-50 border-amber-100"
      }`}>
        <span className="text-xs">{isStrong ? "♻️" : "📈"}</span>
        <Tip text="Composite 0-100 score: valuation depth (30pts) + number of inflection signals (40pts) + EPS growth magnitude (15pts) + analyst consensus (15pts). Score ≥65 = strong re-rating candidate.">
          <span className={`text-[10px] font-bold uppercase tracking-wide cursor-help ${
            isStrong ? "text-teal-700" : "text-amber-700"
          }`}>
            {isStrong ? "Value Recovery" : "Emerging"} · Score {stock.recovery_score.toFixed(0)}/100
          </span>
        </Tip>
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
            <Tip text="Trailing Price-to-Earnings: the stock price divided by last 12 months of earnings. Below ~18-22× suggests the market is undervaluing current earnings power.">
              <div className="shrink-0 text-right cursor-help">
                <div className="text-sm font-bold text-gray-900">
                  {stock.pe_ratio.toFixed(1)}×
                </div>
                <div className="text-[10px] text-gray-400">trailing P/E</div>
              </div>
            </Tip>
          )}
        </div>

        {/* P/E contraction bar */}
        {stock.pe_ratio != null && stock.forward_pe != null && stock.pe_contraction_pct != null && (
          <div>
            <div className="flex items-center justify-between text-[9px] text-gray-400 mb-1">
              <span>Forward P/E {stock.forward_pe.toFixed(1)}×</span>
              <Tip text="Earnings are growing faster than the stock price. When the market reprices to reflect higher earnings, the stock re-rates upward. The larger this contraction, the stronger the re-rating potential.">
                <span className="text-teal-600 font-semibold cursor-help">
                  ↓ {stock.pe_contraction_pct.toFixed(0)}% contraction
                </span>
              </Tip>
              <span>Trailing {stock.pe_ratio.toFixed(1)}×</span>
            </div>
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
              <Tip key={sig} text={SIGNAL_TOOLTIP[sig]}>
                <span
                  className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border cursor-help ${
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
              </Tip>
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

        {/* Analyst consensus + 12m target */}
        <div className="flex items-center gap-2 flex-wrap">
          {consensusStyle && consensusLabel && (
            <Tip text="Wall Street consensus rating aggregated across all covering analysts. Only Buy / Outperform rated stocks appear in this list — Sell and Hold rated stocks are filtered out.">
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border cursor-help ${consensusStyle}`}>
                {consensusLabel}
              </span>
            </Tip>
          )}
          {stock.analyst_target != null && stock.upside_to_target != null && stock.upside_to_target > 0 && (
            <Tip text="12-month consensus price target from Wall Street analysts, based on their DCF and comparable models. Only stocks with ≥15% upside to target appear here — lower-conviction picks are filtered out.">
              <span className="flex items-center gap-1 text-[10px] text-gray-600 cursor-help">
                <TrendingUp size={10} className="text-indigo-500 shrink-0" />
                <span className="font-semibold text-gray-900">{fmt(stock.analyst_target, currency)}</span>
                <span className="text-green-600 font-semibold">
                  +{stock.upside_to_target.toFixed(1)}%
                </span>
                <span className="text-gray-400">12m target</span>
              </span>
            </Tip>
          )}
        </div>

        {/* Reverse DCF row */}
        {stock.implied_growth_pct != null && actualGrowthPct != null && (
          <Tip text={`Reverse DCF: at the current PE, the market is implying ${stock.implied_growth_pct.toFixed(0)}% EPS growth/year over 5 years (10% discount rate, 15× terminal multiple). The company is actually delivering ${actualGrowthPct >= 0 ? "+" : ""}${actualGrowthPct.toFixed(0)}%. ${rdcfGap && rdcfGap > 20 ? `This ${rdcfGap.toFixed(0)}-point gap is your margin of safety — the market is systematically underpricing this stock's earnings trajectory.` : "When the gap closes, the stock re-rates upward."}`}>
            <div className="flex items-center gap-1.5 text-[10px] text-gray-500 bg-purple-50 rounded-lg px-2 py-1 cursor-help">
              <span className="text-purple-500">◈</span>
              <span>Market pricing</span>
              <span className="font-semibold text-gray-700">{stock.implied_growth_pct.toFixed(0)}% EPS growth</span>
              <span>·</span>
              <span>Actual</span>
              <span className={`font-semibold ${rdcfGap && rdcfGap > 0 ? "text-green-600" : "text-red-500"}`}>
                {actualGrowthPct >= 0 ? "+" : ""}{actualGrowthPct.toFixed(0)}%
              </span>
            </div>
          </Tip>
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
