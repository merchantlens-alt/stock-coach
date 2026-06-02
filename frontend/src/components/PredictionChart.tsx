/**
 * PredictionChart — compact SVG chart for a portfolio prediction entry.
 *
 * Design:
 * • Fixed 72 px container — consistent height regardless of card width.
 * • SVG handles lines + dots only (preserveAspectRatio:none, scales fine).
 * • HTML div labels overlay the chart — don't stretch with width.
 * • Correct directional badge logic:
 *     bullish pred  + current > target  →  "AI was conservative"
 *     bearish pred  + current < target  →  "dropped past bearish target"
 *     bullish pred  + current < entry   →  "fell below entry — prediction at risk"
 *     bearish pred  + current > entry   →  "stock rose against negative outlook"
 */

import type { PortfolioEntry } from "../types";

interface Props {
  entry: PortfolioEntry;
  currentPrice?: number;
  currency: string;
}

function fmt(price: number, currency: string): string {
  if (price >= 100_000) return `${currency}${(price / 1000).toFixed(0)}K`;
  if (price >= 10_000)  return `${currency}${(price / 1000).toFixed(1)}K`;
  if (price >= 1_000)   return `${currency}${price.toFixed(0)}`;
  return `${currency}${price.toFixed(2)}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function PredictionChart({ entry, currentPrice, currency }: Props) {
  const entryPrice  = entry.entry_price;
  const predicted   = entry.ai_predicted_change_pct;
  const targetPrice = predicted != null
    ? entryPrice * (1 + predicted / 100)
    : null;

  if (targetPrice == null) return null;

  // ── Time ──────────────────────────────────────────────────────────────────
  const startMs   = new Date(entry.entry_date).getTime();
  const endMs     = new Date(entry.target_date).getTime();
  const totalMs   = endMs - startMs;
  const elapsedMs = Date.now() - startMs;
  const elapsed   = totalMs > 0 ? Math.min(1, Math.max(0, elapsedMs / totalMs)) : 0;

  const onTrackToday = entryPrice + (targetPrice - entryPrice) * elapsed;
  const todayPrice   = currentPrice ?? onTrackToday;

  // ── SVG coordinate space (0-100 wide, 0-60 tall) ─────────────────────────
  // Using viewBox 100×60 so percentages map cleanly to screen %
  const W = 100, H = 60, PAD_T = 7, PAD_B = 12;
  const chartH = H - PAD_T - PAD_B;

  const allPrices = [entryPrice, targetPrice, todayPrice];
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const priceRange = maxP - minP || entryPrice * 0.05;
  const padY = priceRange * 0.3;
  const domainMin = minP - padY;
  const domainMax = maxP + padY;

  const scaleX = (f: number) => f * W;
  const scaleY = (p: number) =>
    PAD_T + (1 - (p - domainMin) / (domainMax - domainMin)) * chartH;

  const xEntry  = scaleX(0);
  const xToday  = scaleX(elapsed);
  const xTarget = scaleX(1);
  const yEntry  = scaleY(entryPrice);
  const yToday  = scaleY(todayPrice);
  const yTarget = scaleY(targetPrice);

  const isPositivePred = targetPrice >= entryPrice;
  const actualUp       = currentPrice != null ? currentPrice > entryPrice : isPositivePred;

  const solidColor  = actualUp ? "#16a34a" : "#dc2626";
  const dashedColor = isPositivePred ? "#16a34a" : "#dc2626";

  // ── Badge logic — direction-aware ─────────────────────────────────────────
  const aboveTarget = currentPrice != null && (
    isPositivePred
      ? currentPrice > targetPrice   // bullish: exceeded the upside target ✓
      : currentPrice < targetPrice   // bearish: dropped past the downside target ✓
  );
  const againstPrediction = currentPrice != null && !aboveTarget && (
    isPositivePred
      ? currentPrice < entryPrice    // bullish: stock fell below entry ✗
      : currentPrice > entryPrice    // bearish: stock rose against negative call ✗
  );

  // ── Delta label for TODAY ─────────────────────────────────────────────────
  const actualDelta    = currentPrice != null
    ? ((currentPrice - entryPrice) / entryPrice) * 100
    : null;
  const todayDeltaStr  = actualDelta != null
    ? `${actualDelta >= 0 ? "+" : ""}${actualDelta.toFixed(1)}%`
    : `day ${Math.round(elapsed * 30)}`;
  const todayColor     = actualDelta != null
    ? actualDelta >= 0 ? "#16a34a" : "#dc2626"
    : "#94a3b8";

  // Only show the TODAY label if it won't collide with the entry or target labels.
  // Threshold: 12% from either edge.
  const showTodayLabel = elapsed > 0.13 && elapsed < 0.87;

  return (
    <div className="w-full space-y-1">

      {/* ── Chart — fixed 72 px height so it never blows up on wide screens ── */}
      <div className="relative w-full" style={{ height: "72px" }}>

        {/* SVG: lines + dots only — scales fine with preserveAspectRatio:none */}
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        >
          {/* Dashed: today → target */}
          <line
            x1={xToday} y1={yToday} x2={xTarget} y2={yTarget}
            stroke={dashedColor} strokeWidth="1.2"
            strokeDasharray="3 2" strokeOpacity="0.55"
          />
          {/* Solid: entry → today */}
          <line
            x1={xEntry} y1={yEntry} x2={xToday} y2={yToday}
            stroke={solidColor} strokeWidth="1.8" strokeLinecap="round"
          />
          {/* TODAY vertical tick */}
          <line
            x1={xToday} y1={PAD_T - 2} x2={xToday} y2={H - PAD_B + 2}
            stroke="#cbd5e1" strokeWidth="0.7" strokeDasharray="2.5 1.5"
          />
          {/* Entry dot */}
          <circle cx={xEntry} cy={yEntry} r="2.2" fill="#6366f1" />
          {/* Target dot */}
          <circle cx={xTarget} cy={yTarget} r="2.2"
            fill={isPositivePred ? "#16a34a" : "#dc2626"} />
          {/* Today dot */}
          <circle cx={xToday} cy={yToday} r="2.8"
            fill={currentPrice != null ? solidColor : "#94a3b8"}
            stroke="white" strokeWidth="0.8"
          />
          {/* Glow when exceeded target */}
          {aboveTarget && (
            <circle cx={xToday} cy={yToday} r="5"
              fill={solidColor} fillOpacity="0.15"
            />
          )}
        </svg>

        {/* HTML labels — rendered over the SVG, don't stretch ──────────── */}

        {/* Entry price — bottom left */}
        <div
          style={{ position: "absolute", bottom: 0, left: 0 }}
          className="text-[9px] font-semibold text-indigo-600 leading-none"
        >
          {fmt(entryPrice, currency)}
        </div>

        {/* Today % delta — bottom center (only if not too close to edges) */}
        {showTodayLabel && (
          <div
            style={{
              position: "absolute",
              bottom: 0,
              left: `${elapsed * 100}%`,
              transform: "translateX(-50%)",
              color: todayColor,
            }}
            className="text-[9px] font-bold leading-none whitespace-nowrap"
          >
            {todayDeltaStr}
          </div>
        )}

        {/* Target price — bottom right */}
        <div
          style={{ position: "absolute", bottom: 0, right: 0 }}
          className={`text-[9px] font-semibold leading-none ${
            isPositivePred ? "text-green-600" : "text-red-500"
          }`}
        >
          {fmt(targetPrice, currency)}
        </div>
      </div>

      {/* ── Date row ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between text-[9px] text-gray-400">
        <span>{fmtDate(entry.entry_date)}</span>
        {currentPrice != null && (
          <span className={`font-semibold ${actualUp ? "text-green-600" : "text-red-500"}`}>
            {fmt(currentPrice, currency)} now
          </span>
        )}
        <span>{fmtDate(entry.target_date)}</span>
      </div>

      {/* ── Directional badges ────────────────────────────────────────────── */}
      {aboveTarget && (
        <div className="flex items-center gap-1 bg-emerald-50 border border-emerald-200 rounded-lg px-2 py-1 text-[10px] font-semibold text-emerald-700">
          🚀{" "}
          {isPositivePred
            ? "Already past AI target — AI was conservative!"
            : "Dropped past bearish target — worse than predicted"}
        </div>
      )}
      {againstPrediction && (
        <div className="flex items-center gap-1 bg-amber-50 border border-amber-100 rounded-lg px-2 py-1 text-[10px] font-semibold text-amber-700">
          ⚠️{" "}
          {isPositivePred
            ? "Stock fell below entry — AI bullish call at risk"
            : `Stock up ${todayDeltaStr} against AI's negative outlook`}
        </div>
      )}
    </div>
  );
}
