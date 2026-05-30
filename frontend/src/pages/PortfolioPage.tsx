import { useState } from "react";
import { Target, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PortfolioEntry, PortfolioStatus } from "../types";

type FilterTab = "all" | "active" | "resolved";

function statusBadge(status: PortfolioStatus) {
  switch (status) {
    case "active":
      return "bg-gray-100 text-gray-600";
    case "win":
      return "bg-green-100 text-green-700";
    case "loss":
      return "bg-red-50 text-red-600";
    case "expired":
      return "bg-amber-100 text-amber-700";
  }
}

function statusLabel(status: PortfolioStatus) {
  switch (status) {
    case "active":  return "Active";
    case "win":     return "Win";
    case "loss":    return "Loss";
    case "expired": return "Expired";
  }
}

function typeBadge(type: "holding" | "watchlist") {
  return type === "holding"
    ? "bg-indigo-50 text-indigo-700"
    : "bg-gray-100 text-gray-600";
}

function typeLabel(type: "holding" | "watchlist") {
  return type === "holding" ? "Holding" : "Watchlist";
}

function daysInfo(entry: PortfolioEntry) {
  const now = Date.now();
  const target = new Date(entry.target_date).getTime();
  const start = new Date(entry.entry_date).getTime();
  const totalMs = target - start;
  const elapsedMs = now - start;
  const daysLeft = Math.ceil((target - now) / 86400000);
  const progressPct = totalMs > 0
    ? Math.min(100, Math.max(0, (elapsedMs / totalMs) * 100))
    : 100;
  return { daysLeft, progressPct };
}

