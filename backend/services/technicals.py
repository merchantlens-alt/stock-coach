"""
Technical indicator computation from OHLCV price history.

All indicators are computed from raw yfinance OHLCV data (no external library needed).
Results are used in two ways:
  1. Formatted as text and injected into the Gemini prompt so the AI can factor
     technical signals into the 30-day prediction.
  2. Returned in StockAnalysisResponse so the frontend can display them as overlays
     on the candlestick chart and as a "Technical Signals" summary card.

Indicators computed:
  RSI-14      — momentum oscillator (overbought > 70, oversold < 30)
  MACD        — trend direction and histogram (bullish / bearish)
  SMA-20      — short-term trend baseline
  SMA-50      — medium-term trend baseline
  Volume trend — recent volume vs 20-day average (institutional conviction)
  Momentum    — 5-day and 20-day price change %
  52-week %   — where current price sits in the year's range
"""
from __future__ import annotations

from typing import Any, Optional

from models.schemas import TechnicalSignals


# ── Core math ─────────────────────────────────────────────────────────────────

def _sma(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return round(sum(values[-period:]) / period, 4)


def _ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average over a list. Returns a list of the same length."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    emas = [values[0]]
    for v in values[1:]:
        emas.append(v * k + emas[-1] * (1 - k))
    return emas


def _rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 2:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period):]
    gains = [max(0.0, d) for d in recent]
    losses = [max(0.0, -d) for d in recent]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1 + rs)), 1)


