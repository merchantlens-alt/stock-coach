/**
 * FundCard — one mutual fund in the Scanner list (advisor-grade v2).
 *
 * Layout:
 *   1. Entry-signal banner + category rank (#3 of 48) + score
 *   2. Name + NAV, with track-record / Discovery badge
 *   3. Rule-out warnings (Closet Index / Fading edge) — shown prominently
 *   4. Returns strip: 3m · 6m · 1y · 3y-CAGR (or SI-CAGR for young funds)
 *   5. Risk row: Sharpe · max drawdown · α vs benchmark
 *   6. AI entry reasoning
 */

import { AlertTriangle, Minus, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import type { FundEntrySignal, FundScheme } from "../types";

interface Props {
  fund: FundScheme;
}

const SIGNAL_META: Record<FundEntrySignal, { label: string; banner: string; text: string; emoji: string }> = {
  strong_entry: { label: "Strong Entry", banner: "bg-green-50 border-green-100", text: "text-green-700", emoji: "✅" },
  watch:        { label: "Watch",        banner: "bg-amber-50 border-amber-100", text: "text-amber-700", emoji: "👀" },
  avoid:        { label: "Avoid",        banner: "bg-gray-100 border-gray-200",  text: "text-gray-500", emoji: "✋" },
};

function pct(v: number | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function pctColor(v: number | undefined): string {
  if (v == null) return "text-gray-400";
  return v >= 0 ? "text-green-600" : "text-red-500";
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] text-gray-400 uppercase tracking-wide">{label}</span>
      <span className="text-xs font-semibold">{children}</span>
    </div>
  );
}

