import {
  ArrowLeftRight, BookOpen, Layers, Lightbulb, Microscope,
  Radio, ScanSearch, Sparkles, Target, TrendingUp,
} from "lucide-react";
import type { ReactNode } from "react";
import type { AppMode } from "../App";

interface HeaderProps {
  mode: AppMode;
  onModeChange: (mode: AppMode) => void;
  activeSubTab: string;
  onSubTabChange: (key: string) => void;
  guideOpen: boolean;
  onToggleGuide: () => void;
}

interface SubTab {
  key: string;
  label: string;
  icon: ReactNode;
}

const FUNDS_TABS: SubTab[] = [
  { key: "build",   label: "TOP 5",   icon: <Sparkles size={12} /> },
  { key: "scanner", label: "SCANNER", icon: <ScanSearch size={12} /> },
  { key: "compare", label: "COMPARE", icon: <ArrowLeftRight size={12} /> },
  { key: "analyse", label: "ANALYSE", icon: <Microscope size={12} /> },
];

const STOCKS_TABS: SubTab[] = [
  { key: "gainers",    label: "MARKET", icon: <TrendingUp size={12} /> },
  { key: "radar",      label: "RADAR",  icon: <Radio size={12} /> },
  { key: "conviction", label: "THESIS", icon: <Lightbulb size={12} /> },
  { key: "portfolio",  label: "PLAYS",  icon: <Target size={12} /> },
];

export function Header({
  mode, onModeChange, activeSubTab, onSubTabChange, guideOpen, onToggleGuide,
}: HeaderProps) {
  const subTabs = mode === "funds" ? FUNDS_TABS : STOCKS_TABS;

  return (
    <header className="border-b border-gray-200 bg-white shrink-0">

      {/* ── Row 1: brand · mode switch · guide ───────────────────────────────── */}
      <div className="px-4 md:px-6 py-2.5 flex items-center justify-between gap-4">

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

        {/* Primary mode switch — Funds is home, Stocks one tap away */}
        <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-xl">
          <ModeButton
            active={mode === "funds" && !guideOpen}
            icon={<Layers size={13} />}
            label="Funds"
            sub="ETFs & MFs"
            onClick={() => onModeChange("funds")}
          />
          <ModeButton
            active={mode === "stocks" && !guideOpen}
            icon={<TrendingUp size={13} />}
            label="Stocks"
            sub="Movers & ideas"
            onClick={() => onModeChange("stocks")}
          />
        </div>

        {/* Guide corner icon */}
        <button
          onClick={onToggleGuide}
          title="Glossary — every term explained"
          className={[
            "flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold rounded-lg transition-all shrink-0",
            guideOpen
              ? "bg-indigo-600 text-white"
              : "text-gray-500 hover:text-gray-700 hover:bg-gray-100",
          ].join(" ")}
        >
          <BookOpen size={14} />
          <span className="hidden md:inline">Guide</span>
        </button>
      </div>

      {/* ── Row 2: sub-tabs for the active mode ──────────────────────────────── */}
      <div className="px-4 md:px-6 pb-2 flex items-center gap-0.5 overflow-x-auto">
        {subTabs.map(({ key, label, icon }) => {
          const isActive = !guideOpen && activeSubTab === key;
          return (
            <button
              key={key}
              onClick={() => onSubTabChange(key)}
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

// ── Mode switch button ──────────────────────────────────────────────────────

function ModeButton({
  active, icon, label, sub, onClick,
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  sub: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all",
        active ? "bg-white shadow-sm" : "hover:bg-white/50",
      ].join(" ")}
    >
      <span className={active ? "text-gray-900" : "text-gray-400"}>{icon}</span>
      <span className="text-left leading-tight">
        <span className={`block text-xs font-bold ${active ? "text-gray-900" : "text-gray-500"}`}>
          {label}
        </span>
        <span className="hidden sm:block text-[9px] text-gray-400">{sub}</span>
      </span>
    </button>
  );
}
