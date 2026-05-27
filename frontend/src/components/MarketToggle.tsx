import type { Market } from "../types";

interface Props {
  market: Market;
  onChange: (market: Market) => void;
}

export function MarketToggle({ market, onChange }: Props) {
  return (
    <div className="flex rounded-lg border border-gray-200 overflow-hidden">
      {(["us", "india"] as Market[]).map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={[
            "px-5 py-2 text-sm font-medium transition-colors",
            market === m
              ? "bg-gray-900 text-white"
              : "bg-white text-gray-600 hover:bg-gray-50",
          ].join(" ")}
        >
          {m === "us" ? "🇺🇸 US" : "🇮🇳 India"}
        </button>
      ))}
    </div>
  );
}
