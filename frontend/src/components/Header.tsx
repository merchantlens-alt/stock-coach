import { TrendingUp } from "lucide-react";

export function Header() {
  return (
    <header className="border-b border-gray-200 bg-white px-6 py-4">
      <div className="max-w-7xl mx-auto flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-green-600 flex items-center justify-center">
          <TrendingUp size={16} className="text-white" />
        </div>
        <div>
          <h1 className="text-base font-bold text-gray-900 leading-tight">StockCoach AI</h1>
          <p className="text-xs text-gray-400">Hybrid signals · movers &amp; catalysts</p>
        </div>
      </div>
    </header>
  );
}
