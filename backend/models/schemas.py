from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


Market = Literal["us", "india"]
Sentiment = Literal["very_positive", "positive", "neutral", "negative", "very_negative"]
MarketSentiment = Literal["very_bullish", "bullish", "mixed", "bearish", "very_bearish"]
CatalystType = Literal[
    "earnings", "fda_approval", "acquisition", "partnership",
    "analyst_upgrade", "macro", "technical", "regulatory", "unknown"
]
OutlookHorizon = Literal["days", "weeks", "months"]
FundamentalSignal = Literal["strong", "moderate", "weak", "unknown"]
ValuationSignal = Literal["undervalued", "fairly_valued", "overvalued", "unknown"]
QualityLabel = Literal["Strong", "Moderate", "Watch", "Risky"]
SignalTier = Literal["confirmed", "catalyst", "mover"]
Period = Literal["1d", "1w", "1m"]


def compute_quality_score(
    price: float, volume: int, change_pct: float, ticker: str
) -> tuple[float, QualityLabel]:
    score = 0.0

    # Price: higher price = more established company
    if price >= 50:
        score += 2.5
    elif price >= 20:
        score += 2.0
    elif price >= 10:
        score += 1.5
    else:
        score += 1.0

    # Volume: more volume = real institutional interest
    if volume >= 20_000_000:
        score += 3.0
    elif volume >= 5_000_000:
        score += 2.5
    elif volume >= 2_000_000:
        score += 2.0
    elif volume >= 1_000_000:
        score += 1.5
    else:
        score += 1.0

    # Change % sweet spot — 5-20% is genuine buying, >60% is suspicious
    if 5 <= change_pct <= 15:
        score += 2.5
    elif 15 < change_pct <= 25:
        score += 2.0
    elif 25 < change_pct <= 40:
        score += 1.5
    elif 40 < change_pct <= 60:
        score += 1.0
    else:
        score += 0.3

    # Ticker length: short tickers = major exchange listing
    if len(ticker) <= 4:
        score += 1.0
    else:
        score += 0.5

    # Normalize to 0–10
    score = min(10.0, round(score * 10 / 9, 1))

    if score >= 7.5:
        label: QualityLabel = "Strong"
    elif score >= 5.5:
        label = "Moderate"
    elif score >= 3.5:
        label = "Watch"
    else:
        label = "Risky"

    return score, label


class StockGainer(BaseModel):
    ticker: str
    name: str
    market: Market
    price: float
    change_pct: float = Field(description="Percentage change today (positive for gainers)")
    change_abs: float = Field(description="Absolute price change today")
    volume: int
    avg_volume: Optional[int] = None
    market_cap: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    quality_score: Optional[float] = None
    quality_label: Optional[QualityLabel] = None
    signal_tier: SignalTier = "mover"
    # Enriched at serve time from the analysis cache — never stored in the gainers list cache.
    # None = no cached prediction yet; present = AI has analysed this stock before.
    ai_prediction_pct: Optional[float] = None
    ai_prediction_confidence: Optional[float] = None

    @field_validator("change_pct")
    @classmethod
    def round_change_pct(cls, v: float) -> float:
        # Gainers list only ever has positive values (filtered upstream in market_data.py).
        # Searched stocks can be negative — allow the real value through so the UI
        # can display the correct sign and colour.
        return round(v, 2)


class FundamentalsData(BaseModel):
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    roe: Optional[float] = None
    debt_equity: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    profit_margin: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    analyst_target_price: Optional[float] = None
    analyst_recommendation: Optional[str] = None
    # Growth Triggers enrichment — from yfinance
    ttm_revenue: Optional[float] = None           # trailing 12-month revenue ($M or ₹Cr)
    ebitda_margin: Optional[float] = None         # as a decimal, e.g. 0.32 = 32%
    market_cap_value: Optional[float] = None      # market cap in raw units
    insider_holding_pct: Optional[float] = None   # fraction, e.g. 0.15 = 15%


class NewsItem(BaseModel):
    title: str
    source: str
    published_at: Optional[datetime] = None
    url: Optional[str] = None
    summary: Optional[str] = None


