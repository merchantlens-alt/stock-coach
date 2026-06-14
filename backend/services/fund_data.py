"""
FundDataService — advisor-grade India mutual-fund scanner via the free mfapi.in API.

Philosophy (v2)
───────────────
A junior screens the same 20 famous funds everyone already owns. A seasoned
advisor does the opposite:

  1. DISCOVER the whole universe — every open-ended equity Direct-Growth fund,
     including new launches (WhiteOak Special Opportunities, Helios, Bandhan, …),
     classified into categories from the scheme name. No hand-picked list.
  2. SCORE within category — percentile vs peers, because a 12% CAGR is poor for
     small-cap and good for large-cap. Absolute cross-category ranking is a lie.
  3. SURFACE young funds, don't bury them — missing 3y/5y metrics rank NEUTRAL,
     so a strong 18-month-old fund competes on what it has and gets a "Discovery"
     badge rather than a zero.
  4. RULE OUT saturation — funds whose recent return has decayed below their long-
     term CAGR (AUM bloat / style drift), and closet indexers that hug their
     benchmark while charging active fees.

Data constraint: mfapi gives NAV history + basic meta only — no AUM / expense /
holdings. So saturation is detected via NAV-derived proxies (return decay +
closet-index alpha vs a passive benchmark). True AUM-based saturation is a later
enhancement (AMFI AAUM disclosures are a scrape, not an API).
"""
from __future__ import annotations

import asyncio
import re
import statistics
import time
from datetime import datetime
from typing import Any, Optional

import httpx

from core.config import Settings
from core.logging import get_logger
from models.schemas import FundScanResponse, FundScheme, ModelPortfolioResponse
from services.fund_portfolio import assemble_portfolio
from services.fund_metrics import (
    build_entry_reason,
    closet_metrics,
    compute_metrics,
    percentile_ranks,
    score_fund,
    track_record_tier,
)

log = get_logger(__name__)

_MFAPI_BASE = "https://api.mfapi.in"
_UNIVERSE_TTL = 24 * 60 * 60   # re-resolve the scheme universe once a day
_FETCH_CONCURRENCY = 12        # bounded parallel NAV fetches (be a good API citizen)
_MIN_HISTORY = 126             # ~6 months of NAV — below this we can't say anything
_MAX_NAV_STALENESS_DAYS = 14   # latest NAV older than this ⇒ dead/merged fund, exclude

# ── Plan / non-equity exclusions ──────────────────────────────────────────────

_EXCLUDE_TOKENS = ("idcw", "dividend", "payout", "reinvest", "bonus", "series", "fof", "segregated")
_GROWTH_TOKENS = ("growth", "cumulative")
_NON_EQUITY = (
    "debt", "liquid", "overnight", "gilt", "bond", "arbitrage", "hybrid",
    "balanced advantage", "money market", "ultra short", "low duration",
    "credit risk", "credit opportun", "cash management", "banking and psu",
    "corporate bond", "gold", "silver", "floater", "dynamic bond", "short duration",
    "medium duration", "conservative", "equity savings", "multi asset",
    "asset allocat", "retirement", "children", "solution",
)
_GLOBAL = ("international", "global", "overseas", "nasdaq", "greater china",
           "emerging market", "world", "fang", "us equity", "us bluechip",
           " us ", "u.s.", "msci", "eafe", "s&p 500", "dow jones", "hang seng",
           "japan", "europe", "china", "taiwan", "korea", "brazil", "asean")

# ── Category taxonomy (first match wins; order matters) ────────────────────────
# Deliberately keeps diversified active equity + genuine special-opportunities
# funds; the long tail of narrow sectoral/index bets is excluded as non-core.
_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("ELSS",            ("elss", "tax saver", "taxsaver")),
    ("Flexi Cap",       ("flexi cap", "flexicap")),
    ("Multi Cap",       ("multi cap", "multicap")),
    ("Large & Mid Cap", ("large & mid", "large and mid")),
    ("Large Cap",       ("large cap", "largecap", "bluechip", "blue chip", "top 100", "top 200")),
    ("Mid Cap",         ("mid cap", "midcap", "emerging equit")),
    ("Small Cap",       ("small cap", "smallcap")),
    ("Focused",         ("focused",)),
    ("Value/Contra",    ("value", "contra")),
    # Genuine go-anywhere special-situations / cycle funds only (e.g. WhiteOak
    # Special Opportunities) — NOT narrow sectoral "X Opportunities" funds.
    ("Special Opportunities", ("special opportun", "business cycle")),
]

