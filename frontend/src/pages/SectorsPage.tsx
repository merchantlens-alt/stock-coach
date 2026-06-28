import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown, ChevronUp, RefreshCw, TrendingUp, TrendingDown,
  Shield, Zap, AlertTriangle, Loader2, ArrowUp,
} from "lucide-react";
import { api } from "../api/client";
import type { Market, SectorCyclicality, SectorGrowthTag, SectorInfo, SectorStock } from "../types";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtPct(v: number | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function fmtPrice(v: number | undefined, market: Market): string {
  if (v == null) return "—";
  const sym = market === "india" ? "₹" : "$";
  return v >= 1000 ? `${sym}${(v / 1000).toFixed(1)}K` : `${sym}${v.toFixed(0)}`;
}

function fmtCap(v: number | undefined, market: Market): string {
  if (v == null) return "—";
  if (market === "india") {
    return v >= 100000 ? `₹${(v / 100000).toFixed(1)}L Cr` : `₹${(v / 1000).toFixed(0)}K Cr`;
  }
  return v >= 1000 ? `$${(v / 1000).toFixed(1)}B` : `$${v.toFixed(0)}M`;
}

function pctClass(v: number | undefined): string {
  if (v == null) return "text-gray-400";
  return v >= 0 ? "text-green-600" : "text-red-500";
}

function CycDot({ cyc }: { cyc: SectorCyclicality }) {
  const color = cyc === "low" ? "bg-emerald-500" : cyc === "mid" ? "bg-amber-400" : "bg-red-400";
  return <span className={`inline-block w-2 h-2 rounded-full ${color} shrink-0`} />;
}

function GrowthBadge({ tag }: { tag: SectorGrowthTag }) {
  const styles: Record<SectorGrowthTag, string> = {
    "High Growth":    "bg-indigo-50 text-indigo-700 border border-indigo-100",
    "Defensive":      "bg-green-50 text-green-700 border border-green-100",
    "Cyclical-Mod":   "bg-amber-50 text-amber-700 border border-amber-100",
    "Cyclical":       "bg-red-50 text-red-600 border border-red-100",
    "Emerging":       "bg-purple-50 text-purple-700 border border-purple-100",
  };
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap ${styles[tag]}`}>
      {tag}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 75 ? "bg-indigo-500" : score >= 50 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-12 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-[10px] text-gray-400 font-medium w-5">{score}</span>
    </div>
  );
}

// ── Grade badge ────────────────────────────────────────────────────────────────

function GradeBadge({ grade }: { grade: string | undefined }) {
  if (!grade) return null;
  const styles: Record<string, string> = {
    A: "bg-emerald-50 text-emerald-700 border border-emerald-200",
    B: "bg-blue-50 text-blue-700 border border-blue-200",
    C: "bg-amber-50 text-amber-700 border border-amber-200",
    D: "bg-red-50 text-red-600 border border-red-200",
    F: "bg-red-100 text-red-700 border border-red-300",
  };
  return (
    <span className={`inline-block text-[9px] font-bold px-1.5 py-0.5 rounded ${styles[grade] ?? "bg-gray-100 text-gray-500"}`}>
      {grade}
    </span>
  );
}

// ── Dual rank indicator ────────────────────────────────────────────────────────

function DualRank({ stock }: { stock: SectorStock }) {
  const oRank = stock.opportunity_rank;
  const fRank = stock.fundamental_rank;
  const isDip = stock.is_dip_opportunity;

  if (!oRank) return <span className="text-[10px] text-gray-300 font-bold w-5">{oRank ?? "—"}</span>;

  if (isDip && fRank) {
    // Rose in opportunity ranking because of dip — highlight it
    return (
      <div className="flex flex-col items-center shrink-0">
        <div className="flex items-center gap-0.5 bg-emerald-50 border border-emerald-200 rounded px-1 py-0.5">
          <ArrowUp size={8} className="text-emerald-600" />
          <span className="text-[9px] font-bold text-emerald-700">#{oRank}</span>
        </div>
        <span className="text-[8px] text-gray-300 mt-0.5">was #{fRank}</span>
      </div>
    );
  }

  return <span className="text-[10px] text-gray-300 font-bold shrink-0">#{oRank}</span>;
}

// ── Stock row ──────────────────────────────────────────────────────────────────

function StockRow({ stock, market }: { stock: SectorStock; market: Market }) {
  const dipPct = stock.pct_from_52w_high;
  const isDip  = stock.is_dip_opportunity;

  return (
    <div className={[
      "grid grid-cols-[44px_1fr_68px_52px_52px_44px] items-center gap-2 py-2 px-3 border-b border-gray-50 last:border-0 transition-colors",
      isDip ? "bg-emerald-50/40 hover:bg-emerald-50" : "hover:bg-gray-50",
    ].join(" ")}>

      {/* Dual rank */}
      <DualRank stock={stock} />

      {/* Name + score */}
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs font-semibold text-gray-900">{stock.ticker.replace(".NS", "").replace(".BO", "")}</span>
          <GradeBadge grade={stock.grade} />
          {stock.fundamental_score != null && (
            <span className="text-[9px] text-gray-400">{stock.fundamental_score.toFixed(1)}/10</span>
          )}
        </div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className="text-[10px] text-gray-400 truncate">{stock.name}</span>
          {dipPct != null && dipPct <= -8 && (
            <span className={`text-[9px] font-semibold whitespace-nowrap ${isDip ? "text-emerald-600" : "text-amber-600"}`}>
              {dipPct.toFixed(0)}% off high
            </span>
          )}
        </div>
      </div>

      {/* Price / MCap */}
      <div className="text-right">
        <div className="text-xs font-medium text-gray-800">{fmtPrice(stock.price, market)}</div>
        <div className="text-[10px] text-gray-400">{fmtCap(stock.market_cap_cr, market)}</div>
      </div>

      {/* 1yr return */}
      <div className={`text-right text-xs font-semibold ${pctClass(stock.change_1yr_pct)}`}>
        {fmtPct(stock.change_1yr_pct)}
      </div>

      {/* 6m return */}
      <div className={`text-right text-xs ${pctClass(stock.change_6m_pct)}`}>
        {fmtPct(stock.change_6m_pct)}
      </div>

      {/* P/E */}
      <div className="text-right text-xs text-gray-500">
        {stock.pe_ratio != null ? `${stock.pe_ratio.toFixed(0)}x` : "—"}
      </div>
    </div>
  );
}

// ── Sector card ────────────────────────────────────────────────────────────────

function SectorCard({ sector, market }: { sector: SectorInfo; market: Market }) {
  const [expanded, setExpanded] = useState(false);
  const hasStocks = sector.top_stocks.length > 0;

  return (
    <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => hasStocks && setExpanded(e => !e)}
        className="w-full flex items-center gap-2.5 px-3 py-3 hover:bg-gray-50 transition-colors text-left"
        disabled={!hasStocks}
      >
        <span className="text-[10px] font-bold text-gray-300 w-5 shrink-0 text-right">{sector.rank}</span>
        <CycDot cyc={sector.cyclicality} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-gray-900">{sector.name}</span>
            <GrowthBadge tag={sector.growth_tag} />
          </div>
          <p className="text-[11px] text-gray-400 mt-0.5 truncate">{sector.macro_theme}</p>
        </div>

        <ScoreBar score={sector.sort_score} />

        {hasStocks ? (
          <span className="text-gray-300 shrink-0">
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        ) : (
          <span className="text-[9px] text-gray-300 shrink-0">no data</span>
        )}
      </button>

      {/* Stock table */}
      {expanded && hasStocks && (
        <div className="border-t border-gray-50">
          {/* Column headers */}
          <div className="grid grid-cols-[44px_1fr_68px_52px_52px_44px] gap-2 px-3 py-1.5 bg-gray-50">
            <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">Rank</span>
            <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">Stock / Score</span>
            <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide text-right">Price / MCap</span>
            <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide text-right">1Yr</span>
            <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide text-right">6M</span>
            <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide text-right">P/E</span>
          </div>
          {sector.top_stocks.map((stock) => (
            <StockRow key={stock.ticker} stock={stock} market={market} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Legend ─────────────────────────────────────────────────────────────────────

function Legend() {
  return (
    <div className="flex items-center gap-4 text-[10px] text-gray-400 flex-wrap">
      <span className="font-bold uppercase tracking-wide">Cyclicality:</span>
      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Low</span>
      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400 inline-block" /> Moderate</span>
      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-400 inline-block" /> High</span>
      <span className="ml-2 text-gray-300">|</span>
      <span className="flex items-center gap-1"><TrendingUp size={10} className="text-indigo-500" /> High Growth</span>
      <span className="flex items-center gap-1"><Shield size={10} className="text-green-600" /> Defensive</span>
      <span className="flex items-center gap-1"><AlertTriangle size={10} className="text-red-400" /> Cyclical</span>
      <span className="flex items-center gap-1"><Zap size={10} className="text-purple-500" /> Emerging</span>
      <span className="ml-2 text-gray-300">|</span>
      <span className="flex items-center gap-1.5 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5">
        <ArrowUp size={9} className="text-emerald-600" /><span className="text-[9px] font-bold text-emerald-700">#1</span>
        <span className="text-[9px] text-gray-400">= rose in rank due to dip entry</span>
      </span>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function SectorsPage() {
  const [market, setMarket] = useState<Market>("india");
  const [refresh, setRefresh] = useState(false);

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["sectors", market, refresh],
    queryFn: () => api.getSectors(market, { refresh }),
    staleTime: 24 * 60 * 60 * 1000,
  });

  function handleRefresh() {
    setRefresh(true);
    setTimeout(() => setRefresh(false), 500);
  }

  const sectors = data?.sectors ?? [];

  // Group into tiers for display
  const highGrowth   = sectors.filter(s => s.sort_score >= 75);
  const midCyclical  = sectors.filter(s => s.sort_score >= 45 && s.sort_score < 75);
  const cyclical     = sectors.filter(s => s.sort_score < 45);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Sector Explorer</h2>
            <p className="text-[11px] text-gray-400 mt-0.5">
              {sectors.length} sectors · ranked by secular growth potential
              {data?.from_cache && <span className="ml-1.5 text-indigo-400">(cached)</span>}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* Market toggle */}
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              {(["india", "us"] as Market[]).map(m => (
                <button
                  key={m}
                  onClick={() => setMarket(m)}
                  className={[
                    "px-3 py-1.5 text-xs font-semibold transition-colors",
                    market === m ? "bg-gray-900 text-white" : "text-gray-500 hover:bg-gray-50",
                  ].join(" ")}
                >
                  {m === "india" ? "India" : "US"}
                </button>
              ))}
            </div>

            {/* Refresh */}
            <button
              onClick={handleRefresh}
              disabled={isFetching}
              title="Refresh sector data"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border border-gray-200 hover:bg-gray-50 text-gray-700 rounded-xl disabled:opacity-50 transition-all"
            >
              <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>
        </div>

        <div className="mt-2">
          <Legend />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center gap-3 py-20 text-gray-400">
            <Loader2 size={28} className="animate-spin text-indigo-400" />
            <p className="text-sm">Fetching sector data — this takes ~20s on first load…</p>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center gap-2 py-20 text-red-500">
            <AlertTriangle size={24} />
            <p className="text-sm font-medium">Failed to load sectors</p>
            <p className="text-xs text-gray-400">
              {error instanceof Error ? error.message : "Unknown error"}
            </p>
          </div>
        ) : sectors.length === 0 ? (
          <div className="text-center py-20 text-gray-400 text-sm">No sector data available.</div>
        ) : (
          <div className="space-y-5 max-w-3xl mx-auto pb-6">
            {/* High Growth / Defensive tier */}
            {highGrowth.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <TrendingUp size={12} className="text-indigo-500" />
                  <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">
                    Priority Sectors — Secular Growth & Defensives
                  </span>
                </div>
                <div className="space-y-1.5">
                  {highGrowth.map(s => <SectorCard key={s.name} sector={s} market={market} />)}
                </div>
              </section>
            )}

            {/* Mid-cyclical tier */}
            {midCyclical.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <TrendingDown size={12} className="text-amber-500" />
                  <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">
                    Moderate Cyclical — Watch for Entry Timing
                  </span>
                </div>
                <div className="space-y-1.5">
                  {midCyclical.map(s => <SectorCard key={s.name} sector={s} market={market} />)}
                </div>
              </section>
            )}

            {/* High-cyclical tier */}
            {cyclical.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle size={12} className="text-red-400" />
                  <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">
                    Cyclical — Lower Priority for SIP Portfolios
                  </span>
                </div>
                <div className="space-y-1.5">
                  {cyclical.map(s => <SectorCard key={s.name} sector={s} market={market} />)}
                </div>
              </section>
            )}

            <p className="text-[10px] text-gray-300 text-center pt-2">
              Sort score = secular growth × 3 + defensiveness × 2 − cyclicality × 2 + macro tailwind bonus. Stock data via yfinance. Refresh every 24h.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
