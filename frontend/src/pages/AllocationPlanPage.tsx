/**
 * AllocationPlanPage — the home screen for users with a saved profile.
 *
 * Shows the AI-generated cross-asset SIP allocation plan:
 *   • Monthly amount split across India Equity, US Equity, Debt, Gold, REIT
 *   • 2–3 specific fund/instrument picks per bucket
 *   • Key principles + rebalance tip
 *
 * Cache: 24 h per profile hash (backend rotates automatically on profile change).
 */

import { ArrowRight, Loader2, RefreshCw, Sparkles, TrendingUp, UserCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { useAllocationPlan, useInvestorProfile } from "../hooks/useAdvisor";
import type { AllocationBucket, AllocationInstrument } from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

const BUCKET_COLOURS: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  "India Equity":   { bg: "bg-indigo-50",  text: "text-indigo-700",  border: "border-indigo-200",  dot: "bg-indigo-500"  },
  "US Equity":      { bg: "bg-blue-50",    text: "text-blue-700",    border: "border-blue-200",    dot: "bg-blue-500"    },
  "Debt":           { bg: "bg-amber-50",   text: "text-amber-700",   border: "border-amber-200",   dot: "bg-amber-500"   },
  "Gold":           { bg: "bg-yellow-50",  text: "text-yellow-700",  border: "border-yellow-200",  dot: "bg-yellow-500"  },
  "Real Estate":    { bg: "bg-green-50",   text: "text-green-700",   border: "border-green-200",   dot: "bg-green-500"   },
};

const INSTRUMENT_LABELS: Record<string, string> = {
  mutual_fund: "MF",
  etf:         "ETF",
  stock:       "Stock",
  bond:        "Bond",
  gold:        "Gold",
  reit:        "REIT",
};

function fmtINR(n: number): string {
  if (n >= 100_000) return `₹${(n / 100_000).toFixed(1)}L`;
  if (n >= 1_000)   return `₹${(n / 1_000).toFixed(0)}K`;
  return `₹${n.toFixed(0)}`;
}

// ── Instrument row ────────────────────────────────────────────────────────────

function InstrumentRow({ instrument }: { instrument: AllocationInstrument }) {
  const typeLabel = INSTRUMENT_LABELS[instrument.instrument_type] ?? instrument.instrument_type;
  return (
    <div className="flex items-start gap-2.5 py-2 border-b border-gray-50 last:border-0">
      <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 uppercase shrink-0 mt-0.5">
        {typeLabel}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-gray-800 leading-tight">{instrument.name}</p>
        <p className="text-[10px] text-gray-400 mt-0.5">{instrument.why}</p>
      </div>
      <span className="text-xs font-bold text-gray-500 shrink-0">{instrument.weight_pct}%</span>
    </div>
  );
}

// ── Bucket card ───────────────────────────────────────────────────────────────

function BucketCard({ bucket }: { bucket: AllocationBucket }) {
  const colours = BUCKET_COLOURS[bucket.asset_class] ?? {
    bg: "bg-gray-50", text: "text-gray-700", border: "border-gray-200", dot: "bg-gray-400",
  };

  return (
    <div className={`rounded-xl border ${colours.border} overflow-hidden`}>
      {/* Header */}
      <div className={`${colours.bg} px-4 py-3 flex items-center justify-between`}>
        <div className="flex items-center gap-2.5">
          <span className={`w-2.5 h-2.5 rounded-full ${colours.dot} shrink-0`} />
          <span className={`text-sm font-bold ${colours.text}`}>{bucket.asset_class}</span>
        </div>
        <div className="text-right">
          <p className={`text-lg font-extrabold ${colours.text} leading-none`}>{bucket.percentage}%</p>
          <p className="text-[10px] text-gray-500 mt-0.5">{fmtINR(bucket.monthly_amount)}/mo</p>
        </div>
      </div>

      {/* Rationale */}
      <div className="px-4 py-2.5 bg-white border-b border-gray-50">
        <p className="text-[11px] text-gray-500 leading-relaxed">{bucket.rationale}</p>
      </div>

      {/* Instruments */}
      <div className="px-4 bg-white">
        {bucket.instruments.map((inst, i) => (
          <InstrumentRow key={i} instrument={inst} />
        ))}
      </div>
    </div>
  );
}

// ── Empty / no-profile state ──────────────────────────────────────────────────

function NoProfileState({ onSetupProfile }: { onSetupProfile: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-5 p-8 text-center">
      <div className="w-14 h-14 rounded-2xl bg-indigo-100 flex items-center justify-center">
        <UserCircle size={28} className="text-indigo-600" />
      </div>
      <div>
        <h2 className="text-base font-bold text-gray-900">Set up your investor profile</h2>
        <p className="text-sm text-gray-500 mt-1.5 max-w-xs leading-relaxed">
          Tell us your age, timeline, risk comfort, and monthly SIP amount — your personalised
          allocation plan across Indian equity, US equity, gold, debt, and REITs will be ready in seconds.
        </p>
      </div>
      <button
        onClick={onSetupProfile}
        className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl px-5 py-2.5 text-sm transition-colors"
      >
        <Sparkles size={14} />
        Build my plan
        <ArrowRight size={14} />
      </button>
    </div>
  );
}

