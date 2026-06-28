import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { onUnauthenticated } from "./api/client";
import { api } from "./api/client";
import { Header } from "./components/Header";
import { AllocationPlanPage } from "./pages/AllocationPlanPage";
import { AuthPage } from "./pages/AuthPage";
import { ConvictionPage } from "./pages/ConvictionPage";
import { Dashboard } from "./pages/Dashboard";
import { FundsPage } from "./pages/FundsPage";
import { GlossaryPage } from "./pages/GlossaryPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SectorsPage } from "./pages/SectorsPage";
import { useAuth } from "./hooks/useAuth";
import type { Market } from "./types";

// Single flat tab — no Funds/Stocks mode split.
export type AppTab = "plan" | "stocks" | "sectors" | "funds" | "thesis" | "tracker";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

// Inner app — needs to be inside QueryClientProvider so it can call hooks
function AppInner({ username, onLogout }: { username: string; onLogout: () => void }) {
  // Land on SECTORS by default — the allocation plan (expensive AI call) only
  // fetches when the user actually navigates to the PLAN tab, since that page
  // is conditionally mounted and its query is gated behind the mount.
  const [tab, setTab]                 = useState<AppTab>("sectors");
  const [guideOpen, setGuideOpen]     = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

  // Cross-tab navigation
  const [jumpTo, setJumpTo]               = useState<{ market: Market; ticker: string } | null>(null);
  const [convictionBelief, setConvictionBelief] = useState("");

  // Auto-open profile wizard if no profile is set (first-time user)
  const { data: profile, isError: profileMissing } = useQuery({
    queryKey: ["investor-profile"],
    queryFn: () => api.getInvestorProfile(),
    retry: false,
    staleTime: 5 * 60_000,
  });
  const autoOpenedRef = useRef(false);
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (profile || profileMissing) {
      if (!profile) {
        autoOpenedRef.current = true;
        setProfileOpen(true);
      }
    }
  }, [profile, profileMissing]);

  function closeOverlays() {
    setGuideOpen(false);
    setProfileOpen(false);
  }

  function handleTabChange(next: AppTab) {
    closeOverlays();
    setTab(next);
  }

  function handleBuildThesis(belief: string) {
    setConvictionBelief(belief);
    closeOverlays();
    setTab("thesis");
  }

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      <Header
        activeTab={tab}
        onTabChange={handleTabChange}
        guideOpen={guideOpen}
        onToggleGuide={() => { setProfileOpen(false); setGuideOpen(o => !o); }}
        profileOpen={profileOpen}
        onToggleProfile={() => { setGuideOpen(false); setProfileOpen(o => !o); }}
        username={username}
        onLogout={onLogout}
      />

      {/* Overlays */}
      {profileOpen ? (
        <ProfilePage
          onClose={() => setProfileOpen(false)}
          onProfileSaved={() => { setProfileOpen(false); setTab("plan"); }}
        />
      ) : guideOpen ? (
        <GlossaryPage />
      ) : tab === "plan" ? (
        <AllocationPlanPage onSetupProfile={() => setProfileOpen(true)} />
      ) : tab === "stocks" ? (
        <Dashboard
          jumpTo={jumpTo}
          onJumpConsumed={() => setJumpTo(null)}
          onBuildThesis={handleBuildThesis}
          onSetupProfile={() => setProfileOpen(true)}
        />
      ) : tab === "sectors" ? (
        <SectorsPage />
      ) : tab === "funds" ? (
        <FundsPage />
      ) : tab === "thesis" ? (
        <ConvictionPage
          initialBelief={convictionBelief}
          onBeliefConsumed={() => setConvictionBelief("")}
        />
      ) : (
        <PortfolioPage />
      )}
    </div>
  );
}

function AuthGate() {
  const { isAuthenticated, username, login, register, logout } = useAuth();

  // Force re-render when a 401 clears the token mid-session
  const [, setTick] = useState(0);
  useEffect(() => {
    onUnauthenticated(() => setTick((n) => n + 1));
  }, []);

  if (!isAuthenticated) {
    return <AuthPage onLogin={login} onRegister={register} />;
  }

  return <AppInner username={username ?? ""} onLogout={logout} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate />
    </QueryClientProvider>
  );
}
