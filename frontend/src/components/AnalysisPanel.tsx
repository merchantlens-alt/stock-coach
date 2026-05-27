import { AlertTriangle, ArrowDown, ArrowUp, Minus, Sparkles, X } from "lucide-react";
import type { GainerDetail } from "../types";

interface Props {
  detail: GainerDetail;
  onClose: () => void;
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 70 ? "bg-green-100 text-green-700" : pct >= 50 ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-500";
  return <span className={`text-xs font-semibold px-2 py-0.5 rounded ${color}`}>{pct}% confident</span>;
}

function SignalDot({ signal }: { signal: string }) {
  const map: Record<string, string> = {
    strong: "bg-green-500",
    undervalued: "bg-green-500",
    moderate: "bg-yellow-400",
    fairly_valued: "bg-yellow-400",
    weak: "bg-red-400",
    overvalued: "bg-red-400",
    unknown: "bg-gray-300",
  };
  return <span className={`inline-block w-2 h-2 rounded-full ${map[signal] ?? "bg-gray-300"}`} />;
}

function FundamentalRow({ label, value }: { label: string; value?: number | string | null }) {
  if (value == null) return null;
  return (
    <div className="flex justify-between text-sm py-1 border-b border-gray-100 last:border-0">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-800">
        {typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value}
      </span>
    </div>
  );
}

