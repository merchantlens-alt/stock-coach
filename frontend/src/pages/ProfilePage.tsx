import { ArrowLeft, ArrowRight, Check, Edit2, Loader2, Plus, Trash2, UserCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSaveProfile, useInvestorProfile } from "../hooks/useAdvisor";
import type {
  AllocationSlice,
  InvestmentGoal,
  InvestorHorizon,
  InvestorProfile,
  RiskCapacity,
  RiskTolerance,
  TaxResidency,
} from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function horizonLabel(years: number): InvestorHorizon {
  if (years < 2) return "short";
  if (years <= 5) return "medium";
  if (years <= 15) return "long";
  return "very_long";
}

const ASSET_CLASSES = [
  "India Equity", "US Equity", "International Equity",
  "Debt / Bonds", "Gold", "Real Estate", "Cash",
];

// ── Step components ───────────────────────────────────────────────────────────

function OptionButton<T extends string | number>({
  value, selected, label, sub, onClick,
}: { value: T; selected: T; label: string; sub?: string; onClick: (v: T) => void }) {
  const active = value === selected;
  return (
    <button
      type="button"
      onClick={() => onClick(value)}
      className={[
        "w-full text-left px-4 py-3 rounded-xl border transition-all",
        active
          ? "border-indigo-600 bg-indigo-50 text-indigo-900"
          : "border-gray-200 bg-white hover:border-indigo-300 text-gray-700",
      ].join(" ")}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold">{label}</p>
          {sub && <p className="text-[11px] text-gray-500 mt-0.5">{sub}</p>}
        </div>
        {active && <Check size={15} className="text-indigo-600 shrink-0" />}
      </div>
    </button>
  );
}

function StepHorizon({
  years, age, onChange,
}: { years: number; age: number; onChange: (y: number, a: number) => void }) {
  const options: { value: number; label: string; sub: string }[] = [
    { value: 1,  label: "Less than 2 years",  sub: "Short-term — preserve capital" },
    { value: 3,  label: "2–5 years",           sub: "Medium-term — balanced approach" },
    { value: 10, label: "5–15 years",           sub: "Long-term — growth focus" },
    { value: 20, label: "15+ years",            sub: "Very long — maximum compounding" },
  ];
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-bold text-gray-900">Your timeline & age</h2>
        <p className="text-[11px] text-gray-500 mt-1">
          Your horizon and age together determine how much risk is appropriate for you.
        </p>
      </div>

      {/* Age input */}
      <div className="space-y-1.5">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Your age</p>
        <div className="flex items-center gap-2 border border-gray-200 rounded-xl px-4 py-2.5 focus-within:border-indigo-400 bg-white">
          <input
            type="number"
            min={18}
            max={90}
            value={age || ""}
            onChange={e => onChange(years, Number(e.target.value))}
            placeholder="e.g. 32"
            className="flex-1 text-sm font-semibold text-gray-900 focus:outline-none"
          />
          <span className="text-xs text-gray-400 shrink-0">years old</span>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">When do you need this money?</p>
        {options.map(o => (
          <OptionButton key={o.value} value={o.value} selected={years} label={o.label} sub={o.sub}
            onClick={v => onChange(v, age)} />
        ))}
      </div>
    </div>
  );
}

