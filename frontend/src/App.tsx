import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Header } from "./components/Header";
import { CatalystPage } from "./pages/CatalystPage";
import { ConvictionPage } from "./pages/ConvictionPage";
import { Dashboard } from "./pages/Dashboard";
import { PortfolioPage } from "./pages/PortfolioPage";
import { RadarPage } from "./pages/RadarPage";
import type { Market } from "./types";

export type AppTab = "scanner" | "radar" | "gainers" | "conviction" | "portfolio";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  const [tab, setTab] = useState<AppTab>("scanner");

  // ── Cross-tab navigation state ──────────────────────────────────────────────
  // Scanner → Gainers: click "Analyse" on a play → open that stock's detail
  const [jumpTo, setJumpTo] = useState<{ market: Market; ticker: string } | null>(null);

  // Radar → Scanner: click "Find moving stocks" on a signal → filter to those tickers
  const [scannerSpotlight, setScannerSpotlight] = useState<string[]>([]);
  const [scannerSpotlightMarket, setScannerSpotlightMarket] = useState<Market>("us");

  // Analysis → Conviction: click "Build Thesis" → pre-fill the belief input
  const [convictionBelief, setConvictionBelief] = useState("");

  function handleSelectFromScanner(market: Market, ticker: string) {
    setJumpTo({ market, ticker });
    setTab("gainers");
  }

  function handleFindMoving(tickers: string[], market: Market) {
    setScannerSpotlight(tickers);
    setScannerSpotlightMarket(market);
    setTab("scanner");
  }

  function handleBuildThesis(belief: string) {
    setConvictionBelief(belief);
    setTab("conviction");
  }

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex flex-col h-screen bg-gray-50">
        <Header activeTab={tab} onTabChange={setTab} />

        {tab === "scanner" && (
          <CatalystPage
            onSelectStock={handleSelectFromScanner}
            spotlightTickers={scannerSpotlight}
            spotlightMarket={scannerSpotlightMarket}
            onClearSpotlight={() => setScannerSpotlight([])}
          />
        )}
        {tab === "radar" && (
          <RadarPage onFindMoving={handleFindMoving} />
        )}
        {tab === "gainers" && (
          <Dashboard
            jumpTo={jumpTo}
            onJumpConsumed={() => setJumpTo(null)}
            onBuildThesis={handleBuildThesis}
          />
        )}
        {tab === "conviction" && (
          <ConvictionPage initialBelief={convictionBelief} onBeliefConsumed={() => setConvictionBelief("")} />
        )}
        {tab === "portfolio" && <PortfolioPage />}
      </div>
    </QueryClientProvider>
  );
}
