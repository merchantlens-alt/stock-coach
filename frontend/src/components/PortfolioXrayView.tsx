/**
 * PortfolioXrayView — the Analyse tab.
 *
 * Add your funds (India MF + US ETF, mixed), pick your risk, and get a data-first
 * X-ray: geography & cap allocation, US sector + top-company look-through,
 * redundancy & quality flags, gaps vs your risk target, and an AI summary.
 */

import { AlertTriangle, Loader2, Plus, Search, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFundScan } from "../hooks/useFunds";
import type { AllocSlice, Market, PortfolioXrayResponse, RiskProfile, XrayFundInput } from "../types";

const RISKS: RiskProfile[] = ["conservative", "balanced", "aggressive"];
const FLAG_LABEL: Record<string, string> = { decaying: "Fading", closet: "Closet index", avoid: "Avoid" };

export function PortfolioXrayView() {
  const [risk, setRisk] = useState<RiskProfile>("balanced");
  const [pickerMarket, setPickerMarket] = useState<Market>("india");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<XrayFundInput[]>([]);

  const { data: universe } = useFundScan(pickerMarket);
  const mutation = useMutation({ mutationFn: api.xrayPortfolio });

  const matches = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return [];
    const chosen = new Set(selected.map(f => f.code));
    return (universe?.funds ?? [])
      .filter(f => !chosen.has(f.scheme_code) && f.name.toLowerCase().includes(q))
      .slice(0, 8);
  }, [query, universe, selected]);

  function add(code: string, name: string) {
    setSelected(prev => [...prev, { market: pickerMarket, code, name }]);
    setQuery("");
  }
  function analyse() {
    if (selected.length === 0) return;
    mutation.mutate({ risk, funds: selected });
  }

  const r = mutation.data;

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">
      {/* Controls */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3 space-y-3 shrink-0">
        <div>
          <h2 className="text-sm font-bold text-gray-900">Portfolio X-ray</h2>
          <p className="text-[11px] text-gray-400">Add your India + US funds — see your sectors, companies, gaps & what to do</p>
        </div>

        {/* Risk */}
        <div className="flex gap-1">
          {RISKS.map(rk => (
            <button key={rk} onClick={() => setRisk(rk)}
              className={["flex-1 text-[10px] font-semibold px-2 py-1.5 rounded-lg border capitalize transition-all",
                risk === rk ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-500 border-gray-200"].join(" ")}>
              {rk}
            </button>
          ))}
        </div>

        {/* Picker with market sub-toggle */}
        <div className="flex gap-2">
          <div className="flex items-center gap-0.5 bg-gray-100 p-0.5 rounded-lg shrink-0">
            {(["india", "us"] as Market[]).map(m => (
              <button key={m} onClick={() => { setPickerMarket(m); setQuery(""); }}
                className={["px-2 py-1 text-[11px] font-semibold rounded-md", pickerMarket === m ? "bg-white shadow-sm" : "text-gray-500"].join(" ")}>
                {m === "india" ? "🇮🇳" : "🇺🇸"}
              </button>
            ))}
          </div>
          <div className="relative flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <input type="text" value={query} onChange={e => setQuery(e.target.value)}
              placeholder={pickerMarket === "us" ? "Add a US ETF…" : "Add an India fund…"}
              className="w-full pl-8 pr-3 py-2 text-xs rounded-xl border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-300" />
            {matches.length > 0 && (
              <div className="absolute z-20 mt-1 w-full bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
                {matches.map(f => (
                  <button key={f.scheme_code} onClick={() => add(f.scheme_code, f.name)}
                    className="w-full text-left px-3 py-2 text-xs hover:bg-indigo-50 flex items-center gap-2">
                    <Plus size={12} className="text-indigo-500 shrink-0" />
                    <span className="truncate">{f.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {selected.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {selected.map(f => (
              <span key={f.code} className="inline-flex items-center gap-1 text-[10px] font-medium bg-gray-100 text-gray-700 rounded-full pl-2 pr-1 py-1">
                <span>{f.market === "india" ? "🇮🇳" : "🇺🇸"}</span>
                {f.name.length > 26 ? f.name.slice(0, 26) + "…" : f.name}
                <button onClick={() => setSelected(prev => prev.filter(x => x.code !== f.code))} className="hover:text-red-500"><X size={11} /></button>
              </span>
            ))}
          </div>
        )}

        <button onClick={analyse} disabled={selected.length === 0 || mutation.isPending}
          className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white font-semibold rounded-xl px-4 py-2.5 text-sm flex items-center justify-center gap-2">
          {mutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          {mutation.isPending ? "Analysing…" : `X-ray ${selected.length || ""} fund${selected.length === 1 ? "" : "s"}`}
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4">
        {mutation.isError && <p className="text-center text-sm text-red-500 py-10">Couldn't analyse. Try again.</p>}
        {!r && !mutation.isPending && !mutation.isError && (
          <div className="text-center py-16 text-gray-400">
            <Sparkles size={28} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm font-medium">Add your funds and hit X-ray</p>
            <p className="text-xs mt-1">Mix India MFs and US ETFs — see where you really stand</p>
          </div>
        )}
        {r && <Results r={r} />}
      </div>
    </div>
  );
}

// ── Results ───────────────────────────────────────────────────────────────────

function Results({ r }: { r: PortfolioXrayResponse }) {
  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {/* AI summary */}
      {r.narrative && (
        <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4">
          <div className="flex items-center gap-1.5 mb-1.5 text-[10px] font-bold text-indigo-600 uppercase tracking-wide">
            <Sparkles size={11} /> The verdict
          </div>
          <p className="text-xs text-gray-700 leading-relaxed">{r.narrative}</p>
        </div>
      )}

      {/* Allocation */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <AllocBlock title="Geography" slices={r.geography} />
        <AllocBlock title="Cap / Style" slices={r.caps} />
      </div>

      {/* Sectors (US look-through) */}
      {r.sectors.length > 0 && (
        <div className="rounded-xl border border-gray-100 bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Sector exposure</span>
            <span className="text-[9px] text-gray-400">US look-through · {Math.round(r.sector_coverage * 100)}% of book</span>
          </div>
          {r.sectors.slice(0, 8).map(s => <Row key={s.sector} label={s.sector} pct={s.pct} max={r.sectors[0].pct} color="bg-teal-500" />)}
          <p className="text-[9px] text-gray-400 mt-2">India funds (the rest) are broadly diversified — holdings look-through isn't available there yet.</p>
        </div>
      )}

      {/* Top companies */}
      {r.top_companies.length > 0 && (
        <div className="rounded-xl border border-gray-100 bg-white p-4">
          <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Top companies you own (via US ETFs)</span>
          <div className="grid grid-cols-2 gap-x-4 mt-2">
            {r.top_companies.slice(0, 8).map(c => (
              <div key={c.symbol ?? c.name} className="flex items-center justify-between text-[11px] py-0.5">
                <span className="text-gray-700 truncate">{c.name}</span>
                <span className="font-semibold text-gray-900 shrink-0">{c.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings: flags, redundancy, gaps */}
      {(r.flagged_funds.length > 0 || r.redundancies.length > 0 || r.gaps.length > 0) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-2">
          <div className="flex items-center gap-1.5 text-[10px] font-bold text-amber-700 uppercase tracking-wide">
            <AlertTriangle size={11} /> What to look at
          </div>
          {r.flagged_funds.map((f, i) => <p key={`f${i}`} className="text-[11px] text-gray-700">⚠️ {f}</p>)}
          {r.redundancies.map((f, i) => <p key={`r${i}`} className="text-[11px] text-gray-700">🔁 {f}</p>)}
          {r.gaps.map((g, i) => <p key={`g${i}`} className="text-[11px] text-gray-700">➕ {g}</p>)}
        </div>
      )}

      {/* Funds */}
      <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
        <div className="px-3.5 py-2 bg-gray-50 border-b border-gray-100 text-[10px] font-bold text-gray-500 uppercase tracking-wide">Your funds</div>
        {r.funds.map(f => (
          <div key={f.code} className="px-3.5 py-2 flex items-center gap-2 text-[11px] border-b border-gray-50 last:border-0">
            <span>{f.market === "india" ? "🇮🇳" : "🇺🇸"}</span>
            <span className="flex-1 truncate text-gray-700">{f.name}</span>
            {f.category && <span className="text-[9px] text-gray-400 shrink-0 hidden sm:inline">{f.category}</span>}
            <span className="text-gray-400 shrink-0">{f.weight.toFixed(0)}%</span>
            {f.flag && (
              <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-red-50 text-red-600 shrink-0">
                {FLAG_LABEL[f.flag] ?? f.flag}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AllocBlock({ title, slices }: { title: string; slices: AllocSlice[] }) {
  const max = slices[0]?.pct ?? 100;
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-4">
      <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">{title}</span>
      <div className="mt-2">
        {slices.map(s => <Row key={s.label} label={s.label} pct={s.pct} max={max} color="bg-indigo-500" />)}
      </div>
    </div>
  );
}

function Row({ label, pct, max, color }: { label: string; pct: number; max: number; color: string }) {
  return (
    <div className="mb-1.5">
      <div className="flex items-center justify-between text-[10px] mb-0.5">
        <span className="text-gray-600">{label}</span>
        <span className="font-semibold text-gray-900">{pct.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max((pct / (max || 1)) * 100, 2)}%` }} />
      </div>
    </div>
  );
}
