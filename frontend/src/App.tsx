import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Header } from "./components/Header";
import { Dashboard } from "./pages/Dashboard";
import { ConvictionPage } from "./pages/ConvictionPage";

type AppTab = "pulse" | "conviction";

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
        {tab === "pulse" ? <Dashboard /> : <ConvictionPage />}
      </div>
    </QueryClientProvider>
  );
}