class GainerAnalysis(BaseModel):
    ticker: str
    why_it_moved: str = ""     # direction-neutral: "fell" for declines, "surged" for gains
    why_it_gained: str = ""    # legacy alias — kept for backward-compat with cached responses
    key_catalysts: list[str]

    @property
    def move_explanation(self) -> str:
        """Return whichever field is populated — new cache uses why_it_moved."""
        return self.why_it_moved or self.why_it_gained
    catalyst_type: CatalystType
    sentiment: Sentiment
    is_sustained: bool
    sustainability_reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    related_beneficiaries: list[str] = Field(default_factory=list)
    beneficiary_reasoning: Optional[str] = None
    comparison_to_gainers: Optional[str] = None


class StockPrediction(BaseModel):
    ticker: str
    outlook: str
    predicted_change_pct: float
    confidence: float = Field(ge=0.0, le=1.0)
    time_horizon: OutlookHorizon
    key_risks: list[str]
    key_tailwinds: list[str]
    valuation_signal: ValuationSignal
    growth_signal: FundamentalSignal
    debt_signal: FundamentalSignal
    disclaimer: str = Field(
        default=(
            "This is AI-generated analysis for educational purposes only. "
            "It is not investment advice. Always consult a registered financial advisor."
        )
    )


class MarketSummary(BaseModel):
    market: Market
    narrative: str
    themes: list[str]
    dominant_sector: Optional[str] = None
    sentiment: MarketSentiment
    watch_list: list[str]
    watch_reason: str
    from_cache: bool = False
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class GainerDetail(BaseModel):
    """Fast data response — gainer info, fundamentals, news. No AI. ~3-5 s cold."""
    gainer: StockGainer
    fundamentals: Optional[FundamentalsData] = None
    news: list[NewsItem] = Field(default_factory=list)
    # analysis / prediction intentionally absent — served by /analyse sub-endpoint
    from_cache: bool = False
    fetched_at: Optional[datetime] = None


class TechnicalSignals(BaseModel):
    """Computed technical indicators from live OHLCV price history."""
    rsi_14: Optional[float] = None
    rsi_signal: Optional[str] = None            # "overbought" | "neutral" | "oversold"
    macd_line: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_signal: Optional[str] = None           # "bullish_cross" | "bearish_cross"
    macd_direction: Optional[str] = None        # "bullish" | "bearish"
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    price_vs_sma20: Optional[str] = None        # "above" | "below"
    price_vs_sma50: Optional[str] = None        # "above" | "below"
    golden_cross: Optional[bool] = None         # True = golden cross (SMA20 > SMA50)
    volume_trend: Optional[str] = None          # "surging" | "rising" | "neutral" | "falling"
    volume_ratio: Optional[float] = None        # recent 5d avg / 20d avg
    momentum_5d: Optional[float] = None         # 5-day price change %
    momentum_20d: Optional[float] = None        # 20-day price change %
    pct_of_52w_range: Optional[float] = None    # 0-100 where price sits in 52-week range
    support: Optional[float] = None             # recent 20-day low (support level)
    resistance: Optional[float] = None          # recent 20-day high (resistance level)


class StockAnalysisResponse(BaseModel):
    """Slow AI response — analysis + 30-day prediction. ~10-15 s cold, cached 6 h."""
    ticker: str
    market: Market
    analysis: Optional[GainerAnalysis] = None
    prediction: Optional[StockPrediction] = None
    technicals: Optional[TechnicalSignals] = None
    quarterly: Optional[QuarterlySnapshot] = None  # last 6 quarters — fed to AI + shown in UI
    from_cache: bool = False
    analysed_at: Optional[datetime] = None


class GainersListResponse(BaseModel):
    market: Market
    period: Period = "1d"
    date: str
    gainers: list[StockGainer]
    summary: Optional[MarketSummary] = None
    from_cache: bool = False
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    cache: Literal["redis", "memory"]
    ai: Literal["vertex_ai", "mock"]