export function FundCard({ fund }: Props) {
  const meta = SIGNAL_META[fund.entry_signal];
  const hasWarning = fund.is_closet_index || fund.is_decaying;
  const isETF = fund.market === "us";
  const currency = isETF ? "$" : "₹";
  // ETFs report a 5Y CAGR; young MFs fall back to since-inception.
  const longReturn = fund.returns_5y_cagr ?? fund.returns_3y_cagr ?? fund.since_inception_cagr;
  const longLabel = fund.returns_5y_cagr != null ? "5Y CAGR"
    : fund.returns_3y_cagr != null ? "3Y CAGR" : "SI CAGR";

  return (
    <div className={`rounded-xl border bg-white transition-shadow hover:shadow-md ${
      fund.is_discovery ? "border-violet-300"
      : fund.entry_signal === "strong_entry" ? "border-green-200"
      : fund.entry_signal === "watch" ? "border-amber-200"
      : "border-gray-200"
    }`}>

      {/* Signal banner */}
      <div className={`rounded-t-xl overflow-hidden flex items-center gap-1.5 px-3.5 py-1.5 border-b ${meta.banner}`}>
        <span className="text-xs">{meta.emoji}</span>
        <span className={`text-[10px] font-bold uppercase tracking-wide ${meta.text}`}>
          {meta.label} · {fund.fund_score.toFixed(0)}
        </span>
        {fund.category_rank != null && fund.category_size != null && (
          <span className="ml-auto text-[10px] font-medium text-gray-500">
            #{fund.category_rank} of {fund.category_size}{fund.category ? ` · ${fund.category}` : ""}
          </span>
        )}
      </div>

      <div className="px-3.5 py-3 space-y-2.5">

        {/* Name + NAV + badges */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <h3 className="text-sm font-bold text-gray-900 leading-tight line-clamp-2">{fund.name}</h3>
            </div>
            <div className="flex items-center gap-1.5 mt-1">
              {fund.is_discovery && (
                <span className="inline-flex items-center gap-0.5 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700">
                  <Sparkles size={9} /> Discovery
                </span>
              )}
              {fund.track_record !== "established" && !fund.is_discovery && (
                <span className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600">
                  {fund.track_record === "new" ? "New fund" : "Emerging"}
                </span>
              )}
              {fund.fund_house && (
                <span className="text-[10px] text-gray-400 truncate">{fund.fund_house}</span>
              )}
            </div>
          </div>
          {fund.nav != null && (
            <div className="shrink-0 text-right">
              <div className="text-sm font-bold text-gray-900">{currency}{fund.nav.toFixed(2)}</div>
              <div className="text-[9px] text-gray-400">{isETF ? "Price" : "NAV"}{fund.nav_date ? ` · ${fund.nav_date}` : ""}</div>
            </div>
          )}
        </div>

        {/* Rule-out warnings */}
        {hasWarning && (
          <div className="flex flex-wrap gap-1.5">
            {fund.is_closet_index && (
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200">
                <AlertTriangle size={10} /> Closet index
              </span>
            )}
            {fund.is_decaying && (
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                <TrendingDown size={10} /> Fading edge
              </span>
            )}
          </div>
        )}

        {/* Returns strip */}
        <div className="grid grid-cols-4 gap-2 rounded-lg bg-gray-50 px-3 py-2">
          <Metric label="3M"><span className={pctColor(fund.returns_3m)}>{pct(fund.returns_3m)}</span></Metric>
          <Metric label="6M"><span className={pctColor(fund.returns_6m)}>{pct(fund.returns_6m)}</span></Metric>
          <Metric label="1Y"><span className={pctColor(fund.returns_1y)}>{pct(fund.returns_1y)}</span></Metric>
          <Metric label={longLabel}><span className={pctColor(longReturn)}>{pct(longReturn)}</span></Metric>
        </div>

        {/* Risk row */}
        <div className="flex items-center gap-3.5 text-[10px] flex-wrap">
          <span className="flex items-center gap-1 text-gray-500">
            <span className="text-gray-400">Sharpe</span>
            <span className={`font-semibold ${
              fund.sharpe == null ? "text-gray-400"
              : fund.sharpe >= 1 ? "text-green-600"
              : fund.sharpe >= 0.5 ? "text-gray-700"
              : "text-red-500"
            }`}>
              {fund.sharpe?.toFixed(2) ?? "—"}
            </span>
          </span>
          <span className="flex items-center gap-1 text-gray-500">
            <span className="text-gray-400">Max DD</span>
            <span className="font-semibold text-red-500">
              {fund.max_drawdown != null ? `${fund.max_drawdown.toFixed(0)}%` : "—"}
            </span>
          </span>
          {fund.active_return_3y != null && (
            <span className="flex items-center gap-1 text-gray-500">
              <span className="text-gray-400">α vs {fund.benchmark_name ?? "bench"}</span>
              <span className={`font-semibold ${fund.active_return_3y >= 0 ? "text-green-600" : "text-red-500"}`}>
                {fund.active_return_3y >= 0 ? "+" : ""}{fund.active_return_3y.toFixed(1)}pp
              </span>
            </span>
          )}
          {fund.expense_ratio != null && (
            <span className="flex items-center gap-1 text-gray-500">
              <span className="text-gray-400">Expense</span>
              <span className={`font-semibold ${fund.expense_ratio <= 0.1 ? "text-green-600" : fund.expense_ratio <= 0.5 ? "text-gray-700" : "text-amber-600"}`}>
                {fund.expense_ratio.toFixed(2)}%
              </span>
            </span>
          )}
        </div>

        {/* AI entry reasoning */}
        {fund.entry_reason && (
          <div className={`flex items-start gap-1.5 rounded-lg px-2.5 py-2 ${
            hasWarning ? "bg-amber-50" : fund.is_discovery ? "bg-violet-50" : "bg-indigo-50"
          }`}>
            <span className="mt-0.5 shrink-0">
              {hasWarning ? <AlertTriangle size={12} className="text-amber-500" />
                : fund.is_discovery ? <Sparkles size={12} className="text-violet-500" />
                : fund.entry_signal === "strong_entry" ? <TrendingUp size={12} className="text-green-600" />
                : fund.entry_signal === "avoid" ? <Minus size={12} className="text-gray-400" />
                : <TrendingUp size={12} className="text-amber-500" />}
            </span>
            <p className="text-[10px] text-gray-600 leading-relaxed">{fund.entry_reason}</p>
          </div>
        )}
      </div>
    </div>
  );
}