function StepRisk({
  tolerance, capacity, emergencyMonths, onChange,
}: {
  tolerance: RiskTolerance;
  capacity: RiskCapacity;
  emergencyMonths: number;
  onChange: (t: RiskTolerance, c: RiskCapacity, em: number) => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-bold text-gray-900">Your risk profile</h2>
        <p className="text-[11px] text-gray-500 mt-1">
          Tolerance = how you feel about a 30% drawdown. Capacity = whether your life changes if this goes to zero.
        </p>
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Risk Tolerance (psychological)</p>
        {([
          ["conservative", "Conservative", "I lose sleep with 10% drops"],
          ["moderate",     "Moderate",     "I can handle 20–30% drops with a long horizon"],
          ["aggressive",   "Aggressive",   "Short-term pain doesn't bother me — I focus on decades"],
        ] as [RiskTolerance, string, string][]).map(([v, l, s]) => (
          <OptionButton key={v} value={v} selected={tolerance} label={l} sub={s}
            onClick={(val) => onChange(val, capacity, emergencyMonths)} />
        ))}
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Risk Capacity (financial)</p>
        {([
          ["low",    "Low",    "I have less than 3 months emergency fund"],
          ["medium", "Medium", "3–6 months emergency fund, some dependents"],
          ["high",   "High",   "6+ months emergency fund, income is stable"],
        ] as [RiskCapacity, string, string][]).map(([v, l, s]) => (
          <OptionButton key={v} value={v} selected={capacity} label={l} sub={s}
            onClick={(val) => onChange(tolerance, val, emergencyMonths)} />
        ))}
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Emergency Fund</p>
        <div className="grid grid-cols-4 gap-2">
          {[0, 3, 6, 12].map(m => (
            <button
              key={m}
              type="button"
              onClick={() => onChange(tolerance, capacity, m)}
              className={[
                "py-2 rounded-xl border text-sm font-semibold transition-all",
                emergencyMonths === m
                  ? "border-indigo-600 bg-indigo-50 text-indigo-900"
                  : "border-gray-200 text-gray-600 hover:border-indigo-300",
              ].join(" ")}
            >
              {m === 0 ? "None" : `${m}mo`}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function StepAllocation({
  allocation, onChange,
}: { allocation: AllocationSlice[]; onChange: (a: AllocationSlice[]) => void }) {
  function addSlice() {
    onChange([...allocation, { asset_class: ASSET_CLASSES[0], percentage: 0 }]);
  }
  function removeSlice(i: number) {
    onChange(allocation.filter((_, idx) => idx !== i));
  }
  function updateSlice(i: number, patch: Partial<AllocationSlice>) {
    onChange(allocation.map((s, idx) => idx === i ? { ...s, ...patch } : s));
  }
  const total = allocation.reduce((sum, s) => sum + (s.percentage || 0), 0);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-bold text-gray-900">Your current portfolio</h2>
        <p className="text-[11px] text-gray-500 mt-1">
          What do you already own? This prevents recommending more of what you already have too much of.
        </p>
      </div>

      <div className="space-y-2">
        {allocation.map((slice, i) => (
          <div key={i} className="flex gap-2 items-center">
            <select
              value={slice.asset_class}
              onChange={e => updateSlice(i, { asset_class: e.target.value })}
              className="flex-1 text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400"
            >
              {ASSET_CLASSES.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
            <div className="flex items-center gap-1 border border-gray-200 rounded-lg px-2 py-1.5 w-20">
              <input
                type="number"
                min={0}
                max={100}
                value={slice.percentage || ""}
                onChange={e => updateSlice(i, { percentage: Number(e.target.value) })}
                className="w-full text-sm text-right focus:outline-none"
                placeholder="0"
              />
              <span className="text-xs text-gray-400">%</span>
            </div>
            <button type="button" onClick={() => removeSlice(i)}
              className="text-gray-300 hover:text-red-400 transition-colors">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      <button type="button" onClick={addSlice}
        className="flex items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors">
        <Plus size={13} />
        Add asset class
      </button>

      {total > 0 && (
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">Total</span>
          <span className={total > 100 ? "text-red-500 font-bold" : total === 100 ? "text-green-600 font-bold" : "text-gray-700 font-semibold"}>
            {total}%
          </span>
        </div>
      )}
    </div>
  );
}

function StepGoals({
  goal, tax, monthlyAmount, onChange,
}: {
  goal: InvestmentGoal;
  tax: TaxResidency;
  monthlyAmount: number;
  onChange: (g: InvestmentGoal, t: TaxResidency, m: number) => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-bold text-gray-900">Goals, tax & monthly SIP</h2>
        <p className="text-[11px] text-gray-500 mt-1">
          These three together power your personalised allocation plan.
        </p>
      </div>

      {/* Monthly invest amount */}
      <div className="space-y-1.5">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Monthly investable amount</p>
        <div className="flex items-center gap-2 border border-gray-200 rounded-xl px-4 py-2.5 focus-within:border-indigo-400 bg-white">
          <span className="text-sm font-semibold text-gray-400">₹</span>
          <input
            type="number"
            min={500}
            step={500}
            value={monthlyAmount || ""}
            onChange={e => onChange(goal, tax, Number(e.target.value))}
            placeholder="e.g. 25000"
            className="flex-1 text-sm font-semibold text-gray-900 focus:outline-none"
          />
          <span className="text-xs text-gray-400 shrink-0">/ month</span>
        </div>
        <p className="text-[10px] text-gray-400">This is the amount you can consistently invest every month</p>
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Primary Goal</p>
        {([
          ["capital_appreciation", "Capital Appreciation", "Grow wealth over time — willing to accept volatility"],
          ["income",               "Regular Income",       "Dividends and distributions matter to me"],
          ["tax_efficiency",       "Tax Efficiency",       "Minimise tax drag — ELSS, indexation, wrappers matter"],
          ["balanced",             "Balanced",            "Mix of growth and stability"],
        ] as [InvestmentGoal, string, string][]).map(([v, l, s]) => (
          <OptionButton key={v} value={v} selected={goal} label={l} sub={s}
            onClick={(val) => onChange(val, tax, monthlyAmount)} />
        ))}
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Tax Residency</p>
        {([
          ["india", "India",  "LTCG 12.5%, STCG 20%, LRS rules apply for US assets"],
          ["us",    "USA",    "US capital gains tax — qualified dividends matter"],
          ["other", "Other",  "Other jurisdiction — advisor will flag tax considerations"],
        ] as [TaxResidency, string, string][]).map(([v, l, s]) => (
          <OptionButton key={v} value={v} selected={tax} label={l} sub={s}
            onClick={(val) => onChange(goal, val, monthlyAmount)} />
        ))}
      </div>
    </div>
  );
}

// ── Profile summary view (shown when profile already exists) ──────────────────

function ProfileRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-50 last:border-0">
      <span className="text-xs text-gray-500">{label}</span>
      <span className="text-xs font-semibold text-gray-800 capitalize">{value}</span>
    </div>
  );
}

function ProfileSummaryView({
  profile, onEdit, onClose,
}: { profile: InvestorProfile; onEdit: () => void; onClose: () => void }) {
  const horizonText: Record<InvestorHorizon, string> = {
    short: "< 2 years", medium: "2–5 years", long: "5–15 years", very_long: "15+ years",
  };

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <UserCircle size={16} className="text-indigo-600" />
          <span className="text-sm font-bold text-gray-800">Investor Profile</span>
        </div>
        <span className="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-semibold">
          Saved ✓
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        <div className="border border-gray-100 rounded-xl overflow-hidden">
          {profile.age && <ProfileRow label="Age" value={`${profile.age} years`} />}
          <ProfileRow label="Investment horizon" value={horizonText[profile.horizon_label]} />
          <ProfileRow label="Risk tolerance" value={profile.risk_tolerance} />
          <ProfileRow label="Risk capacity" value={profile.risk_capacity} />
          <ProfileRow label="Emergency fund" value={`${profile.emergency_fund_months} months`} />
          <ProfileRow label="Primary goal" value={profile.primary_goal.replace(/_/g, " ")} />
          <ProfileRow label="Tax residency" value={profile.tax_residency} />
          {profile.monthly_invest_amount && (
            <ProfileRow
              label="Monthly SIP"
              value={`₹${profile.monthly_invest_amount.toLocaleString("en-IN")}`}
            />
          )}
        </div>

        {profile.existing_allocation.length > 0 && (
          <div className="border border-gray-100 rounded-xl overflow-hidden">
            <div className="px-4 py-2 bg-gray-50 border-b border-gray-100">
              <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Portfolio Allocation</p>
            </div>
            {profile.existing_allocation.map(s => (
              <div key={s.asset_class} className="flex items-center justify-between px-4 py-2.5 border-b border-gray-50 last:border-0">
                <span className="text-xs text-gray-600">{s.asset_class}</span>
                <span className="text-xs font-semibold text-gray-800">{s.percentage}%</span>
              </div>
            ))}
          </div>
        )}

        <p className="text-[10px] text-gray-400 text-center pt-1">
          Every stock and fund analysis includes a Buy / Pass verdict based on this profile.
        </p>
      </div>

      <div className="px-4 py-3 border-t border-gray-100 flex items-center gap-2 shrink-0">
        <button type="button" onClick={onClose}
          className="text-xs font-semibold text-gray-500 hover:text-gray-700 px-3 py-2 rounded-xl border border-gray-200 hover:bg-gray-50 transition-all">
          Close
        </button>
        <div className="flex-1" />
        <button type="button" onClick={onEdit}
          className="flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl px-4 py-2.5 text-sm transition-colors">
          <Edit2 size={13} />
          Edit Profile
        </button>
      </div>
    </div>
  );
}

// ── Main ProfilePage ──────────────────────────────────────────────────────────

const TOTAL_STEPS = 4;

interface ProfilePageProps {
  onClose: () => void;
  onProfileSaved?: () => void;
}

export function ProfilePage({ onClose, onProfileSaved }: ProfilePageProps) {
  const { data: existing } = useInvestorProfile();
  const save = useSaveProfile();
  const [step, setStep] = useState(1);
  const [saved, setSaved] = useState(false);
  const [editMode, setEditMode] = useState(!existing);

  // Form state — defaults filled from existing if already in cache
  const [horizonYears, setHorizonYears]       = useState(existing?.horizon_years ?? 10);
  const [age, setAge]                         = useState(existing?.age ?? 0);
  const [tolerance, setTolerance]             = useState<RiskTolerance>(existing?.risk_tolerance ?? "moderate");
  const [capacity, setCapacity]               = useState<RiskCapacity>(existing?.risk_capacity ?? "high");
  const [emergencyMonths, setEmergencyMonths] = useState(existing?.emergency_fund_months ?? 6);
  const [allocation, setAllocation]           = useState<AllocationSlice[]>(
    existing?.existing_allocation?.length
      ? existing.existing_allocation
      : [{ asset_class: "India Equity", percentage: 100 }]
  );
  const [goal, setGoal]               = useState<InvestmentGoal>(existing?.primary_goal ?? "capital_appreciation");
  const [tax, setTax]                 = useState<TaxResidency>(existing?.tax_residency ?? "india");
  const [monthlyAmount, setMonthlyAmount] = useState(existing?.monthly_invest_amount ?? 0);

  // Sync form when existing profile arrives from cache (handles async load timing)
  const syncedRef = useRef(false);
  useEffect(() => {
    if (!existing || syncedRef.current) return;
    syncedRef.current = true;
    setHorizonYears(existing.horizon_years);
    setAge(existing.age ?? 0);
    setTolerance(existing.risk_tolerance);
    setCapacity(existing.risk_capacity);
    setEmergencyMonths(existing.emergency_fund_months);
    if (existing.existing_allocation.length > 0) {
      setAllocation(existing.existing_allocation);
    }
    setGoal(existing.primary_goal);
    setTax(existing.tax_residency);
    setMonthlyAmount(existing.monthly_invest_amount ?? 0);
    setEditMode(false); // show summary view
  }, [existing]);

  function handleRiskChange(t: RiskTolerance, c: RiskCapacity, em: number) {
    setTolerance(t); setCapacity(c); setEmergencyMonths(em);
  }

  async function handleSave() {
    const profile: InvestorProfile = {
      horizon_years: horizonYears,
      horizon_label: horizonLabel(horizonYears),
      risk_tolerance: tolerance,
      risk_capacity: capacity,
      emergency_fund_months: emergencyMonths,
      primary_goal: goal,
      tax_residency: tax,
      existing_allocation: allocation.filter(a => a.percentage > 0),
      age: age || undefined,
      monthly_invest_amount: monthlyAmount || undefined,
      updated_at: new Date().toISOString(),
    };
    try {
      await save.mutateAsync(profile);
      setSaved(true);
      onProfileSaved?.();
      setTimeout(onClose, 800);
    } catch {
      // save.error is set — button re-enables automatically
    }
  }

  if (saved) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 gap-3 text-center p-6">
        <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center">
          <Check size={24} className="text-green-600" />
        </div>
        <p className="text-sm font-semibold text-gray-800">Profile saved</p>
        <p className="text-xs text-gray-500">Every analysis now includes a verdict personalised for you.</p>
      </div>
    );
  }

  // If profile exists and not in edit mode — show summary
  if (existing && !editMode) {
    return (
      <ProfileSummaryView
        profile={existing}
        onEdit={() => { setStep(1); setEditMode(true); }}
        onClose={onClose}
      />
    );
  }

  // Wizard
  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <UserCircle size={16} className="text-indigo-600" />
          <span className="text-sm font-bold text-gray-800">Investor Profile</span>
          {existing && (
            <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-semibold">
              Editing
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-gray-400">Step {step} of {TOTAL_STEPS}</span>
          <div className="flex gap-1">
            {Array.from({ length: TOTAL_STEPS }, (_, i) => (
              <div key={i} className={`h-1 w-5 rounded-full transition-all ${i + 1 <= step ? "bg-indigo-600" : "bg-gray-200"}`} />
            ))}
          </div>
        </div>
      </div>

      {/* Step content */}
      <div className="flex-1 overflow-y-auto p-4">
        {step === 1 && (
          <StepHorizon
            years={horizonYears}
            age={age}
            onChange={(y, a) => { setHorizonYears(y); setAge(a); }}
          />
        )}
        {step === 2 && (
          <StepRisk
            tolerance={tolerance} capacity={capacity} emergencyMonths={emergencyMonths}
            onChange={handleRiskChange}
          />
        )}
        {step === 3 && <StepAllocation allocation={allocation} onChange={setAllocation} />}
        {step === 4 && (
          <StepGoals
            goal={goal} tax={tax} monthlyAmount={monthlyAmount}
            onChange={(g, t, m) => { setGoal(g); setTax(t); setMonthlyAmount(m); }}
          />
        )}
      </div>

      {/* Navigation */}
      <div className="px-4 py-3 border-t border-gray-100 flex items-center gap-2 shrink-0">
        {step > 1 ? (
          <button type="button" onClick={() => setStep(s => s - 1)}
            className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 px-3 py-2 rounded-xl border border-gray-200 hover:bg-gray-50 transition-all">
            <ArrowLeft size={13} />
            Back
          </button>
        ) : existing ? (
          <button type="button" onClick={() => setEditMode(false)}
            className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 px-3 py-2 rounded-xl border border-gray-200 hover:bg-gray-50 transition-all">
            <ArrowLeft size={13} />
            Cancel edit
          </button>
        ) : (
          <button type="button" onClick={onClose}
            className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 px-3 py-2 rounded-xl border border-gray-200 hover:bg-gray-50 transition-all">
            Cancel
          </button>
        )}

        <div className="flex-1" />

        {step < TOTAL_STEPS ? (
          <button type="button" onClick={() => setStep(s => s + 1)}
            className="flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl px-4 py-2.5 text-sm transition-colors">
            Next
            <ArrowRight size={13} />
          </button>
        ) : (
          <button type="button" onClick={handleSave} disabled={save.isPending}
            className="flex items-center gap-1.5 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-xl px-4 py-2.5 text-sm transition-colors disabled:opacity-60">
            {save.isPending ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            Save Profile
          </button>
        )}
      </div>
    </div>
  );
}
