import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { GainerCard } from "../components/GainerCard";
import { MarketNarrative } from "../components/MarketNarrative";
import { MarketToggle } from "../components/MarketToggle";
import { SearchBar } from "../components/SearchBar";
import { useGainerAnalysis, useGainerDetail, useGainers } from "../hooks/useGainers";
import type { Market, Period, SignalTier } from "../types";

const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "1d", label: "Today" },
  { value: "1w", label: "1 Week" },
  { value: "1m", label: "1 Month" },
];

export function Dashboard() {
  const [market, setMarket] = useState<Market>("us");
  const [period, setPeriod] = useState<Period>("1d");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [searchedTicker, setSearchedTicker] = useState<string | null>(null);
  const [tierFilter, setTierFilter] = useState<SignalTier | "all">("all");
  const queryClient = useQueryClient();

  // Active ticker is either a searched one or one clicked from the list
  const activeTicker = searchedTicker ?? selectedTicker;

  // Cancel in-flight requests for the previous ticker whenever activeTicker changes.
  const prevActiveTickerRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevActiveTickerRef.current;
    prevActiveTickerRef.current = activeTicker;
    if (prev && prev !== activeTicker) {
      queryClient.cancelQueries({ queryKey: ["gainer-detail", market, prev] });
      queryClient.cancelQueries({ queryKey: ["gainer-analysis", market, prev] });
    }
  }, [activeTicker, market, queryClient]);

  const [isRefreshing, setIsRefreshing] = useState(false);

  const { data: gainersData, isLoading: gainersLoading, error: gainersError } = useGainers(market, period);

  const allGainers = gainersData?.gainers ?? [];
  const filteredGainers = tierFilter === "all"
    ? allGainers
    : allGainers.filter(g => (g.signal_tier ?? "mover") === tierFilter);
  const tierCounts = {
    confirmed: allGainers.filter(g => (g.signal_tier ?? "mover") === "confirmed").length,
    catalyst:  allGainers.filter(g => (g.signal_tier ?? "mover") === "catalyst").length,
    mover:     allGainers.filter(g => (g.signal_tier ?? "mover") === "mover").length,
  };

  // Two parallel hooks: fast data (~3-5 s) + slow AI (~10-15 s).
  // The panel renders as soon as the data hook returns; AI fills in when ready.
  const { data: detail, isLoading: detailLoading, error: detailError } = useGainerDetail(market, activeTicker);
  const { data: analysisData, isLoading: analysisLoading } = useGainerAnalysis(market, activeTicker);

  function handleMarketChange(m: Market) {
    setMarket(m);
    setSelectedTicker(null);
    setSearchedTicker(null);
    setTierFilter("all");
  }

  function handlePeriodChange(p: Period) {
    setPeriod(p);
    setSelectedTicker(null);
    setSearchedTicker(null);
    setTierFilter("all");
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

  async function handleRefresh() {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      // Pass refresh=true so backend skips Redis cache and fetches fresh data
      const result = await api.getGainers(market, period, { refresh: true });
      queryClient.setQueryData(["gainers", market, period], result);
    } catch {
      // If the forced refresh fails, invalidate so next render re-fetches normally
      queryClient.invalidateQueries({ queryKey: ["gainers", market, period] });
    } finally {
      setIsRefreshing(false);
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

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left pane — gainer list. On mobile: hidden when a stock is selected */}
      <div className={`${activeTicker ? "hidden md:flex" : "flex"} w-full md:w-96 lg:w-[440px] shrink-0 flex-col border-r border-gray-200`}>
        {/* Controls */}
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3 bg-gray-50">
          <MarketToggle market={market} onChange={handleMarketChange} />
          <div className="flex items-center gap-2">
            {/* Period selector */}
            <div className="flex rounded-lg overflow-hidden border border-gray-200 bg-white text-xs">
              {PERIOD_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => handlePeriodChange(value)}
                  className={`px-2.5 py-1.5 font-medium transition-colors ${
                    period === value
                      ? "bg-gray-900 text-white"
                      : "text-gray-500 hover:bg-gray-50"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              onClick={handleRefresh}
              disabled={isRefreshing || gainersLoading}
              className="p-2 rounded-lg text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition-colors disabled:opacity-40"
              title="Force refresh (bypass cache)"
            >
              <RefreshCw size={15} className={(isRefreshing || gainersLoading) ? "animate-spin" : ""} />
            </button>
          </div>
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
              {gainersData.gainers.length} stocks · {gainersData.date}
            </p>
            {gainersData.from_cache && (
              <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">cached</span>
            )}
          </div>
        )}

        {/* Tier filter tabs */}
        {gainersData && allGainers.length > 0 && (
          <div className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5 overflow-x-auto">
            {(
              [
                { key: "all",       label: "All",       count: allGainers.length, style: "bg-gray-900 text-white", inactive: "text-gray-600 hover:bg-gray-100" },
                { key: "confirmed", label: "Confirmed", count: tierCounts.confirmed, style: "bg-green-600 text-white", inactive: "text-green-700 hover:bg-green-50" },
                { key: "catalyst",  label: "Catalyst",  count: tierCounts.catalyst, style: "bg-indigo-600 text-white", inactive: "text-indigo-700 hover:bg-indigo-50" },
                { key: "mover",     label: "Mover",     count: tierCounts.mover, style: "bg-gray-500 text-white", inactive: "text-gray-500 hover:bg-gray-100" },
              ] as const
            ).map(({ key, label, count, style, inactive }) => (
              <button
                key={key}
                onClick={() => setTierFilter(key)}
                className={[
                  "flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full whitespace-nowrap transition-colors",
                  tierFilter === key ? style : inactive,
                ].join(" ")}
              >
                {label}
                <span className={[
                  "text-xs rounded-full px-1.5 py-0 font-semibold",
                  tierFilter === key ? "bg-white/20" : "bg-gray-100 text-gray-500",
                ].join(" ")}>
                  {count}
                </span>
              </button>
            ))}
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

            {filteredGainers.map((gainer) => (
              <GainerCard
                key={gainer.ticker}
                gainer={gainer}
                isSelected={activeTicker === gainer.ticker}
                isLoading={activeTicker === gainer.ticker && detailLoading}
                onClick={() => {
                  setSearchedTicker(null);
                  setSelectedTicker(selectedTicker === gainer.ticker ? null : gainer.ticker);
                }}
                onPrefetch={() => handlePrefetch(gainer.ticker)}
              />
            ))}

            {filteredGainers.length === 0 && !gainersLoading && (
              <div className="text-center py-12 text-sm text-gray-400">
                {tierFilter === "all"
                  ? "No stocks found."
                  : `No ${tierFilter} stocks in current data.`}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right pane — analysis. On mobile: full-screen when a stock is selected */}
      <div className={`${activeTicker ? "flex" : "hidden md:flex"} flex-1 flex-col overflow-hidden`}>
        {detail ? (
          /* Data arrived (~3-5 s) — show panel immediately; AI fills in via analysisLoading */
          <AnalysisPanel
            detail={detail}
            analysis={analysisData}
            analysisLoading={analysisLoading}
            onClose={() => { setSelectedTicker(null); setSearchedTicker(null); }}
          />
        ) : (
          <div className="h-full flex flex-col text-gray-400">
            {/* Mobile back button — visible while loading or on error */}
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
          </div>
        )}
      </div>
    </div>
  );
}
