/**
 * PredictionChart — mini SVG chart for a portfolio prediction entry.
 *
 * Shows three points on a timeline:
 *   📍 Entry price   (left)
 *   ▼ Today          (vertical marker at elapsed fraction)
 *   🎯 AI target     (right)
 *
 * When currentPrice is provided (live fetch):
 *   • Solid line: entry → currentPrice (actual trajectory)
 *   • Dashed line: currentPrice → target (remaining journey)
 * Without currentPrice:
 *   • Solid line: entry → predicted position today (straight-line trajectory)
 *   • Dashed line: predicted-today → target
 */

import type { PortfolioEntry } from "../types";

interface Props {
  entry: PortfolioEntry;
  currentPrice?: number;
  currency: string;
}

function fmt(price: number, currency: string): string {
  if (price >= 10_000) return `${currency}${(price / 1000).toFixed(1)}K`;
  if (price >= 1_000)  return `${currency}${price.toFixed(0)}`;
  return `${currency}${price.toFixed(2)}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function PredictionChart({ entry, currentPrice, currency }: Props) {
  const entryPrice   = entry.entry_price;
  const predicted    = entry.ai_predicted_change_pct;
  const targetPrice  = predicted != null
    ? entryPrice * (1 + predicted / 100)
    : null;

  if (targetPrice == null) {
    // No AI prediction — show nothing (handled by caller hiding the chart)
    return null;
  }

  // ── Time calculations ──────────────────────────────────────────────────────
  const now        = Date.now();
  const startMs    = new Date(entry.entry_date).getTime();
  const endMs      = new Date(entry.target_date).getTime();
  const totalMs    = endMs - startMs;
  const elapsedMs  = now - startMs;
  const elapsed    = totalMs > 0 ? Math.min(1, Math.max(0, elapsedMs / totalMs)) : 0;

  // The "on-track" price at today's position (straight-line between entry → target)
  const onTrackToday = entryPrice + (targetPrice - entryPrice) * elapsed;
  // Actual position: live price if available, else on-track estimate
  const todayPrice  = currentPrice ?? onTrackToday;

  // ── SVG geometry ──────────────────────────────────────────────────────────
  const W = 300;  // viewBox width  (rendered fluid via width="100%")
  const H = 70;   // viewBox height
  const PAD_L = 6;
  const PAD_R = 6;
  const PAD_T = 10;
  const PAD_B = 14;  // space for date labels

  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  // Price domain
  const allPrices = [entryPrice, targetPrice, todayPrice];
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const priceRange = maxP - minP || entryPrice * 0.05; // at least 5% range
  const padY = priceRange * 0.2; // 20% padding above/below
  const domainMin = minP - padY;
  const domainMax = maxP + padY;

  function scaleX(fraction: number) {
    return PAD_L + fraction * chartW;
  }
  function scaleY(price: number) {
    // SVG y=0 is top; higher prices = smaller y
    return PAD_T + (1 - (price - domainMin) / (domainMax - domainMin)) * chartH;
  }

  const xEntry  = scaleX(0);
  const xToday  = scaleX(elapsed);
  const xTarget = scaleX(1);

  const yEntry  = scaleY(entryPrice);
  const yToday  = scaleY(todayPrice);
  const yTarget = scaleY(targetPrice);

  const isPositive = targetPrice >= entryPrice;
  const actualUp   = currentPrice != null ? currentPrice > entryPrice : isPositive;

  const solidColor  = actualUp ? "#16a34a" : "#dc2626";   // green-600 or red-600
  const dashedColor = isPositive ? "#16a34a" : "#dc2626";
  const targetDotColor = isPositive ? "#16a34a" : "#dc2626";

  // Today-marker: how much has actually moved vs AI prediction
  const aboveTarget  = currentPrice != null && currentPrice > targetPrice;
  const belowTarget  = currentPrice != null && currentPrice < entryPrice;

  // ── Status label  ──────────────────────────────────────────────────────────
  let todayLabel: string;
  let todayLabelColor: string;
  if (currentPrice != null) {
    const delta = ((currentPrice - entryPrice) / entryPrice) * 100;
    todayLabel = `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`;
    todayLabelColor = delta >= 0 ? "#16a34a" : "#dc2626";
  } else {
    const dayNum = Math.round(elapsed * 30);
    todayLabel = `day ${dayNum}`;
    todayLabelColor = "#6b7280";
  }

  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        preserveAspectRatio="none"
        className="overflow-visible"
      >
        {/* ── Dashed line: today → target ─────────────────────────────── */}
        <line
          x1={xToday} y1={yToday}
          x2={xTarget} y2={yTarget}
          stroke={dashedColor}
          strokeWidth="1.5"
          strokeDasharray="4 3"
          strokeOpacity="0.55"
        />

        {/* ── Solid line: entry → today ────────────────────────────────── */}
        <line
          x1={xEntry} y1={yEntry}
          x2={xToday} y2={yToday}
          stroke={solidColor}
          strokeWidth="2"
          strokeLinecap="round"
        />

        {/* ── TODAY vertical marker ────────────────────────────────────── */}
        <line
          x1={xToday} y1={PAD_T - 4}
          x2={xToday} y2={H - PAD_B + 2}
          stroke="#94a3b8"
          strokeWidth="1"
          strokeDasharray="3 2"
        />

        {/* ── Entry dot ────────────────────────────────────────────────── */}
        <circle cx={xEntry} cy={yEntry} r="3.5" fill="#6366f1" />

        {/* ── Target dot ───────────────────────────────────────────────── */}
        <circle cx={xTarget} cy={yTarget} r="3.5" fill={targetDotColor} />

        {/* ── Today dot ────────────────────────────────────────────────── */}
        <circle
          cx={xToday} cy={yToday} r="4"
          fill={currentPrice != null ? solidColor : "#94a3b8"}
          stroke="white" strokeWidth="1.5"
        />

        {/* ── "ABOVE TARGET" flash dot (only when current > target) ──── */}
        {aboveTarget && (
          <circle cx={xToday} cy={yToday} r="7" fill={solidColor} fillOpacity="0.18" />
        )}

        {/* ── Price labels (bottom) ────────────────────────────────────── */}
        {/* Entry */}
        <text x={xEntry} y={H} textAnchor="start"
          fontSize="8" fill="#6366f1" fontWeight="600">
          {fmt(entryPrice, currency)}
        </text>

        {/* Today */}
        <text x={xToday} y={H} textAnchor="middle"
          fontSize="8" fill={todayLabelColor} fontWeight="700">
          {todayLabel}
        </text>

        {/* Target */}
        <text x={xTarget} y={H} textAnchor="end"
          fontSize="8" fill={targetDotColor} fontWeight="600">
          {fmt(targetPrice, currency)}
        </text>
      </svg>

      {/* ── Date labels ────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between text-[9px] text-gray-400 mt-0.5 px-0.5">
        <span>{fmtDate(entry.entry_date)}</span>
        {currentPrice != null && (
          <span className={`font-semibold ${actualUp ? "text-green-600" : "text-red-500"}`}>
            {fmt(currentPrice, currency)} now
          </span>
        )}
        <span>{fmtDate(entry.target_date)}</span>
      </div>

      {/* ── "Above target!" badge ─────────────────────────────────────── */}
      {aboveTarget && (
        <div className="mt-1.5 flex items-center gap-1 bg-emerald-50 border border-emerald-200 rounded-lg px-2 py-1 text-[10px] font-semibold text-emerald-700">
          <span>🚀</span>
          Already past AI target — AI was conservative!
        </div>
      )}
      {belowTarget && currentPrice != null && (
        <div className="mt-1.5 flex items-center gap-1 bg-red-50 border border-red-100 rounded-lg px-2 py-1 text-[10px] font-semibold text-red-600">
          <span>⚠️</span>
          Below entry price — watch closely
        </div>
      )}
    </div>
  );
}