function NoMonthlyAmountState({ onSetupProfile }: { onSetupProfile: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-4 p-8 text-center">
      <div className="w-14 h-14 rounded-2xl bg-amber-100 flex items-center justify-center">
        <TrendingUp size={26} className="text-amber-600" />
      </div>
      <div>
        <h2 className="text-base font-bold text-gray-900">One more detail needed</h2>
        <p className="text-sm text-gray-500 mt-1.5 max-w-xs leading-relaxed">
          Add your monthly SIP amount to your profile — the advisor needs it to split your
          money across asset classes with real rupee amounts.
        </p>
      </div>
      <button
        onClick={onSetupProfile}
        className="flex items-center gap-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-xl px-5 py-2.5 text-sm transition-colors"
      >
        Update profile
        <ArrowRight size={14} />
      </button>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface AllocationPlanPageProps {
  onSetupProfile: () => void;
}

export function AllocationPlanPage({ onSetupProfile }: AllocationPlanPageProps) {
  const { data: profile, isLoading: profileLoading } = useInvestorProfile();
  const hasMonthly = !!(profile?.monthly_invest_amount);
  const { data: plan, isLoading: planLoading, error: planError } = useAllocationPlan(
    !!profile && hasMonthly,
  );

  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const fresh = await api.getAllocationPlan({ refresh: true });
      queryClient.setQueryData(["advisor", "allocation-plan"], fresh);
    } catch {
      queryClient.invalidateQueries({ queryKey: ["advisor", "allocation-plan"] });
    } finally {
      setRefreshing(false);
    }
  }

  if (profileLoading) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 gap-3 text-gray-400">
        <Loader2 size={24} className="animate-spin" />
        <p className="text-sm">Loading your profile…</p>
      </div>
    );
  }

  if (!profile) return <NoProfileState onSetupProfile={onSetupProfile} />;
  if (!hasMonthly) return <NoMonthlyAmountState onSetupProfile={onSetupProfile} />;

  const isLoading = planLoading || refreshing;

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">

      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3 shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Your Allocation Plan</h2>
            <p className="text-[11px] text-gray-400 mt-0.5">
              ₹{profile.monthly_invest_amount!.toLocaleString("en-IN")}/month · {profile.horizon_years}yr horizon · {profile.risk_tolerance} risk
            </p>
          </div>
          <button
            onClick={handleRefresh}
            disabled={isLoading}
            title="Regenerate plan"
            className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-800 disabled:opacity-40"
          >
            <RefreshCw size={13} className={isLoading ? "animate-spin" : ""} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-3">

        {isLoading && !plan && (
          <div className="flex flex-col items-center justify-center py-20 gap-3 text-gray-400">
            <Loader2 size={28} className="animate-spin text-indigo-500" />
            <p className="text-sm font-medium">Building your personalised plan…</p>
            <p className="text-xs">This takes about 15–20 seconds on first load</p>
          </div>
        )}

        {planError && !plan && (
          <div className="flex flex-col items-center justify-center py-16 gap-4 text-gray-400">
            <div className="text-center">
              <p className="text-sm font-medium text-red-500">Couldn't generate your plan</p>
              {planError instanceof Error && (
                <p className="text-xs text-gray-400 mt-1 max-w-xs mx-auto">{planError.message}</p>
              )}
            </div>
            <button
              onClick={handleRefresh}
              className="flex items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:underline"
            >
              <RefreshCw size={12} />
              Try again
            </button>
          </div>
        )}

        {plan && (
          <>
            {/* Allocation buckets */}
            {plan.buckets.map((bucket, i) => (
              <BucketCard key={i} bucket={bucket} />
            ))}

            {/* Key principles */}
            {plan.key_principles.length > 0 && (
              <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
                <div className="px-4 py-2.5 border-b border-gray-50 bg-gray-50">
                  <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">
                    Key Principles for You
                  </p>
                </div>
                <div className="px-4 py-2">
                  {plan.key_principles.map((p, i) => (
                    <div key={i} className="flex items-start gap-2 py-2 border-b border-gray-50 last:border-0">
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 shrink-0 mt-1.5" />
                      <p className="text-xs text-gray-600 leading-relaxed">{p}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Rebalance tip */}
            {plan.rebalance_tip && (
              <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3">
                <p className="text-[10px] font-bold text-amber-600 uppercase tracking-wide mb-1">Rebalance</p>
                <p className="text-xs text-amber-800">{plan.rebalance_tip}</p>
              </div>
            )}

            {/* Disclaimer */}
            <p className="text-[10px] text-gray-400 text-center px-4 pb-2 leading-relaxed">
              {plan.disclaimer}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
