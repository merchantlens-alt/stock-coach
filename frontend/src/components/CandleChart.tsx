import {
  createChart,
  ColorType,
  CrosshairMode,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type UTCTimestamp,
} from "lightweight-charts";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Candle, Market } from "../types";
import { usePriceHistory } from "../hooks/useGainers";

const PERIODS = [
  { label: "1M", value: "1mo" },
  { label: "3M", value: "3mo" },
  { label: "6M", value: "6mo" },
  { label: "1Y", value: "1y" },
];

interface CandleChartProps {
  ticker: string;
  market: Market;
}

type SeriesRefs = {
  candle: ReturnType<ReturnType<typeof createChart>["addSeries"]>;
  volume: ReturnType<ReturnType<typeof createChart>["addSeries"]>;
  sma20:  ReturnType<ReturnType<typeof createChart>["addSeries"]>;
  sma50:  ReturnType<ReturnType<typeof createChart>["addSeries"]>;
};

/** Compute a simple moving average as a time-series array ready for lightweight-charts */
function computeSMA(candles: Candle[], period: number): Array<{ time: UTCTimestamp; value: number }> {
  if (candles.length < period) return [];
  const out: Array<{ time: UTCTimestamp; value: number }> = [];
  for (let i = period - 1; i < candles.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += candles[j].close;
    out.push({ time: candles[i].time as UTCTimestamp, value: sum / period });
  }
  return out;
}

export function CandleChart({ ticker, market }: CandleChartProps) {
  const [period, setPeriod] = useState("3mo");
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRef = useRef<SeriesRefs | null>(null);

  const { data, isLoading, isError, refetch } = usePriceHistory(market, ticker, period);

  // Create chart once on mount, destroy on unmount
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#6b7280",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#f3f4f6" },
        horzLines: { color: "#f3f4f6" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: "#e5e7eb",
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: "#e5e7eb",
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: 220,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      borderUpColor: "#10b981",
      borderDownColor: "#ef4444",
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "#10b98133",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const sma20Series = chart.addSeries(LineSeries, {
      color: "#f97316",          // orange-500 — matches TechnicalPanel swatch
      lineWidth: 1,
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      priceLineVisible: false,
    });

    const sma50Series = chart.addSeries(LineSeries, {
      color: "#60a5fa",          // blue-400 — matches TechnicalPanel swatch
      lineWidth: 1,
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      priceLineVisible: false,
    });

    chartRef.current = chart;
    seriesRef.current = { candle: candleSeries, volume: volumeSeries, sma20: sma20Series, sma50: sma50Series };

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Clear stale candles immediately when ticker changes — prevents the previous
  // stock's chart from showing briefly while the new ticker's data is in-flight.
  // Runs BEFORE the data effect so the clear always wins the ordering race.
  useEffect(() => {
    if (!seriesRef.current) return;
    seriesRef.current.candle.setData([]);
    seriesRef.current.volume.setData([]);
    seriesRef.current.sma20.setData([]);
    seriesRef.current.sma50.setData([]);
  }, [ticker]);

  // Feed data whenever candles change
  useEffect(() => {
    if (!seriesRef.current || !data?.candles?.length) return;

    const sorted = [...data.candles].sort((a, b) => a.time - b.time);

    seriesRef.current.candle.setData(
      sorted.map((c: Candle) => ({
        time: c.time as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );

    seriesRef.current.volume.setData(
      sorted.map((c: Candle) => ({
        time: c.time as UTCTimestamp,
        value: c.volume,
        color: c.close >= c.open ? "#10b98133" : "#ef444433",
      }))
    );

    seriesRef.current.sma20.setData(computeSMA(sorted, 20));
    seriesRef.current.sma50.setData(computeSMA(sorted, 50));

    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return (
    <div>
      {/* Period selector */}
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Price chart</p>
        <div className="flex rounded-lg overflow-hidden border border-gray-200 text-xs">
          {PERIODS.map(p => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-2.5 py-1 font-medium transition-colors ${
                period === p.value
                  ? "bg-gray-900 text-white"
                  : "text-gray-500 hover:bg-gray-50"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart container */}
      <div className="relative rounded-xl overflow-hidden border border-gray-100 bg-white">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
            <div className="w-5 h-5 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin" />
          </div>
        )}
        {/* Hard error (network/server failure) */}
        {isError && (
          <div className="flex flex-col items-center justify-center h-[220px] gap-2">
            <p className="text-xs text-gray-400">Chart unavailable</p>
            <button
              onClick={() => refetch()}
              className="flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-700 transition-colors"
            >
              <RefreshCw size={11} /> Retry
            </button>
          </div>
        )}
        {/* Soft empty: yfinance returned no candles (rate-limited, market closed, etc.) */}
        {!isLoading && !isError && data?.candles != null && data.candles.length === 0 && (
          <div className="flex flex-col items-center justify-center h-[220px] gap-2">
            <p className="text-xs text-gray-400">Price history unavailable</p>
            <button
              onClick={() => refetch()}
              className="flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-700 transition-colors"
            >
              <RefreshCw size={11} /> Retry
            </button>
          </div>
        )}
        <div ref={containerRef} className={isError || (!isLoading && data?.candles != null && data.candles.length === 0) ? "hidden" : ""} />
      </div>
    </div>
  );
}
