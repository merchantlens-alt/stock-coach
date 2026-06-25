import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Header } from "./components/Header";
import { ConvictionPage } from "./pages/ConvictionPage";
import { Dashboard } from "./pages/Dashboard";
import { FundsPage } from "./pages/FundsPage";
import { GlossaryPage } from "./pages/GlossaryPage";
import { MegatrendsPage } from "./pages/MegatrendsPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { ProfilePage } from "./pages/ProfilePage";
import type { Market } from "./types";

// Top-level mode: Funds is the primary home; Stocks is one switch away.
// Each mode lazily mounts its own pages, so stock data never fetches until
// the user actually switches into Stocks mode.
export type AppMode   = "funds" | "stocks";
export type FundsTab  = "build" | "scanner" | "compare" | "analyse";
export type StocksTab = "gainers" | "megatrends" | "conviction" | "portfolio";

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
  const [guideOpen, setGuideOpen]     = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

  // ── Cross-tab navigation state (stocks side) ────────────────────────────────

  // Jump to a specific stock from another tab (e.g. Conviction "Analyse")
  const [jumpTo, setJumpTo] = useState<{ market: Market; ticker: string } | null>(null);

  // Analysis → Conviction: "Build Thesis" pre-fills the belief input
  const [convictionBelief, setConvictionBelief] = useState("");

  // Any cross-tab jump lands in Stocks mode on the right sub-tab, closing overlays.
  function toStocks(tab: StocksTab) {
    setGuideOpen(false);
    setProfileOpen(false);
    setMode("stocks");
    setStocksTab(tab);
  }

  function handleBuildThesis(belief: string) {
    setConvictionBelief(belief);
    toStocks("conviction");
  }

  // ── Header callbacks ────────────────────────────────────────────────────────

  const activeSubTab = mode === "funds" ? fundsTab : stocksTab;

  function handleModeChange(next: AppMode) {
    setGuideOpen(false);
    setProfileOpen(false);
    setMode(next);
  }

  function handleSubTabChange(key: string) {
    setGuideOpen(false);
    setProfileOpen(false);
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
          onToggleGuide={() => { setProfileOpen(false); setGuideOpen(o => !o); }}
          profileOpen={profileOpen}
          onToggleProfile={() => { setGuideOpen(false); setProfileOpen(o => !o); }}
        />

        {/* Profile and Guide overlay mode pages while open */}
        {profileOpen ? (
          <ProfilePage
            onClose={() => setProfileOpen(false)}
            onProfileSaved={() => { setMode("stocks"); setStocksTab("gainers"); }}
          />
        ) : guideOpen ? (
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
                onSetupProfile={() => setProfileOpen(true)}
              />
            )}
            {stocksTab === "megatrends" && <MegatrendsPage />}
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
