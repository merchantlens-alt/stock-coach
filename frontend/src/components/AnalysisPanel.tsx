import { useEffect, useState } from "react";
import {
  AlertTriangle, ArrowDown, ArrowUp, BookmarkPlus, ChevronRight, GitCompare,
  Lightbulb, Loader2, Minus, Newspaper, RefreshCw, Sparkles, TrendingDown, TrendingUp, X, Zap,
} from "lucide-react";
import type { FundamentalsData, GainerDetail, GrowthTrigger, GrowthTriggersReport, Period, PortfolioEntry, QuarterlySnapshot, RiskItem, ScorecardRow, StockAnalysisResponse, TechnicalSignals, TriggerConviction } from "../types";
import { CandleChart } from "./CandleChart";
import { useGrowthTriggers } from "../hooks/useGainers";
import { TrackModal } from "./TrackModal";

// ── Period helpers ────────────────────────────────────────────────────────────

const PERIOD_LABEL: Record<string, string> = {
  "1d": "today",
  "1w": "this week",
  "1m": "this month",
};
// returnLabel is computed dynamically below (gain vs loss depends on change_pct)

// ── Sub-components ────────────────────────────────────────────────────────────

function ConfidencePill({
  value,
  variant = "bullish",
}: {
  value: number;
  /** bullish = green (positive outlook), bearish = red (negative outlook), neutral = indigo */
  variant?: "bullish" | "bearish" | "neutral";
}) {
  const pct = Math.round(value * 100);
  let cls: string;
  if (variant === "bearish") {
    cls = pct >= 70 ? "bg-red-100 text-red-700" : pct >= 50 ? "bg-orange-100 text-orange-700" : "bg-gray-100 text-gray-500";
  } else if (variant === "neutral") {
    cls = "bg-indigo-100 text-indigo-700";
  } else {
    cls = pct >= 70 ? "bg-green-100 text-green-700" : pct >= 50 ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-500";
  }
  return <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cls}`}>{pct}% confident</span>;
}

type MetricSignal = "positive" | "neutral" | "negative" | "unknown";

function evalPE(v?: number | null): MetricSignal {
  if (v == null) return "unknown";
  if (v < 0) return "negative";
  if (v <= 20) return "positive";
  if (v <= 35) return "neutral";
  return "negative";
}
function evalROE(v?: number | null): MetricSignal {
  if (v == null) return "unknown";
  if (v >= 0.15) return "positive";
  if (v >= 0.05) return "neutral";
  return "negative";
}
function evalGrowth(v?: number | null): MetricSignal {
  if (v == null) return "unknown";
  if (v >= 0.10) return "positive";
  if (v >= 0) return "neutral";
  return "negative";
}
function evalMargin(v?: number | null): MetricSignal {
  if (v == null) return "unknown";
  if (v >= 0.10) return "positive";
  if (v >= 0) return "neutral";
  return "negative";
}
function evalDebt(v?: number | null): MetricSignal {
  if (v == null) return "unknown";
  if (v <= 0.5) return "positive";
  if (v <= 1.5) return "neutral";
  return "negative";
}

const SIGNAL_COLORS: Record<MetricSignal, string> = {
  positive: "text-green-700 bg-green-50 border-green-200",
  neutral:  "text-amber-700 bg-amber-50 border-amber-200",
  negative: "text-red-600 bg-red-50 border-red-200",
  unknown:  "text-gray-400 bg-gray-50 border-gray-200",
};

function MetricCard({
  label, value, signal, sub,
}: {
  label: string; value: string | null; signal: MetricSignal; sub?: string;
}) {
  if (value == null) return null;
  return (
    <div className={`flex flex-col items-center justify-center rounded-xl border px-3 py-2 min-w-[72px] ${SIGNAL_COLORS[signal]}`}>
      <span className="text-[10px] font-semibold uppercase tracking-wide opacity-70 mb-0.5">{label}</span>
      <span className="text-sm font-bold leading-tight">{value}</span>
      {sub && <span className="text-[10px] opacity-60 mt-0.5">{sub}</span>}
    </div>
  );
}

function BusinessMetrics({ f, currency }: { f: FundamentalsData; currency: string }) {
  const targetUpside =
    f.analyst_target_price != null
      ? undefined // computed below
      : null;

  return (
    <div className="space-y-2">
      <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
        {f.pe_ratio != null && (
          <MetricCard label="P/E" value={f.pe_ratio.toFixed(1) + "×"} signal={evalPE(f.pe_ratio)} sub="trailing" />
        )}
        {f.forward_pe != null && (
          <MetricCard label="Fwd P/E" value={f.forward_pe.toFixed(1) + "×"} signal={evalPE(f.forward_pe)} sub="forward" />
        )}
        {f.revenue_growth_yoy != null && (
          <MetricCard
            label="Rev Growth"
            value={(f.revenue_growth_yoy * 100).toFixed(0) + "%"}
            signal={evalGrowth(f.revenue_growth_yoy)}
            sub="year/year"
          />
        )}
        {f.roe != null && (
          <MetricCard label="ROE" value={(f.roe * 100).toFixed(0) + "%"} signal={evalROE(f.roe)} sub="return on eq" />
        )}
        {f.profit_margin != null && (
          <MetricCard
            label="Margin"
            value={(f.profit_margin * 100).toFixed(0) + "%"}
            signal={evalMargin(f.profit_margin)}
            sub="profit"
          />
        )}
        {f.debt_equity != null && (
          <MetricCard label="Debt/Eq" value={f.debt_equity.toFixed(2)} signal={evalDebt(f.debt_equity)} />
        )}
      </div>

      {/* Analyst row */}
      {(f.analyst_recommendation || f.analyst_target_price) && (
        <div className="flex items-center gap-3 text-xs text-gray-500 px-1">
          {f.analyst_recommendation && (
            <span>
              Analyst consensus:{" "}
              <span className="font-bold text-gray-800 uppercase">{f.analyst_recommendation}</span>
            </span>
          )}
          {f.analyst_target_price && (
            <span>
              Target:{" "}
              <span className="font-bold text-gray-800">
                {currency}{f.analyst_target_price.toFixed(2)}
              </span>
            </span>
          )}
          {targetUpside}
        </div>
      )}
    </div>
  );
}

// ── Technical signals panel ───────────────────────────────────────────────────

const RSI_COLOR: Record<string, string> = {
  overbought: "text-red-600 bg-red-50 border-red-200",
  oversold:   "text-green-600 bg-green-50 border-green-200",
  neutral:    "text-amber-600 bg-amber-50 border-amber-200",
};
const MACD_COLOR: Record<string, string> = {
  bullish: "text-green-600", bearish: "text-red-500",
};
const VOLUME_COLOR: Record<string, string> = {
  surging: "text-green-700 font-bold", rising: "text-green-600",
  neutral: "text-gray-500", falling: "text-red-500",
};

function TechnicalPanel({ t, currency, currentPrice }: { t: TechnicalSignals; currency: string; currentPrice: number }) {
  const hasSomething = t.rsi_14 != null || t.macd_direction != null || t.sma_20 != null || t.volume_trend != null;
  if (!hasSomething) return null;

  return (
    <section>
      <div className="flex items-center gap-1.5 mb-3">
        <span className="text-xs">📈</span>
        <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">Technical signals</span>
        <span className="text-[10px] text-gray-400 ml-1">— used by AI for the 30-day prediction</span>
      </div>

      <div className="rounded-xl border border-gray-100 bg-gray-50 divide-y divide-gray-100 overflow-hidden">

        {/* RSI */}
        {t.rsi_14 != null && (
          <div className="flex items-center justify-between px-3 py-2.5">
            <div>
              <span className="text-xs font-semibold text-gray-700">RSI (14-day)</span>
              <span className="text-[10px] text-gray-400 ml-1.5">momentum oscillator</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-gray-900">{t.rsi_14.toFixed(1)}</span>
              {t.rsi_signal && (
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${RSI_COLOR[t.rsi_signal]}`}>
                  {t.rsi_signal === "overbought" ? "Overbought >70" : t.rsi_signal === "oversold" ? "Oversold <30" : "Neutral"}
                </span>
              )}
            </div>
          </div>
        )}

        {/* MACD */}
        {t.macd_direction != null && (
          <div className="flex items-center justify-between px-3 py-2.5">
            <div>
              <span className="text-xs font-semibold text-gray-700">MACD</span>
              <span className="text-[10px] text-gray-400 ml-1.5">trend direction</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-bold ${MACD_COLOR[t.macd_direction]}`}>
                {t.macd_direction === "bullish" ? "▲ Bullish" : "▼ Bearish"}
              </span>
              {t.macd_signal && (
                <span className="text-[10px] text-gray-400">
                  {t.macd_signal === "bullish_cross" ? "MACD above signal" : "MACD below signal"}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Moving averages */}
        {(t.sma_20 != null || t.sma_50 != null) && (
          <div className="px-3 py-2.5">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-semibold text-gray-700">Moving Averages</span>
              {t.golden_cross != null && (
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${t.golden_cross ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-600 border border-red-200"}`}>
                  {t.golden_cross ? "Golden Cross" : "Death Cross"}
                </span>
              )}
            </div>
            <div className="flex gap-3">
              {t.sma_20 != null && (
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 bg-orange-400 inline-block rounded" />
                  <span className="text-[11px] text-gray-500">SMA20: {currency}{t.sma_20.toFixed(2)}</span>
                  {t.price_vs_sma20 && (
                    <span className={`text-[10px] font-semibold ${t.price_vs_sma20 === "above" ? "text-green-600" : "text-red-500"}`}>
                      ({t.price_vs_sma20} {Math.abs(((currentPrice - t.sma_20) / t.sma_20) * 100).toFixed(1)}%)
                    </span>
                  )}
                </div>
              )}
              {t.sma_50 != null && (
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 bg-blue-400 inline-block rounded" />
                  <span className="text-[11px] text-gray-500">SMA50: {currency}{t.sma_50.toFixed(2)}</span>
                  {t.price_vs_sma50 && (
                    <span className={`text-[10px] font-semibold ${t.price_vs_sma50 === "above" ? "text-green-600" : "text-red-500"}`}>
                      ({t.price_vs_sma50})
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Volume */}
        {t.volume_trend != null && (
          <div className="flex items-center justify-between px-3 py-2.5">
            <div>
              <span className="text-xs font-semibold text-gray-700">Volume trend</span>
              <span className="text-[10px] text-gray-400 ml-1.5">institutional conviction</span>
            </div>
            <span className={`text-xs ${VOLUME_COLOR[t.volume_trend]}`}>
              {t.volume_trend.charAt(0).toUpperCase() + t.volume_trend.slice(1)}
              {t.volume_ratio != null && ` (${t.volume_ratio.toFixed(1)}× avg)`}
            </span>
          </div>
        )}

        {/* Momentum */}
        {(t.momentum_5d != null || t.momentum_20d != null) && (
          <div className="flex items-center justify-between px-3 py-2.5">
            <span className="text-xs font-semibold text-gray-700">Momentum</span>
            <div className="flex items-center gap-3">
              {t.momentum_5d != null && (
                <span className={`text-xs font-medium ${t.momentum_5d >= 0 ? "text-green-600" : "text-red-500"}`}>
                  5d: {t.momentum_5d >= 0 ? "+" : ""}{t.momentum_5d.toFixed(1)}%
                </span>
              )}
              {t.momentum_20d != null && (
                <span className={`text-xs font-medium ${t.momentum_20d >= 0 ? "text-green-600" : "text-red-500"}`}>
                  20d: {t.momentum_20d >= 0 ? "+" : ""}{t.momentum_20d.toFixed(1)}%
                </span>
              )}
            </div>
          </div>
        )}

        {/* Support / Resistance */}
        {t.support != null && t.resistance != null && (
          <div className="flex items-center justify-between px-3 py-2.5">
            <span className="text-xs font-semibold text-gray-700">Support / Resistance</span>
            <div className="flex items-center gap-3">
              <span className="text-xs text-green-600 font-medium">{currency}{t.support.toFixed(2)} support</span>
              <span className="text-xs text-red-500 font-medium">{currency}{t.resistance.toFixed(2)} resistance</span>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Quarterly results panel ───────────────────────────────────────────────────

const TREND_STYLE: Record<string, { cls: string; icon: string }> = {
  accelerating: { cls: "bg-green-100 text-green-700",   icon: "↑↑" },
  recovering:   { cls: "bg-emerald-100 text-emerald-700", icon: "↑"  },
  stable:       { cls: "bg-gray-100 text-gray-600",      icon: "→"  },
  decelerating: { cls: "bg-amber-100 text-amber-700",    icon: "↓"  },
  compressing:  { cls: "bg-amber-100 text-amber-700",    icon: "↓"  },
  declining:    { cls: "bg-red-100 text-red-600",        icon: "↓↓" },
  expanding:    { cls: "bg-green-100 text-green-700",    icon: "↑"  },
  unknown:      { cls: "bg-gray-100 text-gray-400",      icon: "?"  },
};

function TrendBadge({ label, trend }: { label: string; trend: string }) {
  const { cls, icon } = TREND_STYLE[trend] ?? TREND_STYLE.unknown;
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[9px] text-gray-400 font-semibold uppercase tracking-wide">{label}</span>
      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${cls}`}>
        {icon} {trend}
      </span>
    </div>
  );
}

function GrowthCell({ value }: { value?: number | null }) {
  if (value == null) return <td className="py-2 px-2 text-center text-gray-300 text-[10px]">—</td>;
  const positive = value >= 0;
  return (
    <td className={`py-2 px-2 text-center text-[11px] font-semibold ${positive ? "text-green-600" : "text-red-500"}`}>
      {positive ? "+" : ""}{value.toFixed(1)}%
    </td>
  );
}

function QuarterlyPanel({ q, currency }: { q: QuarterlySnapshot; currency: string }) {
  // Defensive: quarters may be absent on malformed cached data
  const rows = (q?.quarters ?? []).slice(0, 4);
  if (rows.length === 0) return null;

  const unit = q.unit || (q.market === "india" ? "Cr" : "M");

  // Determine insight callout tone from trend signals
  const isPositive =
    (q.earnings_trend === "accelerating" || q.earnings_trend === "recovering") &&
    (q.margin_trend === "expanding" || q.margin_trend === "stable");
  const isWarning =
    q.earnings_trend === "declining" ||
    (q.earnings_trend === "decelerating" && q.margin_trend === "compressing");
  const insightStyle = isWarning
    ? "bg-red-50 border-red-100 text-red-800"
    : isPositive
      ? "bg-green-50 border-green-100 text-green-800"
      : "bg-amber-50 border-amber-100 text-amber-800";

  return (
    <section>
      <div className="flex items-center gap-1.5 mb-3">
        <span className="text-xs">📋</span>
        <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">Quarterly results</span>
        <span className="text-[10px] text-gray-400 ml-1">— used by AI for 30-day prediction</span>
      </div>

      {/* Trend badges — only shown when at least one trend is known.
          US stocks often have only 4-5 quarters from yfinance, giving a single
          YoY data point which is too few to compute a trend direction. */}
      {(q.revenue_trend !== "unknown" || q.margin_trend !== "unknown" || q.earnings_trend !== "unknown") ? (
        <div className="flex items-center gap-3 mb-3">
          {q.revenue_trend !== "unknown" && <TrendBadge label="Revenue" trend={q.revenue_trend} />}
          {q.margin_trend !== "unknown" && <TrendBadge label="Margins" trend={q.margin_trend} />}
          {q.earnings_trend !== "unknown" && <TrendBadge label="Earnings" trend={q.earnings_trend} />}
        </div>
      ) : (
        <p className="text-[10px] text-gray-400 mb-3">
          Trend direction requires 6+ quarters — showing latest available data below.
        </p>
      )}

      {/* Earnings table */}
      <div className="rounded-xl border border-gray-100 overflow-hidden overflow-x-auto">
        <table className="w-full text-xs min-w-[340px]">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="py-2 px-3 text-left text-[10px] font-bold text-gray-500 uppercase tracking-wide">Quarter</th>
              <th className="py-2 px-2 text-right text-[10px] font-bold text-gray-500 uppercase tracking-wide">
                Revenue <span className="font-normal normal-case opacity-60">({currency}{unit})</span>
              </th>
              <th className="py-2 px-2 text-right text-[10px] font-bold text-gray-500 uppercase tracking-wide">OPM%</th>
              <th className="py-2 px-2 text-right text-[10px] font-bold text-gray-500 uppercase tracking-wide">
                PAT <span className="font-normal normal-case opacity-60">({currency}{unit})</span>
              </th>
              <th className="py-2 px-2 text-center text-[10px] font-bold text-gray-500 uppercase tracking-wide">Rev YoY</th>
              <th className="py-2 px-2 text-center text-[10px] font-bold text-gray-500 uppercase tracking-wide">PAT YoY</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {rows.map((r, i) => (
              <tr key={i} className="bg-white">
                <td className="py-2 px-3 font-semibold text-gray-700 whitespace-nowrap">{r.period}</td>
                <td className="py-2 px-2 text-right text-gray-800 font-medium">
                  {r.revenue != null ? r.revenue.toLocaleString() : <span className="text-gray-300">—</span>}
                </td>
                <td className="py-2 px-2 text-right text-gray-700">
                  {r.opm_pct != null ? `${r.opm_pct.toFixed(1)}%` : <span className="text-gray-300">—</span>}
                </td>
                <td className="py-2 px-2 text-right text-gray-800 font-medium">
                  {r.net_profit != null ? r.net_profit.toLocaleString() : <span className="text-gray-300">—</span>}
                </td>
                <GrowthCell value={r.revenue_growth_yoy} />
                <GrowthCell value={r.pat_growth_yoy} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Key takeaway — Warren Buffett style plain-English verdict */}
      {q.quarterly_insight && (
        <div className={`mt-3 rounded-xl border px-4 py-3 ${insightStyle}`}>
          <p className="text-[10px] font-bold uppercase tracking-wide opacity-60 mb-1">Key takeaway</p>
          <p className="text-xs leading-relaxed">{q.quarterly_insight}</p>
        </div>
      )}

      {/* Attribution */}
      <p className="text-[9px] text-gray-300 mt-1.5 text-right">
        {q.market === "india" ? "Source: screener.in" : "Source: SEC EDGAR / yfinance"}
      </p>
    </section>
  );
}

/** Pulsing skeleton while AI is loading */
function AISkeleton() {
  return (
    <div className="space-y-4">
      {[["Why it moved", 3], ["30-day picture", 2]].map(([title, lines]) => (
        <div key={title as string} className="rounded-xl border border-gray-100 p-4 space-y-2">
          <div className="h-3.5 w-32 bg-indigo-100 rounded animate-pulse" />
          {Array.from({ length: lines as number }).map((_, i) => (
            <div key={i} className="h-2.5 bg-gray-100 rounded animate-pulse" style={{ width: `${95 - i * 10}%` }} />
          ))}
        </div>
      ))}
      <div className="flex items-center gap-2 text-xs text-indigo-500 bg-indigo-50 rounded-lg px-3 py-2">
        <div className="w-3 h-3 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin shrink-0" />
        AI is analysing — 10-20 sec
      </div>
    </div>
  );
}

// ── Signal dashboard row ──────────────────────────────────────────────────────

const SIGNAL_DOT: Record<string, string> = {
  strong: "bg-green-500", undervalued: "bg-green-500",
  moderate: "bg-amber-400", fairly_valued: "bg-amber-400",
  weak: "bg-red-400", overvalued: "bg-red-400",
  unknown: "bg-gray-300",
};

function SignalBadge({ label, signal }: { label: string; signal: string }) {
  const dot = SIGNAL_DOT[signal] ?? "bg-gray-300";
  const nice = signal.replace(/_/g, " ");
  return (
    <div className="flex-1 flex flex-col items-center gap-1 bg-gray-50 rounded-xl py-2.5 px-2">
      <span className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide">{label}</span>
      <div className="flex items-center gap-1.5">
        <span className={`w-2 h-2 rounded-full ${dot}`} />
        <span className="text-xs font-medium text-gray-700 capitalize">{nice}</span>
      </div>
    </div>
  );
}

// ── Prediction change pill ────────────────────────────────────────────────────

function ChangePill({ pct }: { pct: number }) {
  const positive = pct >= 0;
  return (
    <div className={`flex items-center gap-1 text-2xl font-bold px-4 py-3 rounded-xl ${positive ? "bg-green-50 text-green-600" : "bg-red-50 text-red-500"}`}>
      {positive ? <TrendingUp size={20} /> : <TrendingDown size={20} />}
      {positive ? "+" : ""}{pct.toFixed(1)}%
    </div>
  );
}

// ── Growth Triggers Panel ─────────────────────────────────────────────────────

const CONVICTION_STYLE: Record<TriggerConviction, { badge: string; bar: string; label: string }> = {
  HIGH:        { badge: "bg-green-100 text-green-800 border-green-200",  bar: "bg-green-500",  label: "HIGH" },
  MEDIUM:      { badge: "bg-amber-100 text-amber-800 border-amber-200",  bar: "bg-amber-400",  label: "MEDIUM" },
  OPTIONALITY: { badge: "bg-blue-100 text-blue-800 border-blue-200",     bar: "bg-blue-400",   label: "OPTIONALITY" },
};

const SCORECARD_STYLE: Record<string, string> = {
  Strong: "text-green-700 bg-green-50 border-green-200",
  Moderate: "text-amber-700 bg-amber-50 border-amber-200",
  Weak: "text-red-600 bg-red-50 border-red-200",
  Rich: "text-red-600 bg-red-50 border-red-200",
  Fair: "text-amber-700 bg-amber-50 border-amber-200",
  Cheap: "text-green-700 bg-green-50 border-green-200",
  Unknown: "text-gray-400 bg-gray-50 border-gray-200",
};

function TriggerCard({ trigger, index }: { trigger: GrowthTrigger; index: number }) {
  const style = CONVICTION_STYLE[trigger.conviction] ?? CONVICTION_STYLE.MEDIUM;
  return (
    <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
      {/* Top accent bar */}
      <div className={`h-0.5 ${style.bar}`} />
      <div className="px-4 py-3 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs font-bold text-gray-400 shrink-0">#{index + 1}</span>
            <h4 className="text-sm font-bold text-gray-900 leading-tight">{trigger.name}</h4>
          </div>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border shrink-0 ${style.badge}`}>
            {style.label}
          </span>
        </div>
        <p className="text-xs text-gray-600 leading-relaxed">{trigger.what}</p>
        <div className="grid grid-cols-2 gap-2 pt-1">
          <div className="bg-green-50 rounded-lg px-2.5 py-2">
            <p className="text-[10px] font-bold text-green-700 uppercase tracking-wide mb-0.5">P&L Impact</p>
            <p className="text-xs text-green-800 font-medium leading-snug">{trigger.p_and_l_impact}</p>
          </div>
          <div className="bg-gray-50 rounded-lg px-2.5 py-2">
            <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-0.5">Timeline</p>
            <p className="text-xs text-gray-800 font-medium leading-snug">{trigger.timeline}</p>
          </div>
        </div>
        <div className="flex items-start gap-1.5 pt-0.5">
          <ChevronRight size={11} className="text-indigo-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-indigo-600 leading-snug"><span className="font-bold">Watch:</span> {trigger.watch_for}</p>
        </div>
      </div>
    </div>
  );
}

function RiskCard({ risk }: { risk: RiskItem }) {
  return (
    <div className="flex gap-3 rounded-xl border border-red-100 bg-red-50 px-3 py-2.5">
      <AlertTriangle size={13} className="text-red-400 shrink-0 mt-0.5" />
      <div>
        <p className="text-xs font-bold text-red-800">{risk.name}</p>
        <p className="text-xs text-red-700 mt-0.5 leading-snug">{risk.what}</p>
        <p className="text-[11px] text-red-500 mt-1 leading-snug">{risk.why_it_matters}</p>
      </div>
    </div>
  );
}

function ScorecardTable({ rows }: { rows: ScorecardRow[] }) {
  return (
    <div className="rounded-xl border border-gray-100 overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="text-left px-3 py-2 font-bold text-gray-500 uppercase tracking-wide text-[10px]">Dimension</th>
            <th className="text-left px-3 py-2 font-bold text-gray-500 uppercase tracking-wide text-[10px]">Rating</th>
            <th className="text-left px-3 py-2 font-bold text-gray-500 uppercase tracking-wide text-[10px] hidden sm:table-cell">Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const style = SCORECARD_STYLE[row.rating] ?? SCORECARD_STYLE.Unknown;
            return (
              <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                <td className="px-3 py-2 font-medium text-gray-700">{row.dimension}</td>
                <td className="px-3 py-2">
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${style}`}>
                    {row.rating}
                  </span>
                </td>
                <td className="px-3 py-2 text-gray-500 hidden sm:table-cell leading-snug">{row.note}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function GrowthTriggersContent({
  report,
  onRetry,
  isRetrying,
}: {
  report: GrowthTriggersReport;
  onRetry?: () => void;
  isRetrying?: boolean;
}) {
  return (
    <div className="space-y-5">
      {/* Company snapshot */}
      <section className="rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3">
        <div className="flex items-center gap-1.5 mb-2">
          <Sparkles size={13} className="text-indigo-500" />
          <span className="text-xs font-bold text-indigo-700 uppercase tracking-wide">Company Snapshot</span>
          <div className="ml-auto flex items-center gap-2">
            {report.from_cache && (
              <span className="text-[10px] text-indigo-400">cached</span>
            )}
            {onRetry && (
              <button
                onClick={onRetry}
                disabled={isRetrying}
                title="Regenerate analysis"
                className="flex items-center gap-1 text-[10px] font-medium text-indigo-400 hover:text-indigo-600 disabled:opacity-40"
              >
                <RefreshCw size={10} className={isRetrying ? "animate-spin" : ""} />
                {isRetrying ? "Running…" : "Refresh"}
              </button>
            )}
          </div>
        </div>
        <p className="text-xs text-indigo-900 leading-relaxed">{report.company_snapshot}</p>
      </section>

      {/* Growth Triggers */}
      <section>
        <div className="flex items-center gap-1.5 mb-3">
          <Zap size={13} className="text-amber-500" />
          <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">
            Growth Triggers ({report.triggers.length})
          </span>
        </div>
        <div className="space-y-3">
          {report.triggers.map((trigger, i) => (
            <TriggerCard key={i} trigger={trigger} index={i} />
          ))}
        </div>
      </section>

      {/* Already in price + upside */}
      <section className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
          <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-1.5">Already in the Price</p>
          <p className="text-xs text-gray-700 leading-relaxed">{report.already_in_price}</p>
        </div>
        <div className="rounded-xl border border-green-100 bg-green-50 px-4 py-3">
          <p className="text-[10px] font-bold text-green-700 uppercase tracking-wide mb-1.5">Upside Scenario</p>
          <p className="text-xs text-green-800 leading-relaxed">{report.upside_scenario}</p>
        </div>
      </section>

      {/* Key Risks */}
      {report.key_risks.length > 0 && (
        <section>
          <div className="flex items-center gap-1.5 mb-3">
            <AlertTriangle size={13} className="text-red-400" />
            <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">Key Risks</span>
          </div>
          <div className="space-y-2">
            {report.key_risks.map((risk, i) => (
              <RiskCard key={i} risk={risk} />
            ))}
          </div>
        </section>
      )}

      {/* Scorecard */}
      {report.scorecard.length > 0 && (
        <section>
          <div className="flex items-center gap-1.5 mb-3">
            <GitCompare size={13} className="text-gray-400" />
            <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">Investment Scorecard</span>
          </div>
          <ScorecardTable rows={report.scorecard} />
        </section>
      )}

      {/* Disclaimer */}
      <div className="flex items-start gap-2 rounded-xl bg-gray-50 border border-gray-200 p-3 text-xs text-gray-400">
        <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-400" />
        {report.disclaimer}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

function _formatAge(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (diff < 2) return "just now";
  if (diff < 60) return `${diff}m ago`;
  const h = Math.floor(diff / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

interface Props {
  detail: GainerDetail;
  analysis?: StockAnalysisResponse | null;
  analysisLoading?: boolean;
  period?: Period;
  onClose: () => void;
  convictionMatches?: string[];
  onRefresh?: () => void;
  isRefreshing?: boolean;
  /** Called when user wants to build a conviction thesis — switches to Thesis tab */
  onBuildThesis?: (belief: string) => void;
  onTrack?: () => void;
}

type ActiveTab = "analysis" | "growth_triggers";

export function AnalysisPanel({ detail, analysis, analysisLoading, period = "1d", onClose, convictionMatches, onRefresh, isRefreshing, onBuildThesis }: Props) {
  const { gainer, fundamentals, news } = detail;
  const ai = analysis;
  const currency = gainer.market === "india" ? "₹" : "$";
  const periodLabel = PERIOD_LABEL[period] ?? "today";
  const isDown = gainer.change_pct < 0;
  const changeSign = isDown ? "" : "+";  // negative numbers already carry their own "-"
  const returnLabel = period === "1d"
    ? (isDown ? "Today's loss" : "Today's gain")
    : period === "1w"
      ? "1-week return"
      : "1-month return";

  const [activeTab, setActiveTab] = useState<ActiveTab>("analysis");
  const [showTrackModal, setShowTrackModal] = useState(false);
  const [trackedEntry, setTrackedEntry] = useState<PortfolioEntry | null>(null);

  // Reset to Analysis tab whenever a different stock is selected — prevents
  // the Growth Triggers tab from auto-firing a 15-25s AI call on every stock switch.
  useEffect(() => {
    setActiveTab("analysis");
  }, [gainer.ticker]);

  // Reset tracked entry when stock changes
  useEffect(() => {
    setTrackedEntry(null);
  }, [gainer.ticker]);

  // Growth Triggers — lazy loaded only when tab is opened
  const {
    data: growthData,
    isLoading: growthLoading,
    error: growthError,
    refetch: retryGrowthTriggers,
    isFetching: growthFetching,
  } = useGrowthTriggers(gainer.market, gainer.ticker, {
    enabled: activeTab === "growth_triggers",
  });

  const hasFundamentals = fundamentals && (
    fundamentals.pe_ratio != null ||
    fundamentals.forward_pe != null ||
    fundamentals.revenue_growth_yoy != null ||
    fundamentals.roe != null ||
    fundamentals.profit_margin != null ||
    fundamentals.debt_equity != null ||
    fundamentals.analyst_recommendation != null ||
    fundamentals.analyst_target_price != null
  );

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-white">

      {/* ── HEADER ─────────────────────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-5 py-3 flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          <button onClick={onClose} className="md:hidden p-1 -ml-1 mt-0.5 text-gray-400 hover:text-gray-700 shrink-0">←</button>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-bold text-gray-900">{gainer.ticker}</h2>
              <span className={`text-sm font-bold px-2.5 py-0.5 rounded-full ${isDown ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>
                {changeSign}{gainer.change_pct.toFixed(1)}%
              </span>
              {period !== "1d" && (
                <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full font-medium">
                  {periodLabel}
                </span>
              )}
            </div>
            <p className="text-sm text-gray-500 mt-0.5 truncate">{gainer.name}</p>
          </div>
        </div>
        <button onClick={onClose} className="hidden md:flex items-center justify-center w-7 h-7 rounded-full hover:bg-gray-100 text-gray-400 shrink-0 mt-0.5">
          <X size={15} />
        </button>
      </div>

      {/* ── TAB SWITCHER ──────────────────────────────────────────────────── */}
      <div className="sticky top-[57px] z-10 bg-white border-b border-gray-100 px-5 flex gap-0">
        {([
          { key: "analysis", label: "Today's Analysis", icon: <Sparkles size={12} /> },
          { key: "growth_triggers", label: "Growth Triggers", icon: <Zap size={12} /> },
        ] as { key: ActiveTab; label: string; icon: React.ReactNode }[]).map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === tab.key
                ? "border-indigo-500 text-indigo-700"
                : "border-transparent text-gray-400 hover:text-gray-600"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── GROWTH TRIGGERS TAB ───────────────────────────────────────────── */}
      {activeTab === "growth_triggers" && (
        <div className="flex-1 px-5 py-4 space-y-5">
          {growthLoading && (
            <div className="space-y-3 animate-pulse">
              <div className="h-24 bg-indigo-50 rounded-xl" />
              <div className="h-32 bg-gray-50 rounded-xl" />
              <div className="h-32 bg-gray-50 rounded-xl" />
              <div className="h-32 bg-gray-50 rounded-xl" />
              <p className="text-center text-xs text-gray-400 pt-2">
                Running institutional-grade research · 15-25 s…
              </p>
            </div>
          )}
          {/* Hard HTTP error */}
          {!growthLoading && !growthFetching && growthError && (
            <div className="rounded-xl bg-red-50 border border-red-100 px-4 py-4 space-y-3">
              <div className="flex items-start gap-2 text-sm text-red-700">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                Could not connect to the research engine. Please try again.
              </div>
              <button
                onClick={() => retryGrowthTriggers()}
                disabled={growthFetching}
                className="flex items-center gap-1.5 text-xs font-semibold text-red-600 hover:text-red-800 disabled:opacity-40"
              >
                <RefreshCw size={11} className={growthFetching ? "animate-spin" : ""} />
                Retry
              </button>
            </div>
          )}

          {/* Soft error — AI call failed but HTTP 200 returned */}
          {!growthLoading && !growthFetching && growthData?.is_error && (
            <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-4 space-y-3">
              <div className="flex items-start gap-2">
                <AlertTriangle size={14} className="text-amber-500 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-semibold text-amber-800">AI research engine timed out</p>
                  <p className="text-xs text-amber-600 mt-0.5">
                    The analysis could not be generated. This usually resolves on retry.
                  </p>
                </div>
              </div>
              <button
                onClick={() => retryGrowthTriggers()}
                disabled={growthFetching}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-white bg-amber-500 hover:bg-amber-600 rounded-lg disabled:opacity-40 transition-colors"
              >
                {growthFetching
                  ? <Loader2 size={11} className="animate-spin" />
                  : <RefreshCw size={11} />
                }
                {growthFetching ? "Running analysis…" : "Retry analysis"}
              </button>
            </div>
          )}

          {/* Successful report */}
          {!growthLoading && growthData && !growthData.is_error && (
            <GrowthTriggersContent report={growthData} onRetry={retryGrowthTriggers} isRetrying={growthFetching} />
          )}
          <div className="h-4" />
        </div>
      )}

      {/* ── ANALYSIS TAB (existing content) ──────────────────────────────── */}
      {activeTab === "analysis" && (
      <div className="flex-1 px-5 py-4 space-y-5">

        {/* ── CONVICTION MATCH ──────────────────────────────────────────────── */}
        {convictionMatches && convictionMatches.length > 0 && (
          <div className="flex items-center gap-2.5 rounded-xl bg-indigo-50 border border-indigo-100 px-4 py-2.5">
            <Lightbulb size={14} className="text-indigo-500 shrink-0" />
            <div>
              <span className="text-xs font-bold text-indigo-700">Your thesis is playing out · </span>
              <span className="text-xs text-indigo-500">{convictionMatches.join(" · ")}</span>
            </div>
          </div>
        )}

        {/* ── PRICE STATS ──────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div className="bg-gray-50 rounded-xl p-3">
            <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide">Price</p>
            <p className="text-base font-bold text-gray-900 mt-0.5">{currency}{gainer.price.toLocaleString()}</p>
          </div>
          <div className={`rounded-xl p-3 ${isDown ? "bg-red-50" : "bg-green-50"}`}>
            <p className={`text-[10px] font-semibold uppercase tracking-wide ${isDown ? "text-red-600" : "text-green-600"}`}>{returnLabel}</p>
            <p className={`text-base font-bold mt-0.5 ${isDown ? "text-red-700" : "text-green-700"}`}>
              {changeSign}{currency}{Math.abs(gainer.change_abs).toFixed(2)}
              <span className="text-xs font-medium ml-1 opacity-70">({changeSign}{gainer.change_pct.toFixed(1)}%)</span>
            </p>
          </div>
          <div className="bg-gray-50 rounded-xl p-3">
            <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide">Volume</p>
            <p className="text-base font-bold text-gray-900 mt-0.5">
              {gainer.volume >= 1_000_000
                ? `${(gainer.volume / 1_000_000).toFixed(1)}M`
                : gainer.volume >= 1_000
                  ? `${(gainer.volume / 1_000).toFixed(0)}K`
                  : gainer.volume.toLocaleString()}
            </p>
          </div>
          {gainer.sector && (
            <div className="bg-gray-50 rounded-xl p-3">
              <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide">Sector</p>
              <p className="text-sm font-bold text-gray-900 mt-0.5 leading-tight">{gainer.sector}</p>
            </div>
          )}
        </div>

        {/* ── THE BUSINESS — fundamentals inline, before chart ──────────────── */}
        {hasFundamentals && (
          <section>
            <SectionHeader icon={<span className="text-xs">🏢</span>} label="The Business" />
            <BusinessMetrics f={fundamentals!} currency={currency} />
          </section>
        )}

        {/* ── PRICE CHART ──────────────────────────────────────────────────── */}
        <section>
          <CandleChart ticker={gainer.ticker} market={gainer.market} />
        </section>

        {/* ── TECHNICAL SIGNALS (fed to AI for the 30-day prediction) ──────── */}
        {ai?.technicals && (
          <TechnicalPanel
            t={ai.technicals}
            currency={currency}
            currentPrice={gainer.price}
          />
        )}

        {/* ── QUARTERLY RESULTS (fed to AI for the 30-day prediction) ──────── */}
        {ai?.quarterly && (
          <QuarterlyPanel q={ai.quarterly} currency={currency} />
        )}

        {/* ── AI ANALYSIS ──────────────────────────────────────────────────── */}

        {/* Cache status + Re-analyse button — shown whenever AI data is present */}
        {ai && !analysisLoading && (
          <div className="flex items-center justify-between gap-2 py-1.5 px-0.5">
            <span className="text-[11px] text-gray-400 flex items-center gap-1">
              {ai.from_cache ? (
                <>
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
                  Cached · {ai.analysed_at ? _formatAge(ai.analysed_at) : "earlier"}
                </>
              ) : (
                <>
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400" />
                  Fresh analysis
                </>
              )}
            </span>
            {onRefresh && (
              <button
                onClick={onRefresh}
                disabled={isRefreshing}
                title="Re-run analysis — fetches latest quarterly results + fresh Gemini call"
                className="flex items-center gap-1 text-[11px] font-medium text-indigo-500 hover:text-indigo-700 disabled:opacity-40 transition-colors"
              >
                {isRefreshing
                  ? <Loader2 size={11} className="animate-spin" />
                  : <RefreshCw size={11} />
                }
                {isRefreshing ? "Re-analysing…" : "Re-analyse"}
              </button>
            )}
          </div>
        )}

        {/* Re-analysing overlay — dim the old content while the new one loads */}
        {isRefreshing && (
          <div className="rounded-xl bg-indigo-50 border border-indigo-100 px-4 py-3 text-xs text-indigo-600 flex items-center gap-2">
            <Loader2 size={13} className="animate-spin shrink-0" />
            Fetching quarterly results + re-running AI analysis — 10-15 seconds…
          </div>
        )}

        {!isRefreshing && analysisLoading && !ai ? (
          <AISkeleton />
        ) : !analysisLoading && !isRefreshing && ai && !ai.analysis ? (
          <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-700">
            AI analysis could not be generated. Try refreshing in a moment.
          </div>
        ) : (
          <>
            {/* WHY IT MOVED */}
            {ai?.analysis && (
              <section>
                <div className="flex items-start justify-between gap-2 mb-3">
                  <SectionHeader
                    icon={isDown
                      ? <ArrowDown size={14} className="text-red-500" />
                      : <ArrowUp size={14} className="text-green-500" />
                    }
                    label={period === "1d"
                      ? (isDown ? "Why it fell today" : "Why it gained today")
                      : `Why it moved ${periodLabel}`
                    }
                  />
                  <ConfidencePill value={ai.analysis.confidence} />
                </div>

                <p className="text-sm text-gray-700 leading-relaxed">
                  {/* why_it_moved is the new field; why_it_gained kept for cached responses */}
                  {ai.analysis.why_it_moved || ai.analysis.why_it_gained}
                </p>

                <ul className="mt-3 space-y-1.5">
                  {ai.analysis.key_catalysts.map((c, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                      {isDown
                        ? <ArrowDown size={12} className="text-red-400 mt-1 shrink-0" />
                        : <ArrowUp size={12} className="text-green-500 mt-1 shrink-0" />
                      }
                      {c}
                    </li>
                  ))}
                </ul>

                {/* Sustained vs one-time — visual pill */}
                <div className={`mt-3 flex items-start gap-2.5 rounded-xl p-3 ${
                  ai.analysis.is_sustained
                    ? "bg-green-50 border border-green-100"
                    : "bg-amber-50 border border-amber-100"
                }`}>
                  {ai.analysis.is_sustained
                    ? <TrendingUp size={14} className="text-green-600 mt-0.5 shrink-0" />
                    : <Minus size={14} className="text-amber-500 mt-0.5 shrink-0" />
                  }
                  <div>
                    <span className={`text-xs font-bold ${ai.analysis.is_sustained ? "text-green-700" : "text-amber-700"}`}>
                      {ai.analysis.is_sustained ? "Sustained catalyst" : "One-time pop"}
                    </span>
                    <p className="text-xs mt-0.5 text-gray-600">{ai.analysis.sustainability_reason}</p>
                  </div>
                </div>
              </section>
            )}

            {/* vs. TODAY'S GAINERS */}
            {ai?.analysis?.comparison_to_gainers && (
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <GitCompare size={13} className="text-violet-500" />
                  <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">vs. Today's top gainers</span>
                </div>
                <div className="rounded-xl border border-violet-100 bg-violet-50 px-4 py-3">
                  <p className="text-sm text-violet-800 leading-relaxed">{ai.analysis.comparison_to_gainers}</p>
                </div>
              </section>
            )}

            {/* THE 30-DAY PICTURE */}
            {ai?.prediction && (
              <section>
                <div className="flex items-start justify-between gap-2 mb-3">
                  <SectionHeader icon={<span className="text-xs">📅</span>} label="30-day picture" />
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-gray-400 capitalize">{ai.prediction.time_horizon} horizon</span>
                    <ConfidencePill
                      value={ai.prediction.confidence}
                      variant={ai.prediction.predicted_change_pct < 0 ? "bearish" : "bullish"}
                    />
                  </div>
                </div>

                <div className="flex items-start gap-3 rounded-xl border border-gray-100 p-4 mb-4">
                  <ChangePill pct={ai.prediction.predicted_change_pct} />
                  <p className="text-sm text-gray-700 leading-relaxed flex-1">{ai.prediction.outlook}</p>
                </div>

                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div className="rounded-xl bg-green-50 border border-green-100 p-3">
                    <p className="text-[10px] font-bold text-green-600 uppercase tracking-wide mb-2">Tailwinds</p>
                    <ul className="space-y-1.5">
                      {ai.prediction.key_tailwinds.map((t, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-xs text-green-800">
                          <ArrowUp size={10} className="text-green-500 mt-0.5 shrink-0" />
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="rounded-xl bg-red-50 border border-red-100 p-3">
                    <p className="text-[10px] font-bold text-red-500 uppercase tracking-wide mb-2">Risks</p>
                    <ul className="space-y-1.5">
                      {ai.prediction.key_risks.map((r, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-xs text-red-800">
                          <ArrowDown size={10} className="text-red-400 mt-0.5 shrink-0" />
                          {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                {/* Signal dashboard */}
                <div className="flex gap-2">
                  <SignalBadge label="Valuation" signal={ai.prediction.valuation_signal} />
                  <SignalBadge label="Growth" signal={ai.prediction.growth_signal} />
                  <SignalBadge label="Debt" signal={ai.prediction.debt_signal} />
                </div>
              </section>
            )}

            {/* ── BUILD THESIS CTA ─────────────────────────────────────────── */}
            {ai?.analysis && onBuildThesis && (
              <button
                onClick={() => {
                  // Pre-fill with the best available context
                  const insight = analysis?.quarterly?.quarterly_insight;
                  const reason  = ai.analysis!.sustainability_reason;
                  const seed    = insight
                    ? insight.slice(0, 120)
                    : reason
                      ? reason.slice(0, 120)
                      : "";
                  const belief = seed
                    ? `I believe in ${gainer.name} (${gainer.ticker}) — ${seed}`
                    : `I believe in ${gainer.name} (${gainer.ticker})`;
                  onBuildThesis(belief);
                }}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-2xl border border-indigo-200 transition-colors"
              >
                <Zap size={14} />
                Build my conviction thesis for {gainer.ticker}
                <span className="text-xs font-normal opacity-60 ml-1">→ Thesis tab</span>
              </button>
            )}

            {/* ── TRACK THIS PREDICTION CTA ────────────────────────────────── */}
            {ai?.prediction && (
              <button
                onClick={() => setShowTrackModal(true)}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded-2xl border border-emerald-200 transition-colors"
              >
                <BookmarkPlus size={14} />
                Track this prediction
                <span className="text-xs font-normal opacity-60 ml-1">→ My Plays</span>
              </button>
            )}

            {/* Tracked confirmation */}
            {trackedEntry && (
              <div className="flex items-center gap-2 rounded-xl bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs text-emerald-700">
                <BookmarkPlus size={12} />
                <span>Tracking {trackedEntry.ticker} — check <strong>My Plays</strong> tab</span>
                <button onClick={() => setTrackedEntry(null)} className="ml-auto text-emerald-400 hover:text-emerald-600">×</button>
              </div>
            )}

            {/* WHO ELSE MAY BENEFIT */}
            {ai?.analysis?.related_beneficiaries && ai.analysis.related_beneficiaries.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles size={13} className="text-indigo-500" />
                  <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">Who else may benefit</span>
                </div>
                <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3">
                  <div className="flex flex-wrap gap-2 mb-2">
                    {ai.analysis.related_beneficiaries.map((t) => (
                      <span key={t} className="text-sm font-bold bg-white border border-indigo-200 text-indigo-700 px-3 py-1 rounded-lg">
                        {t}
                      </span>
                    ))}
                  </div>
                  {ai.analysis.beneficiary_reasoning && (
                    <p className="text-xs text-indigo-600 leading-relaxed">{ai.analysis.beneficiary_reasoning}</p>
                  )}
                </div>
              </section>
            )}

            {/* Disclaimer */}
            {ai?.prediction?.disclaimer && (
              <div className="flex items-start gap-2 rounded-xl bg-gray-50 border border-gray-200 p-3 text-xs text-gray-400">
                <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-400" />
                {ai.prediction.disclaimer}
              </div>
            )}
          </>
        )}

        {/* ── NEWS ────────────────────────────────────────────────────────── */}
        {news.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-2">
              <Newspaper size={13} className="text-gray-400" />
              <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">Recent news</span>
            </div>
            <ul className="space-y-2">
              {news.map((item, i) => (
                <li key={i} className="rounded-xl border border-gray-100 px-3 py-2.5">
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noopener noreferrer"
                      className="text-sm font-medium text-blue-700 hover:underline leading-snug">
                      {item.title}
                    </a>
                  ) : (
                    <p className="text-sm font-medium text-gray-800 leading-snug">{item.title}</p>
                  )}
                  <p className="text-xs text-gray-400 mt-0.5">{item.source}</p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ── 52-WEEK RANGE ───────────────────────────────────────────────── */}
        {fundamentals && (fundamentals.fifty_two_week_low || fundamentals.fifty_two_week_high) && (
          <FiftyTwoWeekBar
            price={gainer.price}
            low={fundamentals.fifty_two_week_low}
            high={fundamentals.fifty_two_week_high}
            currency={currency}
          />
        )}

        {/* bottom padding */}
        <div className="h-4" />
      </div>
      )}

      {/* ── TRACK MODAL ────────────────────────────────────────────────────── */}
      {showTrackModal && (
        <TrackModal
          ticker={gainer.ticker}
          stockName={gainer.name}
          market={gainer.market}
          currentPrice={gainer.price}
          aiPredictedChangePct={ai?.prediction?.predicted_change_pct}
          aiConfidence={ai?.prediction?.confidence}
          catalystType={ai?.analysis?.catalyst_type}
          aiOutlook={ai?.prediction?.outlook}
          onClose={() => setShowTrackModal(false)}
          onSaved={(entry) => {
            setTrackedEntry(entry);
            setShowTrackModal(false);
          }}
        />
      )}
    </div>
  );
}

// ── Section header utility ────────────────────────────────────────────────────

function SectionHeader({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-1.5 mb-0">
      {icon}
      <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">{label}</span>
    </div>
  );
}

// ── 52-week range bar ────────────────────────────────────────────────────────

function FiftyTwoWeekBar({
  price, low, high, currency,
}: {
  price: number; low?: number | null; high?: number | null; currency: string;
}) {
  if (!low || !high || high <= low) return null;
  const pct = Math.min(100, Math.max(0, ((price - low) / (high - low)) * 100));
  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs">📊</span>
        <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">52-week range</span>
      </div>
      <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
        <div className="flex items-center justify-between text-xs text-gray-500 mb-2">
          <span>{currency}{low.toLocaleString()}</span>
          <span className="font-semibold text-gray-700">Now {currency}{price.toLocaleString()}</span>
          <span>{currency}{high.toLocaleString()}</span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full relative">
          <div className="h-full bg-gradient-to-r from-red-400 via-amber-400 to-green-500 rounded-full" />
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white border-2 border-gray-700 rounded-full shadow-sm"
            style={{ left: `calc(${pct}% - 6px)` }}
          />
        </div>
        <div className="mt-1.5 flex justify-between text-[10px] text-gray-400">
          <span>52-week low</span>
          <span className={`font-semibold ${pct > 70 ? "text-green-600" : pct < 30 ? "text-red-500" : "text-amber-600"}`}>
            {pct.toFixed(0)}% of range
          </span>
          <span>52-week high</span>
        </div>
      </div>
    </section>
  );
}