def _macd(closes: list[float]) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Returns (macd_line, histogram, direction).
    macd_line  = EMA12 - EMA26
    signal     = EMA9 of macd_line
    histogram  = macd_line - signal  (positive = bullish cross)
    """
    if len(closes) < 26:
        return None, None, None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_series = [ema12[i] - ema26[i] for i in range(len(ema26))]
    if len(macd_series) < 9:
        return None, None, None
    signal_series = _ema(macd_series, 9)
    current_macd = macd_series[-1]
    current_signal = signal_series[-1]
    histogram = current_macd - current_signal
    direction = "bullish" if current_macd > 0 else "bearish"
    return round(current_macd, 4), round(histogram, 4), direction


# ── Public API ────────────────────────────────────────────────────────────────

def compute_technicals(candles: list[dict[str, Any]], current_price: float) -> TechnicalSignals:
    """
    Compute all technical indicators from a list of OHLCV candles.

    candles: list of {"time": int, "open": float, "high": float,
                       "low": float, "close": float, "volume": int}
    Expects at least 50 candles for full signal coverage (3-month history = ~63 trading days).
    """
    if not candles:
        return TechnicalSignals()

    # Sort ascending by time
    sorted_candles = sorted(candles, key=lambda c: c["time"])

    closes  = [c["close"]  for c in sorted_candles]
    volumes = [c["volume"] for c in sorted_candles]
    highs   = [c["high"]   for c in sorted_candles]
    lows    = [c["low"]    for c in sorted_candles]

    # ── RSI ───────────────────────────────────────────────────────────────
    rsi_val = _rsi(closes)
    if rsi_val is None:
        rsi_signal = None
    elif rsi_val >= 70:
        rsi_signal = "overbought"
    elif rsi_val <= 30:
        rsi_signal = "oversold"
    else:
        rsi_signal = "neutral"

    # ── MACD ──────────────────────────────────────────────────────────────
    macd_val, macd_hist, macd_direction = _macd(closes)
    # Histogram positive → bullish cross (MACD above signal); negative → bearish
    if macd_hist is not None:
        macd_cross = "bullish_cross" if macd_hist > 0 else "bearish_cross"
    else:
        macd_cross = None

    # ── Moving averages ────────────────────────────────────────────────────
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    price_vs_sma20: Optional[str] = None
    price_vs_sma50: Optional[str] = None
    if sma20 is not None:
        price_vs_sma20 = "above" if current_price > sma20 else "below"
    if sma50 is not None:
        price_vs_sma50 = "above" if current_price > sma50 else "below"

    golden_cross: Optional[bool] = None
    if sma20 is not None and sma50 is not None:
        golden_cross = sma20 > sma50  # True = golden cross (bullish), False = death cross

    # ── Volume trend ───────────────────────────────────────────────────────
    vol_5d_avg  = sum(volumes[-5:])  / min(5,  len(volumes)) if volumes else None
    vol_20d_avg = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else None
    volume_trend: Optional[str] = None
    volume_ratio: Optional[float] = None
    if vol_5d_avg and vol_20d_avg and vol_20d_avg > 0:
        volume_ratio = round(vol_5d_avg / vol_20d_avg, 2)
        if volume_ratio >= 1.5:
            volume_trend = "surging"
        elif volume_ratio >= 1.1:
            volume_trend = "rising"
        elif volume_ratio <= 0.7:
            volume_trend = "falling"
        else:
            volume_trend = "neutral"

    # ── Momentum ───────────────────────────────────────────────────────────
    momentum_5d: Optional[float] = None
    momentum_20d: Optional[float] = None
    if len(closes) >= 6:
        momentum_5d = round((closes[-1] / closes[-6] - 1) * 100, 2)
    if len(closes) >= 21:
        momentum_20d = round((closes[-1] / closes[-21] - 1) * 100, 2)

    # ── 52-week range position ─────────────────────────────────────────────
    if len(highs) >= 50:
        yr_high = max(highs[-min(252, len(highs)):])
        yr_low  = min(lows[-min(252, len(lows)):])
        pct_of_range: Optional[float] = (
            round((current_price - yr_low) / (yr_high - yr_low) * 100, 1)
            if yr_high > yr_low else None
        )
    else:
        pct_of_range = None

    # ── Support / Resistance (recent swing highs/lows) ─────────────────────
    recent_high = round(max(highs[-20:]), 4) if len(highs) >= 20 else None
    recent_low  = round(min(lows[-20:]),  4) if len(lows) >= 20 else None

    return TechnicalSignals(
        rsi_14=rsi_val,
        rsi_signal=rsi_signal,
        macd_line=macd_val,
        macd_histogram=macd_hist,
        macd_signal=macd_cross,
        macd_direction=macd_direction,
        sma_20=sma20,
        sma_50=sma50,
        price_vs_sma20=price_vs_sma20,
        price_vs_sma50=price_vs_sma50,
        golden_cross=golden_cross,
        volume_trend=volume_trend,
        volume_ratio=volume_ratio,
        momentum_5d=momentum_5d,
        momentum_20d=momentum_20d,
        pct_of_52w_range=pct_of_range,
        support=recent_low,
        resistance=recent_high,
    )


def format_for_prompt(t: TechnicalSignals, current_price: float, currency: str = "$") -> str:
    """
    Format TechnicalSignals as a structured text block for the Gemini prompt.
    The goal is to give the model the same information a technical analyst would
    read off a chart — stated in plain language with clear implications.
    """
    lines: list[str] = ["TECHNICAL ANALYSIS (from live price history):"]

    # RSI
    if t.rsi_14 is not None:
        interpretation = {
            "overbought": "stock has risen fast — near-term pullback risk",
            "oversold":   "stock may be oversold — potential reversal/bounce",
            "neutral":    "momentum is in balance, no extreme signal",
        }.get(t.rsi_signal or "", "")
        lines.append(f"- RSI (14-day): {t.rsi_14:.1f} → {t.rsi_signal or 'unknown'}"
                     + (f" ({interpretation})" if interpretation else ""))

    # MACD
    if t.macd_direction is not None:
        hist_desc = "above signal line — bullish momentum" if (t.macd_histogram or 0) > 0 else "below signal line — momentum fading"
        lines.append(f"- MACD: {t.macd_direction} trend; histogram {hist_desc}")

    # Moving averages
    if t.sma_20 is not None:
        pct_dev = ((current_price - t.sma_20) / t.sma_20 * 100)
        lines.append(f"- Price vs 20-day SMA ({currency}{t.sma_20:.2f}): "
                     f"{t.price_vs_sma20} by {abs(pct_dev):.1f}%"
                     + (" — short-term extended" if abs(pct_dev) > 10 else ""))
    if t.sma_50 is not None:
        pct_dev50 = ((current_price - t.sma_50) / t.sma_50 * 100)
        lines.append(f"- Price vs 50-day SMA ({currency}{t.sma_50:.2f}): "
                     f"{t.price_vs_sma50} by {abs(pct_dev50):.1f}%")
    if t.golden_cross is not None:
        cross = "Golden cross (SMA20 > SMA50) — medium-term bullish structure" if t.golden_cross \
                else "Death cross (SMA50 > SMA20) — medium-term bearish structure"
        lines.append(f"- MA structure: {cross}")

    # Volume
    if t.volume_trend is not None:
        ratio_str = f" ({t.volume_ratio:.1f}× 20-day avg)" if t.volume_ratio else ""
        volume_meaning = {
            "surging":  "strong institutional buying — confirms price move",
            "rising":   "above-average buying interest",
            "neutral":  "average participation",
            "falling":  "below-average volume — price move lacks conviction",
        }.get(t.volume_trend, "")
        lines.append(f"- Volume trend: {t.volume_trend}{ratio_str} → {volume_meaning}")

    # Momentum
    if t.momentum_5d is not None:
        lines.append(f"- 5-day momentum: {'+' if t.momentum_5d >= 0 else ''}{t.momentum_5d:.1f}%")
    if t.momentum_20d is not None:
        lines.append(f"- 20-day momentum: {'+' if t.momentum_20d >= 0 else ''}{t.momentum_20d:.1f}%")

    # 52-week range
    if t.pct_of_52w_range is not None:
        zone = "near 52-week high (limited upside from technical resistance)" if t.pct_of_52w_range > 80 \
               else "near 52-week low (potential value zone)" if t.pct_of_52w_range < 20 \
               else "mid-range (no immediate technical ceiling)"
        lines.append(f"- 52-week range position: {t.pct_of_52w_range:.0f}% of range → {zone}")

    # Support / resistance
    if t.support is not None and t.resistance is not None:
        lines.append(f"- Recent support: {currency}{t.support:.2f} | Recent resistance: {currency}{t.resistance:.2f}")

    if len(lines) == 1:
        return ""  # no data

    lines.append("\nUse these technical signals together with the fundamentals and news catalyst to "
                 "refine the 30-day prediction. For example: an overbought RSI after a big gap-up "
                 "suggests a near-term pullback even if the fundamental thesis is intact.")
    return "\n".join(lines)
