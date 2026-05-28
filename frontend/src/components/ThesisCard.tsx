import { AlertTriangle, CheckCircle2, Clock, Eye } from "lucide-react";
import type { EntrySignalLevel, ThesisConviction, ThesisConfirmerStatus, ThesisRiskLevel } from "../types";

interface ThesisCardProps {
  conviction: ThesisConviction;
}

// ── Score bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const filled = Math.round((score / 100) * 8);
  const color =
    score >= 75 ? "bg-green-500" :
    score >= 50 ? "bg-indigo-500" :
    "bg-amber-500";
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex gap-0.5">
        {Array.from({ length: 8 }, (_, i) => (
          <div
            key={i}
            className={`w-3 h-2.5 rounded-sm ${i < filled ? color : "bg-gray-200"}`}
          />
        ))}
      </div>
      <span className="text-sm font-bold text-gray-800">{Math.round(score)}%</span>
    </div>
  );
}

// ── Risk level pill ───────────────────────────────────────────────────────────

const RISK_STYLES: Record<ThesisRiskLevel, string> = {
  lower:   "bg-green-50 text-green-700 border-green-200",
  focused: "bg-indigo-50 text-indigo-700 border-indigo-200",
  higher:  "bg-orange-50 text-orange-700 border-orange-200",
};

const RISK_LABELS: Record<ThesisRiskLevel, string> = {
  lower:   "Lower risk",
  focused: "Focused",
  higher:  "Higher risk",
};

// ── Confirmer status icon ─────────────────────────────────────────────────────

function ConfirmerIcon({ status }: { status: ThesisConfirmerStatus }) {
  if (status === "confirmed") return <CheckCircle2 size={14} className="text-green-500 shrink-0 mt-0.5" />;
  if (status === "watch")     return <Eye          size={14} className="text-amber-500 shrink-0 mt-0.5" />;
  return                             <AlertTriangle size={14} className="text-red-500  shrink-0 mt-0.5" />;
}

// ── Entry signal ─────────────────────────────────────────────────────────────

const ENTRY_STYLES: Record<EntrySignalLevel, { dots: number; label: string; color: string }> = {
  strong: { dots: 5, label: "Strong entry", color: "text-green-600" },
  fair:   { dots: 3, label: "Fair entry",   color: "text-amber-600" },
  wait:   { dots: 1, label: "Wait",         color: "text-red-500"   },
};

function EntryDots({ level }: { level: EntrySignalLevel }) {
  const { dots, label, color } = ENTRY_STYLES[level];
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex gap-0.5">
        {Array.from({ length: 5 }, (_, i) => (
          <div
            key={i}
            className={`w-2 h-2 rounded-full ${i < dots ? (level === "strong" ? "bg-green-500" : level === "fair" ? "bg-amber-500" : "bg-red-400") : "bg-gray-200"}`}
          />
        ))}
      </div>
      <span className={`text-xs font-semibold ${color}`}>{label}</span>
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

export function ThesisCard({ conviction }: ThesisCardProps) {
  const {
    theme_label, conviction_score, thesis_summary, instruments,
    confirmers, entry_signal, entry_explanation, exit_triggers, time_horizon,
    disclaimer,
  } = conviction;

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">

      {/* Header — theme + score */}
      <div className="px-5 py-4 bg-gradient-to-r from-indigo-50 to-white border-b border-gray-100">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold text-indigo-500 uppercase tracking-widest mb-0.5">
              Conviction thesis
            </p>
            <h2 className="text-lg font-bold text-gray-900 leading-tight">{theme_label}</h2>
          </div>
          <div className="text-right shrink-0">
            <p className="text-[10px] text-gray-400 mb-1">Thesis strength</p>
            <ScoreBar score={conviction_score} />
          </div>
        </div>
        <p className="mt-2.5 text-sm text-gray-600 leading-relaxed italic">
          "{thesis_summary}"
        </p>
        <div className="mt-2 flex items-center gap-1.5 text-xs text-gray-400">
          <Clock size={11} />
          <span>{time_horizon} horizon</span>
        </div>
      </div>

      {/* How to express this belief */}
      <div className="px-5 py-4 border-b border-gray-100">
        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
          How to express this belief
        </p>
        <div className="space-y-3">
          {instruments.map((inst) => (
            <div key={inst.ticker} className="flex items-start gap-3">
              {/* Risk level pill */}
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border mt-0.5 shrink-0 ${RISK_STYLES[inst.risk_level]}`}>
                {RISK_LABELS[inst.risk_level]}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-gray-900">{inst.ticker}</span>
                  <span className="text-xs text-gray-400 truncate">{inst.description}</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{inst.rationale}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Is my thesis still true? */}
      <div className="px-5 py-4 border-b border-gray-100">
        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
          Is my thesis still true?
        </p>
        <div className="space-y-2">
          {confirmers.map((c, i) => (
            <div key={i} className="flex items-start gap-2">
              <ConfirmerIcon status={c.status} />
              <span className="text-sm text-gray-700 leading-snug">{c.text}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Entry signal */}
      <div className="px-5 py-4 border-b border-gray-100">
        <div className="flex items-center justify-between mb-1.5">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest">
            Entry signal
          </p>
          <EntryDots level={entry_signal} />
        </div>
        <p className="text-sm text-gray-600">{entry_explanation}</p>
      </div>

      {/* Exit triggers */}
      <div className="px-5 py-4 border-b border-gray-100">
        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest mb-2">
          Exit if…
        </p>
        <div className="flex flex-wrap gap-x-2 gap-y-1">
          {exit_triggers.map((t, i) => (
            <span key={i} className="text-xs text-red-600 bg-red-50 px-2 py-0.5 rounded-full border border-red-100">
              {t}
            </span>
          ))}
        </div>
      </div>

      {/* Disclaimer */}
      <div className="px-5 py-3 bg-gray-50">
        <p className="text-[10px] text-gray-400 leading-relaxed">{disclaimer}</p>
      </div>
    </div>
  );
}
