/**
 * MegatrendsPage — DUMMY MOCKUP (hardcoded data) to preview the design.
 *
 * Not wired to the backend yet. Shows the proposed layout: durable themes, each
 * with a thesis, a catalyst ladder (scenario chain — not a price target), vehicles
 * tiered by risk, what-kills-it risks, and confirmers to watch.
 */

import { AlertTriangle, ArrowRight, Eye, Sparkles } from "lucide-react";

type Tier = "ETF" | "Leader" | "Speculative";

interface Vehicle { tier: Tier; ticker: string; name: string; note: string; }
interface Theme {
  name: string;
  emoji: string;
  horizon: string;
  durability: string;
  thesis: string;
  ladder: string[];
  vehicles: Vehicle[];
  kills: string[];
  watch: string[];
}

const TIER_STYLE: Record<Tier, string> = {
  ETF:         "bg-green-50 text-green-700 border-green-200",
  Leader:      "bg-indigo-50 text-indigo-700 border-indigo-200",
  Speculative: "bg-red-50 text-red-600 border-red-200",
};

const THEMES: Theme[] = [
  {
    name: "Robotic & Minimally-Invasive Surgery",
    emoji: "🤖",
    horizon: "10–15 yr",
    durability: "Structural",
    thesis: "Surgical robotics is still <5% penetrated globally. Aging populations, surgeon shortages, and better outcomes drive a multi-decade shift from open to robotic procedures — with telesurgery the next frontier.",
    ladder: [
      "6G ultra-low-latency networks mature",
      "Remote telesurgery becomes clinically viable at scale",
      "TAM expands to rural / cross-border / underserved regions",
      "Value accrues to whoever owns installed base + telesurgery stack + approvals",
    ],
    vehicles: [
      { tier: "ETF", ticker: "—", name: "Healthcare-innovation / robotics ETF", note: "Own the trend without single-stock blow-up risk" },
      { tier: "Leader", ticker: "ISRG", name: "Intuitive Surgical", note: "Dominant US installed base — but watch the Toumai threat to international growth" },
      { tier: "Speculative", ticker: "—", name: "Chinese / emerging challengers", note: "Cheaper clones (Toumai) — high upside, high uncertainty, hard to access" },
    ],
    kills: [
      "Cheaper challengers neutralise the switching-cost moat internationally",
      "Telesurgery reimbursement / regulation stalls",
    ],
    watch: ["Toumai placements outside China", "ISRG international growth + China commentary", "FDA progress for challengers"],
  },
  {
    name: "Quantum Computing",
    emoji: "⚛️",
    horizon: "10–20 yr",
    durability: "Early / high-variance",
    thesis: "Potentially transformative for cryptography, materials, and drug discovery — but commercially pre-mature. The theme is real; most pure-plays are pre-revenue story stocks. Treat as a satellite lottery ticket, not a core holding.",
    ladder: [
      "Error-correction milestones (logical qubits) hit reliably",
      "First narrow commercial advantage in chemistry / optimisation",
      "Cloud quantum-as-a-service revenue inflects",
      "Broad enterprise adoption (the uncertain, far-out step)",
    ],
    vehicles: [
      { tier: "ETF", ticker: "QTUM", name: "Defiance Quantum ETF", note: "Diversified basket — the sane way to own an unproven theme" },
      { tier: "Leader", ticker: "—", name: "Big-tech quantum (IBM / Google / MSFT)", note: "Quantum is a tiny option inside a profitable giant — low risk, diluted exposure" },
      { tier: "Speculative", ticker: "IONQ / RGTI / QBTS", name: "Pure-play quantum", note: "Pre-earnings, dilutive, extreme volatility — power-law outcomes" },
    ],
    kills: ["Error correction stays uneconomic for years", "Valuations price in revenue that never arrives", "Dilution erodes shareholders"],
    watch: ["Logical-qubit / fidelity milestones", "Real (not pilot) enterprise contracts", "Cash runway vs. dilution"],
  },
  {
    name: "AI Infrastructure (Compute · Power · Networking)",
    emoji: "⚡",
    horizon: "5–10 yr",
    durability: "Structural",
    thesis: "The AI build-out needs chips, but also the unglamorous picks-and-shovels: power generation, grid, cooling, networking, memory. The bottleneck is shifting from GPUs to electricity and interconnect.",
    ladder: [
      "Model demand keeps compute scaling",
      "Power & grid become the binding constraint",
      "Capex flows to energy, cooling, networking, memory",
      "Margins concentrate in whoever owns the scarce input",
    ],
    vehicles: [
      { tier: "ETF", ticker: "—", name: "Broad tech / semis + utilities mix", note: "Spread across the whole value chain" },
      { tier: "Leader", ticker: "—", name: "Chip / networking / power incumbents", note: "Cash-generative, but expectations are already high" },
      { tier: "Speculative", ticker: "—", name: "SMR / cooling / memory pure-plays", note: "Leveraged to one link in the chain — higher beta" },
    ],
    kills: ["AI capex digestion / overbuild", "Efficiency gains cut compute demand", "Rich valuations de-rate"],
    watch: ["Hyperscaler capex guidance", "Power-purchase agreements & grid bottlenecks", "Memory / networking pricing"],
  },
];

