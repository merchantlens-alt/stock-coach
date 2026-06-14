/**
 * ModelPortfolioView — "the 5 funds you should own".
 *
 * A generic, self-select-risk model portfolio (no personal profiling). Shows a
 * stacked allocation bar, one card per role (Core / Anchor / Growth / High-Growth
 * / Satellite), and a portfolio-level rationale. The investor picks a risk
 * flavour; the advisor logic does the rest.
 */

import { Loader2, RefreshCw, Sparkles, TrendingDown } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { MarketToggleFunds } from "./MarketToggleFunds";
import { useModelPortfolio } from "../hooks/useFunds";
import type { Market, ModelHolding, RiskProfile } from "../types";

const RISKS: { key: RiskProfile; label: string; sub: string }[] = [
  { key: "conservative", label: "Conservative", sub: "Steadier, lower swings" },
  { key: "balanced",     label: "Balanced",     sub: "Growth with guardrails" },
  { key: "aggressive",   label: "Aggressive",   sub: "Max long-run growth" },
];

// Role → colour (bar segment + badge).
const ROLE_COLOR: Record<string, { bar: string; chip: string }> = {
  "Core":        { bar: "bg-indigo-500", chip: "bg-indigo-50 text-indigo-700 border-indigo-200" },
  "Anchor":      { bar: "bg-blue-500",   chip: "bg-blue-50 text-blue-700 border-blue-200" },
  "Growth":      { bar: "bg-teal-500",   chip: "bg-teal-50 text-teal-700 border-teal-200" },
  "High Growth": { bar: "bg-amber-500",  chip: "bg-amber-50 text-amber-700 border-amber-200" },
  "Satellite":   { bar: "bg-violet-500", chip: "bg-violet-50 text-violet-700 border-violet-200" },
};
const fallbackColor = { bar: "bg-gray-400", chip: "bg-gray-50 text-gray-600 border-gray-200" };

