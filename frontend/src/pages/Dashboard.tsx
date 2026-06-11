import { RefreshCw, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Market } from "../types";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { GainerCard } from "../components/GainerCard";
import { MarketNarrative } from "../components/MarketNarrative";
import { MarketToggle } from "../components/MarketToggle";
import { SearchBar } from "../components/SearchBar";
import { ValueRecoveryCard } from "../components/ValueRecoveryCard";
import { CatalystPage } from "./CatalystPage";
import { useGainerAnalysis, useGainerDetail, useGainers, useRefreshAnalysis, useValueRecovery } from "../hooks/useGainers";
import type { Period } from "../types";

const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "1d", label: "Today" },
  { value: "1w", label: "1 Week" },
  { value: "1m", label: "1 Month" },
];

/** Map of ticker → [theme_label, ...] from saved conviction theses. */
function loadConvictionTickerMap(): Record<string, string[]> {
  try {
    const theses: { conviction: { instruments: { ticker: string }[]; theme_label: string } }[] =
      JSON.parse(localStorage.getItem("conviction_theses") || "[]");
    const map: Record<string, string[]> = {};
    for (const t of theses) {
      for (const inst of t.conviction.instruments ?? []) {
        if (!map[inst.ticker]) map[inst.ticker] = [];
        map[inst.ticker].push(t.conviction.theme_label);
      }
    }
    return map;
  } catch {
    return {};
  }
}

// ── View modes for the left panel ─────────────────────────────────────────────
type ViewMode = "movers" | "catalyst" | "recovery";

interface DashboardProps {
  jumpTo?: { market: Market; ticker: string } | null;
  onJumpConsumed?: () => void;
  onBuildThesis?: (belief: string) => void;
  /** Radar-pushed spotlight — switches to catalyst mode and filters to these tickers */
  scannerSpotlight?: string[];
  scannerSpotlightMarket?: Market;
  onClearSpotlight?: () => void;
  /** "Analyse" from within the embedded Scanner panel */
  onSelectFromScanner?: (market: Market, ticker: string) => void;
}

