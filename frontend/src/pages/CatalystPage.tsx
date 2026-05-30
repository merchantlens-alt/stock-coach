import { AlertTriangle, RefreshCw, Telescope, TrendingUp, X, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { MarketToggle } from "../components/MarketToggle";
import { useCatalystScan } from "../hooks/useGainers";
import type { CatalystPlay, CatalystSignal, CatalystType, Market } from "../types";

// ── Shared label/colour maps ──────────────────────────────────────────────────

const CATALYST_LABEL: Record<CatalystType, string> = {
  earnings:       "Earnings",
  fda_approval:   "FDA",
  acquisition:    "M&A",
  partnership:    "Partnership",
  analyst_upgrade:"Analyst",
  macro:          "Macro",
  technical:      "Technical",
  regulatory:     "Gov / Regulatory",
  unknown:        "Event",
};

const CATALYST_COLOR: Record<CatalystType, string> = {
  earnings:       "bg-blue-50 text-blue-700 border-blue-200",
  fda_approval:   "bg-emerald-50 text-emerald-700 border-emerald-200",
  acquisition:    "bg-violet-50 text-violet-700 border-violet-200",
  partnership:    "bg-indigo-50 text-indigo-700 border-indigo-200",
  analyst_upgrade:"bg-sky-50 text-sky-700 border-sky-200",
  macro:          "bg-amber-50 text-amber-700 border-amber-200",
  technical:      "bg-gray-50 text-gray-600 border-gray-200",
  regulatory:     "bg-orange-50 text-orange-700 border-orange-200",
  unknown:        "bg-gray-50 text-gray-500 border-gray-200",
};

const SIGNAL_BADGE: Record<CatalystSignal, { cls: string; label: string; dot: string }> = {
  strong_move: { cls: "bg-green-100 text-green-700 border-green-200",   label: "Strong Move", dot: "bg-green-500" },
  emerging:    { cls: "bg-amber-100 text-amber-700 border-amber-200",   label: "Emerging",    dot: "bg-amber-400" },
  noise:       { cls: "bg-gray-100 text-gray-500 border-gray-200",      label: "Noise",       dot: "bg-gray-300" },
  potential:   { cls: "bg-blue-100 text-blue-700 border-blue-200",      label: "Loading",     dot: "bg-blue-500" },
};

function scoreBarColor(score: number): string {
  if (score >= 60) return "bg-green-500";
  if (score >= 30) return "bg-amber-400";
  return "bg-gray-300";
}

function formatVol(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000)     return `${(vol / 1_000).toFixed(0)}K`;
  return vol.toLocaleString();
}

function formatAge(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (diff < 2) return "just now";
  if (diff < 60) return `${diff}m ago`;
  const h = Math.floor(diff / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function CatalystSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="rounded-2xl border border-gray-100 bg-white p-4 space-y-3">
          <div className="flex justify-between">
            <div className="h-4 w-24 bg-gray-100 rounded animate-pulse" />
            <div className="h-5 w-20 bg-green-100 rounded-full animate-pulse" />
          </div>
          <div className="flex gap-2">
            <div className="h-6 w-16 bg-gray-100 rounded animate-pulse" />
            <div className="h-6 w-14 bg-amber-100 rounded-full animate-pulse" />
            <div className="h-6 w-20 bg-blue-100 rounded-full animate-pulse" />
          </div>
          <div className="h-1.5 w-full bg-gray-100 rounded animate-pulse" />
          <div className="h-8 bg-amber-50 rounded-lg animate-pulse" />
          <div className="space-y-1.5">
            <div className="h-2.5 bg-gray-100 rounded animate-pulse" style={{ width: "90%" }} />
            <div className="h-2.5 bg-gray-100 rounded animate-pulse" style={{ width: "76%" }} />
          </div>
          <div className="h-8 bg-indigo-50 rounded-xl animate-pulse" />
        </div>
      ))}
      <div className="flex items-center gap-2 text-xs text-green-600 bg-green-50 rounded-lg px-3 py-2">
        <div className="w-3 h-3 rounded-full border-2 border-green-500 border-t-transparent animate-spin shrink-0" />
        Scanning movers · fetching volume history · running AI verdicts — 12-18 sec
      </div>
    </div>
  );
}

// ── Play card ─────────────────────────────────────────────────────────────────

