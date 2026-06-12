import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Header } from "./components/Header";
import { ConvictionPage } from "./pages/ConvictionPage";
import { Dashboard } from "./pages/Dashboard";
import { GlossaryPage } from "./pages/GlossaryPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { RadarPage } from "./pages/RadarPage";
import type { Market } from "./types";

// "scanner" tab has been merged into "gainers" as a catalyst view mode.
export type AppTab = "gainers" | "radar" | "conviction" | "portfolio" | "glossary";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  const [tab, setTab] = useState<AppTab>("gainers");

  // ── Cross-tab navigation state ──────────────────────────────────────────────

  // Gainers panel jump: click "Analyse" anywhere → open stock detail in Market tab
  const [jumpTo, setJumpTo] = useState<{ market: Market; ticker: string } | null>(null);

  // Scanner view inside the Market/Gainers tab — controlled by Dashboard internally,
  // but Radar can push "spotlight" tickers and switch the view to catalyst mode.
  const [scannerSpotlight, setScannerSpotlight]           = useState<string[]>([]);
  const [scannerSpotlightMarket, setScannerSpotlightMarket] = useState<Market>("us");

  // Analysis → Conviction: "Build Thesis" pre-fills the belief input
  const [convictionBelief, setConvictionBelief] = useState("");

  function handleSelectFromScanner(market: Market, ticker: string) {
    // Open in the Market tab's analysis panel (no extra tab switch needed now)
    setJumpTo({ market, ticker });
    setTab("gainers");
  }

  function handleFindMoving(tickers: string[], market: Market) {
    // Radar → Market tab, catalyst view with spotlight
    setScannerSpotlight(tickers);
    setScannerSpotlightMarket(market);
    setTab("gainers");
  }

  function handleBuildThesis(belief: string) {
    setConvictionBelief(belief);
    setTab("conviction");
  }

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex flex-col h-screen bg-gray-50">
        <Header activeTab={tab} onTabChange={setTab} />

        {tab === "gainers" && (
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
        {tab === "radar" && (
          <RadarPage onFindMoving={handleFindMoving} />
        )}
        {tab === "conviction" && (
          <ConvictionPage initialBelief={convictionBelief} onBeliefConsumed={() => setConvictionBelief("")} />
        )}
        {tab === "portfolio" && <PortfolioPage />}
        {tab === "glossary"  && <GlossaryPage />}
      </div>
    </QueryClientProvider>
  );
}
