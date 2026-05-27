import { Search, X } from "lucide-react";
import { useRef, useState } from "react";

interface Props {
  market: "us" | "india";
  onSearch: (ticker: string) => void;
  onClear: () => void;
  isSearching: boolean;
}

export function SearchBar({ market, onSearch, onClear, isSearching }: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const ticker = value.trim().toUpperCase();
    if (ticker.length < 1) return;
    onSearch(ticker);
  }

  function handleClear() {
    setValue("");
    onClear();
    inputRef.current?.focus();
  }

  const placeholder = market === "india" ? "Search NSE ticker e.g. RELIANCE" : "Search ticker e.g. NVDA";

  return (
    <form onSubmit={handleSubmit} className="px-3 py-2 border-b border-gray-100 bg-white">
      <div className="relative flex items-center">
        <Search
          size={14}
          className={`absolute left-3 ${isSearching ? "text-green-500 animate-pulse" : "text-gray-400"}`}
        />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value.toUpperCase())}
          placeholder={placeholder}
          className="w-full pl-8 pr-8 py-2 text-sm bg-gray-50 border border-gray-200 rounded-lg
                     focus:outline-none focus:ring-2 focus:ring-green-400 focus:border-transparent
                     placeholder:text-gray-400 uppercase tracking-wide"
          maxLength={10}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
        />
        {value && (
          <button
            type="button"
            onClick={handleClear}
            className="absolute right-2 p-1 text-gray-400 hover:text-gray-600 rounded"
          >
            <X size={13} />
          </button>
        )}
      </div>
      {value && (
        <p className="text-xs text-gray-400 mt-1 px-1">
          Press Enter to analyse <span className="font-bold text-gray-600">{value}</span>
        </p>
      )}
    </form>
  );
}