function CatalystPlayCard({
  play,
  isSpotlit,
  onAnalyse,
}: {
  play: CatalystPlay;
  isSpotlit: boolean;
  onAnalyse: () => void;
}) {
  const sig  = SIGNAL_BADGE[play.signal];
  const isAccumulating = play.signal === "potential";
  const isDown = play.change_pct < 0;
  const sign   = isDown ? "" : "+";

  return (
    <div className={`rounded-2xl border bg-white shadow-sm overflow-hidden transition-all ${
      isAccumulating
        ? "border-blue-200 ring-1 ring-blue-100"
        : isSpotlit
          ? "border-indigo-300 ring-2 ring-indigo-100"
          : "border-gray-100"
    }`}>
      {/* Accumulation phase banner */}
      {isAccumulating && (
        <div className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-50 border-b border-blue-100">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse shrink-0" />
          <span className="text-[10px] font-bold text-blue-700 uppercase tracking-wide">
            Accumulation phase — high volume, price not yet moved
          </span>
        </div>
      )}

      {/* Radar spotlight banner */}
      {!isAccumulating && isSpotlit && (
        <div className="flex items-center gap-1.5 px-4 py-1.5 bg-indigo-50 border-b border-indigo-100">
          <Telescope size={10} className="text-indigo-500 shrink-0" />
          <span className="text-[10px] font-bold text-indigo-600 uppercase tracking-wide">
            In your Radar theme
          </span>
        </div>
      )}

      <div className="px-4 pt-3.5 pb-4 space-y-3">
        {/* Row 1: Ticker + Signal badge */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <span className="text-base font-bold text-gray-900">{play.ticker}</span>
            {play.name !== play.ticker && (
              <span className="ml-2 text-xs text-gray-400 truncate">{play.name}</span>
            )}
            {play.sector && (
              <span className="ml-2 text-[10px] text-gray-300">{play.sector}</span>
            )}
          </div>
          <span className={`text-[10px] font-bold border px-2 py-0.5 rounded-full shrink-0 flex items-center gap-1 ${sig.cls}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${sig.dot}`} />
            {sig.label}
          </span>
        </div>

        {/* Row 2: Change % + volume ratio + catalyst type */}
        <div className="flex items-center gap-2 flex-wrap">
          {isAccumulating ? (
            /* For accumulation stocks: volume anomaly is the hero metric */
            <span className="text-sm font-semibold text-gray-500">
              {sign}{play.change_pct.toFixed(1)}%
              <span className="ml-1 text-[10px] text-gray-400 font-normal">price</span>
            </span>
          ) : (
            <span className={`text-lg font-bold ${isDown ? "text-red-600" : "text-green-600"}`}>
              {sign}{play.change_pct.toFixed(1)}%
            </span>
          )}

          {play.volume_ratio != null && (
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${
              isAccumulating
                ? "bg-blue-100 text-blue-700 border-blue-200"
                : play.volume_ratio >= 3
                  ? "bg-orange-100 text-orange-700 border-orange-200"
                  : play.volume_ratio >= 1.5
                    ? "bg-amber-100 text-amber-700 border-amber-200"
                    : "bg-gray-100 text-gray-500 border-gray-200"
            }`}>
              {play.volume_ratio.toFixed(1)}× vol
            </span>
          )}
          <span className={`text-[10px] font-semibold border px-2 py-0.5 rounded-full ${
            CATALYST_COLOR[play.catalyst_type]
          }`}>
            {CATALYST_LABEL[play.catalyst_type]}
          </span>
          <span className="text-[10px] text-gray-400 ml-auto">
            {formatVol(play.volume)} shares
          </span>
        </div>

        {/* Score bar */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
              {isAccumulating ? "Volume anomaly" : "Momentum score"}
            </span>
            <span className="text-[10px] font-bold text-gray-600">
              {play.momentum_score.toFixed(0)}/100
            </span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                isAccumulating ? "bg-blue-500" : scoreBarColor(play.momentum_score)
              }`}
              style={{ width: `${play.momentum_score}%` }}
            />
          </div>
        </div>

        {/* Catalyst headline */}
        {play.headline_catalyst && (
          <div className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2">
            <p className="text-[11px] font-medium text-amber-800 leading-snug">
              {play.headline_catalyst}
            </p>
          </div>
        )}

        {/* AI verdict */}
        {play.ai_verdict && (
          <p className="text-xs text-gray-600 leading-relaxed">{play.ai_verdict}</p>
        )}

        {/* Analyse CTA */}
        <button
          onClick={onAnalyse}
          className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl border transition-colors ${
            isAccumulating
              ? "text-blue-700 bg-blue-50 hover:bg-blue-100 border-blue-100"
              : "text-indigo-600 bg-indigo-50 hover:bg-indigo-100 border-indigo-100"
          }`}
        >
          <TrendingUp size={12} />
          Deep dive — analyse {play.ticker}
        </button>
      </div>
    </div>
  );
}

// ── Filter tabs ───────────────────────────────────────────────────────────────

type FilterSignal = "all" | CatalystSignal;

const FILTERS: { key: FilterSignal; label: string }[] = [
  { key: "all",         label: "All" },
  { key: "strong_move", label: "Strong Move" },
  { key: "emerging",    label: "Emerging" },
  { key: "potential",   label: "Potential" },
  { key: "noise",       label: "Noise" },
];

// ── Main page ─────────────────────────────────────────────────────────────────

interface Props {
  /** Called when user clicks "Analyse" on a play — switches to Gainers tab */
  onSelectStock: (market: Market, ticker: string) => void;
  /** Tickers from a Radar signal the user drilled into — filter to these only */
  spotlightTickers?: string[];
  /** The market the Radar signal came from — auto-switches scanner market */
  spotlightMarket?: Market;
  /** Called when user dismisses the spotlight filter */
  onClearSpotlight?: () => void;
}

export function CatalystPage({
  onSelectStock,
  spotlightTickers = [],
  spotlightMarket,
  onClearSpotlight,
}: Props) {
  const [market, setMarket] = useState<Market>("us");
  const [filter, setFilter] = useState<FilterSignal>("all");

  const isSpotlighting = spotlightTickers.length > 0;
  const spotlight = new Set(spotlightTickers);

  // ── Sync market when Radar navigation brings a different market ──────────────
  useEffect(() => {
    if (isSpotlighting && spotlightMarket) {
      setMarket(spotlightMarket);
    }
  }, [spotlightMarket, isSpotlighting]);

  const { data, isLoading, isError, refetch, isFetching } = useCatalystScan(market);

  const allPlays = data?.plays ?? [];

  // When spotlight is active: filter to only those tickers (intersection with today's movers).
  // When not spotlighting: apply the normal signal-type filter.
  const filtered = isSpotlighting
    ? allPlays.filter(p => spotlight.has(p.ticker))
    : (filter === "all" ? allPlays : allPlays.filter(p => p.signal === filter));

  const counts: Record<FilterSignal, number> = {
    all:         allPlays.length,
    strong_move: allPlays.filter(p => p.signal === "strong_move").length,
    emerging:    allPlays.filter(p => p.signal === "emerging").length,
    noise:       allPlays.filter(p => p.signal === "noise").length,
    potential:   allPlays.filter(p => p.signal === "potential").length,
  };

  function handleMarketChange(m: Market) {
    setMarket(m);
    setFilter("all");
    // Manually switching market clears the Radar spotlight (different context)
    if (isSpotlighting) onClearSpotlight?.();
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-gray-50">

      {/* ── Page header — sticky so the cards are immediately scrollable below ─ */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-5 py-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-0.5">
              <Zap size={16} className="text-green-600 shrink-0" />
              <h1 className="text-base font-bold text-gray-900 tracking-tight">
                CATALYST SCANNER
              </h1>
              {data && !isLoading && (
                <span className="text-[10px] text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full font-medium whitespace-nowrap">
                  {data.from_cache ? "cached" : "live"} · {formatAge(data.scanned_at)}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500">
              Stocks moving <span className="font-semibold text-gray-700">right now</span> with confirmed catalysts, plus{" "}
              <span className="font-semibold text-blue-600">Potential</span> stocks showing unusual volume before they move.
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
          <MarketToggle market={market} onChange={handleMarketChange} />
        </div>
      </div>

      {/* ── Disclaimer ───────────────────────────────────────────────────────── */}
      <div className="mx-5 mt-4 flex items-start gap-2 rounded-xl bg-gray-50 border border-gray-200 px-3 py-2 text-xs text-gray-400">
        <AlertTriangle size={11} className="mt-0.5 shrink-0 text-amber-400" />
        AI verdicts are for educational purposes only. Not investment advice. Always verify with your own research.
      </div>

      {/* ── Radar spotlight filter banner (replaces signal tabs when active) ──── */}
      {isSpotlighting ? (
        <div className="mx-5 mt-3 flex items-center gap-2 rounded-xl bg-indigo-50 border border-indigo-200 px-3 py-2">
          <Telescope size={13} className="text-indigo-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-xs font-semibold text-indigo-700">
              Radar filter active — {spotlightTickers.join(", ")}
            </span>
            <span className="ml-1.5 text-[10px] text-indigo-400">
              {filtered.length} of {spotlightTickers.length} moving today
            </span>
          </div>
          <button
            onClick={onClearSpotlight}
            className="flex items-center gap-1 text-[10px] font-semibold text-indigo-500 hover:text-indigo-700 bg-indigo-100 hover:bg-indigo-200 rounded-full px-2 py-0.5 transition-colors shrink-0"
          >
            <X size={10} />
            Clear
          </button>
        </div>
      ) : (
        /* ── Normal signal filter tabs ────────────────────────────────────── */
        !isLoading && allPlays.length > 0 && (
          <div className="px-5 mt-3 flex items-center gap-1.5 overflow-x-auto pb-1">
            {FILTERS.map(({ key, label }) => {
              const active = filter === key;
              const sigStyle = key === "strong_move"
                ? (active ? "bg-green-600 text-white" : "text-green-700 hover:bg-green-50")
                : key === "emerging"
                  ? (active ? "bg-amber-500 text-white" : "text-amber-700 hover:bg-amber-50")
                  : key === "potential"
                    ? (active ? "bg-blue-600 text-white" : "text-blue-700 hover:bg-blue-50")
                    : key === "noise"
                      ? (active ? "bg-gray-500 text-white" : "text-gray-500 hover:bg-gray-100")
                      : (active ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-100");
              return (
                <button
                  key={key}
                  onClick={() => setFilter(key)}
                  className={`flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap transition-colors ${sigStyle}`}
                >
                  {label}
                  <span className={`text-xs rounded-full px-1.5 font-bold ${active ? "bg-white/20" : "bg-gray-100 text-gray-500"}`}>
                    {counts[key]}
                  </span>
                </button>
              );
            })}
          </div>
        )
      )}

      {/* ── Content ──────────────────────────────────────────────────────────── */}
      <div className="flex-1 px-5 py-4 space-y-4">
        {isLoading ? (
          <CatalystSkeleton />
        ) : isError ? (
          <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            Could not load catalyst scan. Check your connection and try again.
          </div>
        ) : allPlays.length === 0 ? (
          <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-8 text-center">
            <Zap size={28} className="text-gray-300 mx-auto mb-2" />
            <p className="text-sm font-medium text-gray-500">No significant movers right now</p>
            <p className="text-xs text-gray-400 mt-1">
              Markets may be closed or moving within normal ranges.
            </p>
          </div>
        ) : isSpotlighting && filtered.length === 0 ? (
          /* ── Spotlight active but none of the tickers are moving today ──── */
          <div className="rounded-xl bg-indigo-50 border border-indigo-200 px-4 py-6 text-center">
            <Telescope size={24} className="text-indigo-300 mx-auto mb-2" />
            <p className="text-sm font-semibold text-indigo-700 mb-1">
              None of your Radar stocks are moving today
            </p>
            <p className="text-xs text-indigo-500 mb-4">
              {spotlightTickers.join(", ")} {spotlightTickers.length === 1 ? "isn't" : "aren't"} in today's {market.toUpperCase()} catalyst scan.
            </p>
            <button
              onClick={onClearSpotlight}
              className="text-xs font-semibold text-indigo-600 bg-white border border-indigo-200 rounded-lg px-4 py-2 hover:bg-indigo-50 transition-colors"
            >
              Show all movers instead
            </button>
          </div>
        ) : filtered.length === 0 ? (
          /* ── Normal signal filter — no matches ───────────────────────────── */
          <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-6 text-center">
            <p className="text-sm text-gray-500">
              {filter === "potential"
                ? "No accumulation-phase stocks detected right now."
                : `No ${filter.replace("_", " ")} plays right now.`}
            </p>
            {filter === "potential" && (
              <p className="text-xs text-gray-400 mt-1">
                Potential stocks appear when a ticker has 2× normal volume but price hasn't moved yet.
              </p>
            )}
          </div>
        ) : (
          <>
            <p className="text-[11px] text-gray-400 font-medium">
              {filtered.length} {
                isSpotlighting
                  ? "Radar theme"
                  : filter === "all" ? "" : filter.replace("_", " ")
              } {filtered.length === 1 ? "play" : "plays"} ·{" "}
              {filter === "potential" ? "sorted by volume anomaly" : "sorted by momentum score"}
            </p>
            {filtered.map((play) => (
              <CatalystPlayCard
                key={play.ticker}
                play={play}
                isSpotlit={false}
                onAnalyse={() => onSelectStock(play.market, play.ticker)}
              />
            ))}
          </>
        )}
        <div className="h-4" />
      </div>
    </div>
  );
}
