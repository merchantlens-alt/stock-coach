/**
 * DipCard — displays one buy-the-dip opportunity.
 *
 * Visual hierarchy (top → bottom):
 *  1. Quality badge + ticker + name
 *  2. Dip depth bar: shows how far price has fallen from 3-month high
 *  3. RSI gauge + analyst consensus chip
 *  4. Upside to analyst target
 *  5. Dip reason (why it fell) + Analyse CTA
 */

import { TrendingDown, TrendingUp } from "lucide-react";
import type { DipStock } from "../types";

interface Props {
  dip: DipStock;
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

function RsiGauge({ rsi }: { rsi: number }) {
  const color =
    rsi < 30 ? "bg-green-500"
    : rsi < 40 ? "bg-emerald-400"
    : rsi < 50 ? "bg-amber-400"
    : "bg-orange-400";
  const label =
    rsi < 30 ? "Strongly oversold"
    : rsi < 40 ? "Oversold"
    : rsi < 50 ? "Approaching oversold"
    : "Neutral";
  const labelColor =
    rsi < 30 ? "text-green-600"
    : rsi < 40 ? "text-emerald-600"
    : rsi < 50 ? "text-amber-600"
    : "text-orange-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${rsi}%` }} />
      </div>
      <span className={`text-[10px] font-semibold ${labelColor}`}>
        RSI {rsi.toFixed(0)} · {label}
      </span>
    </div>
  );
}

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

export function DipCard({ dip, isSelected, isLoading, onClick, onPrefetch }: Props) {
  const currency = dip.market === "india" ? "₹" : "$";
  const isPrime  = dip.dip_quality === "prime";

  // Dip depth visualisation: how far from 3-month high
  const depth    = Math.abs(dip.change_pct_from_high);   // e.g. 18.4
  const depthPct = Math.min(depth / 45 * 100, 100);       // scale to bar width

  const consensus = dip.analyst_consensus?.toLowerCase().replace(/[\s-]/g, "_") ?? null;
  const consensusStyle = consensus ? (CONSENSUS_STYLE[consensus] ?? "bg-gray-100 text-gray-500 border-gray-200") : null;
  const consensusLabel = consensus ? (CONSENSUS_LABEL[consensus] ?? dip.analyst_consensus) : null;

  return (
    <button
      onClick={onClick}
      onMouseEnter={onPrefetch}
      className={[
        "w-full text-left rounded-xl border transition-all duration-150 overflow-hidden",
        "hover:shadow-md",
        isSelected
          ? "border-indigo-400 bg-indigo-50 shadow-md ring-1 ring-indigo-300"
          : isPrime
          ? "border-green-200 bg-white hover:border-green-400"
          : "border-gray-200 bg-white hover:border-amber-300",
        isLoading ? "opacity-70 cursor-wait" : "cursor-pointer",
      ].join(" ")}
    >
      {/* Quality banner */}
      <div className={`flex items-center gap-1.5 px-3.5 py-1.5 border-b ${
        isPrime
          ? "bg-green-50 border-green-100"
          : "bg-amber-50 border-amber-100"
      }`}>
        <span className="text-xs">{isPrime ? "🎯" : "👀"}</span>
        <span className={`text-[10px] font-bold uppercase tracking-wide ${
          isPrime ? "text-green-700" : "text-amber-700"
        }`}>
          {isPrime ? "Prime Dip" : "Watch"} · Score {dip.dip_score.toFixed(0)}/100
        </span>
        {dip.sector && (
          <span className="ml-auto text-[10px] text-gray-400">{dip.sector}</span>
        )}
      </div>

      <div className="px-3.5 py-3 space-y-2.5">
        {/* Row 1: Ticker + price + today's change */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-bold text-gray-900 text-sm">{dip.ticker}</span>
              <span className="text-[10px] text-gray-400 truncate max-w-[160px]">{dip.name}</span>
            </div>
            <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
              <span className="font-semibold text-gray-800">{fmt(dip.price, currency)}</span>
              <span className={`flex items-center gap-0.5 font-medium ${
                dip.change_pct_1d < 0 ? "text-red-500" : "text-green-600"
              }`}>
                {dip.change_pct_1d < 0 ? <TrendingDown size={10} /> : <TrendingUp size={10} />}
                {dip.change_pct_1d >= 0 ? "+" : ""}{dip.change_pct_1d.toFixed(1)}% today
              </span>
            </div>
          </div>
          {/* Dip depth badge */}
          <div className="shrink-0 text-right">
            <div className="text-sm font-bold text-red-600">
              {dip.change_pct_from_high.toFixed(1)}%
            </div>
            <div className="text-[10px] text-gray-400">from {fmt(dip.three_month_high, currency)} high</div>
          </div>
        </div>

        {/* Dip depth bar — visual representation of pullback */}
        <div>
          <div className="flex items-center justify-between text-[9px] text-gray-400 mb-0.5">
            <span>Current {fmt(dip.price, currency)}</span>
            <span>3m high {fmt(dip.three_month_high, currency)}</span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden relative">
            {/* Full bar = 3m high; filled portion = current price as % of high */}
            <div
              className="h-full rounded-full bg-gradient-to-r from-green-400 to-green-600"
              style={{ width: `${100 - depthPct}%` }}
            />
          </div>
          {/* 52-week range labels */}
          {dip.fifty_two_week_low != null && dip.fifty_two_week_high != null && (
            <div className="flex justify-between text-[9px] text-gray-300 mt-0.5">
              <span>52w low {fmt(dip.fifty_two_week_low, currency)}</span>
              <span>52w high {fmt(dip.fifty_two_week_high, currency)}</span>
            </div>
          )}
        </div>

        {/* RSI + analyst consensus */}
        <div className="flex items-center gap-3 flex-wrap">
          {dip.rsi_14 != null && <RsiGauge rsi={dip.rsi_14} />}
          {consensusStyle && consensusLabel && (
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${consensusStyle}`}>
              {consensusLabel}
            </span>
          )}
        </div>

        {/* Upside to analyst target */}
        {dip.analyst_target != null && dip.upside_to_target != null && (
          <div className="flex items-center gap-2 text-xs">
            <TrendingUp size={11} className="text-indigo-500 shrink-0" />
            <span className="text-gray-600">
              Analyst target{" "}
              <span className="font-semibold text-gray-900">{fmt(dip.analyst_target, currency)}</span>
              {" "}
              <span className="text-green-600 font-semibold">
                (+{dip.upside_to_target.toFixed(1)}% upside)
              </span>
            </span>
          </div>
        )}

        {/* Revenue growth chip */}
        {dip.revenue_growth_yoy != null && (
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className={`font-semibold px-2 py-0.5 rounded-full border ${
              dip.revenue_growth_yoy >= 0.1
                ? "bg-green-50 text-green-700 border-green-200"
                : dip.revenue_growth_yoy >= 0
                ? "bg-amber-50 text-amber-700 border-amber-100"
                : "bg-red-50 text-red-600 border-red-100"
            }`}>
              Rev {dip.revenue_growth_yoy >= 0 ? "+" : ""}{(dip.revenue_growth_yoy * 100).toFixed(0)}% YoY
            </span>
            <span className="text-gray-400">{dip.dip_reason}</span>
          </div>
        )}

        {/* Loading indicator */}
        {isLoading && (
          <div className="flex items-center gap-1.5 text-xs text-indigo-600">
            <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
            Analysing with AI…
          </div>
        )}
      </div>
    </button>
  );
}
