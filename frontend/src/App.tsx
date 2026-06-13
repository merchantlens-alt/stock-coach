import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Header } from "./components/Header";
import { ConvictionPage } from "./pages/ConvictionPage";
import { Dashboard } from "./pages/Dashboard";
import { FundsPage } from "./pages/FundsPage";
import { GlossaryPage } from "./pages/GlossaryPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { RadarPage } from "./pages/RadarPage";
import type { Market } from "./types";

// Top-level mode: Funds is the primary home; Stocks is one switch away.
// Each mode lazily mounts its own pages, so stock data never fetches until
// the user actually switches into Stocks mode.
export type AppMode   = "funds" | "stocks";
export type FundsTab  = "build" | "scanner" | "analyse" | "switch";
export type StocksTab = "gainers" | "radar" | "conviction" | "portfolio";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  const [mode, setMode]           = useState<AppMode>("funds");   // ← Funds is home
  const [fundsTab, setFundsTab]   = useState<FundsTab>("build");
  const [stocksTab, setStocksTab] = useState<StocksTab>("gainers");
  const [guideOpen, setGuideOpen] = useState(false);

  // ── Cross-tab navigation state (stocks side) ────────────────────────────────

  // Gainers panel jump: click "Analyse" anywhere → open stock detail in Market tab
  const [jumpTo, setJumpTo] = useState<{ market: Market; ticker: string } | null>(null);

  // Scanner view inside the Market/Gainers tab — Radar can push "spotlight" tickers.
  const [scannerSpotlight, setScannerSpotlight]             = useState<string[]>([]);
  const [scannerSpotlightMarket, setScannerSpotlightMarket] = useState<Market>("us");

  // Analysis → Conviction: "Build Thesis" pre-fills the belief input
  const [convictionBelief, setConvictionBelief] = useState("");

  // Any cross-tab jump lands in Stocks mode on the right sub-tab, closing the guide.
  function toStocks(tab: StocksTab) {
    setGuideOpen(false);
    setMode("stocks");
    setStocksTab(tab);
  }

  function handleSelectFromScanner(market: Market, ticker: string) {
    setJumpTo({ market, ticker });
    toStocks("gainers");
  }

  function handleFindMoving(tickers: string[], market: Market) {
    setScannerSpotlight(tickers);
    setScannerSpotlightMarket(market);
    toStocks("gainers");
  }

  function handleBuildThesis(belief: string) {
    setConvictionBelief(belief);
    toStocks("conviction");
  }

  // ── Header callbacks ────────────────────────────────────────────────────────

  const activeSubTab = mode === "funds" ? fundsTab : stocksTab;

  function handleModeChange(next: AppMode) {
    setGuideOpen(false);
    setMode(next);
  }

  function handleSubTabChange(key: string) {
    setGuideOpen(false);
    if (mode === "funds") setFundsTab(key as FundsTab);
    else setStocksTab(key as StocksTab);
  }

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex flex-col h-screen bg-gray-50">
        <Header
          mode={mode}
          onModeChange={handleModeChange}
          activeSubTab={activeSubTab}
          onSubTabChange={handleSubTabChange}
          guideOpen={guideOpen}
          onToggleGuide={() => setGuideOpen(o => !o)}
        />

        {/* Guide overlays whatever mode is active; mode pages stay unmounted while open */}
        {guideOpen ? (
          <GlossaryPage />
        ) : mode === "funds" ? (
          <FundsPage tab={fundsTab} />
        ) : (
          <>
            {stocksTab === "gainers" && (
              <Dashboard
                jumpTo={jumpTo}
                onJumpConsumed={() => setJumpTo(null)}
                onBuildThesis={handleBuildThesis}
                scannerSpotlight={scannerSpotlight}
                scannerSpotlightMarket={scannerSpotlightMarket}
                onClearSpotlight={() => setScannerSpotlight([])}
                onSelectFromScanner={handleSelectFromScanner}
              />
            )}
            {stocksTab === "radar"      && <RadarPage onFindMoving={handleFindMoving} />}
            {stocksTab === "conviction" && (
              <ConvictionPage initialBelief={convictionBelief} onBeliefConsumed={() => setConvictionBelief("")} />
            )}
            {stocksTab === "portfolio"  && <PortfolioPage />}
          </>
        )}
      </div>
    </QueryClientProvider>
  );
}