export function Dashboard({
  jumpTo,
  onJumpConsumed,
  onBuildThesis,
  scannerSpotlight = [],
  scannerSpotlightMarket,
  onClearSpotlight,
  onSelectFromScanner,
}: DashboardProps = {}) {
  const [market, setMarket]           = useState<Market>("us");
  const [period, setPeriod]           = useState<Period>("1d");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [searchedTicker, setSearchedTicker] = useState<string | null>(null);
  const [viewMode, setViewMode]       = useState<ViewMode>("movers");
  const [aiBullishOnly, setAiBullishOnly] = useState(false);
  const queryClient = useQueryClient();

  const convictionMap = useMemo(() => loadConvictionTickerMap(), []);

  const activeTicker = searchedTicker ?? selectedTicker;

  // Cancel stale requests when ticker changes
  const prevActiveTickerRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevActiveTickerRef.current;
    prevActiveTickerRef.current = activeTicker;
    if (prev && prev !== activeTicker) {
      queryClient.cancelQueries({ queryKey: ["gainer-detail", market, prev] });
      queryClient.cancelQueries({ queryKey: ["gainer-analysis", market, prev] });
    }
  }, [activeTicker, market, queryClient]);

  // ── Cross-tab jump (from Scanner "Analyse" or Radar) ──────────────────────
  useEffect(() => {
    if (jumpTo) {
      setMarket(jumpTo.market);
      setSearchedTicker(jumpTo.ticker);
      setSelectedTicker(null);
      onJumpConsumed?.();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpTo]);

  // ── Radar spotlight → switch to catalyst view ─────────────────────────────
  useEffect(() => {
    if (scannerSpotlight.length > 0) {
      setViewMode("catalyst");
      if (scannerSpotlightMarket) setMarket(scannerSpotlightMarket);
    }
  }, [scannerSpotlight, scannerSpotlightMarket]);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRecoveryRefreshing, setIsRecoveryRefreshing] = useState(false);

  const { data: gainersData, isLoading: gainersLoading, error: gainersError } = useGainers(market, period);

  const allGainers = gainersData?.gainers ?? [];

  const bullishGainers  = allGainers.filter(g => (g.ai_prediction_pct ?? -1) > 0);
  const filteredGainers = aiBullishOnly ? bullishGainers : allGainers;

  // Value Recovery scan data
  const { data: recoveryData, isLoading: recoveryLoading } = useValueRecovery(market);

  const { data: detail, isLoading: detailLoading, error: detailError } = useGainerDetail(market, activeTicker);
  const { data: analysisData, isLoading: analysisLoading } = useGainerAnalysis(market, activeTicker);
  const refreshAnalysis = useRefreshAnalysis(market, activeTicker);

  function handleMarketChange(m: Market) {
    setMarket(m);
    setSelectedTicker(null);
    setSearchedTicker(null);
    setAiBullishOnly(false);
    if (viewMode !== "catalyst") setViewMode("movers");
    onClearSpotlight?.();
  }

  function handlePeriodChange(p: Period) {
    setPeriod(p);
    setSelectedTicker(null);
    setSearchedTicker(null);
  }

  function handleSearch(query: string) {
    const cleaned = query.trim().toUpperCase().replace(/\s+/g, "");
    setSearchedTicker(cleaned);
    setSelectedTicker(null);
  }

  function handleClearSearch() {
    setSearchedTicker(null);
  }

  async function handleRefresh() {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      const result = await api.getGainers(market, period, { refresh: true });
      queryClient.setQueryData(["gainers", market, period], result);
    } catch {
      queryClient.invalidateQueries({ queryKey: ["gainers", market, period] });
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleRecoveryRefresh() {
    if (isRecoveryRefreshing) return;
    setIsRecoveryRefreshing(true);
    try {
      const result = await api.getValueRecovery(market, { refresh: true });
      queryClient.setQueryData(["value-recovery", market], result);
    } catch {
      queryClient.invalidateQueries({ queryKey: ["value-recovery", market] });
    } finally {
      setIsRecoveryRefreshing(false);
    }
  }

  function handlePrefetch(ticker: string) {
    queryClient.prefetchQuery({
      queryKey: ["gainer-detail", market, ticker],
      queryFn: () => api.getGainerDetail(market, ticker),
      staleTime: 30 * 60 * 1000,
    });
    queryClient.prefetchQuery({
      queryKey: ["gainer-analysis", market, ticker],
      queryFn: () => api.getGainerAnalysis(market, ticker),
      staleTime: 30 * 60 * 1000,
    });
  }

  // When the user clicks "Analyse" from the embedded Scanner
  function handleScannerAnalyse(market: Market, ticker: string) {
    if (onSelectFromScanner) {
      onSelectFromScanner(market, ticker);
    } else {
      // Fallback: open in the analysis panel directly
      setMarket(market);
      setSearchedTicker(ticker);
      setSelectedTicker(null);
    }
  }

  // ── VIEW MODE TABS ──────────────────────────────────────────────────────────
  const recoveryCount       = recoveryData?.stocks.length ?? 0;
  const strongRecoveryCount = recoveryData?.stocks.filter(s => s.recovery_quality === "strong").length ?? 0;

  const VIEW_TABS: { key: ViewMode; label: string; count?: number; color: string; inactive: string }[] = [
    {
      key: "movers",
      label: "Top Movers",
      count: allGainers.length,
      color: "bg-gray-900 text-white",
      inactive: "text-gray-600 hover:bg-gray-100",
    },
    {
      key: "catalyst",
      label: "⚡ Catalyst",
      color: "bg-green-600 text-white",
      inactive: "text-green-700 hover:bg-green-50",
    },
    {
      key: "recovery",
      label: "♻️ Recovery",
      count: recoveryCount || undefined,
      color: "bg-teal-600 text-white",
      inactive: "text-teal-700 hover:bg-teal-50",
    },
  ];

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* ── Left pane ──────────────────────────────────────────────────── */}
      <div className={`${activeTicker ? "hidden md:flex" : "flex"} w-full md:w-96 lg:w-[440px] shrink-0 flex-col border-r border-gray-200`}>

        {/* Controls row */}
        <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between gap-2 bg-gray-50">
          <MarketToggle market={market} onChange={handleMarketChange} />
          <div className="flex items-center gap-1.5">
            {viewMode === "movers" && (
              <div className="flex rounded-lg overflow-hidden border border-gray-200 bg-white text-xs">
                {PERIOD_OPTIONS.map(({ value, label }) => (
                  <button
                    key={value}
                    onClick={() => handlePeriodChange(value)}
                    className={`px-2 py-1.5 font-medium transition-colors ${
                      period === value ? "bg-gray-900 text-white" : "text-gray-500 hover:bg-gray-50"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {viewMode === "movers" && (
              <button
                onClick={handleRefresh}
                disabled={isRefreshing || gainersLoading}
                className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition-colors disabled:opacity-40"
                title="Force refresh gainers"
              >
                <RefreshCw size={13} className={(isRefreshing || gainersLoading) ? "animate-spin" : ""} />
              </button>
            )}
          </div>
        </div>

        {/* View mode tabs */}
        <div className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5 overflow-x-auto bg-white">
          {VIEW_TABS.map(({ key, label, count, color, inactive }) => (
            <button
              key={key}
              onClick={() => {
                setViewMode(key);
                if (key !== "catalyst") onClearSpotlight?.();
              }}
              className={[
                "flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap transition-colors",
                viewMode === key ? color : inactive,
              ].join(" ")}
            >
              {label}
              {count != null && (
                <span className={[
                  "text-[10px] rounded-full px-1.5 font-bold",
                  viewMode === key ? "bg-white/20" : "bg-gray-100 text-gray-500",
                ].join(" ")}>
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* ── CATALYST mode: embed the Scanner ─────────────────────────── */}
        {viewMode === "catalyst" ? (
          <div className="flex-1 overflow-hidden">
            <CatalystPage
              onSelectStock={handleScannerAnalyse}
              spotlightTickers={scannerSpotlight}
              spotlightMarket={scannerSpotlightMarket}
              onClearSpotlight={onClearSpotlight}
            />
          </div>
        ) : viewMode === "recovery" ? (
          /* ── RECOVERY mode: value re-rating opportunities ──────────────── */
          <div className="flex-1 overflow-y-auto pb-3">
            <div className="px-4 py-3 border-b border-teal-100 bg-teal-50 flex items-start gap-2">
              <p className="text-[10px] text-teal-700 font-semibold leading-relaxed flex-1">
                ♻️ Stocks with <span className="font-bold">compressed valuations and improving fundamentals</span> — P/E below market avg or forward P/E contracting, plus ≥2 inflection signals (EPS growth, ROE, analyst upgrades). Market hasn't repriced yet.
              </p>
              <button
                onClick={handleRecoveryRefresh}
                disabled={isRecoveryRefreshing || recoveryLoading}
                className="shrink-0 p-1 rounded-lg text-teal-500 hover:bg-teal-100 hover:text-teal-700 transition-colors disabled:opacity-40"
                title="Force refresh scan"
              >
                <RefreshCw size={13} className={(isRecoveryRefreshing || recoveryLoading) ? "animate-spin" : ""} />
              </button>
            </div>
            <div className="p-3 space-y-2 mt-1">
              {recoveryLoading && !recoveryData && (
                <>
                  {[1, 2, 3, 4].map(i => (
                    <div key={i} className="h-44 rounded-xl bg-gray-100 animate-pulse" />
                  ))}
                  <div className="flex items-center gap-2 text-xs text-teal-600 bg-teal-50 rounded-lg px-3 py-2">
                    <div className="w-3 h-3 rounded-full border-2 border-teal-400 border-t-transparent animate-spin shrink-0" />
                    Scanning fundamentals — P/E, forward earnings, ROE, analyst targets… 15-25 sec
                  </div>
                </>
              )}
              {recoveryData?.stocks.length === 0 && !recoveryLoading && (
                <div className="text-center py-12 text-sm text-gray-400">
                  <p className="text-2xl mb-2">♻️</p>
                  <p className="font-medium text-gray-600">No value recoveries right now</p>
                  <p className="text-xs mt-1">
                    Most stocks are fairly or fully priced. Check back when valuations compress.
                  </p>
                </div>
              )}
              {strongRecoveryCount > 0 && (
                <p className="text-[10px] font-bold text-teal-700 uppercase tracking-wide px-1">
                  ♻️ Strong — {strongRecoveryCount} high-conviction re-rating candidates
                </p>
              )}
              {recoveryData?.stocks.map(stock => (
                <ValueRecoveryCard
                  key={stock.ticker}
                  stock={stock}
                  isSelected={activeTicker === stock.ticker}
                  isLoading={activeTicker === stock.ticker && detailLoading}
                  onClick={() => {
                    setSearchedTicker(null);
                    setSelectedTicker(selectedTicker === stock.ticker ? null : stock.ticker);
                  }}
                  onPrefetch={() => handlePrefetch(stock.ticker)}
                />
              ))}
            </div>
          </div>
        ) : (
          /* ── MOVERS / BULLISH mode: gainer list ────────────────────── */
          <>
            {/* Search */}
            <SearchBar
              market={market}
              onSearch={handleSearch}
              onClear={handleClearSearch}
              isSearching={!!searchedTicker && detailLoading}
            />

            {/* Summary bar */}
            {gainersData && (
              <div className="px-3 py-1.5 bg-gray-50 border-b border-gray-100 flex items-center gap-2">
                <p className="text-[10px] text-gray-400 shrink-0">
                  {filteredGainers.length} stocks · {gainersData.date}
                </p>
                {/* AI Bullish toggle chip */}
                {bullishGainers.length > 0 && (
                  <button
                    onClick={() => setAiBullishOnly(v => !v)}
                    className={[
                      "flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border transition-colors whitespace-nowrap",
                      aiBullishOnly
                        ? "bg-emerald-600 text-white border-emerald-600"
                        : "bg-white text-emerald-700 border-emerald-300 hover:bg-emerald-50",
                    ].join(" ")}
                  >
                    🟢 AI Bullish
                    <span className={`text-[9px] rounded-full px-1 font-bold ${aiBullishOnly ? "bg-white/20" : "bg-emerald-100 text-emerald-600"}`}>
                      {bullishGainers.length}
                    </span>
                  </button>
                )}
                {gainersData.from_cache && (
                  <span className="ml-auto text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded shrink-0">cached</span>
                )}
              </div>
            )}

            {/* Scrollable list */}
            <div className="flex-1 overflow-y-auto pb-3">
              {gainersData?.summary && (
                <MarketNarrative summary={gainersData.summary} />
              )}

              {gainersLoading && (
                <div className="mx-3 mt-3 h-28 rounded-xl bg-indigo-50 animate-pulse" />
              )}

              <div className="p-3 space-y-2 mt-1">
                {gainersLoading && !gainersData && (
                  Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="h-20 rounded-xl bg-gray-100 animate-pulse" />
                  ))
                )}

                {gainersError && (
                  <div className="text-center py-12 text-sm text-red-500">
                    <p>Failed to load stocks.</p>
                    <button onClick={handleRefresh} className="mt-2 text-blue-500 hover:underline">
                      Try again
                    </button>
                  </div>
                )}

                {filteredGainers.map(gainer => (
                  <GainerCard
                    key={gainer.ticker}
                    gainer={gainer}
                    isSelected={activeTicker === gainer.ticker}
                    isLoading={activeTicker === gainer.ticker && detailLoading}
                    period={period}
                    convictionThemes={convictionMap[gainer.ticker]}
                    onClick={() => {
                      setSearchedTicker(null);
                      setSelectedTicker(selectedTicker === gainer.ticker ? null : gainer.ticker);
                    }}
                    onPrefetch={() => handlePrefetch(gainer.ticker)}
                  />
                ))}

                {filteredGainers.length === 0 && !gainersLoading && (
                  <div className="text-center py-12 text-sm text-gray-400">
                    {aiBullishOnly
                      ? "No AI-bullish stocks yet — run analysis on some stocks first."
                      : "No stocks found."}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── Right pane — analysis panel ────────────────────────────────── */}
      <div className={`${activeTicker ? "flex" : "hidden md:flex"} flex-1 flex-col overflow-hidden`}>
        {detail ? (
          <AnalysisPanel
            detail={detail}
            analysis={analysisData}
            analysisLoading={analysisLoading}
            period={period}
            onClose={() => { setSelectedTicker(null); setSearchedTicker(null); }}
            convictionMatches={activeTicker ? convictionMap[activeTicker] : undefined}
            onRefresh={() => refreshAnalysis.mutate()}
            isRefreshing={refreshAnalysis.isPending}
            onBuildThesis={onBuildThesis}
          />
        ) : (
          <div className="h-full flex flex-col text-gray-400">
            {activeTicker && (
              <div className="md:hidden flex items-center px-4 py-3 border-b border-gray-100">
                <button
                  onClick={() => { setSelectedTicker(null); setSearchedTicker(null); }}
                  className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
                >
                  ← Back
                </button>
              </div>
            )}
            <div className="flex-1 flex flex-col items-center justify-center gap-3 p-8">
              {detailLoading ? (
                <div className="text-center">
                  <div className="w-10 h-10 rounded-full border-2 border-green-500 border-t-transparent animate-spin mx-auto mb-3" />
                  <p className="text-sm font-medium text-gray-600">
                    {searchedTicker ? `Looking up ${searchedTicker}…` : "Fetching stock data…"}
                  </p>
                  <p className="text-xs mt-1 text-gray-400">
                    Resolving ticker · Fetching fundamentals · 3–5 sec
                  </p>
                </div>
              ) : detailError && activeTicker ? (
                <div className="text-center">
                  <p className="text-sm font-medium text-red-500">
                    Could not find <span className="font-bold">{activeTicker}</span>
                  </p>
                  <p className="text-xs mt-1 text-gray-400">Check the ticker symbol and try again</p>
                  <button
                    onClick={() => { setSelectedTicker(null); setSearchedTicker(null); }}
                    className="mt-3 text-xs text-blue-500 hover:underline"
                  >
                    Clear
                  </button>
                </div>
              ) : (
                <>
                  <div className="w-14 h-14 rounded-xl bg-gray-100 flex items-center justify-center">
                    <Zap size={24} className="text-gray-300" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium text-gray-500">Select a stock to analyse</p>
                    <p className="text-xs text-gray-400 mt-1">
                      Pick from the list · Use ⚡ Catalyst for confirmed movers · Search any ticker
                    </p>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
