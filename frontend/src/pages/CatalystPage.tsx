import { AlertTriangle, ChevronDown, ChevronUp, RefreshCw, Telescope, TrendingUp, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { MarketToggle } from "../components/MarketToggle";
import { useCatalystScan } from "../hooks/useGainers";
import type { CatalystPlay, CatalystType, Market } from "../types";

// ── Label / colour maps ───────────────────────────────────────────────────────

const CATALYST_LABEL: Record<CatalystType, string> = {
  earnings:       "Earnings",
  fda_approval:   "FDA",
  acquisition:    "M&A",
  partnership:    "Partnership",
  analyst_upgrade:"Analyst",
  macro:          "Macro",
  technical:      "Technical",
  regulatory:     "Regulatory",
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

function formatAge(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (diff < 2) return "just now";
  if (diff < 60) return `${diff}m ago`;
  const h = Math.floor(diff / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function formatVol(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000)     return `${(vol / 1_000).toFixed(0)}K`;
  return vol.toLocaleString();
}

// ── Compact play card ─────────────────────────────────────────────────────────

function PlayCard({
  play,
  isSpotlit,
  onAnalyse,
}: {
  play: CatalystPlay;
  isSpotlit: boolean;
  onAnalyse: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isAccumulating = play.signal === "potential";
  const isDown = play.change_pct < 0;
  const sign   = play.change_pct >= 0 ? "+" : "";

  // Contradiction detection: high technical momentum but AI predicts reversal.
  // A stock with strong_move/high score + negative AI prediction is a "one-time pop"
  // — show a clear warning so users don't mistake technical momentum for a buy signal.
  const hasPrediction = play.ai_prediction_pct != null;
  const aiPredNegative = hasPrediction && play.ai_prediction_pct! < 0;

  return (
    <div className={`rounded-xl border bg-white overflow-hidden transition-all ${
      isAccumulating ? "border-blue-200 ring-1 ring-blue-100" :
      isSpotlit ? "border-indigo-300 ring-1 ring-indigo-100" :
      "border-gray-100"
    }`}>
      {/* ── Top banners ─────────────────────────────────────────────── */}
      {isAccumulating && (
        <div className="flex items-center gap-1.5 px-3 py-1 bg-blue-50 border-b border-blue-100">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse shrink-0" />
          <span className="text-[10px] font-bold text-blue-700 uppercase tracking-wide">
            Accumulation — unusual volume, price hasn't moved yet
          </span>
        </div>
      )}
      {!isAccumulating && isSpotlit && (
        <div className="flex items-center gap-1.5 px-3 py-1 bg-indigo-50 border-b border-indigo-100">
          <Telescope size={9} className="text-indigo-500 shrink-0" />
          <span className="text-[10px] font-bold text-indigo-600 uppercase tracking-wide">
            In your Radar theme
          </span>
        </div>
      )}

      {/* ── Main row ────────────────────────────────────────────────── */}
      <div className="px-3.5 py-3">
        <div className="flex items-center gap-2">
          {/* Ticker + name */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-bold text-gray-900">{play.ticker}</span>
              {play.name !== play.ticker && (
                <span className="text-xs text-gray-400 truncate max-w-[120px]">{play.name}</span>
              )}
            </div>
            {/* Catalyst headline — 1 line, truncated */}
            {play.headline_catalyst && (
              <p className="text-[11px] text-amber-700 mt-0.5 line-clamp-1 leading-snug">
                {play.headline_catalyst}
              </p>
            )}
          </div>

          {/* Right cluster: change + vol + score */}
          <div className="flex items-center gap-2 shrink-0">
            {/* Change % */}
            <span className={`text-sm font-bold ${isDown ? "text-red-600" : "text-green-600"}`}>
              {sign}{play.change_pct.toFixed(1)}%
            </span>

            {/* Volume ratio */}
            {play.volume_ratio != null && (
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${
                play.volume_ratio >= 4 ? "bg-orange-100 text-orange-700 border-orange-200" :
                play.volume_ratio >= 2 ? "bg-amber-100 text-amber-700 border-amber-200" :
                "bg-gray-100 text-gray-500 border-gray-200"
              }`}>
                {play.volume_ratio.toFixed(1)}×
              </span>
            )}

            {/* Catalyst type */}
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border hidden sm:block ${
              CATALYST_COLOR[play.catalyst_type]
            }`}>
              {CATALYST_LABEL[play.catalyst_type]}
            </span>

            {/* Momentum score mini-bar */}
            <div className="flex flex-col items-center gap-0.5 w-10">
              <div className="w-full h-1 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    play.momentum_score >= 60 ? "bg-green-500" :
                    play.momentum_score >= 30 ? "bg-amber-400" : "bg-gray-300"
                  }`}
                  style={{ width: `${play.momentum_score}%` }}
                />
              </div>
              <span className="text-[9px] text-gray-400 font-medium">{play.momentum_score.toFixed(0)}</span>
            </div>
          </div>
        </div>

        {/* ── AI prediction badge ─────────────────────────────────────── */}
        {hasPrediction && (
          <div className={`flex items-center gap-1.5 mt-2 rounded-lg px-2 py-1 text-[10px] font-semibold w-fit ${
            aiPredNegative
              ? "bg-red-50 text-red-600 border border-red-100"
              : "bg-emerald-50 text-emerald-700 border border-emerald-100"
          }`}>
            <span>{aiPredNegative ? "↓" : "↑"}</span>
            <span>
              AI 30d: {play.ai_prediction_pct! >= 0 ? "+" : ""}{play.ai_prediction_pct!.toFixed(1)}%
            </span>
            {play.ai_prediction_confidence != null && (
              <span className="font-normal opacity-60">
                · {Math.round(play.ai_prediction_confidence * 100)}% conf
              </span>
            )}
          </div>
        )}

        {/* ── Action row ──────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 mt-2.5">
          {/* Vol shares */}
          <span className="text-[10px] text-gray-400">{formatVol(play.volume)} shares</span>

          {/* Expand AI verdict */}
          {play.ai_verdict && (
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded(v => !v); }}
              className="flex items-center gap-0.5 text-[10px] text-gray-400 hover:text-gray-600 transition-colors ml-1"
            >
              {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
              {expanded ? "Hide verdict" : "AI verdict"}
            </button>
          )}

          {/* Analyse CTA */}
          <button
            onClick={onAnalyse}
            className={`ml-auto flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-xl border transition-colors ${
              isAccumulating
                ? "text-blue-700 bg-blue-50 hover:bg-blue-100 border-blue-100"
                : "text-indigo-600 bg-indigo-50 hover:bg-indigo-100 border-indigo-100"
            }`}
          >
            <TrendingUp size={11} />
            Analyse
          </button>
        </div>

        {/* ── Expanded AI verdict ─────────────────────────────────────── */}
        {expanded && play.ai_verdict && (
          <div className="mt-2.5 border-t border-gray-100 pt-2">
            <p className="text-[11px] text-gray-600 leading-relaxed">{play.ai_verdict}</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({
  icon,
  label,
  count,
  description,
  collapsed,
  onToggle,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  description: string;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="w-full flex items-center gap-2 py-2 group"
    >
      {icon}
      <span className="text-xs font-bold text-gray-700 uppercase tracking-wide">{label}</span>
      <span className="text-[10px] font-semibold bg-gray-100 text-gray-500 rounded-full px-1.5 py-0.5">
        {count}
      </span>
      <span className="text-[10px] text-gray-400 ml-1">{description}</span>
      <span className="ml-auto text-gray-400 group-hover:text-gray-600 transition-colors">
        {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </span>
    </button>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function CatalystSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3, 4, 5].map(i => (
        <div key={i} className="rounded-xl border border-gray-100 bg-white p-3.5 space-y-2">
          <div className="flex justify-between">
            <div className="h-4 w-20 bg-gray-100 rounded animate-pulse" />
            <div className="h-4 w-12 bg-green-100 rounded animate-pulse" />
          </div>
          <div className="flex gap-2">
            <div className="h-1 w-24 bg-gray-100 rounded animate-pulse" />
            <div className="h-1 w-16 bg-amber-100 rounded animate-pulse" />
          </div>
          <div className="flex gap-2 items-center">
            <div className="h-6 w-16 bg-gray-100 rounded animate-pulse" />
            <div className="h-6 w-16 bg-indigo-100 rounded-xl animate-pulse ml-auto" />
          </div>
        </div>
      ))}
      <div className="flex items-center gap-2 text-xs text-green-600 bg-green-50 rounded-lg px-3 py-2">
        <div className="w-3 h-3 rounded-full border-2 border-green-500 border-t-transparent animate-spin shrink-0" />
        Scanning movers · fetching volume data · running AI verdicts — 12–18 sec
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface Props {
  onSelectStock: (market: Market, ticker: string) => void;
  spotlightTickers?: string[];
  spotlightMarket?: Market;
  onClearSpotlight?: () => void;
}

type SectionKey = "strong_move" | "emerging" | "potential" | "noise" | "reversal";

const SECTIONS: {
  key: SectionKey;
  label: string;
  description: string;
  icon: React.ReactNode;
}[] = [
  {
    key: "strong_move",
    label: "Strong Moves",
    description: "confirmed catalyst · AI outlook positive or unanalysed",
    icon: <span className="text-sm">🔥</span>,
  },
  {
    key: "emerging",
    label: "Emerging",
    description: "building momentum, watch closely",
    icon: <span className="text-sm">⚡</span>,
  },
  {
    key: "potential",
    label: "Loading",
    description: "unusual volume — price hasn't moved yet",
    icon: <span className="text-sm">🔵</span>,
  },
  {
    key: "reversal",
    label: "Likely Reversals",
    description: "moved today but AI predicts pullback — likely speculative",
    icon: <span className="text-sm">🚨</span>,
  },
  {
    key: "noise",
    label: "Noise",
    description: "low conviction",
    icon: <span className="text-sm">○</span>,
  },
];

export function CatalystPage({
  onSelectStock,
  spotlightTickers = [],
  spotlightMarket,
  onClearSpotlight,
}: Props) {
  const [market, setMarket] = useState<Market>("us");
  // "reversal" and "noise" start collapsed — user sees only actionable signals by default
  const [collapsed, setCollapsed] = useState<Set<SectionKey>>(new Set(["noise", "reversal"]));

  const isSpotlighting = spotlightTickers.length > 0;
  const spotlight = new Set(spotlightTickers);

  useEffect(() => {
    if (isSpotlighting && spotlightMarket) setMarket(spotlightMarket);
  }, [spotlightMarket, isSpotlighting]);

  const { data, isLoading, isError, refetch, isFetching } = useCatalystScan(market);
  const allPlays = data?.plays ?? [];

  // Spotlight mode: show only those tickers
  const displayPlays = isSpotlighting
    ? allPlays.filter(p => spotlight.has(p.ticker))
    : allPlays;

  // Classify plays: strong_move stocks with a negative AI prediction are split off
  // into "reversal" so they don't pollute the Strong Moves section.
  // A negative prediction + high momentum = "moved today on speculation, AI expects pullback."
  // Stocks without a prediction stay in strong_move (benefit of the doubt).
  const isLikelyReversal = (p: CatalystPlay) =>
    p.signal === "strong_move" &&
    p.ai_prediction_pct != null &&
    p.ai_prediction_pct < 0;

  const grouped: Record<SectionKey, CatalystPlay[]> = {
    strong_move: displayPlays.filter(p => p.signal === "strong_move" && !isLikelyReversal(p)),
    emerging:    displayPlays.filter(p => p.signal === "emerging"),
    potential:   displayPlays.filter(p => p.signal === "potential"),
    reversal:    displayPlays.filter(p => isLikelyReversal(p)),
    noise:       displayPlays.filter(p => p.signal === "noise"),
  };

  function toggleSection(key: SectionKey) {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  function handleMarketChange(m: Market) {
    setMarket(m);
    if (isSpotlighting) onClearSpotlight?.();
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-gray-50">

      {/* ── Sticky header ──────────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-5 py-3.5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Zap size={15} className="text-green-600 shrink-0" />
            <div>
              <h1 className="text-sm font-bold text-gray-900 leading-tight">CATALYST SCANNER</h1>
              <p className="text-[10px] text-gray-400">
                {data && !isLoading ? `${allPlays.length} plays · ${formatAge(data.scanned_at)}` : "Scanning…"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <MarketToggle market={market} onChange={handleMarketChange} />
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors disabled:opacity-40"
              title="Refresh"
            >
              <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
            </button>
          </div>
        </div>
      </div>

      {/* ── Disclaimer ─────────────────────────────────────────────────── */}
      <div className="mx-4 md:mx-5 mt-3 rounded-xl bg-gray-50 border border-gray-200 px-3 py-2 space-y-1">
        <div className="flex items-center gap-2 text-[10px] text-gray-400">
          <AlertTriangle size={10} className="shrink-0 text-amber-400" />
          <span>AI verdicts are educational only · Not investment advice · Always do your own research</span>
        </div>
        <div className="text-[10px] text-gray-400 leading-relaxed">
          <span className="font-semibold text-gray-500">How it works:</span>
          {" "}🔥 <span className="text-gray-500">Strong Moves</span> = high momentum AND AI 30-day outlook agrees (or no analysis yet).
          {" "}🚨 <span className="text-gray-500">Likely Reversals</span> = moved big today but AI predicts a pullback — speculative plays, collapsed by default.
        </div>
      </div>

      {/* ── Radar spotlight banner ─────────────────────────────────────── */}
      {isSpotlighting && (
        <div className="mx-4 md:mx-5 mt-3 flex items-center gap-2 rounded-xl bg-indigo-50 border border-indigo-200 px-3 py-2">
          <Telescope size={12} className="text-indigo-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-xs font-semibold text-indigo-700">
              Radar filter: {spotlightTickers.join(", ")}
            </span>
            <span className="ml-1.5 text-[10px] text-indigo-400">
              {displayPlays.length} moving today
            </span>
          </div>
          <button
            onClick={onClearSpotlight}
            className="text-[10px] font-semibold text-indigo-500 hover:text-indigo-700 bg-indigo-100 hover:bg-indigo-200 rounded-full px-2 py-0.5 transition-colors shrink-0"
          >
            Clear
          </button>
        </div>
      )}

      {/* ── Content ────────────────────────────────────────────────────── */}
      <div className="flex-1 px-4 md:px-5 py-4 space-y-1">
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
            <p className="text-xs text-gray-400 mt-1">Markets may be closed or moving within normal ranges.</p>
          </div>
        ) : isSpotlighting && displayPlays.length === 0 ? (
          <div className="rounded-xl bg-indigo-50 border border-indigo-200 px-4 py-6 text-center">
            <Telescope size={24} className="text-indigo-300 mx-auto mb-2" />
            <p className="text-sm font-semibold text-indigo-700 mb-1">
              None of your Radar stocks are moving today
            </p>
            <p className="text-xs text-indigo-500 mb-4">
              {spotlightTickers.join(", ")} {spotlightTickers.length === 1 ? "isn't" : "aren't"} in today's scan.
            </p>
            <button
              onClick={onClearSpotlight}
              className="text-xs font-semibold text-indigo-600 bg-white border border-indigo-200 rounded-lg px-4 py-2 hover:bg-indigo-50 transition-colors"
            >
              Show all movers
            </button>
          </div>
        ) : (
          /* ── Grouped sections ──────────────────────────────────────── */
          SECTIONS.map(({ key, label, description, icon }) => {
            const plays = grouped[key];
            if (plays.length === 0) return null;
            const isCollapsed = collapsed.has(key);
            return (
              <div key={key} className="space-y-2">
                <SectionHeader
                  icon={icon}
                  label={label}
                  count={plays.length}
                  description={description}
                  collapsed={isCollapsed}
                  onToggle={() => toggleSection(key)}
                />
                {!isCollapsed && (
                  <div className="space-y-2 pl-0">
                    {plays.map(play => (
                      <PlayCard
                        key={play.ticker}
                        play={play}
                        isSpotlit={spotlight.has(play.ticker)}
                        onAnalyse={() => onSelectStock(play.market, play.ticker)}
                      />
                    ))}
                  </div>
                )}
                <div className="h-1" />
              </div>
            );
          })
        )}
        <div className="h-6" />
      </div>
    </div>
  );
}
