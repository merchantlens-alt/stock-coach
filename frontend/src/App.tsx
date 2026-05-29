import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Header } from "./components/Header";
import { Dashboard } from "./pages/Dashboard";
import { ConvictionPage } from "./pages/ConvictionPage";
import { RadarPage } from "./pages/RadarPage";

export type AppTab = "pulse" | "radar" | "conviction";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  const [tab, setTab] = useState<AppTab>("pulse");

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex flex-col h-screen bg-gray-50">
        <Header activeTab={tab} onTabChange={setTab} />
        {tab === "pulse" ? (
          <Dashboard />
        ) : tab === "radar" ? (
          <RadarPage />
        ) : (
          <ConvictionPage />
        )}
      </div>
    </QueryClientProvider>
  );
}
