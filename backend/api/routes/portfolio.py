from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from models.portfolio import (
    AddPortfolioEntryRequest,
    PortfolioEntry,
    PortfolioStatus,
    PortfolioSummary,
    ResolveEntryRequest,
)
from services.portfolio_store import PortfolioStore
from api.deps import get_portfolio_store
from core.logging import get_logger

router = APIRouter(tags=["portfolio"])
log = get_logger(__name__)


def _fetch_prices_sync(tickers: list[str], market: str) -> dict[str, float]:
    """Blocking yfinance batch price fetch — run inside asyncio.to_thread."""
    import yfinance as yf

    suffix = ".NS" if market == "india" else ""
    yf_tickers = [f"{t}{suffix}" for t in tickers]
    prices: dict[str, float] = {}
    try:
        # yf.Tickers handles multi-ticker fast_info efficiently
        batch = yf.Tickers(" ".join(yf_tickers))
        for ticker, yf_ticker in zip(tickers, yf_tickers):
            try:
                fi = batch.tickers[yf_ticker].fast_info
                price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
                if price and float(price) > 0:
                    prices[ticker] = round(float(price), 2)
            except Exception:
                pass
    except Exception as exc:
        log.warning("portfolio.prices_batch_failed", error=str(exc))
    return prices


@router.get("/portfolio/prices")
async def get_portfolio_prices(
    tickers: Annotated[str, Query(description="Comma-separated ticker symbols, max 20")],
    market: Annotated[str, Query()] = "us",
) -> dict:
    """
    Batch-fetch current market prices for portfolio tickers.
    Returns {prices: {TICKER: price}} — missing tickers are silently omitted.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:20]
    if not ticker_list:
        return {"prices": {}}
    prices = await asyncio.to_thread(_fetch_prices_sync, ticker_list, market)
    log.info("portfolio.prices_fetched", market=market, requested=len(ticker_list), returned=len(prices))
    return {"prices": prices}


@router.get("/portfolio", response_model=PortfolioSummary)
async def list_portfolio(
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> PortfolioSummary:
    """Return all tracked positions with win/loss summary."""
    return await store.summary()


@router.post("/portfolio", response_model=PortfolioEntry, status_code=201)
async def add_portfolio_entry(
    body: AddPortfolioEntryRequest,
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> PortfolioEntry:
    """Add a stock to portfolio tracking (holding or watchlist)."""
    today = date.today()
    entry = PortfolioEntry(
        id=str(uuid.uuid4()),
        ticker=body.ticker.upper().strip(),
        market=body.market,
        type=body.type,
        entry_price=body.entry_price,
        purchase_avg=body.purchase_avg,
        shares=body.shares,
        stock_name=body.stock_name,
        ai_predicted_change_pct=body.ai_predicted_change_pct,
        ai_confidence=body.ai_confidence,
        catalyst_type=body.catalyst_type,
        ai_outlook=body.ai_outlook,
        entry_date=today.isoformat(),
        target_date=(today + timedelta(days=30)).isoformat(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await store.save(entry)
    log.info("portfolio.entry_added", ticker=entry.ticker, market=entry.market, type=body.type.value)
    return entry


@router.post("/portfolio/resolve-expired", response_model=dict)
async def mark_expired(
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> dict:
    """Mark all active entries past their target_date as 'expired'.
    Call this daily (cron) or manually. Expired entries prompt user to enter actual price."""
    entries = await store.get_all()
    today = date.today()
    marked = 0
    for entry in entries:
        if entry.status == PortfolioStatus.active:
            if date.fromisoformat(entry.target_date) < today:
                await store.save(entry.model_copy(update={"status": PortfolioStatus.expired}))
                marked += 1
    log.info("portfolio.expired_marked", count=marked)
    return {"marked_expired": marked}


@router.get("/portfolio/{entry_id}", response_model=PortfolioEntry)
async def get_portfolio_entry(
    entry_id: Annotated[str, Path()],
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> PortfolioEntry:
    entry = await store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Portfolio entry not found")
    return entry


@router.delete("/portfolio/{entry_id}", status_code=204, response_model=None)
async def delete_portfolio_entry(
    entry_id: Annotated[str, Path()],
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> None:
    if not await store.delete(entry_id):
        raise HTTPException(status_code=404, detail="Portfolio entry not found")
    log.info("portfolio.entry_deleted", id=entry_id)


@router.post("/portfolio/{entry_id}/resolve", response_model=PortfolioEntry)
async def resolve_portfolio_entry(
    entry_id: Annotated[str, Path()],
    body: ResolveEntryRequest,
    store: Annotated[PortfolioStore, Depends(get_portfolio_store)],
) -> PortfolioEntry:
    """Resolve a position with its actual price. Computes outcome vs AI prediction."""
    entry = await store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Portfolio entry not found")
    if entry.status in (PortfolioStatus.win, PortfolioStatus.loss):
        raise HTTPException(status_code=400, detail="Entry already resolved")

    actual_change_pct = round(
        (body.actual_price - entry.entry_price) / entry.entry_price * 100, 2
    )

    direction_correct: Optional[bool] = None
    if entry.ai_predicted_change_pct is not None:
        direction_correct = (entry.ai_predicted_change_pct >= 0) == (actual_change_pct >= 0)

    if direction_correct is True:
        status = PortfolioStatus.win
    elif direction_correct is False:
        status = PortfolioStatus.loss
    else:
        status = PortfolioStatus.expired  # no prediction to compare — mark expired

    updated = entry.model_copy(update={
        "actual_price": body.actual_price,
        "actual_change_pct": actual_change_pct,
        "direction_correct": direction_correct,
        "status": status,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    })
    await store.save(updated)
    log.info(
        "portfolio.entry_resolved",
        id=entry_id,
        ticker=entry.ticker,
        predicted_pct=entry.ai_predicted_change_pct,
        actual_pct=actual_change_pct,
        correct=direction_correct,
        status=status.value,
    )
    return updated
