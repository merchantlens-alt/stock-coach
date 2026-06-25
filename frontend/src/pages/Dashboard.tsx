import { Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { MarketToggle } from "../components/MarketToggle";
import { SearchBar } from "../components/SearchBar";
import { useGainerAnalysis, useGainerDetail, useRefreshAnalysis } from "../hooks/useGainers";
import type { Market } from "../types";

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

interface DashboardProps {
  jumpTo?: { market: Market; ticker: string } | null;
  onJumpConsumed?: () => void;
  onBuildThesis?: (belief: string) => void;
  onSetupProfile?: () => void;
}

export function Dashboard({
  jumpTo,
  onJumpConsumed,
  onBuildThesis,
  onSetupProfile,
}: DashboardProps = {}) {
  const [market, setMarket]                 = useState<Market>("us");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [searchedTicker, setSearchedTicker] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const convictionMap = useMemo(() => loadConvictionTickerMap(), []);
  const activeTicker  = searchedTicker ?? selectedTicker;

  const prevActiveTickerRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevActiveTickerRef.current;
    prevActiveTickerRef.current = activeTicker;
    if (prev && prev !== activeTicker) {
      queryClient.cancelQueries({ queryKey: ["gainer-detail", market, prev] });
      queryClient.cancelQueries({ queryKey: ["gainer-analysis", market, prev] });
    }
  }, [activeTicker, market, queryClient]);

  useEffect(() => {
    if (jumpTo) {
      setMarket(jumpTo.market);
      setSearchedTicker(jumpTo.ticker);
      setSelectedTicker(null);
      onJumpConsumed?.();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpTo]);

  const { data: detail, isLoading: detailLoading, error: detailError } =
    useGainerDetail(market, activeTicker);
  const { data: analysisData, isLoading: analysisLoading } =
    useGainerAnalysis(market, activeTicker);
  const refreshAnalysis = useRefreshAnalysis(market, activeTicker);

  function handleMarketChange(m: Market) {
    setMarket(m);
    setSelectedTicker(null);
    setSearchedTicker(null);
  }

  function handleSearch(query: string) {
    setSearchedTicker(query.trim().toUpperCase().replace(/\s+/g, ""));
    setSelectedTicker(null);
  }

  // Prefetch on hover — used by future ticker-list components
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

  void handlePrefetch; // suppress unused-variable warning until ticker lists return

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* ── Left pane ──────────────────────────────────────────────────────── */}
      <div className={`${activeTicker ? "hidden md:flex" : "flex"} w-full md:w-96 lg:w-[440px] shrink-0 flex-col border-r border-gray-200`}>

        {/* Market toggle */}
        <div className="px-3 py-2.5 border-b border-gray-100 bg-gray-50">
          <MarketToggle market={market} onChange={handleMarketChange} />
        </div>

        {/* Search */}
        <SearchBar
          market={market}
          onSearch={handleSearch}
          onClear={() => setSearchedTicker(null)}
          isSearching={!!searchedTicker && detailLoading}
        />

        {/* Empty state */}
        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="w-14 h-14 rounded-xl bg-indigo-50 flex items-center justify-center">
            <Sparkles size={24} className="text-indigo-300" />
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500">Search any stock to analyse</p>
            <p className="text-xs text-gray-400 mt-1.5 leading-relaxed">
              Enter a ticker above to get fundamentals,<br />
              AI analysis, and your personalised verdict
            </p>
          </div>
        </div>
      </div>

      {/* ── Right pane — analysis panel ────────────────────────────────────── */}
      <div className={`${activeTicker ? "flex" : "hidden md:flex"} flex-1 flex-col overflow-hidden`}>
        {detail ? (
          <AnalysisPanel
            detail={detail}
            analysis={analysisData}
            analysisLoading={analysisLoading}
            period="1d"
            onClose={() => { setSelectedTicker(null); setSearchedTicker(null); }}
            convictionMatches={activeTicker ? convictionMap[activeTicker] : undefined}
            onRefresh={() => refreshAnalysis.mutate()}
            isRefreshing={refreshAnalysis.isPending}
            onBuildThesis={onBuildThesis}
            onSetupProfile={onSetupProfile}
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
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-500">Select a stock to analyse</p>
                  <p className="text-xs text-gray-400 mt-1">Search any ticker on the left</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
