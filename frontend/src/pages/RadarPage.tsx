import { AlertTriangle, Radio, RefreshCw, TrendingUp, Zap } from "lucide-react";
import { useState } from "react";
import { MarketToggle } from "../components/MarketToggle";
import { useGainers } from "../hooks/useGainers";
import { useRadar } from "../hooks/useGainers";
import type { Market, RadarSignal } from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

const CATALYST_LABEL: Record<string, string> = {
  earnings: "Earnings",
  fda_approval: "FDA",
  acquisition: "M&A",
  partnership: "Partnership",
  analyst_upgrade: "Analyst",
  macro: "Macro",
  technical: "Technical",
  regulatory: "Regulatory",
  unknown: "Event",
};

const CATALYST_COLOR: Record<string, string> = {
  earnings: "bg-blue-50 text-blue-700 border-blue-200",
  fda_approval: "bg-emerald-50 text-emerald-700 border-emerald-200",
  acquisition: "bg-violet-50 text-violet-700 border-violet-200",
  partnership: "bg-indigo-50 text-indigo-700 border-indigo-200",
  analyst_upgrade: "bg-sky-50 text-sky-700 border-sky-200",
  macro: "bg-amber-50 text-amber-700 border-amber-200",
  technical: "bg-gray-50 text-gray-700 border-gray-200",
  regulatory: "bg-orange-50 text-orange-700 border-orange-200",
  unknown: "bg-gray-50 text-gray-500 border-gray-200",
};

function convictionColor(v: number): string {
  if (v >= 0.75) return "bg-green-500";
  if (v >= 0.55) return "bg-amber-400";
  return "bg-red-400";
}
function convictionLabel(v: number): string {
  if (v >= 0.75) return "High";
  if (v >= 0.55) return "Moderate";
  return "Low";
}
function convictionTextColor(v: number): string {
  if (v >= 0.75) return "text-green-700";
  if (v >= 0.55) return "text-amber-600";
  return "text-red-500";
}

