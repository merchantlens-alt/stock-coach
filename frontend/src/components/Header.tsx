import {
  BookOpen, Layers, LayoutDashboard, Lightbulb, LogOut, Target, TrendingUp, UserCircle,
} from "lucide-react";
import type { ReactNode } from "react";
import { useInvestorProfile } from "../hooks/useAdvisor";
import type { AppTab } from "../App";

interface HeaderProps {
  activeTab: AppTab;
  onTabChange: (tab: AppTab) => void;
  guideOpen: boolean;
  onToggleGuide: () => void;
  profileOpen: boolean;
  onToggleProfile: () => void;
  username: string;
  onLogout: () => void;
}

interface Tab {
  key: AppTab;
  label: string;
  icon: ReactNode;
}

const TABS: Tab[] = [
  { key: "plan",    label: "PLAN",    icon: <LayoutDashboard size={12} /> },
  { key: "stocks",  label: "STOCKS",  icon: <TrendingUp size={12} /> },
  { key: "funds",   label: "FUNDS",   icon: <Layers size={12} /> },
  { key: "thesis",  label: "THESIS",  icon: <Lightbulb size={12} /> },
  { key: "tracker", label: "TRACKER", icon: <Target size={12} /> },
];

export function Header({
  activeTab, onTabChange, guideOpen, onToggleGuide, profileOpen, onToggleProfile,
  username, onLogout,
}: HeaderProps) {
  const { data: profile } = useInvestorProfile();

  return (
    <header className="border-b border-gray-200 bg-white shrink-0">

      {/* ── Row 1: brand · profile + guide ───────────────────────────────── */}
      <div className="px-4 md:px-6 py-2.5 flex items-center justify-between gap-4">

        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-green-600 flex items-center justify-center shrink-0">
            <TrendingUp size={16} className="text-white" />
          </div>
          <div className="hidden sm:block">
            <h1 className="text-sm font-bold text-gray-900 leading-tight">StockCoach AI</h1>
            <p className="text-[11px] text-gray-400">Your wealth advisor</p>
          </div>
        </div>

        {/* Profile + Guide + User */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onToggleProfile}
            title="Investor Profile — personalise every verdict"
            className={[
              "relative flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold rounded-lg transition-all",
              profileOpen
                ? "bg-indigo-600 text-white"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-100",
            ].join(" ")}
          >
            <UserCircle size={14} />
            <span className="hidden md:inline">Profile</span>
            {!profile && !profileOpen && (
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-amber-400 rounded-full" />
            )}
          </button>
          <button
            onClick={onToggleGuide}
            title="Glossary — every term explained"
            className={[
              "flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold rounded-lg transition-all",
              guideOpen
                ? "bg-indigo-600 text-white"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-100",
            ].join(" ")}
          >
            <BookOpen size={14} />
            <span className="hidden md:inline">Guide</span>
          </button>
          <div className="hidden sm:flex items-center gap-1 ml-1 pl-2 border-l border-gray-200">
            <span className="text-xs text-gray-500 font-medium">{username}</span>
            <button
              onClick={onLogout}
              title="Sign out"
              className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all"
            >
              <LogOut size={13} />
            </button>
          </div>
        </div>
      </div>

      {/* ── Row 2: flat tab bar ───────────────────────────────────────────── */}
      <div className="px-4 md:px-6 pb-2 flex items-center gap-0.5 overflow-x-auto">
        {TABS.map(({ key, label, icon }) => {
          const isActive = !guideOpen && !profileOpen && activeTab === key;
          return (
            <button
              key={key}
              onClick={() => onTabChange(key)}
              className={[
                "flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all whitespace-nowrap",
                isActive
                  ? "bg-gray-900 text-white shadow-sm"
                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-100",
              ].join(" ")}
            >
              {icon}
              {label}
            </button>
          );
        })}
      </div>
    </header>
  );
}
