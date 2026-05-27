import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { GainerCard } from "../components/GainerCard";
import { MarketToggle } from "../components/MarketToggle";
import { useGainerDetail, useGainers } from "../hooks/useGainers";
import type { Market } from "../types";

export function Dashboard() {
  const [market, setMarket] = useState<Market>("us");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: gainersData, isLoading: gainersLoading, error: gainersError, refetch } = useGainers(market);
  const { data: detail, isLoading: detailLoading } = useGainerDetail(market, selectedTicker);

  function handleMarketChange(m: Market) {
    setMarket(m);
    setSelectedTicker(null);
  }

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["gainers", market] });
    refetch();
  }

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left pane — gainer list */}
      <div className="w-full md:w-96 lg:w-[420px] shrink-0 flex flex-col border-r border-gray-200">
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

        {/* List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {gainersLoading && (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-24 rounded-xl bg-gray-100 animate-pulse" />
              ))}
            </div>
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
              isSelected={selectedTicker === gainer.ticker}
              isLoading={selectedTicker === gainer.ticker && detailLoading}
              onClick={() =>
                setSelectedTicker(
                  selectedTicker === gainer.ticker ? null : gainer.ticker
                )
              }
            />
          ))}

          {gainersData?.gainers.length === 0 && !gainersLoading && (
            <div className="text-center py-12 text-sm text-gray-400">
              No gainers found for today.
            </div>
          )}
        </div>
      </div>

      {/* Right pane — analysis */}
      <div className="flex-1 overflow-hidden">
        {detail ? (
          <AnalysisPanel detail={detail} onClose={() => setSelectedTicker(null)} />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-3 p-8">
            {detailLoading ? (
              <div className="text-center">
                <div className="w-10 h-10 rounded-full border-2 border-green-500 border-t-transparent animate-spin mx-auto mb-3" />
                <p className="text-sm">AI is analysing the stock…</p>
                <p className="text-xs mt-1 text-gray-300">This takes 15–30 seconds on first load</p>
              </div>
            ) : (
              <>
                <p className="text-sm">Select a stock to see AI analysis</p>
                <p className="text-xs text-gray-300">Why it gained · 30-day outlook · Fundamentals</p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