function pct(v: number | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function ModelPortfolioView({ market, onMarketChange }: { market: Market; onMarketChange: (m: Market) => void }) {
  const [risk, setRisk] = useState<RiskProfile>("balanced");
  const [refreshing, setRefreshing] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useModelPortfolio(market, risk);

  // Warm all three risk profiles up front so switching is instant (the funds are
  // the same — only the weights differ — so the other two are cheap to pre-load).
  useEffect(() => {
    for (const r of ["conservative", "balanced", "aggressive"] as RiskProfile[]) {
      queryClient.prefetchQuery({
        queryKey: ["funds", "model", market, r],
        queryFn: () => api.getModelPortfolio(market, r),
        staleTime: 12 * 60 * 60 * 1000,
      });
    }
  }, [market, queryClient]);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const result = await api.getModelPortfolio(market, risk, { refresh: true });
      queryClient.setQueryData(["funds", "model", market, risk], result);
    } catch {
      queryClient.invalidateQueries({ queryKey: ["funds", "model", market, risk] });
    } finally {
      setRefreshing(false);
    }
  }

  const holdings = data?.holdings ?? [];

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">

      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3 space-y-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center shrink-0">
            <Sparkles size={16} className="text-indigo-600" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-gray-900">Funds you should own</h2>
            <p className="text-[11px] text-gray-400 truncate">
              {market === "us" ? "A low-cost ETF core" : "A diversified 5-fund core"} · ranked on long-term potential · pick your risk
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <MarketToggleFunds market={market} onChange={onMarketChange} />
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50"
            >
              <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>

        {/* Risk selector */}
        <div className="flex gap-1.5">
          {RISKS.map(r => {
            const active = risk === r.key;
            return (
              <button
                key={r.key}
                onClick={() => setRisk(r.key)}
                className={[
                  "flex-1 rounded-xl border px-3 py-2 text-left transition-all",
                  active ? "border-indigo-400 bg-indigo-50" : "border-gray-200 bg-white hover:border-gray-300",
                ].join(" ")}
              >
                <span className={`block text-xs font-bold ${active ? "text-indigo-700" : "text-gray-700"}`}>{r.label}</span>
                <span className="hidden sm:block text-[10px] text-gray-400">{r.sub}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4">
        {isLoading && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <Loader2 size={28} className="animate-spin mb-3 text-indigo-500" />
            <p className="text-sm font-medium">Building your portfolio…</p>
            <p className="text-xs mt-1">Scoring the full fund universe — ~30s first time</p>
          </div>
        )}

        {error && !isLoading && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-sm font-medium text-red-500">Couldn't build the portfolio</p>
            <button onClick={handleRefresh} className="mt-3 text-xs font-semibold text-indigo-600 hover:underline">Try again</button>
          </div>
        )}

        {!isLoading && !error && holdings.length > 0 && (
          <div className="max-w-3xl mx-auto space-y-4">

            {/* Allocation bar */}
            <div>
              <div className="flex h-3 rounded-full overflow-hidden">
                {holdings.map(h => {
                  const c = ROLE_COLOR[h.role] ?? fallbackColor;
                  return <div key={h.role} className={c.bar} style={{ width: `${h.weight_pct}%` }} title={`${h.role} ${h.weight_pct}%`} />;
                })}
              </div>
              <div className="flex justify-between mt-1.5 text-[9px] text-gray-400">
                <span>5 funds · diversified across market caps</span>
                {data?.blended_expense_ratio != null && (
                  <span>Blended expense {data.blended_expense_ratio.toFixed(2)}%</span>
                )}
              </div>
            </div>

            {/* Holdings */}
            {holdings.map(h => <HoldingCard key={h.fund.scheme_code} h={h} />)}

            {/* Rationale */}
            {data?.rationale && (
              <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4">
                <p className="text-[11px] text-indigo-700 leading-relaxed">
                  <span className="font-bold">Why this mix: </span>{data.rationale}
                </p>
              </div>
            )}

            <p className="text-[10px] text-gray-400 text-center leading-relaxed">
              Generic guidance from fund data — not personal advice. Rankings use NAV-derived long-term
              potential (sustained alpha, risk-adjusted return, drawdown), with saturated and closet-index funds excluded.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Holding card ──────────────────────────────────────────────────────────────

function HoldingCard({ h }: { h: ModelHolding }) {
  const f = h.fund;
  const c = ROLE_COLOR[h.role] ?? fallbackColor;
  const longReturn = f.returns_5y_cagr ?? f.returns_3y_cagr ?? f.since_inception_cagr;
  const longLabel = f.returns_5y_cagr != null ? "5Y" : f.returns_3y_cagr != null ? "3Y" : "SI";

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-4">
      <div className="flex items-start gap-3">
        {/* Weight dial */}
        <div className="shrink-0 text-center">
          <div className="text-lg font-bold text-gray-900 leading-none">{h.weight_pct.toFixed(0)}%</div>
          <span className={`inline-block mt-1 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full border ${c.chip}`}>
            {h.role}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-bold text-gray-900 leading-tight line-clamp-2">{f.name}</h3>
            <div className="shrink-0 text-right">
              <div className="text-[10px] text-gray-400">Long-term</div>
              <div className="text-sm font-bold text-indigo-600">{f.long_term_score.toFixed(0)}</div>
            </div>
          </div>

          {/* Key metrics */}
          <div className="flex items-center gap-3 mt-1.5 text-[10px] text-gray-500">
            <span><span className="text-gray-400">{longLabel} CAGR </span><span className={`font-semibold ${(longReturn ?? 0) >= 0 ? "text-green-600" : "text-red-500"}`}>{pct(longReturn)}</span></span>
            <span><span className="text-gray-400">Sharpe </span><span className="font-semibold text-gray-700">{f.sharpe?.toFixed(2) ?? "—"}</span></span>
            {f.active_return_3y != null && (
              <span><span className="text-gray-400">α </span><span className={`font-semibold ${f.active_return_3y >= 0 ? "text-green-600" : "text-red-500"}`}>{f.active_return_3y >= 0 ? "+" : ""}{f.active_return_3y.toFixed(0)}pp</span></span>
            )}
            {f.max_drawdown != null && (
              <span className="flex items-center gap-0.5"><TrendingDown size={9} className="text-gray-400" /><span className="font-semibold text-red-500">{f.max_drawdown.toFixed(0)}%</span></span>
            )}
          </div>

          <p className="text-[10px] text-gray-500 leading-relaxed mt-1.5">{h.why}</p>
        </div>
      </div>
    </div>
  );
}
