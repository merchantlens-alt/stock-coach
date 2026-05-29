import { Lightbulb, Loader2, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ThesisCard } from "../components/ThesisCard";
import { useConvictionAnalysis } from "../hooks/useConviction";
import type { Market, ThesisConviction } from "../types";

const EXAMPLE_BELIEFS = [
  "I believe AI will drive massive memory chip demand",
  "I think India's infrastructure boom has years to run",
  "Nuclear energy is coming back as clean baseload power",
  "Obesity drugs will transform healthcare and food spending",
  "Autonomous vehicles will reshape insurance and mapping",
];

interface SavedThesis {
  belief: string;
  conviction: ThesisConviction;
  savedAt: string;
}

function loadSaved(): SavedThesis[] {
  try {
    return JSON.parse(localStorage.getItem("conviction_theses") || "[]");
  } catch {
    return [];
  }
}

function saveToDB(theses: SavedThesis[]) {
  localStorage.setItem("conviction_theses", JSON.stringify(theses.slice(0, 10)));
}

interface ConvictionPageProps {
  /** Pre-filled belief from Analysis Panel "Build Thesis" button */
  initialBelief?: string;
  /** Called once the pre-fill has been consumed so App can clear it */
  onBeliefConsumed?: () => void;
}

export function ConvictionPage({ initialBelief = "", onBeliefConsumed }: ConvictionPageProps = {}) {
  const [belief, setBelief] = useState(initialBelief);
  const [market, setMarket] = useState<Market>("us");
  const [saved, setSaved] = useState<SavedThesis[]>(loadSaved);
  const [activeTab, setActiveTab] = useState<"new" | "saved">("new");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // When App sends a new pre-fill (user navigated from Analysis Panel)
  useEffect(() => {
    if (initialBelief) {
      setBelief(initialBelief);
      onBeliefConsumed?.();
      // Auto-focus so user can immediately edit/submit
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialBelief]);

  const mutation = useConvictionAnalysis();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = belief.trim();
    if (!trimmed || mutation.isPending) return;
    mutation.mutate({ belief: trimmed, market }, {
      onSuccess: (data) => {
        const entry: SavedThesis = {
          belief: trimmed,
          conviction: data.conviction,
          savedAt: new Date().toISOString(),
        };
        const updated = [entry, ...saved.filter(s => s.belief !== trimmed)];
        setSaved(updated);
        saveToDB(updated);
        setActiveTab("saved");
      },
    });
  }

  function handleExample(text: string) {
    setBelief(text);
    inputRef.current?.focus();
  }

  function handleRemove(belief: string) {
    const updated = saved.filter(s => s.belief !== belief);
    setSaved(updated);
    saveToDB(updated);
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Stacked on mobile, side-by-side on desktop */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">

        {/* Left: belief input panel — capped at 55vh on mobile so results are visible below */}
        <div className="max-h-[55vh] md:max-h-none md:w-[420px] lg:w-[460px] shrink-0 flex flex-col border-b md:border-b-0 md:border-r border-gray-200 bg-white">
          <div className="px-5 py-4 border-b border-gray-100 bg-gray-50">
            <div className="flex items-center gap-2 mb-1">
              <Lightbulb size={16} className="text-indigo-500" />
              <h2 className="text-sm font-bold text-gray-900">Conviction Builder</h2>
            </div>
            <p className="text-xs text-gray-500">
              State a belief about the world. AI maps it to stocks, checks if evidence backs it,
              and tells you when to enter or exit.
            </p>
          </div>

          <div className="flex-1 overflow-y-auto">
            {/* Input form */}
            <form onSubmit={handleSubmit} className="px-5 pt-5 pb-4">
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Your belief
              </label>
              <textarea
                ref={inputRef}
                value={belief}
                onChange={e => setBelief(e.target.value)}
                placeholder="I believe that…"
                rows={3}
                className="w-full px-3 py-2.5 text-sm text-gray-800 placeholder-gray-400 border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
                disabled={mutation.isPending}
              />

              {/* Market selector */}
              <div className="mt-3 flex items-center gap-2">
                <span className="text-xs text-gray-500 shrink-0">Market:</span>
                <div className="flex rounded-lg overflow-hidden border border-gray-200 text-xs">
                  {(["us", "india"] as Market[]).map(m => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setMarket(m)}
                      className={`px-3 py-1.5 font-medium transition-colors ${
                        market === m ? "bg-gray-900 text-white" : "text-gray-500 hover:bg-gray-50"
                      }`}
                    >
                      {m === "us" ? "🇺🇸 US" : "🇮🇳 India"}
                    </button>
                  ))}
                </div>
              </div>

              <button
                type="submit"
                disabled={!belief.trim() || mutation.isPending}
                className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 text-white text-sm font-semibold rounded-xl hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {mutation.isPending ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    Analysing thesis…
                  </>
                ) : (
                  <>
                    <Sparkles size={15} />
                    Build thesis
                  </>
                )}
              </button>

              {mutation.isError && (
                <p className="mt-2 text-xs text-red-500 text-center">{mutation.error.message}</p>
              )}
            </form>

            {/* Example beliefs */}
            <div className="px-5 pb-5">
              <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
                Example beliefs
              </p>
              <div className="space-y-1.5">
                {EXAMPLE_BELIEFS.map(b => (
                  <button
                    key={b}
                    type="button"
                    onClick={() => handleExample(b)}
                    className="w-full text-left px-3 py-2 text-xs text-gray-600 bg-gray-50 hover:bg-indigo-50 hover:text-indigo-700 rounded-lg transition-colors border border-transparent hover:border-indigo-100"
                  >
                    {b}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Right: thesis results — min-h-0 prevents flex-1 overflowing in flex-col on mobile */}
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden bg-gray-50">
          {/* Tabs: new result / saved */}
          {saved.length > 0 && (
            <div className="px-5 py-3 border-b border-gray-200 bg-white flex items-center gap-1">
              <button
                onClick={() => setActiveTab("new")}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                  activeTab === "new"
                    ? "bg-indigo-600 text-white"
                    : "text-gray-500 hover:bg-gray-100"
                }`}
              >
                Latest result
              </button>
              <button
                onClick={() => setActiveTab("saved")}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                  activeTab === "saved"
                    ? "bg-indigo-600 text-white"
                    : "text-gray-500 hover:bg-gray-100"
                }`}
              >
                Saved theses ({saved.length})
              </button>
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-5">
            {/* Loading state */}
            {mutation.isPending && (
              <div className="flex flex-col items-center justify-center h-48 text-center">
                <div className="w-10 h-10 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin mb-3" />
                <p className="text-sm font-medium text-gray-600">Building your conviction thesis…</p>
                <p className="text-xs text-gray-400 mt-1">AI is mapping your belief to instruments · 10-15 sec</p>
              </div>
            )}

            {/* Latest result (new tab) */}
            {!mutation.isPending && activeTab === "new" && mutation.data && (
              <ThesisCard conviction={mutation.data.conviction} />
            )}

            {/* Saved theses list */}
            {!mutation.isPending && activeTab === "saved" && saved.length > 0 && (
              <div className="space-y-6">
                {saved.map(s => (
                  <div key={s.belief} className="relative group">
                    <ThesisCard conviction={s.conviction} />
                    <button
                      onClick={() => handleRemove(s.belief)}
                      className="absolute top-3 right-3 text-[10px] text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity bg-white rounded px-1.5 py-0.5 border border-gray-200"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Empty state */}
            {!mutation.isPending && !mutation.data && saved.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center text-gray-400 py-20">
                <Lightbulb size={36} className="text-indigo-200 mb-3" />
                <p className="text-sm font-medium text-gray-600">State your first belief</p>
                <p className="text-xs mt-1 text-gray-400 max-w-xs">
                  Tell the AI what you believe will happen in the world —
                  it will map that to specific stocks and tell you what evidence to watch.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
