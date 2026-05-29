import { Flame, Lightbulb, TrendingUp, Zap } from "lucide-react";
import type { Period, QualityLabel, SignalTier, StockGainer } from "../types";

const PERIOD_SUFFIX: Record<string, string> = { "1d": "", "1w": " 1W", "1m": " 1M" };

interface Props {
  gainer: StockGainer;
  isSelected: boolean;
  isLoading: boolean;
  period?: Period;
  onClick: () => void;
  onPrefetch?: () => void;
  /** Theme labels of saved conviction theses that include this ticker */
  convictionThemes?: string[];
}

function formatVolume(vol: number): string {
  if (vol >= 1e9) return `${(vol / 1e9).toFixed(1)}B`;
  if (vol >= 1e6) return `${(vol / 1e6).toFixed(1)}M`;
  return `${(vol / 1e3).toFixed(0)}K`;
}

const QUALITY_STYLES: Record<QualityLabel, string> = {
  Strong:   "bg-emerald-100 text-emerald-700 border-emerald-200",
  Moderate: "bg-blue-50 text-blue-600 border-blue-200",
  Watch:    "bg-amber-50 text-amber-600 border-amber-200",
  Risky:    "bg-red-50 text-red-500 border-red-200",
};

const TIER_CONFIG: Record<SignalTier, { label: string; style: string; icon: React.ReactNode }> = {
  confirmed: {
    label: "Confirmed",
    style: "bg-green-100 text-green-700 border-green-200",
    icon: <Flame size={10} className="shrink-0" />,
  },
  catalyst: {
    label: "Catalyst",
    style: "bg-indigo-100 text-indigo-700 border-indigo-200",
    icon: <Zap size={10} className="shrink-0" />,
  },
  mover: {
    label: "Mover",
    style: "bg-gray-100 text-gray-500 border-gray-200",
    icon: <TrendingUp size={10} className="shrink-0" />,
  },
};

export function GainerCard({ gainer, isSelected, isLoading, period = "1d", onClick, onPrefetch, convictionThemes }: Props) {
  const currency = gainer.market === "india" ? "₹" : "$";
  const qualityStyle = gainer.quality_label ? QUALITY_STYLES[gainer.quality_label] : "";
  const tier = gainer.signal_tier ?? "mover";
  const tierConfig = TIER_CONFIG[tier];

  return (
    <button
      onClick={onClick}
      onMouseEnter={onPrefetch}
      className={[
        "w-full text-left rounded-xl border p-4 transition-all duration-150",
        "hover:shadow-md hover:border-green-300",
        isSelected
          ? "border-green-500 bg-green-50 shadow-md ring-1 ring-green-400"
          : "border-gray-200 bg-white",
        isLoading ? "opacity-70 cursor-wait" : "cursor-pointer",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-gray-900 text-sm">{gainer.ticker}</span>
            <span className={`flex items-center gap-1 text-xs px-1.5 py-0.5 rounded border font-semibold ${tierConfig.style}`}>
              {tierConfig.icon}
              {tierConfig.label}
            </span>
            {gainer.quality_label && (
              <span className={`text-xs px-1.5 py-0.5 rounded border font-medium ${qualityStyle}`}>
                {gainer.quality_label}
                {gainer.quality_score != null && (
                  <span className="ml-1 opacity-70">{gainer.quality_score.toFixed(1)}</span>
                )}
              </span>
            )}
            {gainer.sector && (
              <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                {gainer.sector}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{gainer.name !== gainer.ticker ? gainer.name : ""}</p>
        </div>

        <div className="flex items-center gap-1 shrink-0 bg-green-100 text-green-700 font-bold text-sm px-2 py-1 rounded-lg">
          <TrendingUp size={13} />
          <span>+{gainer.change_pct.toFixed(1)}%{PERIOD_SUFFIX[period]}</span>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
        <span>
          {currency}{gainer.price.toLocaleString()}
          <span className="text-green-600 ml-1">(+{currency}{gainer.change_abs.toFixed(2)})</span>
        </span>
        <span>Vol {formatVolume(gainer.volume)}</span>
      </div>

      {convictionThemes && convictionThemes.length > 0 && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-indigo-600 bg-indigo-50 rounded-lg px-2 py-1">
          <Lightbulb size={11} className="shrink-0" />
          <span className="truncate">Your thesis: {convictionThemes[0]}</span>
        </div>
      )}

      {isLoading && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-green-600">
          <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          Analysing with AI…
        </div>
      )}
    </button>
  );
}