interface EntryCardProps {
  entry: PortfolioEntry;
  currency: string;
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
  onDelete,
  onResolve,
  resolvingId,
  setResolvingId,
  resolvePrice,
  setResolvePrice,
  isDeleting,
  isResolving,
}: EntryCardProps) {
  const marketFlag = entry.market === "india" ? "🇮🇳" : "🇺🇸";
  const { daysLeft, progressPct } = daysInfo(entry);
  const isResolvingThis = resolvingId === entry.id;
  const canResolve = entry.status === "active" || entry.status === "expired";

  const predictedPositive =
    entry.ai_predicted_change_pct != null &&
    entry.ai_predicted_change_pct >= 0;

  return (
    <div className="rounded-xl border border-gray-100 bg-white px-4 py-3 space-y-2.5">
      {/* Row 1 */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-sm">{marketFlag}</span>
          <strong className="text-sm font-bold text-gray-900">{entry.ticker}</strong>
          {entry.stock_name && (
            <>
              <span className="text-gray-400 text-xs">·</span>
              <span className="text-xs text-gray-500 truncate max-w-[120px]">
                {entry.stock_name}
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span
            className={`text-[10px] font-bold px-2 py-0.5 rounded-full capitalize ${statusBadge(entry.status)}`}
          >
            {statusLabel(entry.status)}
          </span>
          <span
            className={`text-[10px] font-bold px-2 py-0.5 rounded-full capitalize ${typeBadge(entry.type)}`}
          >
            {typeLabel(entry.type)}
          </span>
        </div>
      </div>

      {/* Row 2 */}
      <div className="flex items-center gap-3 text-xs text-gray-500">
        <span>
          Tracking from{" "}
          <span className="font-semibold text-gray-700">
            {currency}{entry.entry_price.toFixed(2)}
          </span>
        </span>
        {entry.purchase_avg != null && (
          <>
            <span className="text-gray-300">·</span>
            <span>
              Bought at{" "}
              <span className="font-semibold text-gray-700">
                {currency}{entry.purchase_avg.toFixed(2)}
              </span>
            </span>
          </>
        )}
      </div>

      {/* Row 3 — AI prediction box */}
      {entry.ai_predicted_change_pct != null && (
        <div
          className={`rounded-lg px-3 py-2 text-xs flex items-center justify-between gap-2 ${
            predictedPositive
              ? "bg-green-50 text-green-800"
              : "bg-red-50 text-red-700"
          }`}
        >
          <span className="font-semibold">
            AI: {predictedPositive ? "+" : ""}
            {entry.ai_predicted_change_pct.toFixed(1)}% in 30 days
            {entry.ai_confidence != null && (
              <span className="font-normal opacity-70 ml-1">
                · {Math.round(entry.ai_confidence * 100)}% conf
              </span>
            )}
          </span>
          <span className="opacity-70">
            Target:{" "}
            {currency}
            {(
              entry.entry_price *
              (1 + entry.ai_predicted_change_pct / 100)
            ).toFixed(2)}
          </span>
        </div>
      )}

      {/* Row 4 — time / resolved info */}
      {entry.status === "active" || entry.status === "expired" ? (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-gray-500">
            {daysLeft > 0 ? (
              <span>{daysLeft} days left</span>
            ) : (
              <span className="text-amber-600">
                Expired {Math.abs(daysLeft)} days ago
              </span>
            )}
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-400 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      ) : entry.actual_price != null ? (
        <div
          className={`text-xs font-semibold ${
            entry.status === "win" ? "text-green-600" : "text-red-500"
          }`}
        >
          Actual: {currency}{entry.actual_price.toFixed(2)}
          {entry.actual_change_pct != null && (
            <span className="ml-1">
              ({entry.actual_change_pct >= 0 ? "+" : ""}
              {entry.actual_change_pct.toFixed(1)}%)
            </span>
          )}
        </div>
      ) : null}

      {/* Row 5 — actions */}
      <div className="flex items-center gap-2 pt-0.5">
        <button
          onClick={() => onDelete(entry.id)}
          disabled={isDeleting}
          className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 disabled:opacity-50 transition-colors"
          title="Delete entry"
        >
          <Trash2 size={13} />
          <span>Delete</span>
        </button>

        {canResolve && !isResolvingThis && (
          <button
            onClick={() => {
              setResolvingId(entry.id);
              setResolvePrice("");
            }}
            className="border border-gray-200 hover:bg-gray-50 text-gray-700 font-medium rounded-xl px-3 py-2 text-xs transition-colors"
          >
            Resolve
          </button>
        )}

        {isResolvingThis && (
          <div className="flex items-center gap-2 flex-1">
            <input
              type="number"
              min="0"
              step="0.01"
              value={resolvePrice}
              onChange={(e) => setResolvePrice(e.target.value)}
              placeholder="Actual price"
              className="flex-1 rounded-xl border border-gray-200 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-300"
            />
            <button
              onClick={() => {
                const price = parseFloat(resolvePrice);
                if (!isNaN(price) && price > 0) {
                  onResolve(entry.id, price);
                }
              }}
              disabled={isResolving || !resolvePrice}
              className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl px-4 py-2.5 text-sm disabled:opacity-60 transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => setResolvingId(null)}
              className="text-xs text-gray-400 hover:text-gray-600 px-1"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const [filterTab, setFilterTab] = useState<FilterTab>("all");
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolvePrice, setResolvePrice] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api.getPortfolio(),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deletePortfolioEntry(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
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

  const entries = data?.entries ?? [];

  const filteredEntries = entries.filter((e) => {
    if (filterTab === "active") return e.status === "active";
    if (filterTab === "resolved")
      return e.status === "win" || e.status === "loss" || e.status === "expired";
    return true;
  });

  const FILTER_TABS: { key: FilterTab; label: string }[] = [
    { key: "all",      label: "All" },
    { key: "active",   label: "Active" },
    { key: "resolved", label: "Resolved" },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-5 py-4">
        <h1 className="text-lg font-bold text-gray-900 mb-3">My Plays</h1>

        {/* Stats bar */}
        {data && (
          <div className="flex items-center gap-3 mb-3 flex-wrap">
            <StatChip label="Active" value={data.total_active} />
            <StatChip label="Wins" value={data.wins} colorClass="text-green-600" />
            <StatChip label="Losses" value={data.losses} colorClass="text-red-500" />
            {data.win_rate != null && (
              <StatChip
                label="Win Rate"
                value={`${data.win_rate.toFixed(0)}%`}
                colorClass="text-indigo-600"
              />
            )}
          </div>
        )}

        {/* Filter tabs */}
        <div className="flex items-center gap-0.5 bg-gray-100 p-1 rounded-xl w-fit">
          {FILTER_TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setFilterTab(key)}
              className={[
                "px-3 py-1.5 text-xs font-semibold rounded-lg transition-all",
                filterTab === key
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700",
              ].join(" ")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-5 py-4 space-y-3">
        {isLoading && (
          <div className="flex items-center justify-center py-16 text-gray-400 text-sm">
            Loading…
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">
            Failed to load portfolio. Please try again.
          </div>
        )}

        {!isLoading && !error && filteredEntries.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
            <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center">
              <Target size={22} className="text-gray-400" />
            </div>
            <p className="text-base font-semibold text-gray-700">
              No plays tracked yet
            </p>
            <p className="text-sm text-gray-400 max-w-xs leading-relaxed">
              Open any stock analysis, click &ldquo;Track this prediction&rdquo; to start.
            </p>
          </div>
        )}

        {filteredEntries.map((entry) => {
          const currency = entry.market === "india" ? "₹" : "$";
          return (
            <EntryCard
              key={entry.id}
              entry={entry}
              currency={currency}
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
      </div>
    </div>
  );
}

function StatChip({
  label,
  value,
  colorClass = "text-gray-700",
}: {
  label: string;
  value: number | string;
  colorClass?: string;
}) {
  return (
    <div className="flex items-center gap-1.5 bg-gray-50 border border-gray-100 rounded-lg px-3 py-1.5">
      <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">
        {label}:
      </span>
      <span className={`text-sm font-bold ${colorClass}`}>{value}</span>
    </div>
  );
}
