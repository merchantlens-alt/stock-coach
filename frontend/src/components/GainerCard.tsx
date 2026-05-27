import { TrendingUp } from "lucide-react";
import type { StockGainer } from "../types";

interface Props {
  gainer: StockGainer;
  isSelected: boolean;
  isLoading: boolean;
  onClick: () => void;
}

function formatMarketCap(cap?: number): string {
  if (!cap) return "—";
  if (cap >= 1e12) return `$${(cap / 1e12).toFixed(1)}T`;
  if (cap >= 1e9) return `$${(cap / 1e9).toFixed(1)}B`;
  return `$${(cap / 1e6).toFixed(0)}M`;
}

function formatVolume(vol: number): string {
  if (vol >= 1e9) return `${(vol / 1e9).toFixed(1)}B`;
  if (vol >= 1e6) return `${(vol / 1e6).toFixed(1)}M`;
  return `${(vol / 1e3).toFixed(0)}K`;
}

export function GainerCard({ gainer, isSelected, isLoading, onClick }: Props) {
  const currency = gainer.market === "india" ? "₹" : "$";

  return (
    <button
      onClick={onClick}
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
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-bold text-gray-900 text-sm">{gainer.ticker}</span>
            {gainer.sector && (
              <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                {gainer.sector}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{gainer.name}</p>
        </div>

        <div className="flex items-center gap-1 shrink-0 bg-green-100 text-green-700 font-bold text-sm px-2 py-1 rounded-lg">
          <TrendingUp size={13} />
          <span>+{gainer.change_pct.toFixed(1)}%</span>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
        <span>
          {currency}
          {gainer.price.toLocaleString()}
          <span className="text-green-600 ml-1">
            (+{currency}
            {gainer.change_abs.toFixed(2)})
          </span>
        </span>
        <div className="flex gap-3">
          <span>Vol {formatVolume(gainer.volume)}</span>
          <span>{formatMarketCap(gainer.market_cap)}</span>
        </div>
      </div>

      {isLoading && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-green-600">
          <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          Analysing with AI…
        </div>
      )}
    </button>
  );
}
