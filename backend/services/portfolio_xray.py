"""
portfolio_xray — analyse a mixed India-MF + US-ETF portfolio.

Data-first: everything below is computed deterministically (allocation, sector &
company look-through for the US sleeve, redundancy, quality flags, gaps vs the
risk target). An AI agent then *summarises* it in plain English — it never
invents numbers.

Honest data tiers:
  • US ETFs  → real sector weights + top holdings (yfinance look-through).
  • India MF → category/cap/geography/quality analysis (mfapi has no holdings),
               so India sector/company look-through is intentionally absent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from core.logging import get_logger
from models.schemas import (
    AllocSlice,
    CompanyHolding,
    PortfolioXrayResponse,
    SectorSlice,
    XrayFundLine,
    XrayRequest,
)

log = get_logger(__name__)

# category → (cap bucket, geography). India + US category names don't collide.
_CAP: dict[str, str] = {
    "Flexi Cap": "Flexi/Multi", "Multi Cap": "Flexi/Multi", "ELSS": "Flexi/Multi",
    "Focused": "Flexi/Multi", "Value/Contra": "Flexi/Multi",
    "Large Cap": "Large", "Large & Mid Cap": "Large & Mid", "Mid Cap": "Mid",
    "Small Cap": "Small", "Special Opportunities": "Thematic",
    "US Broad Market": "Large", "US Large Growth": "Large", "US Large Value": "Large",
    "US Dividend": "Large", "US Mid Cap": "Mid", "US Small Cap": "Small",
    "US Technology": "Sector", "US Sector": "Sector",
    "International Developed": "Intl", "International Total": "Intl",
    "Emerging Markets": "Intl", "Bonds": "Bonds", "REIT": "REIT",
}
_GEO: dict[str, str] = {
    "International Developed": "International", "International Total": "International",
    "Emerging Markets": "International", "Bonds": "Bonds",
}
_US_EQUITY_CATS = {
    "US Broad Market", "US Large Growth", "US Large Value", "US Dividend",
    "US Mid Cap", "US Small Cap", "US Technology", "US Sector", "REIT",
}

_SECTOR_LABEL = {
    "realestate": "Real Estate", "consumer_cyclical": "Consumer Cyclical",
    "basic_materials": "Materials", "consumer_defensive": "Consumer Defensive",
    "technology": "Technology", "communication_services": "Communication",
    "financial_services": "Financials", "utilities": "Utilities",
    "industrials": "Industrials", "energy": "Energy", "healthcare": "Healthcare",
}


def _geo_of(market: str, category: Optional[str]) -> str:
    if market == "us":
        return _GEO.get(category or "", "US Equity")
    return "India Equity"


def _normalise_weights(weights: list[Optional[float]]) -> list[float]:
    if not weights:
        return []
    if all(w is None for w in weights):
        return [round(100.0 / len(weights), 4)] * len(weights)
    return [float(w) if w is not None else 0.0 for w in weights]


def _slices(totals: dict[str, float]) -> list[AllocSlice]:
    out = [AllocSlice(label=k, pct=round(v, 1)) for k, v in totals.items() if v > 0.05]
    out.sort(key=lambda s: s.pct, reverse=True)
    return out


def _gaps_for_risk(risk: str, caps: dict[str, float], geo: dict[str, float]) -> list[str]:
    small = caps.get("Small", 0)
    mid = caps.get("Mid", 0)
    intl = geo.get("International", 0)
    bonds = geo.get("Bonds", 0) + caps.get("Bonds", 0)
    gaps: list[str] = []

    if intl < 5:
        gaps.append("No meaningful international exposure — adds diversification beyond your home market.")
    if risk == "aggressive":
        if small + mid < 25:
            gaps.append("Light on mid/small-cap for an aggressive profile — that's where long-run growth concentrates.")
        if bonds > 15:
            gaps.append("More bonds than an aggressive 10-15y horizon needs — they cap your upside.")
    elif risk == "conservative":
        if bonds < 10:
            gaps.append("No bond/defensive ballast — a conservative profile usually wants 15-25% to cushion drawdowns.")
        if small > 20:
            gaps.append("Heavy small-cap for a conservative profile — it raises volatility more than it should.")
    else:  # balanced
        if small + mid < 15:
            gaps.append("Could use a bit more mid/small-cap growth for a balanced 7+ year horizon.")
        if bonds < 5 and intl < 5:
            gaps.append("Almost entirely home-market equity — consider a small international or debt sleeve.")
    return gaps


async def run_xray(india_svc: Any, us_svc: Any, agent: Any, req: XrayRequest) -> PortfolioXrayResponse:
    weights = _normalise_weights([f.weight for f in req.funds])
    items = list(zip(req.funds, weights))
    has_india = any(f.market == "india" for f, _ in items)
    has_us = any(f.market == "us" for f, _ in items)

    # Reuse the cached scans to resolve category + quality flags per fund.
    india_scan, us_scan = await asyncio.gather(
        india_svc.scan(category=None) if has_india else _empty(),
        us_svc.scan(category=None) if has_us else _empty(),
    )
    india_by_code = {f.scheme_code: f for f in (india_scan.funds if india_scan else [])}
    us_by_code = {f.scheme_code: f for f in (us_scan.funds if us_scan else [])}

    fund_lines: list[XrayFundLine] = []
    cap_tot: dict[str, float] = {}
    geo_tot: dict[str, float] = {}
    cat_counts: dict[str, list[str]] = {}
    flagged: list[str] = []

    for f, w in items:
        scanned = (us_by_code if f.market == "us" else india_by_code).get(f.code)
        category = scanned.category if scanned else None
        flag = None
        if scanned:
            if scanned.is_closet_index:
                flag = "closet"
            elif scanned.is_decaying:
                flag = "decaying"
            elif scanned.entry_signal == "avoid":
                flag = "avoid"
        if flag:
            flagged.append(f"{f.name} ({flag})")

        cap = _CAP.get(category or "", "Other")
        geo = _geo_of(f.market, category)
        cap_tot[cap] = cap_tot.get(cap, 0) + w
        geo_tot[geo] = geo_tot.get(geo, 0) + w
        cat_counts.setdefault(category or "Other", []).append(f.name)

        fund_lines.append(XrayFundLine(
            market=f.market, code=f.code, name=f.name, category=category, weight=round(w, 1),
            fund_score=scanned.fund_score if scanned else None, flag=flag,
        ))

    # ── US look-through: sectors + top companies, weighted by portfolio share ──
    sector_tot: dict[str, float] = {}
    company_tot: dict[str, tuple[str, float]] = {}   # symbol → (name, pct)
    us_items = [(f, w) for f, w in items if f.market == "us"]
    if us_items:
        holdings = await asyncio.gather(*[us_svc.get_holdings(f.code) for f, _ in us_items])
        for (f, w), (sectors, top) in zip(us_items, holdings):
            for skey, sw in sectors.items():
                label = _SECTOR_LABEL.get(skey, skey.replace("_", " ").title())
                sector_tot[label] = sector_tot.get(label, 0) + w * sw
            for sym, name, hp in top:
                prev = company_tot.get(sym, (name, 0.0))
                company_tot[sym] = (name, prev[1] + w * hp)

    sectors = [SectorSlice(sector=k, pct=round(v, 1)) for k, v in sector_tot.items() if v > 0.05]
    sectors.sort(key=lambda s: s.pct, reverse=True)
    companies = [
        CompanyHolding(symbol=sym, name=nm, pct=round(p, 1))
        for sym, (nm, p) in company_tot.items() if p > 0.05
    ]
    companies.sort(key=lambda c: c.pct, reverse=True)
    sector_coverage = round(sum(w for f, w in us_items) / 100, 2) if us_items else 0.0

    # ── Redundancy: multiple funds in the same (overlapping) category ──────────
    redundancies: list[str] = []
    for cat, names in cat_counts.items():
        if len(names) >= 2 and cat in {"Flexi Cap", "Multi Cap", "Large Cap", "US Broad Market", "US Large Growth"}:
            redundancies.append(f"{len(names)} {cat} funds ({', '.join(n.split(' - ')[0][:24] for n in names)}) — these overlap heavily; one is usually enough.")

    gaps = _gaps_for_risk(req.risk, cap_tot, geo_tot)

    geography = _slices(geo_tot)
    caps = _slices(cap_tot)

    # ── AI narrative (data-first: agent only summarises the computed picture) ──
    narrative = ""
    try:
        narrative = await agent.summarise(
            risk=req.risk, geography=geography, caps=caps, sectors=sectors[:6],
            companies=companies[:6], redundancies=redundancies, gaps=gaps,
            flagged=flagged, sector_coverage=sector_coverage, has_india=has_india,
        )
    except Exception as exc:
        log.warning("xray.narrative_failed", error=str(exc))

    log.info("xray.done", funds=len(items), us=len(us_items), flagged=len(flagged))
    return PortfolioXrayResponse(
        risk=req.risk, geography=geography, caps=caps, sectors=sectors[:10],
        top_companies=companies[:10], sector_coverage=sector_coverage,
        redundancies=redundancies, gaps=gaps, flagged_funds=flagged,
        narrative=narrative, funds=fund_lines,
    )


async def _empty():
    return None
