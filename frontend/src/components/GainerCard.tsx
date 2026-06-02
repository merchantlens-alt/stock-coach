import { ArrowDown, ArrowUp, Flame, Lightbulb, TrendingUp, Zap } from "lucide-react";
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

/** Volume heat: dots showing how unusual the volume is */
function VolumeHeat({ ratio }: { ratio: number }) {
  const full  = ratio >= 4 ? 3 : ratio >= 2.5 ? 2 : ratio >= 1.5 ? 1 : 0;
  const color = full >= 3 ? "bg-orange-500" : full >= 2 ? "bg-amber-400" : full >= 1 ? "bg-yellow-300" : "bg-gray-200";
  return (
    <span className="flex items-center gap-0.5" title={`${ratio.toFixed(1)}× average volume`}>
      {[0, 1, 2].map(i => (
        <span key={i} className={`w-1.5 h-1.5 rounded-full ${i < full ? color : "bg-gray-200"}`} />
      ))}
    </span>
  );
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
  const currency    = gainer.market === "india" ? "₹" : "$";
  const qualityStyle = gainer.quality_label ? QUALITY_STYLES[gainer.quality_label] : "";
  const tier        = gainer.signal_tier ?? "mover";
  const tierConfig  = TIER_CONFIG[tier];
  const isDown      = gainer.change_pct < 0;

  // Volume ratio: current vol / avg vol
  const volRatio = gainer.avg_volume && gainer.avg_volume > 0
    ? gainer.volume / gainer.avg_volume
    : null;

  const hasPrediction = gainer.ai_prediction_pct != null;
  const predPositive  = (gainer.ai_prediction_pct ?? 0) >= 0;

  return (
    <button
      onClick={onClick}
      onMouseEnter={onPrefetch}
      className={[
        "w-full text-left rounded-xl border transition-all duration-150",
        "hover:shadow-md",
        isSelected
          ? "border-indigo-400 bg-indigo-50 shadow-md ring-1 ring-indigo-300"
          : isDown
          ? "border-gray-200 bg-white hover:border-red-200"
          : "border-gray-200 bg-white hover:border-green-300",
        isLoading ? "opacity-70 cursor-wait" : "cursor-pointer",
      ].join(" ")}
    >
      {/* ── Main content ─────────────────────────────────────────────── */}
      <div className="px-3.5 pt-3 pb-2.5">
        {/* Row 1: Ticker + tier + change% */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-bold text-gray-900 text-sm">{gainer.ticker}</span>
              <span className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border font-semibold ${tierConfig.style}`}>
                {tierConfig.icon}
                {tierConfig.label}
              </span>
              {gainer.quality_label && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${qualityStyle}`}>
                  {gainer.quality_label}
                </span>
              )}
            </div>
            <p className="text-[11px] text-gray-400 mt-0.5 truncate">
              {gainer.name !== gainer.ticker ? gainer.name : ""}
              {gainer.sector && (
                <span className="ml-1.5 text-gray-300">· {gainer.sector}</span>
              )}
            </p>
          </div>

          {/* Change % badge */}
          <div className={`flex items-center gap-1 shrink-0 font-bold text-sm px-2.5 py-1.5 rounded-lg ${
            isDown
              ? "bg-red-50 text-red-600"
              : "bg-green-100 text-green-700"
          }`}>
            {isDown ? <ArrowDown size={12} /> : <TrendingUp size={12} />}
            <span>
              {isDown ? "" : "+"}{gainer.change_pct.toFixed(1)}%{PERIOD_SUFFIX[period]}
            </span>
          </div>
        </div>

        {/* Row 2: Price + volume + volume ratio heat */}
        <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
          <span className="font-medium text-gray-700">
            {currency}{gainer.price.toLocaleString()}
          </span>
          <span className="text-gray-300">·</span>
          <span>Vol {formatVolume(gainer.volume)}</span>
          {volRatio != null && volRatio >= 1.2 && (
            <>
              <span className="text-gray-300">·</span>
              <span className={`flex items-center gap-1 font-semibold ${
                volRatio >= 4 ? "text-orange-600" :
                volRatio >= 2.5 ? "text-amber-600" :
                "text-yellow-600"
              }`}>
                <VolumeHeat ratio={volRatio} />
                <span>{volRatio.toFixed(1)}× avg</span>
              </span>
            </>
          )}
        </div>
      </div>

      {/* ── AI Prediction strip ───────────────────────────────────────── */}
      {hasPrediction && (
        <div className={`flex items-center gap-2 px-3.5 py-2 border-t text-xs font-semibold ${
          predPositive
            ? "bg-emerald-50 border-emerald-100 text-emerald-700"
            : "bg-red-50 border-red-100 text-red-600"
        }`}>
          {predPositive
            ? <ArrowUp size={11} className="shrink-0" />
            : <ArrowDown size={11} className="shrink-0" />
          }
          <span>
            AI 30d: {predPositive ? "+" : ""}{gainer.ai_prediction_pct!.toFixed(1)}%
          </span>
          {gainer.ai_prediction_confidence != null && (
            <span className="font-normal opacity-60">
              · {Math.round(gainer.ai_prediction_confidence * 100)}% conf
            </span>
          )}
          <span className="ml-auto text-[10px] font-normal opacity-50">30-day outlook</span>
        </div>
      )}

      {/* ── Conviction thesis tag ─────────────────────────────────────── */}
      {convictionThemes && convictionThemes.length > 0 && (
        <div className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs text-indigo-600 bg-indigo-50 ${
          hasPrediction ? "" : "border-t border-indigo-100"
        }`}>
          <Lightbulb size={10} className="shrink-0" />
          <span className="truncate">Your thesis: {convictionThemes[0]}</span>
        </div>
      )}

      {/* ── Loading indicator ─────────────────────────────────────────── */}
      {isLoading && (
        <div className="px-3.5 py-2 flex items-center gap-1.5 text-xs text-indigo-600 bg-indigo-50 border-t border-indigo-100">
          <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          Analysing with AI…
        </div>
      )}
    </button>
  );
}
