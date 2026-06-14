/**
 * CompareView — SIP backtest: your funds vs the model portfolio.
 *
 * Pick your funds, set a monthly SIP amount, choose which model (risk) to compare
 * against, and see what the same SIP would be worth today over the trailing
 * 1 / 3 / 5 years — your basket vs the model's.
 */

import { Loader2, Plus, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { MarketToggleFunds } from "./MarketToggleFunds";
import { useFundScan } from "../hooks/useFunds";
import type { CompareResponse, FundScheme, Market, RiskProfile } from "../types";

const RISKS: RiskProfile[] = ["conservative", "balanced", "aggressive"];

const SIP_CFG: Record<Market, { min: number; max: number; step: number; def: number }> = {
  india: { min: 1000, max: 200000, step: 1000, def: 25000 },
  us:    { min: 100,  max: 10000,  step: 100,  def: 1000 },
};

function fmtMoney(v: number | undefined, market: Market): string {
  if (v == null) return "—";
  if (market === "india") {
    if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
    if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
    return `₹${Math.round(v).toLocaleString("en-IN")}`;
  }
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${Math.round(v).toLocaleString("en-US")}`;
  return `$${Math.round(v)}`;
}

export function CompareView({ market, onMarketChange }: { market: Market; onMarketChange: (m: Market) => void }) {
  const [risk, setRisk] = useState<RiskProfile>("balanced");
  const [amount, setAmount] = useState(SIP_CFG[market].def);
  const [selected, setSelected] = useState<FundScheme[]>([]);
  const [query, setQuery] = useState("");

  const { data: universe } = useFundScan(market);
  const mutation = useMutation({ mutationFn: api.compareFunds });

  // Reset everything when the market changes (funds belong to one market).
  useEffect(() => {
    setSelected([]);
    setAmount(SIP_CFG[market].def);
    setQuery("");
    mutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market]);

  const matches = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return [];
    const chosen = new Set(selected.map(f => f.scheme_code));
    return (universe?.funds ?? [])
      .filter(f => !chosen.has(f.scheme_code) && f.name.toLowerCase().includes(q))
      .slice(0, 8);
  }, [query, universe, selected]);

  function add(f: FundScheme) {
    setSelected(prev => [...prev, f]);
    setQuery("");
  }
  function remove(code: string) {
    setSelected(prev => prev.filter(f => f.scheme_code !== code));
  }
  function runCompare() {
    if (selected.length === 0) return;
    mutation.mutate({
      market, risk, amount,
      user_funds: selected.map(f => ({ code: f.scheme_code, name: f.name })),
    });
  }

  const cfg = SIP_CFG[market];
  const result = mutation.data;

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">

      {/* Sticky header + controls */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3 space-y-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-gray-900">Compare with the model</h2>
            <p className="text-[11px] text-gray-400 truncate">Same monthly SIP — your funds vs our 5 — over the last 1/3/5 years</p>
          </div>
          <div className="ml-auto"><MarketToggleFunds market={market} onChange={onMarketChange} /></div>
        </div>

        {/* SIP amount + risk */}
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Monthly SIP</span>
              <span className="text-xs font-bold text-indigo-600">{fmtMoney(amount, market)}/mo</span>
            </div>
            <input
              type="range" min={cfg.min} max={cfg.max} step={cfg.step} value={amount}
              onChange={e => setAmount(Number(e.target.value))}
              className="w-full accent-indigo-600"
            />
          </div>
          <div className="flex items-end gap-1">
            {RISKS.map(r => (
              <button
                key={r}
                onClick={() => setRisk(r)}
                className={[
                  "text-[10px] font-semibold px-2 py-1.5 rounded-lg border capitalize transition-all",
                  risk === r ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-500 border-gray-200",
                ].join(" ")}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        {/* Fund picker */}
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            type="text" value={query} onChange={e => setQuery(e.target.value)}
            placeholder={market === "us" ? "Add your ETFs — search e.g. VTI, QQQ…" : "Add your funds — search e.g. HDFC, Parag Parikh…"}
            className="w-full pl-8 pr-3 py-2 text-xs rounded-xl border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          />
          {matches.length > 0 && (
            <div className="absolute z-20 mt-1 w-full bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
              {matches.map(f => (
                <button
                  key={f.scheme_code}
                  onClick={() => add(f)}
                  className="w-full text-left px-3 py-2 text-xs hover:bg-indigo-50 flex items-center gap-2"
                >
                  <Plus size={12} className="text-indigo-500 shrink-0" />
                  <span className="truncate">{f.name}</span>
                  {f.category && <span className="ml-auto text-[9px] text-gray-400 shrink-0">{f.category}</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Selected chips */}
        {selected.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {selected.map(f => (
              <span key={f.scheme_code} className="inline-flex items-center gap-1 text-[10px] font-medium bg-gray-100 text-gray-700 rounded-full pl-2.5 pr-1 py-1">
                {f.name.length > 30 ? f.name.slice(0, 30) + "…" : f.name}
                <button onClick={() => remove(f.scheme_code)} className="hover:text-red-500"><X size={11} /></button>
              </span>
            ))}
          </div>
        )}

        <button
          onClick={runCompare}
          disabled={selected.length === 0 || mutation.isPending}
          className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white font-semibold rounded-xl px-4 py-2.5 text-sm flex items-center justify-center gap-2"
        >
          {mutation.isPending ? <Loader2 size={15} className="animate-spin" /> : null}
          {mutation.isPending ? "Backtesting…" : `Compare ${selected.length || ""} fund${selected.length === 1 ? "" : "s"} vs the model`}
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4">
        {mutation.isError && (
          <p className="text-center text-sm text-red-500 py-10">Couldn't run the comparison. Try again.</p>
        )}
        {!result && !mutation.isPending && !mutation.isError && (
          <div className="text-center py-16 text-gray-400">
            <Search size={28} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm font-medium">Add your funds and hit Compare</p>
            <p className="text-xs mt-1">See what the same SIP would be worth in your funds vs the model 5</p>
          </div>
        )}
        {result && <Results result={result} market={market} />}
      </div>
    </div>
  );
}

// ── Results ───────────────────────────────────────────────────────────────────

function Results({ result, market }: { result: CompareResponse; market: Market }) {
  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {result.windows.map(w => {
        const both = w.user_value != null && w.model_value != null;
        const maxV = Math.max(w.user_value ?? 0, w.model_value ?? 0) || 1;
        const modelWins = both && (w.model_value ?? 0) >= (w.user_value ?? 0);
        const delta = both ? (w.model_value ?? 0) - (w.user_value ?? 0) : null;
        return (
          <div key={w.years} className="rounded-xl border border-gray-100 bg-white p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold text-gray-900">{w.years}-year SIP</span>
              <span className="text-[10px] text-gray-400">invested {fmtMoney(w.invested, market)}</span>
            </div>

            <Bar label="Your funds" value={w.user_value} gain={w.user_gain_pct} pct={(w.user_value ?? 0) / maxV}
                 color="bg-gray-400" market={market} winner={both && !modelWins} coverage={w.user_coverage} />
            <div className="h-2" />
            <Bar label="Model 5" value={w.model_value} gain={w.model_gain_pct} pct={(w.model_value ?? 0) / maxV}
                 color="bg-indigo-500" market={market} winner={modelWins} coverage={w.model_coverage} />

            {delta != null && Math.abs(delta) > 0 && (
              <p className={`mt-2 text-[10px] ${modelWins ? "text-indigo-600" : "text-green-600"}`}>
                {modelWins
                  ? `The model would be ${fmtMoney(Math.abs(delta), market)} ahead.`
                  : `Your funds would be ${fmtMoney(Math.abs(delta), market)} ahead.`}
              </p>
            )}
          </div>
        );
      })}

      <Breakdown title="Your funds" rows={result.user_funds} />
      <Breakdown title="Model 5" rows={result.model_funds} />

      <p className="text-[10px] text-gray-400 text-center leading-relaxed">
        Backtest of a fixed monthly SIP using actual NAV history. Funds without enough history for a window are
        excluded and weights renormalised (coverage shown). Past performance is not indicative of future returns.
      </p>
    </div>
  );
}

function Bar({ label, value, gain, pct, color, market, winner, coverage }: {
  label: string; value?: number; gain?: number; pct: number; color: string;
  market: Market; winner: boolean; coverage: number;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] mb-1">
        <span className={`font-semibold ${winner ? "text-gray-900" : "text-gray-500"}`}>
          {label}{winner && " 🏆"}
          {coverage < 1 && <span className="text-amber-500 font-normal"> · {Math.round(coverage * 100)}% covered</span>}
        </span>
        <span className="font-bold text-gray-900">
          {fmtMoney(value, market)}
          {gain != null && <span className={`ml-1.5 font-semibold ${gain >= 0 ? "text-green-600" : "text-red-500"}`}>{gain >= 0 ? "+" : ""}{gain.toFixed(0)}%</span>}
        </span>
      </div>
      <div className="h-5 bg-gray-100 rounded-lg overflow-hidden">
        <div className={`h-full rounded-lg ${color} transition-all`} style={{ width: `${Math.max(pct * 100, 2)}%` }} />
      </div>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: CompareResponse["user_funds"] }) {
  if (rows.length === 0) return null;
  return (
    <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
      <div className="px-3.5 py-2 bg-gray-50 border-b border-gray-100 flex items-center text-[10px] font-bold text-gray-500 uppercase tracking-wide">
        <span className="flex-1">{title}</span>
        <span className="w-12 text-right">1Y</span>
        <span className="w-12 text-right">3Y</span>
        <span className="w-12 text-right">5Y</span>
      </div>
      {rows.map(r => (
        <div key={r.code} className="px-3.5 py-2 flex items-center text-[11px] border-b border-gray-50 last:border-0">
          <span className="flex-1 truncate text-gray-700">{r.name}</span>
          {[r.returns_1y, r.returns_3y, r.returns_5y].map((v, i) => (
            <span key={i} className={`w-12 text-right font-medium ${v == null ? "text-gray-300" : v >= 0 ? "text-green-600" : "text-red-500"}`}>
              {v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(0)}%`}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}
