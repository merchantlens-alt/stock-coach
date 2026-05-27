import { Brain, Eye, TrendingUp } from "lucide-react";
import type { MarketSentiment, MarketSummary } from "../types";

interface Props {
  summary: MarketSummary;
}

const SENTIMENT_STYLES: Record<MarketSentiment, { bar: string; text: string; label: string }> = {
  very_bullish: { bar: "bg-emerald-500", text: "text-emerald-700", label: "Very Bullish" },
  bullish:      { bar: "bg-green-400",   text: "text-green-700",   label: "Bullish" },
  mixed:        { bar: "bg-amber-400",   text: "text-amber-700",   label: "Mixed" },
  bearish:      { bar: "bg-orange-400",  text: "text-orange-700",  label: "Bearish" },
  very_bearish: { bar: "bg-red-500",     text: "text-red-700",     label: "Very Bearish" },
};

export function MarketNarrative({ summary }: Props) {
  const s = SENTIMENT_STYLES[summary.sentiment];

  return (
    <div className="mx-3 mt-3 rounded-xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-white p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain size={15} className="text-indigo-500" />
          <span className="text-xs font-semibold text-indigo-700 uppercase tracking-wide">AI Market Pulse</span>
        </div>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${s.text} border-current bg-white`}>
          {s.label}
        </span>
      </div>

      {/* Narrative */}
      <p className="text-sm text-gray-700 leading-relaxed">{summary.narrative}</p>

      {/* Themes */}
      {summary.themes.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {summary.themes.map((theme, i) => (
            <span key={i} className="flex items-center gap-1 text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">
              <TrendingUp size={10} />
              {theme}
            </span>
          ))}
        </div>
      )}

      {/* Watch list */}
      {summary.watch_list.length > 0 && (
        <div className="rounded-lg bg-amber-50 border border-amber-100 p-2.5">
          <div className="flex items-center gap-1.5 mb-1">
            <Eye size={12} className="text-amber-600" />
            <span className="text-xs font-semibold text-amber-700">Watch next</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-1">
            {summary.watch_list.map((ticker) => (
              <span key={ticker} className="text-xs font-bold bg-white border border-amber-200 text-amber-700 px-1.5 py-0.5 rounded">
                {ticker}
              </span>
            ))}
          </div>
          <p className="text-xs text-amber-600">{summary.watch_reason}</p>
        </div>
      )}
    </div>
  );
}
