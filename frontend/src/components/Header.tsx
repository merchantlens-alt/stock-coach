import { Lightbulb, Radio, Target, TrendingUp, Zap } from "lucide-react";
import type { AppTab } from "../App";

interface HeaderProps {
  activeTab: AppTab;
  onTabChange: (tab: AppTab) => void;
}

const TABS: { key: AppTab; label: string; icon: React.ReactNode; sub: string }[] = [
  {
    key:   "scanner",
    label: "SCANNER",
    icon:  <Zap size={12} />,
    sub:   "Moving now",
  },
  {
    key:   "radar",
    label: "THEMES",
    icon:  <Radio size={12} />,
    sub:   "What's building",
  },
  {
    key:   "gainers",
    label: "GAINERS",
    icon:  <TrendingUp size={12} />,
    sub:   "Top movers",
  },
  {
    key:   "conviction",
    label: "THESIS",
    icon:  <Lightbulb size={12} />,
    sub:   "My beliefs",
  },
  {
    key:   "portfolio",
    label: "PLAYS",
    icon:  <Target size={12} />,
    sub:   "My bets",
  },
];

export function Header({ activeTab, onTabChange }: HeaderProps) {
  return (
    <header className="border-b border-gray-200 bg-white px-4 md:px-6 py-3 flex items-center justify-between gap-4 shrink-0">
      {/* Brand */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-green-600 flex items-center justify-center shrink-0">
          <TrendingUp size={16} className="text-white" />
        </div>
        <div className="hidden sm:block">
          <h1 className="text-sm font-bold text-gray-900 leading-tight">StockCoach AI</h1>
          <p className="text-[11px] text-gray-400">Find · Validate · Commit</p>
        </div>
      </div>

      {/* Navigation tabs */}
      <nav className="flex items-center gap-0.5 bg-gray-100 p-1 rounded-xl">
        {TABS.map(({ key, label, icon }) => (
          <button
            key={key}
            onClick={() => onTabChange(key)}
            className={[
              "flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all",
              activeTab === key
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700",
            ].join(" ")}
          >
            {icon}
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </nav>

      {/* Spacer to balance layout */}
      <div className="w-8 sm:w-32" />
    </header>
  );
}