# ── Conviction / Thesis schemas ───────────────────────────────────────────────

ThesisRiskLevel = Literal["lower", "focused", "higher"]
ThesisConfirmerStatus = Literal["confirmed", "watch", "risk"]
EntrySignalLevel = Literal["strong", "fair", "wait"]


class ThesisInstrument(BaseModel):
    ticker: str
    name: str
    risk_level: ThesisRiskLevel
    description: str = Field(description="E.g. 'Diversified basket', 'Pure-play US DRAM'")
    rationale: str = Field(description="Why this instrument expresses the thesis")


class ThesisConfirmer(BaseModel):
    text: str = Field(description="Evidence statement, e.g. 'NVIDIA HBM orders up 40%'")
    status: ThesisConfirmerStatus


class ThesisConviction(BaseModel):
    belief: str = Field(description="Cleaned-up version of the user's stated belief")
    theme_label: str = Field(description="Short title, e.g. 'AI MEMORY DEMAND' (all caps, 2-4 words)")
    conviction_score: float = Field(ge=0.0, le=100.0, description="0-100 score for thesis strength")
    thesis_summary: str = Field(description="1-2 sentence thesis statement explaining the structural shift")
    instruments: list[ThesisInstrument] = Field(description="3 instruments: lower/focused/higher risk")
    confirmers: list[ThesisConfirmer] = Field(description="3-5 real-world data points confirming or challenging the thesis")
    entry_signal: EntrySignalLevel
    entry_explanation: str = Field(description="Short explanation of entry timing")
    exit_triggers: list[str] = Field(description="2-3 specific conditions that would invalidate the thesis")
    time_horizon: str = Field(description="Expected thesis duration, e.g. 'multi-year', '1-2 years'")
    disclaimer: str = Field(
        default=(
            "This is AI-generated analysis for educational purposes only. "
            "It is not investment advice. Always consult a registered financial advisor."
        )
    )


class ConvictionRequest(BaseModel):
    belief: str = Field(description="The user's stated investment belief/thesis", min_length=5, max_length=500)
    market: Market = "us"


class ConvictionResponse(BaseModel):
    conviction: ThesisConviction
    from_cache: bool = False
    analysed_at: Optional[datetime] = None


# ── Radar / catalyst-scanner schemas ─────────────────────────────────────────

class RadarSignal(BaseModel):
    """One structural theme identified from news that could move specific stocks."""
    theme: str = Field(description="Short theme label, e.g. 'AI Memory Bandwidth Squeeze'")
    narrative: str = Field(description="2-3 sentence explanation of the theme and why it matters now")
    tickers: list[str] = Field(description="1-4 tickers that haven't fully priced in this theme yet")
    catalyst_type: CatalystType
    conviction: float = Field(ge=0.0, le=1.0, description="0-1 evidence score")
    time_frame: str = Field(description="When this could play out, e.g. '3-5 days', '1-2 weeks'")
    evidence: str = Field(description="The specific news item or data point driving this signal")
    source_headlines: list[str] = Field(description="1-3 headlines that support this theme")


class RadarResponse(BaseModel):
    market: Market
    signals: list[RadarSignal] = Field(default_factory=list)
    no_signals_reason: Optional[str] = None  # set when signals is empty
    from_cache: bool = False
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Quarterly results schemas ─────────────────────────────────────────────────

class QuarterlyResult(BaseModel):
    """One quarter of financial results."""
    period: str                          # e.g. "Sep 2024" or "Sep '24"
    revenue: Optional[float] = None      # Cr for India, $M for US
    operating_profit: Optional[float] = None
    opm_pct: Optional[float] = None      # operating profit margin %
    net_profit: Optional[float] = None   # PAT
    eps: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None   # % vs same quarter last year
    pat_growth_yoy: Optional[float] = None        # % vs same quarter last year