# Category → passive benchmark (resolved to a broad index fund's NAV series).
_BENCHMARK_BY_CATEGORY: dict[str, str] = {
    "Large Cap":        "nifty50",
    "Large & Mid Cap":  "nifty50",
    "Flexi Cap":        "nifty50",
    "Multi Cap":        "nifty50",
    "ELSS":             "nifty50",
    "Focused":          "nifty50",
    "Value/Contra":     "nifty50",
    "Special Opportunities": "nifty50",
    "Mid Cap":          "midcap150",
    "Small Cap":        "smallcap250",
}
# Categories where a passive index is a genuine substitute → closet-index is a rule-out.
_CLOSET_ENFORCE = {"Large Cap", "Large & Mid Cap"}

# Benchmark index funds to resolve (needle → label/display).
_BENCHMARK_FUNDS: dict[str, tuple[str, str]] = {
    "nifty50":     ("UTI Nifty 50 Index", "Nifty 50"),
    "midcap150":   ("Motilal Oswal Nifty Midcap 150 Index", "Nifty Midcap 150"),
    "smallcap250": ("Nippon India Nifty Smallcap 250 Index", "Nifty Smallcap 250"),
}

# Scoring weights for the category-relative percentile blend.
_W_SHARPE, _W_CAGR, _W_1Y, _W_DD, _W_ACTIVE = 0.30, 0.25, 0.20, 0.10, 0.15

# ── Model-portfolio slots (role, primary category, fallback categories, role note) ─
# A diversified 5-fund core — one fund per role, not five top-scorers (which would
# overlap). Weights come from the risk preset below.
_SLOTS: list[tuple[str, str, list[str], str]] = [
    ("Core",        "Flexi Cap",            ["Multi Cap"],
     "the all-weather workhorse — one manager allocating across the whole market"),
    ("Anchor",      "Large Cap",            ["Large & Mid Cap"],
     "stability and shallower drawdowns from established blue-chips"),
    ("Growth",      "Mid Cap",              [],
     "the compounding engine — tomorrow's large-caps, more volatile"),
    ("High Growth", "Small Cap",            [],
     "highest long-run growth potential, sized down for its higher risk"),
    ("Satellite",   "Special Opportunities", ["Focused", "Value/Contra", "ELSS"],
     "a differentiated, go-anywhere bet to add alpha beyond the core"),
]

# Allocation per risk preset: [Core, Anchor, Growth, High Growth, Satellite].
_RISK_WEIGHTS: dict[str, list[float]] = {
    "conservative": [35, 30, 20, 10,  5],
    "balanced":     [30, 20, 25, 15, 10],
    "aggressive":   [25, 15, 25, 20, 15],
}

_RISK_RATIONALE: dict[str, str] = {
    "conservative": (
        "Tilted to large-caps and the flexi-cap core for steadier, lower-drawdown "
        "compounding — suited to shorter horizons or lower risk appetite."
    ),
    "balanced": (
        "A middle path — a flexi-cap core with meaningful mid/small-cap growth — "
        "for investors with a 7+ year horizon who want growth without the full swing."
    ),
    "aggressive": (
        "Leans into mid/small-caps and a satellite bet for maximum long-run growth — "
        "only for long horizons (10+ years) and the stomach for deep drawdowns."
    ),
}

# Decay is judged RELATIVE to the category: a fund decelerating ≥6pp more than
# its cohort median is fund-specific fade (saturation / drift), not market beta.
_DECAY_REL_THRESHOLD = -6.0
_CLOSET_CORR = 0.95         # benchmark correlation above this …
_CLOSET_ACTIVE = 1.5        # … with ≤1.5pp alpha ⇒ closet indexer


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _parse_nav_date(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d, "%d-%m-%Y")
    except (ValueError, TypeError):
        return None


def _is_candidate(scheme_name: str, needle: str) -> bool:
    s = scheme_name.lower()
    return (
        needle.lower() in s
        and "direct" in s
        and not any(tok in s for tok in _EXCLUDE_TOKENS)
    )