export function MegatrendsPage() {
  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center shrink-0">
            <Sparkles size={16} className="text-amber-600" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-gray-900">Megatrends</h2>
            <p className="text-[11px] text-gray-400">Durable themes · catalyst scenarios · risk-tiered vehicles</p>
          </div>
          <span className="ml-auto text-[10px] font-semibold px-2 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
            Scenarios, not price predictions
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4">
        <div className="max-w-3xl mx-auto space-y-4">
          {THEMES.map(t => <ThemeCard key={t.name} t={t} />)}
          <p className="text-[10px] text-gray-400 text-center leading-relaxed pb-4">
            Dummy preview. Catalyst ladders are scenario chains — the conditions that would have to hold —
            not forecasts. Thematic pure-plays are the highest-risk corner of the market; size as satellites, not core.
          </p>
        </div>
      </div>
    </div>
  );
}

function ThemeCard({ t }: { t: Theme }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-amber-50 to-white">
        <span className="text-xl">{t.emoji}</span>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-bold text-gray-900 leading-tight">{t.name}</h3>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700">{t.durability}</span>
            <span className="text-[9px] text-gray-400">Horizon {t.horizon}</span>
          </div>
        </div>
      </div>

      <div className="px-4 py-3 space-y-3">
        <p className="text-xs text-gray-700 leading-relaxed">{t.thesis}</p>

        {/* Catalyst ladder */}
        <div>
          <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-1.5">Catalyst ladder</div>
          <div className="flex flex-col gap-1">
            {t.ladder.map((step, i) => (
              <div key={i} className="flex items-start gap-1.5 text-[11px] text-gray-600">
                <span className="shrink-0 w-4 h-4 rounded-full bg-gray-100 text-gray-500 text-[9px] font-bold flex items-center justify-center mt-0.5">{i + 1}</span>
                <span>{step}</span>
                {i < t.ladder.length - 1 && <ArrowRight size={10} className="text-gray-300 mt-1 ml-auto shrink-0" />}
              </div>
            ))}
          </div>
        </div>

        {/* Vehicles */}
        <div>
          <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-1.5">How to play it</div>
          <div className="space-y-1.5">
            {t.vehicles.map(v => (
              <div key={v.tier} className="flex items-start gap-2">
                <span className={`shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full border ${TIER_STYLE[v.tier]}`}>{v.tier}</span>
                <div className="min-w-0 text-[11px]">
                  <span className="font-semibold text-gray-900">{v.ticker !== "—" ? `${v.ticker} · ` : ""}{v.name}</span>
                  <span className="text-gray-500"> — {v.note}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Risks + confirmers */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
          <div className="rounded-lg bg-red-50 p-2.5">
            <div className="flex items-center gap-1 text-[10px] font-bold text-red-600 uppercase tracking-wide mb-1"><AlertTriangle size={10} /> What kills it</div>
            {t.kills.map((k, i) => <p key={i} className="text-[10px] text-gray-600 leading-snug">• {k}</p>)}
          </div>
          <div className="rounded-lg bg-blue-50 p-2.5">
            <div className="flex items-center gap-1 text-[10px] font-bold text-blue-600 uppercase tracking-wide mb-1"><Eye size={10} /> Watch for</div>
            {t.watch.map((w, i) => <p key={i} className="text-[10px] text-gray-600 leading-snug">• {w}</p>)}
          </div>
        </div>
      </div>
    </div>
  );
}
