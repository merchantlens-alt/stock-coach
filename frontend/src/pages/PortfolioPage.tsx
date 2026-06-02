import { useState } from "react";
import { ArrowDown, ArrowUp, Target, Trash2, Trophy } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PortfolioEntry, PortfolioStatus } from "../types";
import { PredictionChart } from "../components/PredictionChart";

type FilterTab = "all" | "active" | "resolved";

// ── Helpers ───────────────────────────────────────────────────────────────────

function daysInfo(entry: PortfolioEntry) {
  const now = Date.now();
  const target = new Date(entry.target_date).getTime();
  const start  = new Date(entry.entry_date).getTime();
  const totalMs   = target - start;
  const elapsedMs = now - start;
  const daysLeft  = Math.ceil((target - now) / 86400000);
  const progressPct = totalMs > 0
    ? Math.min(100, Math.max(0, (elapsedMs / totalMs) * 100))
    : 100;
  return { daysLeft, progressPct };
}

function statusBadge(status: PortfolioStatus) {
  switch (status) {
    case "active":  return "bg-indigo-100 text-indigo-700";
    case "win":     return "bg-green-100 text-green-700";
    case "loss":    return "bg-red-50 text-red-600";
    case "expired": return "bg-amber-100 text-amber-700";
  }
}

function statusLabel(status: PortfolioStatus) {
  switch (status) {
    case "active":  return "Active";
    case "win":     return "✓ Win";
    case "loss":    return "✗ Loss";
    case "expired": return "Expired";
  }
}

// ── Win-rate bar ──────────────────────────────────────────────────────────────

function WinRateBar({ wins, losses }: { wins: number; losses: number }) {
  const total = wins + losses;
  if (total === 0) return null;
  const pct = Math.round((wins / total) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-red-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-green-500 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs font-bold ${pct >= 60 ? "text-green-600" : pct >= 40 ? "text-amber-600" : "text-red-500"}`}>
        {pct}%
      </span>
    </div>
  );
}

// ── Stats dashboard ───────────────────────────────────────────────────────────

function StatsDashboard({
  totalActive,
  wins,
  losses,
  winRate,
}: {
  totalActive: number;
  wins: number;
  losses: number;
  winRate?: number | null;
}) {
  return (
    <div className="rounded-xl border border-gray-100 bg-gradient-to-br from-gray-50 to-white p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">AI Track Record</span>
        {winRate != null && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
            winRate >= 60 ? "bg-green-100 text-green-700"
            : winRate >= 40 ? "bg-amber-100 text-amber-700"
            : "bg-red-50 text-red-600"
          }`}>
            {winRate.toFixed(0)}% accuracy
          </span>
        )}
      </div>

      {/* Win / loss counts */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <div className="w-6 h-6 rounded-full bg-green-100 flex items-center justify-center">
            <Trophy size={12} className="text-green-600" />
          </div>
          <div>
            <div className="text-base font-bold text-green-600 leading-none">{wins}</div>
            <div className="text-[9px] text-gray-400">wins</div>
          </div>
        </div>

        <WinRateBar wins={wins} losses={losses} />

        <div className="flex items-center gap-1.5">
          <div>
            <div className="text-base font-bold text-red-500 leading-none text-right">{losses}</div>
            <div className="text-[9px] text-gray-400 text-right">losses</div>
          </div>
          <div className="w-6 h-6 rounded-full bg-red-50 flex items-center justify-center">
            <ArrowDown size={12} className="text-red-500" />
          </div>
        </div>
      </div>

      {/* Active count */}
      {totalActive > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-gray-500 border-t border-gray-100 pt-2">
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
          {totalActive} active prediction{totalActive !== 1 ? "s" : ""} running
        </div>
      )}
    </div>
  );
}

// ── Entry card ────────────────────────────────────────────────────────────────

interface EntryCardProps {
  entry: PortfolioEntry;
  currency: string;
  currentPrice?: number;
  onDelete: (id: string) => void;
  onResolve: (id: string, price: number) => void;
  resolvingId: string | null;
  setResolvingId: (id: string | null) => void;
  resolvePrice: string;
  setResolvePrice: (v: string) => void;
  isDeleting: boolean;
  isResolving: boolean;
}

