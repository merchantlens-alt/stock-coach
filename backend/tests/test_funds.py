"""
Tests for the Fund Scanner (India mutual funds via mfapi.in).

Coverage:
  • Pure metric math (fund_metrics) — no network, deterministic
  • Scoring → entry-signal thresholds
  • The /funds/scan route with FundDataService.scan mocked at the import point
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from models.schemas import (
    FundScanResponse,
    FundScheme,
    ModelHolding,
    ModelPortfolioResponse,
)
from services.fund_metrics import (
    annualised_volatility,
    closet_metrics,
    compute_metrics,
    decay_decel,
    max_drawdown,
    percentile_ranks,
    score_fund,
    sharpe_ratio,
    since_inception_cagr,
    track_record_tier,
)


def _rising_navs(n: int = 1300, daily: float = 0.0006, start: float = 100.0) -> list[float]:
    """A steadily compounding NAV series, oldest → newest."""
    navs = [start]
    for _ in range(1, n):
        navs.append(navs[-1] * (1 + daily))
    return navs


class TestFundMetricsMath:
    def test_point_returns_positive_on_rising_series(self) -> None:
        navs = _rising_navs()
        m = compute_metrics(navs)
        assert m["returns_1m"] is not None and m["returns_1m"] > 0
        assert m["returns_1y"] is not None and m["returns_1y"] > 0

    def test_cagr_present_with_enough_history(self) -> None:
        navs = _rising_navs(n=1300)
        m = compute_metrics(navs)
        assert m["returns_3y_cagr"] is not None
        assert m["returns_5y_cagr"] is not None
        # ~0.06% daily ≈ ~16% annualised; allow a wide band
        assert 8 < m["returns_3y_cagr"] < 25

    def test_short_history_yields_none_for_long_horizons(self) -> None:
        navs = _rising_navs(n=100)  # < 1y of data
        m = compute_metrics(navs)
        assert m["returns_3m"] is not None
        assert m["returns_1y"] is None
        assert m["returns_3y_cagr"] is None

    def test_empty_series_returns_empty_dict(self) -> None:
        assert compute_metrics([]) == {}

    def test_volatility_none_when_too_few_points(self) -> None:
        assert annualised_volatility([100.0, 101.0]) is None

    def test_volatility_positive_on_noisy_series(self) -> None:
        navs = [100.0]
        for i in range(1, 300):
            navs.append(navs[-1] * (1.01 if i % 2 else 0.99))
        vol = annualised_volatility(navs)
        assert vol is not None and vol > 0

    def test_max_drawdown_is_negative_after_a_crash(self) -> None:
        navs = [100, 120, 140, 70, 90, 110]  # peak 140 → trough 70 = -50%
        mdd = max_drawdown([float(x) for x in navs])
        assert mdd is not None
        assert abs(mdd - (-50.0)) < 0.01

    def test_max_drawdown_zero_on_monotonic_rise(self) -> None:
        assert max_drawdown([100.0, 110.0, 120.0]) == 0.0

    def test_sharpe_none_when_volatility_zero(self) -> None:
        assert sharpe_ratio(12.0, 0.0) is None

    def test_sharpe_positive_when_return_beats_riskfree(self) -> None:
        # 20% return, 10% vol, 6.5% rf → (0.20-0.065)/0.10 = 1.35
        s = sharpe_ratio(20.0, 10.0)
        assert s is not None and 1.2 < s < 1.5


class TestAdvisorMetrics:
    def test_percentile_ranks_orders_and_neutralises_none(self) -> None:
        vals = [10.0, 20.0, 30.0, None]
        pr = percentile_ranks(vals, higher_is_better=True)
        assert pr[0] == 0.0          # lowest
        assert pr[2] == 100.0        # highest
        assert pr[3] == 50.0         # None ⇒ neutral
        assert pr[0] < pr[1] < pr[2]

    def test_percentile_ranks_lower_is_better_for_drawdown(self) -> None:
        # max drawdown: -10 (shallow) should rank ABOVE -50 (deep) when higher_is_better
        pr = percentile_ranks([-10.0, -50.0, -30.0], higher_is_better=True)
        assert pr[0] == 100.0
        assert pr[1] == 0.0

    def test_percentile_ranks_all_none_is_neutral(self) -> None:
        assert percentile_ranks([None, None]) == [50.0, 50.0]

    def test_since_inception_cagr_positive(self) -> None:
        navs = _rising_navs(n=1300)
        si = since_inception_cagr(navs)
        assert si is not None and 10 < si < 25

    def test_decay_decel_negative_when_recent_lags(self) -> None:
        # Strong early growth, then a flat last year ⇒ recent 1y << 3y CAGR.
        navs = _rising_navs(n=1000, daily=0.0010)         # ~older strong growth
        navs += [navs[-1]] * 260                            # flat last ~year
        d = decay_decel(navs)
        assert d is not None and d < 0

    def test_decay_decel_none_without_3y(self) -> None:
        assert decay_decel(_rising_navs(n=200)) is None

    def test_track_record_tiers(self) -> None:
        assert track_record_tier(1300) == "established"   # >3y
        assert track_record_tier(400) == "emerging"       # ~1.5y
        assert track_record_tier(120) == "new"            # <1y

    def test_closet_metrics_high_correlation_low_active(self) -> None:
        # Fund that nearly mirrors the benchmark ⇒ ~0 active return, high correlation.
        dates = [f"{(i % 28) + 1:02d}-01-2024" if i < 0 else "" for i in range(0)]
        # Build aligned dated series with the same dates.
        from datetime import datetime, timedelta
        base = datetime(2022, 1, 1)
        bench, fund = [], []
        bv = fv = 100.0
        for i in range(800):
            d = (base + timedelta(days=i)).strftime("%d-%m-%Y")
            step = 0.0005 + (0.0003 if i % 2 else -0.0003)
            bv *= (1 + step)
            fv *= (1 + step * 1.001)        # almost identical path
            bench.append((d, bv))
            fund.append((d, fv))
        cm = closet_metrics(fund, bench)
        assert cm["common_points"] >= 60
        assert cm["correlation"] is not None and cm["correlation"] > 0.95
        assert cm["active_return"] is not None and abs(cm["active_return"]) < 2.0

    def test_closet_metrics_no_overlap(self) -> None:
        cm = closet_metrics([("01-01-2020", 10.0)], [("02-02-2021", 20.0)])
        assert cm["common_points"] == 0
        assert cm["active_return"] is None


class TestCategoryScoring:
    """The heart of v2 — category-relative scoring + rule-out flags, no network."""

    def _cohort(self):
        from services.fund_data import FundDataService, _ScannedFund
        from core.config import Settings

        def mk(code, sharpe, cagr3, r1y, mdd, active, corr, decel=None, track="established"):
            f = FundScheme(
                scheme_code=code, name=f"Fund {code}", category="Large Cap",
                fund_type="mutual_fund", market="india",
                sharpe=sharpe, returns_3y_cagr=cagr3, returns_1y=r1y,
                max_drawdown=mdd, active_return_3y=active, track_record=track,
            )
            m = {
                "sharpe": sharpe, "returns_3y_cagr": cagr3, "returns_1y": r1y,
                "max_drawdown": mdd, "returns_6m": r1y, "decay_decel": decel,
                "_correlation": corr, "history_points": 1300,
            }
            return _ScannedFund(f, m, [])

        svc = FundDataService(Settings(), analyst=None)
        # All funds mildly decelerate (market-wide soft year) EXCEPT "decaying",
        # which fades far more than its peers ⇒ fund-specific saturation.
        cohort = [
            mk("best",     1.6, 19.0, 22.0, -12.0,  6.0, 0.80, decel=-2.0),   # outperformer
            mk("good",     1.1, 15.0, 14.0, -16.0,  3.0, 0.85, decel=-3.0),
            mk("mid",      0.6, 11.0,  8.0, -22.0,  0.5, 0.90, decel=-4.0),
            mk("closet",   0.7, 12.0,  9.0, -18.0,  0.4, 0.98, decel=-3.0),   # hugs benchmark
            mk("decaying", 0.9, 16.0, -2.0, -20.0,  1.0, 0.80, decel=-14.0),  # fades hard
        ]
        svc._score_cohort("Large Cap", cohort)
        return {s.fund.scheme_code: s.fund for s in cohort}

    def test_closet_fund_is_flagged_and_not_strong_entry(self) -> None:
        funds = self._cohort()
        assert funds["closet"].is_closet_index is True
        assert funds["closet"].entry_signal != "strong_entry"

    def test_decaying_fund_is_flagged_and_not_strong_entry(self) -> None:
        funds = self._cohort()
        assert funds["decaying"].is_decaying is True
        assert funds["decaying"].entry_signal != "strong_entry"

    def test_best_fund_ranks_first(self) -> None:
        funds = self._cohort()
        assert funds["best"].category_rank == 1
        assert funds["best"].category_size == 5
        assert funds["best"].fund_score > funds["mid"].fund_score

    def test_long_term_score_is_populated(self) -> None:
        funds = self._cohort()
        assert funds["best"].long_term_score > 0
        # Momentum-free long-term score still favours the genuine outperformer.
        assert funds["best"].long_term_score > funds["mid"].long_term_score

    def test_young_strong_fund_gets_discovery_badge(self) -> None:
        from services.fund_data import FundDataService, _ScannedFund
        from core.config import Settings

        def mk(code, sharpe, cagr3, r1y, mdd, active, corr, track):
            f = FundScheme(
                scheme_code=code, name=f"Fund {code}", category="Small Cap",
                sharpe=sharpe, returns_3y_cagr=cagr3, returns_1y=r1y,
                max_drawdown=mdd, active_return_3y=active, track_record=track,
            )
            m = {"sharpe": sharpe, "returns_3y_cagr": cagr3, "returns_1y": r1y,
                 "max_drawdown": mdd, "returns_6m": r1y, "decay_decel": None,
                 "_correlation": corr, "history_points": 1300}
            return _ScannedFund(f, m, [])

        svc = FundDataService(Settings(), analyst=None)
        cohort = [
            mk("young", 1.8, None, 34.0, -14.0, 9.0, 0.70, "emerging"),  # no 3y, dominates 1y
            mk("a", 0.8, 14.0, 10.0, -24.0, 1.0, 0.80, "established"),
            mk("b", 0.6, 12.0,  8.0, -28.0, 0.0, 0.85, "established"),
            mk("c", 0.5, 11.0,  6.0, -30.0, -1.0, 0.85, "established"),
            mk("d", 0.4, 10.0,  4.0, -32.0, -2.0, 0.85, "established"),
        ]
        svc._score_cohort("Small Cap", cohort)
        young = next(s.fund for s in cohort if s.fund.scheme_code == "young")
        assert young.is_discovery is True
        assert young.fund_score >= 60


class TestScoreFund:
    def test_strong_fund_scores_high(self) -> None:
        metrics = {
            "returns_1m": 3.0, "returns_3m": 12.0, "returns_6m": 18.0,
            "returns_1y": 22.0, "returns_3y_cagr": 20.0, "returns_5y_cagr": 18.0,
            "volatility": 13.0, "sharpe": 1.6, "max_drawdown": -12.0,
        }
        score, signal = score_fund(metrics)
        assert score >= 65
        assert signal == "strong_entry"

    def test_weak_fund_scores_low(self) -> None:
        metrics = {
            "returns_1m": -8.0, "returns_3m": -12.0, "returns_6m": -15.0,
            "returns_1y": -10.0, "returns_3y_cagr": 2.0, "returns_5y_cagr": 1.0,
            "volatility": 28.0, "sharpe": -0.4, "max_drawdown": -55.0,
        }
        score, signal = score_fund(metrics)
        assert score < 40
        assert signal == "avoid"

    def test_middling_fund_is_watch(self) -> None:
        metrics = {
            "returns_1m": 0.5, "returns_3m": 4.0, "returns_6m": 5.0,
            "returns_1y": 9.0, "returns_3y_cagr": 9.0, "returns_5y_cagr": 8.0,
            "volatility": 18.0, "sharpe": 0.5, "max_drawdown": -28.0,
        }
        score, signal = score_fund(metrics)
        assert 40 <= score < 65
        assert signal == "watch"

    def test_empty_metrics_scores_zero_avoid(self) -> None:
        score, signal = score_fund({})
        assert score == 0.0
        assert signal == "avoid"


# ── Route tests ────────────────────────────────────────────────────────────────

def _sample_fund(code: str = "120503", signal: str = "strong_entry", score: float = 78.0) -> FundScheme:
    return FundScheme(
        scheme_code=code,
        name="Parag Parikh Flexi Cap Fund - Direct Growth",
        fund_house="PPFAS Mutual Fund",
        category="Flexi Cap",
        fund_type="mutual_fund",
        market="india",
        nav=82.5,
        nav_date="12-06-2026",
        returns_1m=2.4, returns_3m=11.0, returns_6m=16.5, returns_1y=21.0,
        returns_3y_cagr=19.5, returns_5y_cagr=17.8,
        volatility=12.8, sharpe=1.55, max_drawdown=-13.4,
        fund_score=score, entry_signal=signal,
        entry_reason="Strong risk-adjusted track record with healthy momentum.",
    )


class TestFundScanRoute:
    def test_scan_returns_funds(self, client: TestClient) -> None:
        resp_obj = FundScanResponse(funds=[_sample_fund()], category=None)
        with patch(
            "services.fund_data.FundDataService.scan",
            new=AsyncMock(return_value=resp_obj),
        ):
            resp = client.get("/api/funds/scan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["market"] == "india"
        assert len(body["funds"]) == 1
        assert body["funds"][0]["entry_signal"] == "strong_entry"
        assert body["funds"][0]["scheme_code"] == "120503"

    def test_scan_with_category_filter(self, client: TestClient) -> None:
        resp_obj = FundScanResponse(funds=[_sample_fund()], category="Flexi Cap")
        with patch(
            "services.fund_data.FundDataService.scan",
            new=AsyncMock(return_value=resp_obj),
        ) as mock_scan:
            resp = client.get("/api/funds/scan?category=Flexi%20Cap")
        assert resp.status_code == 200
        assert resp.json()["category"] == "Flexi Cap"
        mock_scan.assert_awaited_once()

    def test_scan_empty_is_ok(self, client: TestClient) -> None:
        resp_obj = FundScanResponse(funds=[], category=None)
        with patch(
            "services.fund_data.FundDataService.scan",
            new=AsyncMock(return_value=resp_obj),
        ):
            resp = client.get("/api/funds/scan")
        assert resp.status_code == 200
        assert resp.json()["funds"] == []

    def test_refresh_param_busts_cache(self, client: TestClient) -> None:
        resp_obj = FundScanResponse(funds=[_sample_fund()], category=None)
        with patch(
            "services.fund_data.FundDataService.scan",
            new=AsyncMock(return_value=resp_obj),
        ) as mock_scan:
            client.get("/api/funds/scan")            # cold → caches
            client.get("/api/funds/scan")            # warm → served from cache
            client.get("/api/funds/scan?refresh=true")  # busts → scans again
        # Scanned on first call and on the refresh call, but not the cached middle one.
        assert mock_scan.await_count == 2


class TestModelPortfolio:
    """Generic 5-fund model portfolio construction — no network."""

    def _svc(self, funds: list[FundScheme]):
        from core.config import Settings
        from services.fund_data import FundDataService

        svc = FundDataService(Settings(), analyst=None)

        async def fake_scan(category=None):
            return FundScanResponse(funds=funds, universe_size=len(funds))

        svc.scan = fake_scan  # type: ignore[assignment]
        return svc

    @staticmethod
    def _f(code: str, name: str, category: str, lt: float, **flags) -> FundScheme:
        return FundScheme(
            scheme_code=code, name=name, category=category,
            long_term_score=lt, category_rank=1, category_size=8,
            active_return_3y=4.0, **flags,
        )

    def _one_per_slot(self) -> list[FundScheme]:
        return [
            self._f("1", "HDFC Flexi Cap Fund", "Flexi Cap", 88),
            self._f("2", "Axis Large Cap Fund", "Large Cap", 80),
            self._f("3", "Kotak Midcap Fund", "Mid Cap", 84),
            self._f("4", "Nippon Small Cap Fund", "Small Cap", 79),
            self._f("5", "WhiteOak Special Opportunities Fund", "Special Opportunities", 72),
        ]

    def test_builds_five_roles_in_order(self) -> None:
        svc = self._svc(self._one_per_slot())
        resp = asyncio.run(svc.build_model_portfolio("balanced"))
        assert [h.role for h in resp.holdings] == ["Core", "Anchor", "Growth", "High Growth", "Satellite"]
        assert abs(sum(h.weight_pct for h in resp.holdings) - 100.0) < 0.1

    def test_balanced_weights(self) -> None:
        svc = self._svc(self._one_per_slot())
        resp = asyncio.run(svc.build_model_portfolio("balanced"))
        assert [h.weight_pct for h in resp.holdings] == [30, 20, 25, 15, 10]

    def test_excludes_ruled_out_and_renormalises(self) -> None:
        funds = self._one_per_slot()
        # Make the only Large Cap fund a closet indexer ⇒ Anchor cannot be filled.
        funds[1] = self._f("2", "Axis Large Cap Fund", "Large Cap", 80, is_closet_index=True)
        svc = self._svc(funds)
        resp = asyncio.run(svc.build_model_portfolio("balanced"))
        assert len(resp.holdings) == 4
        assert "Anchor" not in [h.role for h in resp.holdings]
        assert abs(sum(h.weight_pct for h in resp.holdings) - 100.0) < 0.1

    def test_avoids_duplicate_amc(self) -> None:
        funds = [
            self._f("1", "HDFC Flexi Cap Fund", "Flexi Cap", 90),
            self._f("2", "HDFC Large Cap Fund", "Large Cap", 95),   # same AMC, higher score
            self._f("3", "Axis Large Cap Fund", "Large Cap", 80),   # different AMC, lower
            self._f("4", "Kotak Midcap Fund", "Mid Cap", 84),
            self._f("5", "Nippon Small Cap Fund", "Small Cap", 79),
            self._f("6", "Quant Special Opportunities Fund", "Special Opportunities", 70),
        ]
        svc = self._svc(funds)
        resp = asyncio.run(svc.build_model_portfolio("aggressive"))
        anchor = next(h for h in resp.holdings if h.role == "Anchor")
        # Should skip HDFC (already used by Core) and pick Axis instead.
        assert anchor.fund.name.startswith("Axis")

    def test_uses_fallback_category(self) -> None:
        # No "Special Opportunities" — Satellite should fall back to Focused.
        funds = [
            self._f("1", "HDFC Flexi Cap Fund", "Flexi Cap", 88),
            self._f("2", "Axis Large Cap Fund", "Large Cap", 80),
            self._f("3", "Kotak Midcap Fund", "Mid Cap", 84),
            self._f("4", "Nippon Small Cap Fund", "Small Cap", 79),
            self._f("5", "DSP Focused Fund", "Focused", 75),
        ]
        svc = self._svc(funds)
        resp = asyncio.run(svc.build_model_portfolio("balanced"))
        sat = next(h for h in resp.holdings if h.role == "Satellite")
        assert sat.fund.category == "Focused"


class TestModelPortfolioRoute:
    def test_route_returns_portfolio(self, client: TestClient) -> None:
        resp_obj = ModelPortfolioResponse(
            risk="aggressive",
            holdings=[ModelHolding(
                role="Core", weight_pct=25.0, why="Core: the workhorse.",
                fund=_sample_fund(),
            )],
            rationale="Leans into growth.",
        )
        with patch(
            "services.fund_data.FundDataService.build_model_portfolio",
            new=AsyncMock(return_value=resp_obj),
        ):
            resp = client.get("/api/funds/model-portfolio?risk=aggressive")
        assert resp.status_code == 200
        body = resp.json()
        assert body["risk"] == "aggressive"
        assert len(body["holdings"]) == 1
        assert body["holdings"][0]["role"] == "Core"


class TestFundAnalystMock:
    def test_mock_agent_returns_reason_per_fund(self, client: TestClient) -> None:
        # MOCK_AI=true in conftest → agent uses heuristic reasons, never hits network.
        import asyncio

        from agents.fund_analyst import FundAnalystAgent
        from core.config import Settings

        agent = FundAnalystAgent(Settings())
        funds = [_sample_fund("100"), _sample_fund("200", signal="avoid", score=22.0)]
        reasons = asyncio.run(agent.analyse(funds))
        assert set(reasons.keys()) == {"100", "200"}
        assert all(isinstance(v, str) and v for v in reasons.values())