class QuarterlySnapshot(BaseModel):
    """
    Last 6 quarters of results for a stock, plus computed trend labels.
    Injected into Gemini prompt to ground the 30-day prediction in earnings reality.
    """
    ticker: str
    market: Market
    quarters: list[QuarterlyResult]  # most recent first, up to 6
    revenue_trend: str   # accelerating | stable | decelerating | declining | recovering | unknown
    margin_trend: str    # expanding | stable | compressing | unknown
    earnings_trend: str  # accelerating | stable | decelerating | declining | recovering | unknown
    currency: str = "₹"
    unit: str = "Cr"     # Cr for India, M for US
    quarterly_insight: Optional[str] = None  # plain-English earnings verdict surfaced in the UI


# ── Catalyst Scanner schemas ───────────────────────────────────────────────────

# ── Growth Triggers schemas ───────────────────────────────────────────────────

TriggerConviction = Literal["HIGH", "MEDIUM", "OPTIONALITY"]


class GrowthTrigger(BaseModel):
    """One specific business lever that could drive earnings growth."""
    name: str = Field(description="Short trigger label, e.g. 'Premium Mix Shift'")
    what: str = Field(description="Plain-English explanation of what this trigger is")
    p_and_l_impact: str = Field(description="Quantified P&L impact, e.g. 'Adds 200-300 bps to margin'")
    timeline: str = Field(description="When this shows up in results, e.g. 'Q2 FY26', 'H2 2025'")
    conviction: TriggerConviction
    watch_for: str = Field(description="Specific metric or event to monitor, e.g. 'Gross margin >45%'")


class RiskItem(BaseModel):
    """One investment risk with plain-English context."""
    name: str
    what: str = Field(description="What this risk is in plain English")
    why_it_matters: str = Field(description="P&L or stock-price impact if this materialises")


class ScorecardRow(BaseModel):
    """One row of the investment scorecard table."""
    dimension: str = Field(description="e.g. 'Revenue Growth', 'Margin Expansion'")
    rating: str = Field(description="e.g. 'Strong', 'Moderate', 'Weak', 'Rich', 'Fair', 'Cheap'")
    note: str = Field(description="One sentence explanation")


class GrowthTriggersReport(BaseModel):
    """AI-generated institutional-style growth triggers research note."""
    ticker: str
    market: Market
    company_snapshot: str = Field(description="3-4 sentences: what company does, what changed recently, revenue/margin snapshot, market cap context")
    triggers: list[GrowthTrigger] = Field(description="3-5 specific growth triggers")
    already_in_price: str = Field(description="What the current valuation implies market already expects")
    upside_scenario: str = Field(description="Additional upside if all triggers play out")
    key_risks: list[RiskItem] = Field(description="2-3 key risks with plain-English context")
    scorecard: list[ScorecardRow] = Field(description="5-row investment scorecard")
    is_error: bool = False   # True when AI call failed — route skips cache, UI shows retry
    from_cache: bool = False
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    disclaimer: str = Field(
        default=(
            "This is AI-generated analysis for educational purposes only. "
            "It is not investment advice. Always consult a registered financial advisor."
        )
    )


CatalystSignal = Literal["strong_move", "emerging", "noise", "potential"]


class CatalystPlay(BaseModel):
    """One moving stock with momentum score and AI verdict."""
    ticker: str
    name: str
    market: Market
    sector: Optional[str] = None
    price: float
    change_pct: float
    change_abs: float
    volume: int
    avg_volume: Optional[int] = None      # 20-day average volume
    volume_ratio: Optional[float] = None  # current / avg, e.g. 3.2 = 3.2× average
    momentum_score: float                 # 0-100 composite score
    catalyst_type: CatalystType
    signal: CatalystSignal                # strong_move | emerging | noise
    headline_catalyst: Optional[str] = None  # top catalyst headline
    ai_verdict: str = ""                  # 2-sentence plain English explanation
    # Enriched from analysis cache — None if stock hasn't been analysed yet
    ai_prediction_pct: Optional[float] = None
    ai_prediction_confidence: Optional[float] = None


class CatalystScanResponse(BaseModel):
    market: Market
    plays: list[CatalystPlay] = Field(default_factory=list)
    from_cache: bool = False
    scanned_at: datetime = Field(default_factory=datetime.utcnow)