function formatAge(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (diff < 2) return "just now";
  if (diff < 60) return `${diff}m ago`;
  const h = Math.floor(diff / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Signal card ───────────────────────────────────────────────────────────────

function SignalCard({
  signal,
  pulseGainers,
  market,
  onFindMoving,
}: {
  signal: RadarSignal;
  pulseGainers: Set<string>;
  market: Market;
  onFindMoving: (tickers: string[], market: Market) => void;
}) {
  const confirming = signal.tickers.filter((t) => pulseGainers.has(t));

  return (
    <div className="rounded-2xl border border-gray-100 bg-white shadow-sm overflow-hidden">
      {/* Header row */}
      <div className="px-4 pt-4 pb-3 border-b border-gray-50">
        <div className="flex items-start justify-between gap-3 mb-2">
          <h3 className="text-sm font-bold text-gray-900 leading-snug flex-1">{signal.theme}</h3>
          <span className={`text-[10px] font-semibold border px-2 py-0.5 rounded-full shrink-0 ${CATALYST_COLOR[signal.catalyst_type]}`}>
            {CATALYST_LABEL[signal.catalyst_type] ?? signal.catalyst_type}
          </span>
        </div>

        {/* Conviction bar */}
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${convictionColor(signal.conviction)}`}
              style={{ width: `${signal.conviction * 100}%` }}
            />
          </div>
          <span className={`text-[10px] font-bold ${convictionTextColor(signal.conviction)}`}>
            {convictionLabel(signal.conviction)} · {Math.round(signal.conviction * 100)}%
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        <p className="text-xs text-gray-600 leading-relaxed">{signal.narrative}</p>

        {/* Tickers */}
        <div className="flex items-center gap-2 flex-wrap">
          {signal.tickers.map((ticker) => {
            const isConfirming = pulseGainers.has(ticker);
            return (
              <span
                key={ticker}
                className={`text-xs font-bold px-2.5 py-1 rounded-lg border ${
                  isConfirming
                    ? "bg-green-50 text-green-700 border-green-200"
                    : "bg-gray-50 text-gray-700 border-gray-200"
                }`}
              >
                {ticker}
                {isConfirming && <span className="ml-1 text-[9px] text-green-600">↑ PULSE</span>}
              </span>
            );
          })}
          <span className="text-[10px] text-gray-400 bg-gray-50 border border-gray-200 px-2 py-1 rounded-lg">
            {signal.time_frame}
          </span>
        </div>

        {/* Confirming in PULSE banner */}
        {confirming.length > 0 && (
          <div className="flex items-center gap-2 rounded-xl bg-green-50 border border-green-100 px-3 py-2">
            <TrendingUp size={12} className="text-green-600 shrink-0" />
            <span className="text-xs font-semibold text-green-700">
              Thesis confirming in PULSE — {confirming.join(", ")} {confirming.length === 1 ? "is" : "are"} in today's gainers
            </span>
          </div>
        )}

        {/* Evidence */}
        <div className="rounded-xl bg-amber-50 border border-amber-100 px-3 py-2">
          <p className="text-[10px] font-bold text-amber-600 uppercase tracking-wide mb-0.5">Signal evidence</p>
          <p className="text-xs text-amber-800 leading-relaxed">{signal.evidence}</p>
        </div>

        {/* Source headlines */}
        {signal.source_headlines.length > 0 && (
          <ul className="space-y-1">
            {signal.source_headlines.map((h, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[11px] text-gray-400">
                <span className="mt-0.5 shrink-0 text-gray-300">›</span>
                <span className="leading-snug">{h}</span>
              </li>
            ))}
          </ul>
        )}

        {/* ── Radar → Scanner CTA ──────────────────────────────────────────── */}
        <button
          onClick={() => onFindMoving(signal.tickers, market)}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold text-green-700 bg-green-50 hover:bg-green-100 rounded-xl border border-green-100 transition-colors"
        >
          <Zap size={11} />
          Find stocks moving on this theme →
        </button>
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function RadarSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="rounded-2xl border border-gray-100 bg-white p-4 space-y-3">
          <div className="h-4 w-3/5 bg-gray-100 rounded animate-pulse" />
          <div className="h-1.5 w-full bg-gray-100 rounded animate-pulse" />
          <div className="space-y-1.5">
            <div className="h-2.5 bg-gray-100 rounded animate-pulse" style={{ width: "92%" }} />
            <div className="h-2.5 bg-gray-100 rounded animate-pulse" style={{ width: "80%" }} />
          </div>
          <div className="flex gap-2">
            {[40, 55, 45].map((w) => (
              <div key={w} className="h-6 rounded-lg bg-gray-100 animate-pulse" style={{ width: w }} />
            ))}
          </div>
        </div>
      ))}
      <div className="flex items-center gap-2 text-xs text-indigo-500 bg-indigo-50 rounded-lg px-3 py-2">
        <div className="w-3 h-3 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin shrink-0" />
        Scanning today's news for structural themes — 10-20 sec
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface RadarPageProps {
  onFindMoving: (tickers: string[], market: Market) => void;
}

export function RadarPage({ onFindMoving }: RadarPageProps) {
  const [market, setMarket] = useState<Market>("us");
  const { data, isLoading, isError, refetch, isFetching } = useRadar(market);

  // Pull current gainer tickers for cross-referencing (uses cached data, free)
  const { data: gainersData } = useGainers(market, "1d");
  const pulseGainers = new Set<string>(
    (gainersData?.gainers ?? []).map((g) => g.ticker)
  );

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-gray-50">
      {/* ── Page header ──────────────────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-100 px-4 md:px-5 py-4">
        {/* Title row — wraps on mobile so refresh button doesn't overlap the badge */}
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-0.5">
              <Radio size={16} className="text-indigo-500 shrink-0" />
              <h1 className="text-base font-bold text-gray-900 tracking-tight">RADAR</h1>
              {data && !isLoading && (
                <span className="text-[10px] text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full font-medium whitespace-nowrap">
                  {data.from_cache ? "cached" : "live"} · {formatAge(data.generated_at)}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500">
              Structural themes from today's news — stocks that{" "}
              <span className="font-semibold text-gray-700">haven't moved yet</span> but are
              positioned to benefit.
            </p>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-800 px-3 py-1.5 rounded-lg border border-gray-200 hover:border-gray-300 transition-colors disabled:opacity-40 shrink-0"
          >
            <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>

        <div className="mt-3">
          <MarketToggle market={market} onChange={setMarket} />
        </div>
      </div>

      {/* ── Disclaimer ───────────────────────────────────────────────────────── */}
      <div className="mx-5 mt-4 flex items-start gap-2 rounded-xl bg-gray-50 border border-gray-200 px-3 py-2 text-xs text-gray-400">
        <AlertTriangle size={11} className="mt-0.5 shrink-0 text-amber-400" />
        AI-generated themes for educational purposes only. Not investment advice. Always verify
        with your own research.
      </div>

      {/* ── Content ──────────────────────────────────────────────────────────── */}
      <div className="flex-1 px-5 py-4 space-y-4">
        {isLoading ? (
          <RadarSkeleton />
        ) : isError ? (
          <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            Could not load radar signals. Check your connection and try again.
          </div>
        ) : data?.signals.length === 0 ? (
          <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-6 text-center">
            <Radio size={24} className="text-gray-300 mx-auto mb-2" />
            <p className="text-sm font-medium text-gray-500">No structural signals today</p>
            <p className="text-xs text-gray-400 mt-1">
              {data.no_signals_reason ?? "News flow doesn't show a clear structural theme right now."}
            </p>
          </div>
        ) : (
          <>
            <p className="text-[11px] text-gray-400 font-medium">
              {data?.signals.length ?? 0} signal{data?.signals.length !== 1 ? "s" : ""} · cross-referenced against today's PULSE gainers
            </p>
            {data?.signals.map((signal, i) => (
              <SignalCard key={i} signal={signal} pulseGainers={pulseGainers} market={market} onFindMoving={onFindMoving} />
            ))}
          </>
        )}
        <div className="h-4" />
      </div>
    </div>
  );
}
