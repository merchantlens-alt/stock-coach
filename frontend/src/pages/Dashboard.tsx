import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { GainerCard } from "../components/GainerCard";
import { MarketNarrative } from "../components/MarketNarrative";
import { MarketToggle } from "../components/MarketToggle";
import { SearchBar } from "../components/SearchBar";
import { useGainerAnalysis, useGainerDetail, useGainers } from "../hooks/useGainers";
import type { Market } from "../types";

export function Dashboard() {
  const [market, setMarket] = useState<Market>("us");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [searchedTicker, setSearchedTicker] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Active ticker is either a searched one or one clicked from the list
  const activeTicker = searchedTicker ?? selectedTicker;

  const { data: gainersData, isLoading: gainersLoading, error: gainersError, refetch } = useGainers(market);

  // Two parallel hooks: fast data (~3-5 s) + slow AI (~10-15 s).
  // The panel renders as soon as the data hook returns; AI fills in when ready.
  const { data: detail, isLoading: detailLoading, error: detailError } = useGainerDetail(market, activeTicker);
  const { data: analysisData, isLoading: analysisLoading } = useGainerAnalysis(market, activeTicker);

  function handleMarketChange(m: Market) {
    setMarket(m);
    setSelectedTicker(null);
    setSearchedTicker(null);
  }

  function handleSearch(query: string) {
    // Strip whitespace; the backend resolves company names → tickers automatically
    const cleaned = query.trim().toUpperCase().replace(/\s+/g, "");
    setSearchedTicker(cleaned);
    setSelectedTicker(null);
  }

  function handleClearSearch() {
    setSearchedTicker(null);
  }

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["gainers", market] });
    refetch();
  }

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left pane — gainer list */}
      <div className="w-full md:w-96 lg:w-[440px] shrink-0 flex flex-col border-r border-gray-200">
        {/* Controls */}
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3 bg-gray-50">
          <MarketToggle market={market} onChange={handleMarketChange} />
          <button
            onClick={handleRefresh}
            disabled={gainersLoading}
            className="p-2 rounded-lg text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={15} className={gainersLoading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Search */}
        <SearchBar
          market={market}
          onSearch={handleSearch}
          onClear={handleClearSearch}
          isSearching={!!searchedTicker && detailLoading}
        />

        {/* Summary bar */}
        {gainersData && (
          <div className="px-4 py-2 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
            <p className="text-xs text-gray-500">
              {gainersData.gainers.length} gainers · {gainersData.date}
            </p>
            {gainersData.from_cache && (
              <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">cached</span>
            )}
          </div>
        )}

        {/* Scrollable list + narrative */}
        <div className="flex-1 overflow-y-auto pb-3">
          {/* AI Market Narrative */}
          {gainersData?.summary && (
            <MarketNarrative summary={gainersData.summary} />
          )}

          {/* Skeleton while loading narrative */}
          {gainersLoading && (
            <div className="mx-3 mt-3 h-36 rounded-xl bg-indigo-50 animate-pulse" />
          )}

          <div className="p-3 space-y-2 mt-1">
            {gainersLoading && !gainersData && (
              Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-24 rounded-xl bg-gray-100 animate-pulse" />
              ))
            )}

            {gainersError && (
              <div className="text-center py-12 text-sm text-red-500">
                <p>Failed to load gainers.</p>
                <button onClick={handleRefresh} className="mt-2 text-blue-500 hover:underline">
                  Try again
                </button>
              </div>
            )}

            {gainersData?.gainers.map((gainer) => (
              <GainerCard
                key={gainer.ticker}
                gainer={gainer}
                isSelected={activeTicker === gainer.ticker}
                isLoading={activeTicker === gainer.ticker && detailLoading}
                onClick={() => {
                  setSearchedTicker(null);
                  setSelectedTicker(selectedTicker === gainer.ticker ? null : gainer.ticker);
                }}
              />
            ))}

            {gainersData?.gainers.length === 0 && !gainersLoading && (
              <div className="text-center py-12 text-sm text-gray-400">
                No gainers found for today.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right pane — analysis */}
      <div className="flex-1 overflow-hidden">
        {detail ? (
          /* Data arrived (~3-5 s) — show panel immediately; AI fills in via analysisLoading */
          <AnalysisPanel
            detail={detail}
            analysis={analysisData}
            analysisLoading={analysisLoading}
            onClose={() => { setSelectedTicker(null); setSearchedTicker(null); }}
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-3 p-8">
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
                <p className="text-xs mt-1 text-gray-400">
                  Check the ticker symbol and try again
                </p>
                <button
                  onClick={() => { setSelectedTicker(null); setSearchedTicker(null); }}
                  className="mt-3 text-xs text-blue-500 hover:underline"
                >
                  Clear
                </button>
              </div>
            ) : (
              <>
                <p className="text-sm">Select a stock or search any ticker</p>
                <p className="text-xs text-gray-300">Why it gained · 30-day outlook · Who else benefits</p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
