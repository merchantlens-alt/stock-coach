from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional
import uuid

from pydantic import BaseModel, Field

from models.schemas import Market, CatalystType


class PortfolioEntryType(str, Enum):
    holding = "holding"
    watchlist = "watchlist"


class PortfolioStatus(str, Enum):
    active = "active"
    win = "win"
    loss = "loss"
    expired = "expired"   # past target_date, actual_price not yet entered


class AddPortfolioEntryRequest(BaseModel):
    ticker: str
    market: Market
    type: PortfolioEntryType
    entry_price: float                       # today's market price (prediction tracking anchor)
    purchase_avg: Optional[float] = None     # holdings only — the real cost basis
    shares: Optional[float] = None
    stock_name: Optional[str] = None
    # Snapshot of AI prediction at time of tracking
    ai_predicted_change_pct: Optional[float] = None
    ai_confidence: Optional[float] = None
    catalyst_type: Optional[str] = None
    ai_outlook: Optional[str] = None


class PortfolioEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    market: Market
    type: PortfolioEntryType
    entry_price: float
    purchase_avg: Optional[float] = None
    shares: Optional[float] = None
    stock_name: Optional[str] = None
    ai_predicted_change_pct: Optional[float] = None
    ai_confidence: Optional[float] = None
    catalyst_type: Optional[str] = None
    ai_outlook: Optional[str] = None
    entry_date: str      # YYYY-MM-DD
    target_date: str     # YYYY-MM-DD (entry_date + 30 days)
    status: PortfolioStatus = PortfolioStatus.active
    actual_price: Optional[float] = None
    actual_change_pct: Optional[float] = None
    direction_correct: Optional[bool] = None
    resolved_at: Optional[str] = None       # ISO datetime
    created_at: str                          # ISO datetime


class ResolveEntryRequest(BaseModel):
    actual_price: float


class PortfolioSummary(BaseModel):
    entries: list[PortfolioEntry]
    total_active: int
    total_resolved: int
    wins: int
    losses: int
    win_rate: Optional[float] = None   # 0.0–1.0; None when no resolved entries