def _select_scheme(index: list[dict[str, Any]], needle: str) -> Optional[dict[str, Any]]:
    """Pick the plain Direct-Growth scheme for a name needle (prefers Growth/Cumulative)."""
    cands = [row for row in index if _is_candidate(str(row.get("schemeName", "")), needle)]
    if not cands:
        return None
    cands.sort(key=lambda r: (
        0 if any(t in str(r["schemeName"]).lower() for t in _GROWTH_TOKENS) else 1,
        len(str(r["schemeName"])),
    ))
    return cands[0]


def _amc_of(name: str) -> str:
    """Normalised AMC key from a scheme name (first brand word) for overlap control."""
    words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    return words[0] if words else name.lower()


def _classify(name: str) -> Optional[str]:
    n = name.lower()
    for cat, kws in _CATEGORIES:
        if any(k in n for k in kws):
            return cat
    return None


def _is_equity_dg(name: str) -> bool:
    """An ACTIVE Direct-Growth, open-ended, domestic equity plan.

    Excludes debt/hybrid/global AND passive index/ETF funds — index funds are the
    benchmark, not an active pick to rank (they're resolved separately for closet
    detection).
    """
    s = name.lower()
    if "direct" not in s:
        return False
    if not any(g in s for g in _GROWTH_TOKENS):
        return False
    if any(x in s for x in _EXCLUDE_TOKENS):
        return False
    if any(x in s for x in _NON_EQUITY):
        return False
    if any(x in s for x in _GLOBAL):
        return False
    if "index" in s or "etf" in s:          # passive — not an active pick
        return False
    return True


class _ScannedFund:
    """Internal carrier: a FundScheme plus the raw metrics needed for scoring."""
    __slots__ = ("fund", "metrics", "dated")

    def __init__(self, fund: FundScheme, metrics: dict, dated: list[tuple[str, float]]) -> None:
        self.fund = fund
        self.metrics = metrics
        self.dated = dated


