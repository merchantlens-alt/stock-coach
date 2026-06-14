/**
 * FundsPage — primary home of the app. India MF + US ETF tooling.
 *
 * Sub-views (market toggle shared across all):
 *   • Top 5   — the model portfolio you should own (ModelPortfolioView).
 *   • Scanner — screen the universe with category-relative / cost-led scoring.
 *   • Compare — SIP backtest: your funds vs the model (CompareView).
 *   • Analyse — placeholder: deep dive on one fund.
 */

import { Loader2, Microscope, RefreshCw, ScanSearch, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { CompareView } from "../components/CompareView";
import { FundCard } from "../components/FundCard";
import { MarketToggleFunds } from "../components/MarketToggleFunds";
import { ModelPortfolioView } from "../components/ModelPortfolioView";
import { useFundScan } from "../hooks/useFunds";
import type { FundsTab } from "../App";
import type { Market } from "../types";

// ── Scanner ─────────────────────────────────────────────────────────────────

const INDIA_CATEGORIES = [
  "Flexi Cap", "Multi Cap", "Large Cap", "Large & Mid Cap", "Mid Cap",
  "Small Cap", "ELSS", "Focused", "Value/Contra", "Special Opportunities",
];
const US_CATEGORIES = [
  "US Broad Market", "US Large Growth", "US Large Value", "US Dividend",
  "US Mid Cap", "US Small Cap", "US Technology", "US Sector",
  "International Developed", "International Total", "Emerging Markets", "Bonds", "REIT",
];

function FundScanner({ market, onMarketChange }: { market: Market; onMarketChange: (m: Market) => void }) {
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [refreshing, setRefreshing] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useFundScan(market, category);

  // Categories differ per market — reset the filter when the market changes.
  useEffect(() => { setCategory(undefined); }, [market]);
  const categories = market === "us" ? US_CATEGORIES : INDIA_CATEGORIES;

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const result = await api.getFundScan(market, category, { refresh: true });
      queryClient.setQueryData(["funds", "scan", market, category ?? "all"], result);
    } catch {
      queryClient.invalidateQueries({ queryKey: ["funds", "scan", market, category ?? "all"] });
    } finally {
      setRefreshing(false);
    }
  }

  const funds = data?.funds ?? [];

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">

      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3 space-y-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center shrink-0">
            <ScanSearch size={16} className="text-violet-600" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-gray-900">Fund Scanner</h2>
            <p className="text-[11px] text-gray-400 truncate">
              {market === "us"
                ? "US ETFs · cost-led ranking on expense ratio, return & size"
                : "India MFs · ranked within category · saturation & closet-index ruled out"}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <MarketToggleFunds market={market} onChange={onMarketChange} />
            {funds.length > 0 && (
              <span className="hidden md:inline text-[11px] text-gray-400">
                {funds.length}{data?.universe_size ? ` / ${data.universe_size}` : ""}
              </span>
            )}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              title="Force a fresh scan"
              className="flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50"
            >
              <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>

        {/* Category pills */}
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setCategory(undefined)}
            className={[
              "text-[10px] font-semibold px-2.5 py-1 rounded-full border transition-all",
              category === undefined
                ? "bg-violet-600 text-white border-violet-600"
                : "bg-white text-gray-500 border-gray-200 hover:border-gray-300",
            ].join(" ")}
          >
            All
          </button>
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setCategory(cat === category ? undefined : cat)}
              className={[
                "text-[10px] font-semibold px-2.5 py-1 rounded-full border transition-all",
                category === cat
                  ? "bg-violet-600 text-white border-violet-600"
                  : "bg-white text-gray-500 border-gray-200 hover:border-gray-300",
              ].join(" ")}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4">
        {isLoading && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <Loader2 size={28} className="animate-spin mb-3 text-violet-500" />
            <p className="text-sm font-medium">Scanning {market === "us" ? "ETFs" : "funds"} & computing metrics…</p>
            <p className="text-xs mt-1">{market === "us" ? "Pulling ETF data — a few seconds" : "First scan pulls NAV history — ~30s"}</p>
          </div>
        )}

        {error && !isLoading && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-sm font-medium text-red-500">Couldn't load funds</p>
            <button onClick={handleRefresh} className="mt-3 text-xs font-semibold text-violet-600 hover:underline">
              Try again
            </button>
          </div>
        )}

        {!isLoading && !error && funds.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <ScanSearch size={28} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm font-medium">No funds found{category ? ` in ${category}` : ""}</p>
          </div>
        )}

        {funds.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {funds.map(f => <FundCard key={f.scheme_code} fund={f} />)}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Placeholder sub-view (Analyse) ────────────────────────────────────────────

interface Placeholder {
  icon: ReactNode;
  title: string;
  tagline: string;
  bullets: { lead: string; rest: string }[];
}

const ANALYSE_PLACEHOLDER: Placeholder = {
  icon: <Microscope size={22} className="text-violet-600" />,
  title: "Fund Analyser",
  tagline: "Deep dive on a single fund — and cross-reference the stocks it actually holds.",
  bullets: [
    { lead: "Holdings heatmap", rest: "Sector and top-company exposure — see what you're really buying under the label." },
    { lead: "Cost compounding", rest: "What the expense ratio actually costs you over 10 and 20 years." },
    { lead: "Stock crossover",  rest: "\"This fund holds Infosys at 23% — here's the AI analysis we already ran on it.\"" },
  ],
};

function PlaceholderView({ p }: { p: Placeholder }) {
  return (
    <div className="flex-1 overflow-y-auto bg-gray-50">
      <div className="max-w-2xl mx-auto px-4 md:px-6 py-10">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-12 h-12 rounded-2xl bg-violet-100 flex items-center justify-center shrink-0">
            {p.icon}
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900 leading-tight">{p.title}</h2>
            <span className="inline-flex items-center gap-1 text-[10px] font-bold text-violet-600 uppercase tracking-wide">
              <Sparkles size={11} /> Coming next
            </span>
          </div>
        </div>
        <p className="text-sm text-gray-500 leading-relaxed mb-6">{p.tagline}</p>
        <div className="space-y-2.5">
          {p.bullets.map((b, i) => (
            <div key={i} className="rounded-xl border border-gray-100 bg-white p-4">
              <p className="text-xs text-gray-700 leading-relaxed">
                <span className="font-bold text-gray-900">{b.lead}</span>
                <span className="text-gray-300"> · </span>
                {b.rest}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-6 rounded-xl border border-violet-100 bg-violet-50 p-4">
          <p className="text-[11px] text-violet-700 leading-relaxed">
            <span className="font-bold">Why this beats Groww / ET Money / Moneycontrol:</span> they
            show you ranked tables. StockCoach tells you <span className="font-semibold">whether to act</span> —
            enter, hold, or switch — with AI reasoning grounded in the fund's real holdings and your existing stock analysis.
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Page shell ────────────────────────────────────────────────────────────────

export function FundsPage({ tab }: { tab: FundsTab }) {
  // Market (India MF / US ETF) is shared across the Funds sub-tabs.
  const [market, setMarket] = useState<Market>("india");
  if (tab === "build") return <ModelPortfolioView market={market} onMarketChange={setMarket} />;
  if (tab === "scanner") return <FundScanner market={market} onMarketChange={setMarket} />;
  if (tab === "compare") return <CompareView market={market} onMarketChange={setMarket} />;
  return <PlaceholderView p={ANALYSE_PLACEHOLDER} />;
}
