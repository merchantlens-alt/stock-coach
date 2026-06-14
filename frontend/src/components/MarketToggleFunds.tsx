/**
 * MarketToggleFunds — India MF ⇄ US ETF switch for the Funds views.
 * Small segmented control; state lives in FundsPage so it persists across sub-tabs.
 */

import type { Market } from "../types";

interface Props {
  market: Market;
  onChange: (m: Market) => void;
}

const OPTS: { key: Market; label: string; flag: string }[] = [
  { key: "india", label: "India MF", flag: "🇮🇳" },
  { key: "us",    label: "US ETF",   flag: "🇺🇸" },
];

export function MarketToggleFunds({ market, onChange }: Props) {
  return (
    <div className="flex items-center gap-0.5 bg-gray-100 p-0.5 rounded-lg">
      {OPTS.map(o => {
        const active = market === o.key;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className={[
              "flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-md transition-all",
              active ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700",
            ].join(" ")}
          >
            <span>{o.flag}</span>
            <span className="hidden sm:inline">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}