export function AnalysisPanel({ detail, onClose }: Props) {
  const { gainer, fundamentals, news, analysis, prediction } = detail;
  const currency = gainer.market === "india" ? "₹" : "$";

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-white">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-200 px-5 py-4 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold text-gray-900">{gainer.ticker}</h2>
            <span className="bg-green-100 text-green-700 text-sm font-semibold px-2 py-0.5 rounded-md">
              +{gainer.change_pct.toFixed(1)}%
            </span>
          </div>
          <p className="text-sm text-gray-500">{gainer.name}</p>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400">
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 px-5 py-4 space-y-6">
        {/* Price row */}
        <div className="flex gap-4 text-sm">
          <div>
            <span className="text-gray-400">Price</span>
            <p className="font-semibold text-gray-900">
              {currency}{gainer.price.toLocaleString()}
            </p>
          </div>
          <div>
            <span className="text-gray-400">Change</span>
            <p className="font-semibold text-green-600">
              +{currency}{gainer.change_abs.toFixed(2)}
            </p>
          </div>
          {gainer.sector && (
            <div>
              <span className="text-gray-400">Sector</span>
              <p className="font-semibold text-gray-900">{gainer.sector}</p>
            </div>
          )}
        </div>

        {/* Why it gained */}
        {analysis && (
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-gray-900">Why it gained today</h3>
              <ConfidenceBadge value={analysis.confidence} />
            </div>
            <p className="text-sm text-gray-700 leading-relaxed">{analysis.why_it_gained}</p>
            <ul className="mt-3 space-y-1">
              {analysis.key_catalysts.map((c, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                  <ArrowUp size={13} className="text-green-500 mt-0.5 shrink-0" />
                  {c}
                </li>
              ))}
            </ul>
            <div className="mt-3 rounded-lg bg-gray-50 p-3 text-xs text-gray-600 flex items-start gap-2">
              {analysis.is_sustained ? (
                <ArrowUp size={13} className="text-green-500 mt-0.5 shrink-0" />
              ) : (
                <Minus size={13} className="text-yellow-500 mt-0.5 shrink-0" />
              )}
              <span>
                <strong>{analysis.is_sustained ? "Sustained catalyst:" : "One-time pop:"}</strong>{" "}
                {analysis.sustainability_reason}
              </span>
            </div>
          </section>
        )}

        {/* 30-day prediction */}
        {prediction && (
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-gray-900">30-day outlook</h3>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400 capitalize">{prediction.time_horizon} horizon</span>
                <ConfidenceBadge value={prediction.confidence} />
              </div>
            </div>
            <div className="rounded-lg border border-gray-200 p-3 mb-3 flex items-center gap-3">
              <div
                className={`text-2xl font-bold ${prediction.predicted_change_pct >= 0 ? "text-green-600" : "text-red-500"}`}
              >
                {prediction.predicted_change_pct >= 0 ? "+" : ""}
                {prediction.predicted_change_pct.toFixed(1)}%
              </div>
              <p className="text-sm text-gray-600 flex-1">{prediction.outlook}</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs font-semibold text-green-600 mb-1.5 uppercase tracking-wide">Tailwinds</p>
                <ul className="space-y-1">
                  {prediction.key_tailwinds.map((t, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-gray-600">
                      <ArrowUp size={11} className="text-green-500 mt-0.5 shrink-0" />
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="text-xs font-semibold text-red-500 mb-1.5 uppercase tracking-wide">Risks</p>
                <ul className="space-y-1">
                  {prediction.key_risks.map((r, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-gray-600">
                      <ArrowDown size={11} className="text-red-400 mt-0.5 shrink-0" />
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2">
              {(
                [
                  ["Valuation", prediction.valuation_signal],
                  ["Growth", prediction.growth_signal],
                  ["Debt", prediction.debt_signal],
                ] as [string, string][]
              ).map(([label, signal]) => (
                <div key={label} className="rounded-lg bg-gray-50 p-2 text-center">
                  <p className="text-xs text-gray-400 mb-1">{label}</p>
                  <div className="flex items-center justify-center gap-1.5">
                    <SignalDot signal={signal} />
                    <span className="text-xs font-medium capitalize text-gray-700">
                      {signal.replace("_", " ")}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Fundamentals */}
        {fundamentals && (
          <section>
            <h3 className="font-semibold text-gray-900 mb-2">Fundamentals</h3>
            <div className="rounded-lg border border-gray-200 px-3 py-1">
              <FundamentalRow label="P/E Ratio" value={fundamentals.pe_ratio} />
              <FundamentalRow label="Forward P/E" value={fundamentals.forward_pe} />
              <FundamentalRow
                label="Return on Equity"
                value={fundamentals.roe != null ? `${(fundamentals.roe * 100).toFixed(1)}%` : null}
              />
              <FundamentalRow
                label="Revenue Growth (YoY)"
                value={
                  fundamentals.revenue_growth_yoy != null
                    ? `${(fundamentals.revenue_growth_yoy * 100).toFixed(1)}%`
                    : null
                }
              />
              <FundamentalRow label="Debt / Equity" value={fundamentals.debt_equity} />
              <FundamentalRow
                label="Profit Margin"
                value={
                  fundamentals.profit_margin != null
                    ? `${(fundamentals.profit_margin * 100).toFixed(1)}%`
                    : null
                }
              />
              <FundamentalRow label="Analyst Target" value={fundamentals.analyst_target_price} />
              <FundamentalRow
                label="Analyst Consensus"
                value={fundamentals.analyst_recommendation?.toUpperCase()}
              />
            </div>
          </section>
        )}

        {/* News */}
        {news.length > 0 && (
          <section>
            <h3 className="font-semibold text-gray-900 mb-2">Recent news</h3>
            <ul className="space-y-2">
              {news.map((item, i) => (
                <li key={i} className="rounded-lg border border-gray-100 p-3">
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-blue-700 hover:underline"
                    >
                      {item.title}
                    </a>
                  ) : (
                    <p className="text-sm font-medium text-gray-800">{item.title}</p>
                  )}
                  <p className="text-xs text-gray-400 mt-0.5">{item.source}</p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Related beneficiaries */}
        {analysis?.related_beneficiaries && analysis.related_beneficiaries.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-2">
              <Sparkles size={14} className="text-indigo-500" />
              <h3 className="font-semibold text-gray-900">Who else may benefit</h3>
            </div>
            <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3">
              <div className="flex flex-wrap gap-2 mb-2">
                {analysis.related_beneficiaries.map((ticker) => (
                  <span
                    key={ticker}
                    className="text-sm font-bold bg-white border border-indigo-200 text-indigo-700 px-2.5 py-1 rounded-lg"
                  >
                    {ticker}
                  </span>
                ))}
              </div>
              {analysis.beneficiary_reasoning && (
                <p className="text-xs text-indigo-600 leading-relaxed">{analysis.beneficiary_reasoning}</p>
              )}
            </div>
          </section>
        )}

        {/* Disclaimer */}
        {prediction?.disclaimer && (
          <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            {prediction.disclaimer}
          </div>
        )}
      </div>
    </div>
  );
}
