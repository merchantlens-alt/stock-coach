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

import { ArrowRight, Loader2, RefreshCw, Sliders, Sparkles, TrendingUp, UserCircle, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { useAllocationPlan, useInvestorProfile } from "../hooks/useAdvisor";
import type { AllocationBucket, AllocationInstrument, AllocationPreferences } from "../types";
import { ASSET_CLASSES } from "../types";

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

// ── Preference editor panel ───────────────────────────────────────────────────

interface PreferencePanelProps {
  currentPlan: AllocationBucket[] | undefined;
  preferences: AllocationPreferences;
  onChange: (prefs: AllocationPreferences) => void;
  onClose: () => void;
  onApply: () => void;
  loading: boolean;
}

function PreferencePanel({ currentPlan, preferences, onChange, onClose, onApply, loading }: PreferencePanelProps) {
  const lockedSum = Object.values(preferences).reduce((s, v) => s + v, 0);
  const remaining = Math.max(0, 100 - lockedSum);
  const isOver = lockedSum > 100;

  function handleChange(cls: string, raw: string) {
    const val = parseInt(raw, 10);
    if (raw === "" || isNaN(val)) {
      const next = { ...preferences };
      delete next[cls];
      onChange(next);
    } else {
      onChange({ ...preferences, [cls]: Math.min(100, Math.max(0, val)) });
    }
  }

  function currentPct(cls: string): number {
    return currentPlan?.find(b => b.asset_class === cls)?.percentage ?? 0;
  }

  return (
    <div className="rounded-xl border border-indigo-100 bg-indigo-50 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 bg-indigo-600">
        <div className="flex items-center gap-2">
          <Sliders size={13} className="text-indigo-200" />
          <span className="text-xs font-bold text-white">Customise Allocation</span>
        </div>
        <button onClick={onClose} className="text-indigo-200 hover:text-white">
          <X size={14} />
        </button>
      </div>
      <div className="px-4 py-3 space-y-2.5">
        <p className="text-[10px] text-indigo-700 leading-relaxed">
          Set a target % for any asset class. Leave the rest blank — the AI will distribute the remaining <strong>{remaining}%</strong> based on your profile.
        </p>

        <div className="space-y-1.5">
          {ASSET_CLASSES.map(cls => {
            const locked = preferences[cls] !== undefined;
            return (
              <div key={cls} className="flex items-center gap-3">
                <span className={`text-xs flex-1 ${locked ? "font-semibold text-indigo-800" : "text-gray-600"}`}>
                  {cls}
                </span>
                <span className="text-[10px] text-gray-400 w-12 text-right">
                  {locked ? "" : `AI: ${currentPct(cls)}%`}
                </span>
                <div className="relative">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    placeholder={String(currentPct(cls))}
                    value={preferences[cls] ?? ""}
                    onChange={e => handleChange(cls, e.target.value)}
                    className={`w-16 text-xs text-right rounded-lg border px-2 py-1 focus:outline-none focus:ring-2 focus:ring-indigo-300
                      ${locked ? "border-indigo-400 bg-white font-semibold text-indigo-800" : "border-gray-200 bg-white text-gray-700"}`}
                  />
                  {locked && (
                    <span className="absolute -right-1 -top-1 w-2 h-2 rounded-full bg-indigo-600" />
                  )}
                </div>
                <span className="text-xs text-gray-400">%</span>
              </div>
            );
          })}
        </div>

        {isOver && (
          <p className="text-[10px] text-red-500 font-medium">Total exceeds 100% — reduce one or more values.</p>
        )}

        <div className="flex items-center justify-between pt-1">
          <button
            onClick={() => onChange({})}
            className="text-[10px] text-indigo-500 hover:underline"
          >
            Reset to AI default
          </button>
          <button
            onClick={onApply}
            disabled={loading || isOver}
            className="flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-semibold rounded-lg px-3 py-1.5 transition-colors"
          >
            {loading && <Loader2 size={11} className="animate-spin" />}
            Regenerate plan
          </button>
        </div>
      </div>
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
  const { data: cachedPlan, isLoading: planLoading, error: planError } = useAllocationPlan(
    !!profile && hasMonthly,
  );

  const queryClient = useQueryClient();
  const [refreshing, setRefreshing]     = useState(false);
  const [showPrefs, setShowPrefs]       = useState(false);
  const [preferences, setPreferences]   = useState<AllocationPreferences>({});
  // activePlan is either the customised result or the cached default
  const [activePlan, setActivePlan]     = useState<typeof cachedPlan>(undefined);

  // Use the custom plan if one exists, otherwise fall back to the react-query cache
  const plan = activePlan ?? cachedPlan;

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    setActivePlan(undefined);
    try {
      const fresh = await api.getAllocationPlan({ refresh: true });
      queryClient.setQueryData(["advisor", "allocation-plan"], fresh);
    } catch {
      queryClient.invalidateQueries({ queryKey: ["advisor", "allocation-plan"] });
    } finally {
      setRefreshing(false);
    }
  }

  async function handleApplyPreferences() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const fresh = Object.keys(preferences).length > 0
        ? await api.customizeAllocationPlan(preferences)
        : await api.getAllocationPlan({ refresh: true });
      setActivePlan(fresh);
      // Also update the query cache if no preferences (pure refresh)
      if (!Object.keys(preferences).length) {
        queryClient.setQueryData(["advisor", "allocation-plan"], fresh);
      }
      setShowPrefs(false);
    } catch {
      /* error is surfaced via planError — nothing extra needed */
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
  const hasPrefs  = Object.keys(preferences).length > 0;

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
          <div className="flex items-center gap-2">
            {/* Customise button */}
            <button
              onClick={() => setShowPrefs(v => !v)}
              className={`flex items-center gap-1.5 text-xs font-medium rounded-lg px-2.5 py-1.5 border transition-colors
                ${showPrefs
                  ? "bg-indigo-600 text-white border-indigo-600"
                  : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}
            >
              <Sliders size={12} />
              <span>Customise</span>
              {hasPrefs && !showPrefs && (
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
              )}
            </button>
            {/* Refresh */}
            <button
              onClick={handleRefresh}
              disabled={isLoading}
              title="Regenerate plan with AI defaults"
              className="flex items-center gap-1.5 text-xs font-medium border border-gray-200 rounded-lg px-2.5 py-1.5 text-gray-600 hover:bg-gray-50 disabled:opacity-40 transition-colors"
            >
              <RefreshCw size={12} className={isLoading ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>

        {/* Applied preferences badge */}
        {plan?.user_preferences_applied && Object.keys(plan.user_preferences_applied).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {Object.entries(plan.user_preferences_applied).map(([cls, pct]) => (
              <span key={cls} className="text-[9px] font-bold bg-indigo-100 text-indigo-700 rounded-full px-2 py-0.5 uppercase tracking-wide">
                {cls} {pct}% locked
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-3">

        {/* Preference panel */}
        {showPrefs && (
          <PreferencePanel
            currentPlan={plan?.buckets}
            preferences={preferences}
            onChange={setPreferences}
            onClose={() => setShowPrefs(false)}
            onApply={handleApplyPreferences}
            loading={refreshing}
          />
        )}

        {isLoading && !plan && (
          <div className="flex flex-col items-center justify-center py-20 gap-3 text-gray-400">
            <Loader2 size={28} className="animate-spin text-indigo-500" />
            <p className="text-sm font-medium">Building your personalised plan…</p>
            <p className="text-xs">This takes about 15–20 seconds on first load</p>
          </div>
        )}

        {isLoading && plan && (
          <div className="flex items-center justify-center gap-2 py-3 text-indigo-500">
            <Loader2 size={14} className="animate-spin" />
            <span className="text-xs font-medium">Regenerating with your preferences…</span>
          </div>
        )}

        {!isLoading && planError && !plan && (
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
