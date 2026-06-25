import { CheckCircle, Loader2, UserCircle, XCircle, AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import type { AdvisorRecommendation, AdvisorVerdict } from "../types";

// ── Verdict styling ───────────────────────────────────────────────────────────

const VERDICT_STYLE: Record<AdvisorVerdict, { bg: string; border: string; badge: string; icon: JSX.Element; label: string }> = {
  buy: {
    bg: "bg-green-50",
    border: "border-green-200",
    badge: "bg-green-600 text-white",
    icon: <CheckCircle size={15} className="text-green-600" />,
    label: "BUY",
  },
  pass: {
    bg: "bg-red-50",
    border: "border-red-200",
    badge: "bg-red-500 text-white",
    icon: <XCircle size={15} className="text-red-500" />,
    label: "PASS",
  },
  conditional: {
    bg: "bg-amber-50",
    border: "border-amber-200",
    badge: "bg-amber-500 text-white",
    icon: <AlertCircle size={15} className="text-amber-500" />,
    label: "CONDITIONAL",
  },
};

const CONFIDENCE_STYLE: Record<string, string> = {
  high:   "bg-green-100 text-green-700",
  medium: "bg-amber-100 text-amber-700",
  low:    "bg-gray-100 text-gray-500",
};

// ── Score bar ─────────────────────────────────────────────────────────────────

function MatchScoreBar({ score }: { score: number }) {
  const pct = Math.round(score);
  const color = pct >= 70 ? "bg-green-500" : pct >= 45 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-bold text-gray-500 tabular-nums w-7 text-right">{pct}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface AdvisorVerdictCardProps {
  recommendation: AdvisorRecommendation;
}

export function AdvisorVerdictCard({ recommendation }: AdvisorVerdictCardProps) {
  const [expanded, setExpanded] = useState(false);
  const style = VERDICT_STYLE[recommendation.verdict];

  return (
    <div className={`rounded-xl border ${style.border} ${style.bg} p-3 space-y-2.5`}>
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {style.icon}
          <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">
            Advisor Verdict — For You
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${CONFIDENCE_STYLE[recommendation.confidence]}`}>
            {recommendation.confidence} conf.
          </span>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${style.badge}`}>
            {style.label}
          </span>
        </div>
      </div>

      {/* Match score */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-gray-400 font-medium">Investor match</span>
        </div>
        <MatchScoreBar score={recommendation.investor_match_score} />
      </div>

      {/* Summary */}
      <p className="text-xs text-gray-700 leading-relaxed">{recommendation.summary}</p>

      {/* Expand / collapse */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="flex items-center gap-1 text-[10px] font-semibold text-gray-400 hover:text-gray-600 transition-colors"
      >
        {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        {expanded ? "Less detail" : "Why this verdict"}
      </button>

      {expanded && (
        <div className="space-y-2.5 pt-0.5 border-t border-gray-200">
          {/* Fit dimensions */}
          <div className="space-y-1">
            {[
              { label: "Horizon", text: recommendation.horizon_fit },
              { label: "Risk", text: recommendation.risk_fit },
              { label: "Allocation", text: recommendation.allocation_fit },
            ].map(({ label, text }) => (
              <div key={label} className="flex gap-2">
                <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide pt-0.5 w-16 shrink-0">
                  {label}
                </span>
                <p className="text-[11px] text-gray-600 leading-snug">{text}</p>
              </div>
            ))}
          </div>

          {/* Reasons for / against */}
          {recommendation.reasons_for.length > 0 && (
            <div className="space-y-1">
              <span className="text-[9px] font-bold text-green-600 uppercase tracking-wide">For</span>
              <ul className="space-y-0.5">
                {recommendation.reasons_for.map((r, i) => (
                  <li key={i} className="flex gap-1.5 text-[11px] text-gray-600">
                    <span className="text-green-500 mt-0.5 shrink-0">+</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {recommendation.reasons_against.length > 0 && (
            <div className="space-y-1">
              <span className="text-[9px] font-bold text-red-500 uppercase tracking-wide">Against</span>
              <ul className="space-y-0.5">
                {recommendation.reasons_against.map((r, i) => (
                  <li key={i} className="flex gap-1.5 text-[11px] text-gray-600">
                    <span className="text-red-400 mt-0.5 shrink-0">−</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Sizing + caveats */}
          {recommendation.suggested_sizing && (
            <div className="flex gap-2">
              <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide pt-0.5 w-16 shrink-0">
                Sizing
              </span>
              <p className="text-[11px] text-indigo-700 font-medium">{recommendation.suggested_sizing}</p>
            </div>
          )}
          {recommendation.caveats && (
            <div className="flex gap-2">
              <span className="text-[9px] font-bold text-gray-400 uppercase tracking-wide pt-0.5 w-16 shrink-0">
                Note
              </span>
              <p className="text-[11px] text-amber-700 leading-snug">{recommendation.caveats}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Loading state ─────────────────────────────────────────────────────────────

export function AdvisorVerdictLoading() {
  return (
    <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 flex items-center gap-2">
      <Loader2 size={13} className="text-indigo-400 animate-spin shrink-0" />
      <span className="text-xs text-indigo-600 font-medium">Getting your personalised verdict…</span>
    </div>
  );
}

// ── No-profile prompt ─────────────────────────────────────────────────────────

export function AdvisorVerdictPrompt({ onSetupProfile }: { onSetupProfile: () => void }) {
  return (
    <button
      onClick={onSetupProfile}
      className="w-full rounded-xl border border-dashed border-gray-300 bg-gray-50 hover:bg-gray-100 hover:border-indigo-300 transition-all p-3 flex items-center gap-2.5 text-left"
    >
      <UserCircle size={18} className="text-gray-400 shrink-0" />
      <div>
        <p className="text-xs font-semibold text-gray-600">Set up your Investor Profile</p>
        <p className="text-[10px] text-gray-400 mt-0.5">Get a personalised Buy / Pass verdict based on your horizon, risk, and portfolio</p>
      </div>
    </button>
  );
}