class FundDataService:
    def __init__(self, settings: Settings, analyst: Any | None = None) -> None:
        self._settings = settings
        self._analyst = analyst
        # Instance caches (process lifetime, refreshed every _UNIVERSE_TTL).
        self._universe: Optional[list[dict[str, str]]] = None   # [{code, name, category}]
        self._universe_at: float = 0.0
        self._benchmarks: dict[str, list[tuple[str, float]]] = {}  # key → dated NAV series

    # ── Public API ──────────────────────────────────────────────────────────────

    async def scan(self, category: Optional[str] = None) -> FundScanResponse:
        universe = await self._resolve_universe()
        if not universe:
            return FundScanResponse(funds=[], category=category, scanned_at=datetime.utcnow())

        target = [u for u in universe if (not category or u["category"] == category)]
        if not target:
            return FundScanResponse(funds=[], category=category, scanned_at=datetime.utcnow())

        await self._ensure_benchmarks(universe)

        # Fetch + compute metrics for the target funds (bounded concurrency).
        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
        results = await asyncio.gather(
            *[self._build_one(u, sem) for u in target],
            return_exceptions=True,
        )
        scanned: list[_ScannedFund] = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("fund_data.fund_build_failed", error=str(r))
            elif r is not None:
                scanned.append(r)

        if not scanned:
            return FundScanResponse(funds=[], category=category, scanned_at=datetime.utcnow())

        # Category-relative scoring + rule-out flags.
        self._score_by_category(scanned)
        funds = [s.fund for s in scanned]

        # AI reasoning (batched; mock/heuristic fallback inside the agent).
        if self._analyst is not None and funds:
            try:
                reasons = await self._analyst.analyse(funds)
                for f in funds:
                    if f.scheme_code in reasons:
                        f.entry_reason = reasons[f.scheme_code]
            except Exception as exc:
                log.warning("fund_data.ai_reasoning_failed", error=str(exc))

        funds.sort(key=lambda f: f.fund_score, reverse=True)
        log.info(
            "fund_data.scan_done",
            category=category or "all",
            scanned=len(funds),
            strong=sum(1 for f in funds if f.entry_signal == "strong_entry"),
            discovery=sum(1 for f in funds if f.is_discovery),
            ruled_out=sum(1 for f in funds if f.is_closet_index or f.is_decaying),
        )
        return FundScanResponse(
            funds=funds, category=category, universe_size=len(universe), scanned_at=datetime.utcnow()
        )

    # ── Model portfolio ("the 5 funds you should own") ──────────────────────────

    async def build_model_portfolio(self, risk: str = "balanced") -> ModelPortfolioResponse:
        """
        Construct a diversified 5-fund core portfolio for a self-selected risk
        flavour. One fund per role (Core / Anchor / Growth / High-Growth /
        Satellite), each the best LONG-TERM-potential fund in its category with no
        rule-out flags, avoiding two funds from the same AMC. Generic — no personal
        profiling — so it serves any investor who picks a risk level.
        """
        risk = risk if risk in _RISK_WEIGHTS else "balanced"
        scan = await self.scan(category=None)
        return assemble_portfolio(
            funds=scan.funds, slots=_SLOTS, weights=_RISK_WEIGHTS[risk],
            risk=risk, rationale=_RISK_RATIONALE[risk], market="india",
            universe_size=scan.universe_size,
            no_cost_note=("Every pick is a Direct-Growth plan — the lowest-cost, "
                          "commission-free share class — which itself protects years of compounding."),
        )

    # ── Universe discovery ──────────────────────────────────────────────────────

    async def _resolve_universe(self) -> list[dict[str, str]]:
        if self._universe is not None and (time.monotonic() - self._universe_at) < _UNIVERSE_TTL:
            return self._universe

        index = await self._get_json(f"{_MFAPI_BASE}/mf", timeout=25.0)
        if not isinstance(index, list):
            log.warning("fund_data.index_fetch_failed")
            return self._universe or []

        seen: set[str] = set()
        universe: list[dict[str, str]] = []
        for row in index:
            name = str(row.get("schemeName", ""))
            if not _is_equity_dg(name):
                continue
            cat = _classify(name)
            if cat is None:
                continue
            # Dedupe near-identical plan rows by the first 6 normalised words.
            key = " ".join(re.sub(r"[^a-z0-9 ]", "", name.lower()).split()[:6])
            if key in seen:
                continue
            seen.add(key)
            universe.append({"code": str(row.get("schemeCode")), "name": name, "category": cat})

        log.info("fund_data.universe_resolved", total=len(universe))
        self._universe = universe
        self._universe_at = time.monotonic()
        return universe

    async def _ensure_benchmarks(self, universe: list[dict[str, str]]) -> None:
        if self._benchmarks:
            return
        # Resolve benchmark index funds from the same index we already pulled is
        # cheaper, but we only have classified names here — re-fetch the raw index.
        index = await self._get_json(f"{_MFAPI_BASE}/mf", timeout=25.0)
        if not isinstance(index, list):
            return
        for key, (needle, _label) in _BENCHMARK_FUNDS.items():
            row = _select_scheme(index, needle)
            if row is None:
                continue
            dated = await self._fetch_dated(str(row["schemeCode"]))
            if dated:
                self._benchmarks[key] = dated
        log.info("fund_data.benchmarks_ready", resolved=len(self._benchmarks))

    # ── Per-fund build ──────────────────────────────────────────────────────────

    async def _build_one(self, u: dict[str, str], sem: asyncio.Semaphore) -> Optional[_ScannedFund]:
        async with sem:
            dated = await self._fetch_dated(u["code"])
        if len(dated) < _MIN_HISTORY:
            return None

        # Staleness gate: a merged/closed fund's NAV stops updating. Its "recent"
        # returns would be computed on years-old data — exclude it entirely.
        latest_dt = _parse_nav_date(dated[-1][0])
        if latest_dt is None or (datetime.utcnow() - latest_dt).days > _MAX_NAV_STALENESS_DAYS:
            return None

        navs = [v for _, v in dated]
        m = compute_metrics(navs)
        cat = u["category"]

        bench_key = _BENCHMARK_BY_CATEGORY.get(cat)
        active_return: Optional[float] = None
        correlation: Optional[float] = None
        bench_name: Optional[str] = None
        if bench_key and bench_key in self._benchmarks:
            cm = closet_metrics(dated, self._benchmarks[bench_key])
            active_return = cm.get("active_return")
            correlation = cm.get("correlation")
            bench_name = _BENCHMARK_FUNDS[bench_key][1]

        fund = FundScheme(
            scheme_code=u["code"],
            name=u["name"],
            category=cat,
            fund_type="mutual_fund",
            market="india",
            nav=navs[-1],
            nav_date=dated[-1][0],
            returns_1m=m.get("returns_1m"),
            returns_3m=m.get("returns_3m"),
            returns_6m=m.get("returns_6m"),
            returns_1y=m.get("returns_1y"),
            returns_3y_cagr=m.get("returns_3y_cagr"),
            returns_5y_cagr=m.get("returns_5y_cagr"),
            since_inception_cagr=m.get("since_inception_cagr"),
            volatility=m.get("volatility"),
            sharpe=m.get("sharpe"),
            max_drawdown=m.get("max_drawdown"),
            track_record=track_record_tier(m.get("history_points", len(navs))),
            active_return_3y=active_return,
            benchmark_name=bench_name,
        )
        # Stash correlation for the closet decision (not a schema field).
        m["_correlation"] = correlation
        return _ScannedFund(fund=fund, metrics=m, dated=dated)

    # ── Category-relative scoring + rule-outs ──────────────────────────────────

    def _score_by_category(self, scanned: list[_ScannedFund]) -> None:
        by_cat: dict[str, list[_ScannedFund]] = {}
        for s in scanned:
            by_cat.setdefault(s.fund.category or "?", []).append(s)

        for cat, cohort in by_cat.items():
            self._score_cohort(cat, cohort)

    def _score_cohort(self, category: str, cohort: list[_ScannedFund]) -> None:
        # Too few peers for stable percentiles → absolute fallback.
        if len(cohort) < 5:
            for s in cohort:
                score, signal = score_fund(s.metrics)
                s.fund.long_term_score = score   # no peer set to rank against
                self._finalise(s, score, signal)
            self._assign_ranks(cohort)
            return

        p_sharpe = percentile_ranks([s.fund.sharpe for s in cohort], higher_is_better=True)
        p_cagr   = percentile_ranks([s.fund.returns_3y_cagr for s in cohort], higher_is_better=True)
        p_1y     = percentile_ranks([s.fund.returns_1y for s in cohort], higher_is_better=True)
        p_dd     = percentile_ranks([s.fund.max_drawdown for s in cohort], higher_is_better=True)
        p_active = percentile_ranks([s.fund.active_return_3y for s in cohort], higher_is_better=True)

        # Long-term horizon return (5y → 3y → since-inception, whatever exists).
        long_cagr = [
            s.fund.returns_5y_cagr if s.fund.returns_5y_cagr is not None
            else s.fund.returns_3y_cagr if s.fund.returns_3y_cagr is not None
            else s.fund.since_inception_cagr
            for s in cohort
        ]
        p_longcagr = percentile_ranks(long_cagr, higher_is_better=True)
        # Cost percentile (lower TER ⇒ better) — only contributes if any TER sourced.
        expense_vals = [s.fund.expense_ratio for s in cohort]
        has_cost = any(v is not None for v in expense_vals)
        p_cost = percentile_ranks(expense_vals, higher_is_better=False) if has_cost else None

        # Category-relative decay baseline: a soft year for the WHOLE category is
        # market beta, not fund-specific saturation. Only flag funds decaying
        # materially MORE than their peers (vs the cohort median deceleration).
        decels = [s.metrics.get("decay_decel") for s in cohort]
        present_decels = [d for d in decels if d is not None]
        median_decel = statistics.median(present_decels) if present_decels else 0.0

        for i, s in enumerate(cohort):
            base = (
                _W_SHARPE * p_sharpe[i]
                + _W_CAGR * p_cagr[i]
                + _W_1Y * p_1y[i]
                + _W_DD * p_dd[i]
                + _W_ACTIVE * p_active[i]
            )

            # ── Rule-out flags ────────────────────────────────────────────────
            decay = s.metrics.get("decay_decel")
            is_decaying = (
                decay is not None
                and decay < 0
                and (decay - median_decel) <= _DECAY_REL_THRESHOLD
            )

            corr = s.metrics.get("_correlation")
            is_closet = (
                category in _CLOSET_ENFORCE
                and corr is not None and corr >= _CLOSET_CORR
                and s.fund.active_return_3y is not None
                and s.fund.active_return_3y <= _CLOSET_ACTIVE
            )

            if is_decaying:
                base -= 18
            if is_closet:
                base -= 25
            score = round(max(0.0, min(base, 100.0)), 1)

            # ── Long-term potential: momentum-free, alpha- & consistency-led ───
            if has_cost and p_cost is not None:
                lt = (0.27 * p_active[i] + 0.23 * p_sharpe[i] + 0.18 * p_longcagr[i]
                      + 0.14 * p_dd[i] + 0.18 * p_cost[i])
            else:
                lt = (0.32 * p_active[i] + 0.28 * p_sharpe[i] + 0.22 * p_longcagr[i]
                      + 0.18 * p_dd[i])
            # Saturation / closet hurt a multi-decade hold even more than an entry.
            if is_decaying:
                lt -= 15
            if is_closet:
                lt -= 28
            long_term = round(max(0.0, min(lt, 100.0)), 1)

            signal = "strong_entry" if score >= 65 else "watch" if score >= 42 else "avoid"
            # Rule-outs can never be a "Strong Entry".
            if (is_closet or is_decaying) and signal == "strong_entry":
                signal = "watch"

            s.fund.is_decaying = is_decaying
            s.fund.is_closet_index = is_closet
            # Discovery: a young fund already ranking well, with no red flags.
            s.fund.is_discovery = (
                s.fund.track_record in ("emerging", "new")
                and score >= 60
                and not is_closet and not is_decaying
            )
            s.fund.long_term_score = long_term
            self._finalise(s, score, signal)

        self._assign_ranks(cohort)

    def _finalise(self, s: _ScannedFund, score: float, signal: str) -> None:
        s.fund.fund_score = score
        s.fund.entry_signal = signal  # type: ignore[assignment]
        s.fund.entry_reason = build_entry_reason(
            category=s.fund.category,
            signal=signal,
            track_record=s.fund.track_record,
            m=s.metrics,
            active_return=s.fund.active_return_3y,
            is_closet=s.fund.is_closet_index,
            is_decaying=s.fund.is_decaying,
            is_discovery=s.fund.is_discovery,
        )

    @staticmethod
    def _assign_ranks(cohort: list[_ScannedFund]) -> None:
        ranked = sorted(cohort, key=lambda s: s.fund.fund_score, reverse=True)
        size = len(ranked)
        for rank, s in enumerate(ranked, 1):
            s.fund.category_rank = rank
            s.fund.category_size = size

    # ── HTTP helpers ────────────────────────────────────────────────────────────

    async def get_price_series(self, code: str) -> list[tuple[datetime, float]]:
        """Dated NAV series [(datetime, nav), …] oldest→newest, for backtests."""
        dated = await self._fetch_dated(code)
        out: list[tuple[datetime, float]] = []
        for d, nav in dated:
            dt = _parse_nav_date(d)
            if dt is not None:
                out.append((dt, nav))
        return out

    async def _fetch_dated(self, code: str) -> list[tuple[str, float]]:
        """Fetch a scheme's NAV history as [(DD-MM-YYYY, nav), …] oldest → newest."""
        payload = await self._get_json(f"{_MFAPI_BASE}/mf/{code}", timeout=10.0)
        if not isinstance(payload, dict):
            return []
        data = payload.get("data") or []
        dated: list[tuple[str, float]] = []
        for row in reversed(data):  # mfapi returns newest-first
            nv = _safe_float(row.get("nav"))
            d = row.get("date")
            if nv is not None and nv > 0 and d:
                dated.append((str(d), nv))
        return dated

    async def _get_json(self, url: str, timeout: float) -> Any:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await asyncio.wait_for(client.get(url), timeout=timeout + 2)
                if resp.status_code != 200:
                    log.warning("fund_data.http_non_200", url=url, status=resp.status_code)
                    return None
                return resp.json()
        except Exception as exc:
            log.warning("fund_data.http_error", url=url, error=str(exc))
            return None
