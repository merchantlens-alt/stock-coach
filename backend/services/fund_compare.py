"""
fund_compare — head-to-head lumpsum backtest: a user's basket of funds vs the
generic model portfolio, over the trailing 1 / 3 / 5 years.

Works for either market by taking a `service` that exposes:
  • build_model_portfolio(risk) -> ModelPortfolioResponse
  • get_price_series(code)       -> [(datetime, nav), …] oldest→newest

Lumpsum semantics: "if you'd invested ₹amount across these funds N years ago,
what's it worth today?" Per-fund weights default to equal-weight; funds without
N years of history are dropped for that window and the rest renormalised.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from core.logging import get_logger
from models.schemas import (
    CompareFundReturn,
    CompareRequest,
    CompareResponse,
    CompareWindow,
)
from services.fund_metrics import basket_sip, growth_over_years

log = get_logger(__name__)

_WINDOWS = (1, 3, 5)


def _normalise_weights(weights: list[Optional[float]]) -> list[float]:
    """Equal-weight if none given; otherwise treat missing as 0."""
    if not weights:
        return []
    if all(w is None for w in weights):
        return [round(100.0 / len(weights), 4)] * len(weights)
    return [float(w) if w is not None else 0.0 for w in weights]


async def run_compare(service: Any, req: CompareRequest) -> CompareResponse:
    model = await service.build_model_portfolio(req.risk)

    user_weights = _normalise_weights([uf.weight for uf in req.user_funds])
    user_meta = [
        (uf.code, uf.name, w) for uf, w in zip(req.user_funds, user_weights)
    ]
    model_meta = [
        (h.fund.scheme_code, h.fund.name, h.weight_pct) for h in model.holdings
    ]

    # Fetch every needed price series once, in parallel. One retry on an empty
    # result so a transient network blip doesn't blank a whole basket.
    async def fetch(code: str) -> list[tuple[datetime, float]]:
        try:
            s = await service.get_price_series(code)
            if not s:
                await asyncio.sleep(0.3)
                s = await service.get_price_series(code)
            return s or []
        except Exception:
            return []

    codes = list({c for c, _, _ in user_meta} | {c for c, _, _ in model_meta})
    series_list = await asyncio.gather(*[fetch(c) for c in codes])
    series_by_code: dict[str, list[tuple[datetime, float]]] = dict(zip(codes, series_list))

    def basket(meta: list[tuple[str, str, float]]) -> list[tuple[list, float]]:
        return [(series_by_code.get(c, []), w) for c, _, w in meta]

    user_basket = basket(user_meta)
    model_basket = basket(model_meta)

    windows: list[CompareWindow] = []
    for y in _WINDOWS:
        u_corpus, u_inv, uc = basket_sip(user_basket, req.amount, y)
        m_corpus, m_inv, mc = basket_sip(model_basket, req.amount, y)
        invested = u_inv if u_inv is not None else m_inv
        windows.append(CompareWindow(
            years=y,
            invested=round(invested) if invested is not None else None,
            user_value=round(u_corpus) if u_corpus is not None else None,
            user_gain_pct=round((u_corpus / u_inv - 1) * 100, 1) if u_corpus and u_inv else None,
            model_value=round(m_corpus) if m_corpus is not None else None,
            model_gain_pct=round((m_corpus / m_inv - 1) * 100, 1) if m_corpus and m_inv else None,
            user_coverage=uc, model_coverage=mc,
        ))

    def lines(meta: list[tuple[str, str, float]]) -> list[CompareFundReturn]:
        out: list[CompareFundReturn] = []
        for code, name, w in meta:
            s = series_by_code.get(code, [])
            def r(years: int) -> Optional[float]:
                g = growth_over_years(s, years)
                return round((g - 1) * 100, 1) if g is not None else None
            out.append(CompareFundReturn(
                code=code, name=name, weight=round(w, 1),
                returns_1y=r(1), returns_3y=r(3), returns_5y=r(5),
            ))
        return out

    log.info("fund_compare.done", market=req.market, user_funds=len(user_meta), model_funds=len(model_meta))
    return CompareResponse(
        market=req.market, risk=req.risk, amount=req.amount, windows=windows,
        user_funds=lines(user_meta), model_funds=lines(model_meta),
    )
