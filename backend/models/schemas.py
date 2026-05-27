from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


Market = Literal["us", "india"]
Sentiment = Literal["very_positive", "positive", "neutral", "negative", "very_negative"]
CatalystType = Literal[
    "earnings", "fda_approval", "acquisition", "partnership",
    "analyst_upgrade", "macro", "technical", "regulatory", "unknown"
]
OutlookHorizon = Literal["days", "weeks", "months"]
FundamentalSignal = Literal["strong", "moderate", "weak", "unknown"]
ValuationSignal = Literal["undervalued", "fairly_valued", "overvalued", "unknown"]


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

    @field_validator("change_pct")
    @classmethod
    def must_be_positive_for_gainer(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Gainers must have positive change_pct")
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


class NewsItem(BaseModel):
    title: str
    source: str
    published_at: Optional[datetime] = None
    url: Optional[str] = None
    summary: Optional[str] = None


class GainerAnalysis(BaseModel):
    """Output from the Gainer Analyst AI agent."""
    ticker: str
    why_it_gained: str = Field(description="Plain-English explanation of the gain catalyst")
    key_catalysts: list[str] = Field(description="Bullet list of specific catalysts")
    catalyst_type: CatalystType
    sentiment: Sentiment
    is_sustained: bool = Field(
        description="True if the catalyst likely drives sustained momentum vs a one-time pop"
    )
    sustainability_reason: str
    confidence: float = Field(ge=0.0, le=1.0)


class StockPrediction(BaseModel):
    """Output from the Predictor AI agent."""
    ticker: str
    outlook: str = Field(description="Plain-English 30-day outlook for a beginner investor")
    predicted_change_pct: float = Field(
        description="AI estimated % price change over the horizon"
    )
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


class GainerDetail(BaseModel):
    """Full detail response for a single gainer ticker."""
    gainer: StockGainer
    fundamentals: Optional[FundamentalsData] = None
    news: list[NewsItem] = Field(default_factory=list)
    analysis: Optional[GainerAnalysis] = None
    prediction: Optional[StockPrediction] = None
    from_cache: bool = False
    analysed_at: Optional[datetime] = None


class GainersListResponse(BaseModel):
    market: Market
    date: str
    gainers: list[StockGainer]
    from_cache: bool = False
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    cache: Literal["redis", "memory"]
    ai: Literal["vertex_ai", "mock"]