function EntryCard({
  entry,
  currency,
  currentPrice,
  onDelete,
  onResolve,
  resolvingId,
  setResolvingId,
  resolvePrice,
  setResolvePrice,
  isDeleting,
  isResolving,
}: EntryCardProps) {
  const marketFlag   = entry.market === "india" ? "🇮🇳" : "🇺🇸";
  const { daysLeft, progressPct } = daysInfo(entry);
  const isResolvingThis = resolvingId === entry.id;
  const canResolve      = entry.status === "active" || entry.status === "expired";
  const isExpiredNow    = entry.status === "active" && daysLeft <= 0;

  const hasPrediction   = entry.ai_predicted_change_pct != null;
  const isPositivePred  = (entry.ai_predicted_change_pct ?? 0) >= 0;

  // Current price delta vs entry
  const actualDelta    = currentPrice != null
    ? ((currentPrice - entry.entry_price) / entry.entry_price) * 100
    : null;

  // Holdings P&L
  const hasHolding = entry.type === "holding" && entry.shares != null && currentPrice != null;
  const holdingPL  = hasHolding
    ? (currentPrice! - (entry.purchase_avg ?? entry.entry_price)) * entry.shares!
    : null;
  const holdingPLPct = hasHolding
    ? ((currentPrice! - (entry.purchase_avg ?? entry.entry_price)) / (entry.purchase_avg ?? entry.entry_price)) * 100
    : null;

  return (
    <div className={`rounded-xl border bg-white shadow-sm overflow-hidden ${
      entry.status === "win"   ? "border-green-200" :
      entry.status === "loss"  ? "border-red-200"   :
      isExpiredNow             ? "border-amber-300"  :
      "border-gray-100"
    }`}>
      {/* ── Expired banner ────────────────────────────────────────────── */}
      {isExpiredNow && (
        <div className="flex items-center gap-1.5 px-4 py-1.5 bg-amber-50 border-b border-amber-200">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <span className="text-[10px] font-bold text-amber-700 uppercase tracking-wide">
            30 days up — ready to resolve
          </span>
        </div>
      )}

      <div className="px-4 py-3.5 space-y-3">
        {/* ── Row 1: Ticker + badges ───────────────────────────────────── */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-sm">{marketFlag}</span>
              <strong className="text-sm font-bold text-gray-900">{entry.ticker}</strong>
              {entry.stock_name && (
                <span className="text-xs text-gray-400 truncate max-w-[140px]">
                  {entry.stock_name}
                </span>
              )}
            </div>
            {entry.catalyst_type && entry.catalyst_type !== "unknown" && (
              <span className="text-[10px] text-gray-400 capitalize mt-0.5 block">
                {entry.catalyst_type.replace("_", " ")} catalyst
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${statusBadge(entry.status)}`}>
              {statusLabel(entry.status)}
            </span>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
              entry.type === "holding" ? "bg-indigo-50 text-indigo-700" : "bg-gray-100 text-gray-600"
            }`}>
              {entry.type === "holding" ? "Holding" : "Watchlist"}
            </span>
          </div>
        </div>

        {/* ── Prediction chart ─────────────────────────────────────────── */}
        {hasPrediction && (entry.status === "active" || isExpiredNow) && (
          <div className="pt-1">
            <PredictionChart entry={entry} currentPrice={currentPrice} currency={currency} />
          </div>
        )}

        {/* ── Key numbers row ──────────────────────────────────────────── */}
        <div className="flex items-center gap-3 flex-wrap text-xs">
          <div className="flex items-center gap-1 text-gray-600">
            <span className="text-gray-400">Entry</span>
            <span className="font-semibold text-gray-800">{currency}{entry.entry_price.toFixed(2)}</span>
          </div>

          {currentPrice != null && actualDelta != null && (
            <div className={`flex items-center gap-0.5 font-semibold ${actualDelta >= 0 ? "text-green-600" : "text-red-500"}`}>
              {actualDelta >= 0 ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
              <span>{Math.abs(actualDelta).toFixed(1)}% now</span>
            </div>
          )}

          {hasPrediction && (
            <div className={`flex items-center gap-0.5 font-semibold ${isPositivePred ? "text-emerald-600" : "text-red-500"}`}>
              {isPositivePred ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
              <span>
                AI {isPositivePred ? "+" : ""}{entry.ai_predicted_change_pct!.toFixed(1)}%
                {entry.ai_confidence != null && (
                  <span className="font-normal text-gray-400 ml-1">
                    · {Math.round(entry.ai_confidence * 100)}% conf
                  </span>
                )}
              </span>
            </div>
          )}
        </div>

        {/* ── Holdings P&L ─────────────────────────────────────────────── */}
        {hasHolding && holdingPL != null && holdingPLPct != null && (
          <div className={`rounded-lg px-3 py-2 text-xs flex items-center justify-between ${
            holdingPL >= 0 ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"
          }`}>
            <span className="font-semibold">
              {entry.shares} shares · avg {currency}{(entry.purchase_avg ?? entry.entry_price).toFixed(2)}
            </span>
            <span className="font-bold">
              {holdingPL >= 0 ? "+" : ""}{currency}{Math.abs(holdingPL).toFixed(0)}
              <span className="font-normal ml-1 opacity-80">
                ({holdingPLPct >= 0 ? "+" : ""}{holdingPLPct.toFixed(1)}%)
              </span>
            </span>
          </div>
        )}

        {/* ── AI outlook ───────────────────────────────────────────────── */}
        {entry.ai_outlook && (
          <p className="text-[11px] text-gray-500 leading-relaxed italic border-l-2 border-gray-200 pl-2">
            {entry.ai_outlook}
          </p>
        )}

        {/* ── Time progress (active/expired) ───────────────────────────── */}
        {(entry.status === "active" || entry.status === "expired") && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[10px] text-gray-400">
              <span>
                {daysLeft > 0
                  ? `${Math.round(progressPct)}% of 30 days · ${daysLeft}d left`
                  : `Expired ${Math.abs(daysLeft)}d ago`}
              </span>
            </div>
            <div className="h-1 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${daysLeft <= 0 ? "bg-amber-400" : "bg-indigo-400"}`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}

        {/* ── Resolved result ──────────────────────────────────────────── */}
        {entry.actual_price != null && entry.status !== "active" && (
          <div className={`rounded-lg px-3 py-2 text-xs flex items-center justify-between ${
            entry.status === "win" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"
          }`}>
            <span className="font-semibold">Closed at {currency}{entry.actual_price.toFixed(2)}</span>
            {entry.actual_change_pct != null && (
              <span className="font-bold">
                {entry.actual_change_pct >= 0 ? "+" : ""}{entry.actual_change_pct.toFixed(1)}% actual
                {entry.ai_predicted_change_pct != null && (
                  <span className="font-normal opacity-70 ml-1">
                    vs AI {entry.ai_predicted_change_pct >= 0 ? "+" : ""}{entry.ai_predicted_change_pct.toFixed(1)}%
                  </span>
                )}
              </span>
            )}
          </div>
        )}

        {/* ── Actions ──────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 pt-0.5">
          <button
            onClick={() => onDelete(entry.id)}
            disabled={isDeleting}
            className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 disabled:opacity-50 transition-colors"
          >
            <Trash2 size={12} />
            Delete
          </button>

          {canResolve && !isResolvingThis && (
            <button
              onClick={() => {
                setResolvingId(entry.id);
                // Pre-fill with live current price if available
                if (currentPrice != null) {
                  setResolvePrice(currentPrice.toFixed(2));
                } else {
                  setResolvePrice("");
                }
              }}
              className={`ml-auto flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-xl border transition-colors ${
                isExpiredNow
                  ? "bg-amber-50 border-amber-300 text-amber-700 hover:bg-amber-100"
                  : "border-gray-200 hover:bg-gray-50 text-gray-700"
              }`}
            >
              {isExpiredNow ? "⚡ Resolve now" : "Resolve"}
            </button>
          )}

          {isResolvingThis && (
            <div className="flex items-center gap-2 flex-1 ml-auto">
              <input
                type="number"
                min="0"
                step="0.01"
                value={resolvePrice}
                onChange={(e) => setResolvePrice(e.target.value)}
                placeholder={currentPrice != null ? `${currentPrice.toFixed(2)}` : "Actual price"}
                className="flex-1 rounded-xl border border-gray-200 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-300"
              />
              <button
                onClick={() => {
                  const price = parseFloat(resolvePrice);
                  if (!isNaN(price) && price > 0) onResolve(entry.id, price);
                }}
                disabled={isResolving || !resolvePrice}
                className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl px-3 py-1.5 text-xs disabled:opacity-60 transition-colors whitespace-nowrap"
              >
                Confirm
              </button>
              <button
                onClick={() => setResolvingId(null)}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const [filterTab, setFilterTab]     = useState<FilterTab>("all");
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolvePrice, setResolvePrice] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api.getPortfolio(),
  });

  const entries = data?.entries ?? [];

  // ── Batch-fetch live prices for active entries ─────────────────────────────
  const activeEntries = entries.filter(e => e.status === "active");

  // Group by market so we can make separate calls (US vs India)
  const usActive    = activeEntries.filter(e => e.market === "us").map(e => e.ticker);
  const indiaActive = activeEntries.filter(e => e.market === "india").map(e => e.ticker);

  const { data: usPrices } = useQuery({
    queryKey: ["portfolio-prices", "us", usActive.sort().join(",")],
    queryFn: () => api.getPortfolioPrices(usActive, "us"),
    enabled: usActive.length > 0,
    staleTime: 5 * 60 * 1000,  // 5 min
    refetchInterval: 10 * 60 * 1000,  // refresh every 10 min
  });

  const { data: indiaPrices } = useQuery({
    queryKey: ["portfolio-prices", "india", indiaActive.sort().join(",")],
    queryFn: () => api.getPortfolioPrices(indiaActive, "india"),
    enabled: indiaActive.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
  });

  // Merged price map: ticker → current price
  const priceMap: Record<string, number> = {
    ...(usPrices?.prices ?? {}),
    ...(indiaPrices?.prices ?? {}),
  };

  // ── Mutations ──────────────────────────────────────────────────────────────
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deletePortfolioEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["portfolio"] }),
  });

  const resolveMutation = useMutation({
    mutationFn: ({ id, price }: { id: string; price: number }) =>
      api.resolvePortfolioEntry(id, price),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      setResolvingId(null);
      setResolvePrice("");
    },
  });

  // ── Filtering ──────────────────────────────────────────────────────────────
  const filteredEntries = entries.filter(e => {
    if (filterTab === "active")   return e.status === "active";
    if (filterTab === "resolved") return e.status === "win" || e.status === "loss" || e.status === "expired";
    return true;
  });

  const FILTER_TABS: { key: FilterTab; label: string; count: number }[] = [
    { key: "all",      label: "All",      count: entries.length },
    { key: "active",   label: "Active",   count: entries.filter(e => e.status === "active").length },
    { key: "resolved", label: "Resolved", count: entries.filter(e => e.status !== "active").length },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-5 py-4 space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="text-base font-bold text-gray-900">My Plays</h1>
          {data && data.total_resolved > 0 && (
            <span className="text-[10px] text-gray-400">
              {data.total_resolved} resolved
            </span>
          )}
        </div>

        {/* Stats dashboard */}
        {data && (data.wins > 0 || data.losses > 0 || data.total_active > 0) && (
          <StatsDashboard
            totalActive={data.total_active}
            wins={data.wins}
            losses={data.losses}
            winRate={data.win_rate}
          />
        )}

        {/* Filter tabs */}
        <div className="flex items-center gap-0.5 bg-gray-100 p-1 rounded-xl w-fit">
          {FILTER_TABS.map(({ key, label, count }) => (
            <button
              key={key}
              onClick={() => setFilterTab(key)}
              className={[
                "flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all",
                filterTab === key
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700",
              ].join(" ")}
            >
              {label}
              {count > 0 && (
                <span className={`text-[10px] rounded-full px-1.5 font-bold ${
                  filterTab === key ? "bg-gray-100 text-gray-700" : "bg-white/50 text-gray-400"
                }`}>
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-5 py-4">
      <div className="max-w-2xl mx-auto space-y-3">
        {isLoading && (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-48 rounded-xl bg-gray-100 animate-pulse" />
            ))}
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">
            Failed to load portfolio. Please try again.
          </div>
        )}

        {!isLoading && !error && filteredEntries.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
            <div className="w-14 h-14 rounded-full bg-indigo-50 flex items-center justify-center">
              <Target size={24} className="text-indigo-400" />
            </div>
            <p className="text-base font-semibold text-gray-700">No plays tracked yet</p>
            <p className="text-sm text-gray-400 max-w-xs leading-relaxed">
              Open any stock analysis and click <strong>"Track this prediction"</strong> to start tracking AI accuracy.
            </p>
          </div>
        )}

        {filteredEntries.map(entry => {
          const currency = entry.market === "india" ? "₹" : "$";
          const livePrice = priceMap[entry.ticker];
          return (
            <EntryCard
              key={entry.id}
              entry={entry}
              currency={currency}
              currentPrice={livePrice}
              onDelete={(id) => deleteMutation.mutate(id)}
              onResolve={(id, price) => resolveMutation.mutate({ id, price })}
              resolvingId={resolvingId}
              setResolvingId={setResolvingId}
              resolvePrice={resolvePrice}
              setResolvePrice={setResolvePrice}
              isDeleting={deleteMutation.isPending}
              isResolving={resolveMutation.isPending}
            />
          );
        })}
        <div className="h-4" />
      </div>{/* max-w-2xl */}
      </div>
    </div>
  );
}
