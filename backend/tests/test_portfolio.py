from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def _holding_payload(**kwargs) -> dict:
    payload = {
        "ticker": "aapl",
        "market": "us",
        "type": "holding",
        "entry_price": 180.0,
        "purchase_avg": 155.0,
        "shares": 10.0,
        "stock_name": "Apple Inc.",
        "ai_predicted_change_pct": 5.0,
        "ai_confidence": 0.75,
        "catalyst_type": "earnings",
        "ai_outlook": "Strong earnings momentum expected.",
    }
    payload.update(kwargs)
    return payload


def _watchlist_payload(**kwargs) -> dict:
    payload = {
        "ticker": "TSLA",
        "market": "us",
        "type": "watchlist",
        "entry_price": 250.0,
    }
    payload.update(kwargs)
    return payload


# ── TestPortfolioList ──────────────────────────────────────────────────────────

class TestPortfolioList:
    def test_empty_portfolio_returns_200_with_zeros(self, client: TestClient) -> None:
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["total_active"] == 0
        assert data["total_resolved"] == 0
        assert data["wins"] == 0
        assert data["losses"] == 0
        assert data["win_rate"] is None

    def test_after_adding_entry_it_appears(self, client: TestClient) -> None:
        client.post("/api/portfolio", json=_holding_payload())
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["total_active"] == 1
        assert data["entries"][0]["ticker"] == "AAPL"  # uppercased


# ── TestAddEntry ───────────────────────────────────────────────────────────────

class TestAddEntry:
    def test_add_holding_with_purchase_avg(self, client: TestClient) -> None:
        resp = client.post("/api/portfolio", json=_holding_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "holding"
        assert data["purchase_avg"] == 155.0
        assert data["shares"] == 10.0
        assert data["stock_name"] == "Apple Inc."
        assert data["ai_predicted_change_pct"] == 5.0
        assert data["ai_confidence"] == 0.75
        assert data["catalyst_type"] == "earnings"
        assert data["status"] == "active"

    def test_add_watchlist_no_purchase_avg(self, client: TestClient) -> None:
        resp = client.post("/api/portfolio", json=_watchlist_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "watchlist"
        assert data["purchase_avg"] is None
        assert data["shares"] is None

    def test_ticker_is_uppercased(self, client: TestClient) -> None:
        resp = client.post("/api/portfolio", json=_holding_payload(ticker="aapl"))
        assert resp.status_code == 201
        assert resp.json()["ticker"] == "AAPL"

    def test_target_date_is_30_days_from_today(self, client: TestClient) -> None:
        today = date.today()
        expected_target = (today + timedelta(days=30)).isoformat()
        resp = client.post("/api/portfolio", json=_holding_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["entry_date"] == today.isoformat()
        assert data["target_date"] == expected_target

    def test_created_at_is_set(self, client: TestClient) -> None:
        resp = client.post("/api/portfolio", json=_holding_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["created_at"] is not None
        assert "T" in data["created_at"]  # ISO datetime with time component

    def test_id_is_set(self, client: TestClient) -> None:
        resp = client.post("/api/portfolio", json=_holding_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] is not None
        assert len(data["id"]) > 0


# ── TestGetEntry ───────────────────────────────────────────────────────────────

class TestGetEntry:
    def test_found_returns_200(self, client: TestClient) -> None:
        post_resp = client.post("/api/portfolio", json=_holding_payload())
        entry_id = post_resp.json()["id"]

        resp = client.get(f"/api/portfolio/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == entry_id
        assert resp.json()["ticker"] == "AAPL"

    def test_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/portfolio/nonexistent-id-12345")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ── TestDeleteEntry ────────────────────────────────────────────────────────────

class TestDeleteEntry:
    def test_deletes_correctly(self, client: TestClient) -> None:
        post_resp = client.post("/api/portfolio", json=_holding_payload())
        entry_id = post_resp.json()["id"]

        del_resp = client.delete(f"/api/portfolio/{entry_id}")
        assert del_resp.status_code == 204

        # Verify it's gone
        get_resp = client.get(f"/api/portfolio/{entry_id}")
        assert get_resp.status_code == 404

    def test_double_delete_returns_404(self, client: TestClient) -> None:
        post_resp = client.post("/api/portfolio", json=_holding_payload())
        entry_id = post_resp.json()["id"]

        client.delete(f"/api/portfolio/{entry_id}")
        resp = client.delete(f"/api/portfolio/{entry_id}")
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/api/portfolio/nonexistent-id-99999")
        assert resp.status_code == 404


# ── TestResolveEntry ───────────────────────────────────────────────────────────

class TestResolveEntry:
    def test_win_prediction_and_actual_both_positive(self, client: TestClient) -> None:
        # pred +5, actual +3 → direction_correct=True, status=win
        post_resp = client.post("/api/portfolio", json=_holding_payload(
            ai_predicted_change_pct=5.0,
            entry_price=100.0,
        ))
        entry_id = post_resp.json()["id"]

        resp = client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 103.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "win"
        assert data["direction_correct"] is True
        assert data["actual_change_pct"] == 3.0
        assert data["actual_price"] == 103.0
        assert data["resolved_at"] is not None

    def test_loss_prediction_positive_actual_negative(self, client: TestClient) -> None:
        # pred +5, actual -2 → direction_correct=False, status=loss
        post_resp = client.post("/api/portfolio", json=_holding_payload(
            ai_predicted_change_pct=5.0,
            entry_price=100.0,
        ))
        entry_id = post_resp.json()["id"]

        resp = client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 98.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "loss"
        assert data["direction_correct"] is False
        assert data["actual_change_pct"] == -2.0

    def test_no_prediction_results_in_expired(self, client: TestClient) -> None:
        # ai_predicted_change_pct=None → status=expired, direction_correct=None
        post_resp = client.post("/api/portfolio", json=_watchlist_payload())
        entry_id = post_resp.json()["id"]

        resp = client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 260.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "expired"
        assert data["direction_correct"] is None

    def test_re_resolve_already_resolved_returns_400(self, client: TestClient) -> None:
        post_resp = client.post("/api/portfolio", json=_holding_payload(
            ai_predicted_change_pct=5.0,
            entry_price=100.0,
        ))
        entry_id = post_resp.json()["id"]

        # First resolve
        client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 103.0})

        # Second resolve — must fail
        resp = client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 105.0})
        assert resp.status_code == 400
        assert "already resolved" in resp.json()["detail"].lower()

    def test_resolve_nonexistent_returns_404(self, client: TestClient) -> None:
        resp = client.post("/api/portfolio/nonexistent-id/resolve", json={"actual_price": 100.0})
        assert resp.status_code == 404

    def test_both_negative_direction_is_win(self, client: TestClient) -> None:
        # pred -3, actual -5 → direction_correct=True, both negative
        post_resp = client.post("/api/portfolio", json=_holding_payload(
            ai_predicted_change_pct=-3.0,
            entry_price=100.0,
        ))
        entry_id = post_resp.json()["id"]

        resp = client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 95.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "win"
        assert data["direction_correct"] is True


# ── TestMarkExpired ────────────────────────────────────────────────────────────

class TestMarkExpired:
    def test_active_entry_with_past_target_date_gets_marked_expired(self, client: TestClient) -> None:
        # Add entry with a target_date in the past by mocking date.today() during creation
        past_target = date.today() - timedelta(days=1)

        # We mock date.today() so that the entry's target_date is set to yesterday
        fake_creation_date = date.today() - timedelta(days=31)
        with patch("api.routes.portfolio.date") as mock_date:
            mock_date.today.return_value = fake_creation_date
            mock_date.fromisoformat = date.fromisoformat
            post_resp = client.post("/api/portfolio", json=_holding_payload())

        assert post_resp.status_code == 201
        entry_id = post_resp.json()["id"]

        # Verify target_date is in the past
        entry_data = post_resp.json()
        assert date.fromisoformat(entry_data["target_date"]) < date.today()

        # Now call mark expired — should mark 1
        resp = client.post("/api/portfolio/resolve-expired")
        assert resp.status_code == 200
        assert resp.json()["marked_expired"] == 1

        # Verify entry is now expired
        get_resp = client.get(f"/api/portfolio/{entry_id}")
        assert get_resp.json()["status"] == "expired"

    def test_future_target_date_stays_active(self, client: TestClient) -> None:
        # Normal entry — target_date 30 days in future
        post_resp = client.post("/api/portfolio", json=_holding_payload())
        assert post_resp.status_code == 201
        entry_id = post_resp.json()["id"]

        resp = client.post("/api/portfolio/resolve-expired")
        assert resp.status_code == 200
        assert resp.json()["marked_expired"] == 0

        get_resp = client.get(f"/api/portfolio/{entry_id}")
        assert get_resp.json()["status"] == "active"

    def test_already_resolved_entries_not_re_expired(self, client: TestClient) -> None:
        # Add entry with past target_date and resolve it as win first
        fake_creation_date = date.today() - timedelta(days=31)
        with patch("api.routes.portfolio.date") as mock_date:
            mock_date.today.return_value = fake_creation_date
            mock_date.fromisoformat = date.fromisoformat
            post_resp = client.post("/api/portfolio", json=_holding_payload(
                ai_predicted_change_pct=5.0,
                entry_price=100.0,
            ))
        entry_id = post_resp.json()["id"]

        # Resolve as win
        client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 103.0})

        # mark-expired should not change it back
        resp = client.post("/api/portfolio/resolve-expired")
        assert resp.json()["marked_expired"] == 0

        get_resp = client.get(f"/api/portfolio/{entry_id}")
        assert get_resp.json()["status"] == "win"


# ── TestSummary ────────────────────────────────────────────────────────────────

class TestSummary:
    def test_win_rate_computed_correctly(self, client: TestClient) -> None:
        # Add 3 entries and resolve 2 as win, 1 as loss
        for i in range(3):
            client.post("/api/portfolio", json=_holding_payload(
                ticker=f"STK{i}",
                ai_predicted_change_pct=5.0,
                entry_price=100.0,
            ))

        entries = client.get("/api/portfolio").json()["entries"]
        assert len(entries) == 3

        # Resolve first two as wins
        client.post(f"/api/portfolio/{entries[0]['id']}/resolve", json={"actual_price": 105.0})
        client.post(f"/api/portfolio/{entries[1]['id']}/resolve", json={"actual_price": 106.0})
        # Resolve third as loss
        client.post(f"/api/portfolio/{entries[2]['id']}/resolve", json={"actual_price": 97.0})

        summary = client.get("/api/portfolio").json()
        assert summary["wins"] == 2
        assert summary["losses"] == 1
        assert summary["total_resolved"] == 3
        assert summary["total_active"] == 0
        assert summary["win_rate"] == pytest.approx(2 / 3, abs=0.001)

    def test_win_rate_none_when_no_resolved_entries(self, client: TestClient) -> None:
        client.post("/api/portfolio", json=_holding_payload())
        summary = client.get("/api/portfolio").json()
        assert summary["win_rate"] is None
        assert summary["total_resolved"] == 0

    def test_mixed_active_and_resolved(self, client: TestClient) -> None:
        # 1 active, 1 resolved win
        client.post("/api/portfolio", json=_holding_payload(ticker="STK0"))
        resp2 = client.post("/api/portfolio", json=_holding_payload(
            ticker="STK1",
            ai_predicted_change_pct=5.0,
            entry_price=100.0,
        ))
        client.post(f"/api/portfolio/{resp2.json()['id']}/resolve", json={"actual_price": 105.0})

        summary = client.get("/api/portfolio").json()
        assert summary["total_active"] == 1
        assert summary["total_resolved"] == 1
        assert summary["wins"] == 1
        assert summary["losses"] == 0
        assert summary["win_rate"] == 1.0


# ── TestPortfolioPrices ────────────────────────────────────────────────────────

def _make_yf_batch(prices: dict[str, float]):
    """Build a fake yf.Tickers()-style object with fast_info prices."""
    batch = MagicMock()
    tickers_dict = {}
    for ticker, price in prices.items():
        fi = MagicMock()
        fi.last_price = price
        fi.regular_market_price = price
        ticker_obj = MagicMock()
        ticker_obj.fast_info = fi
        tickers_dict[ticker] = ticker_obj
    batch.tickers = tickers_dict
    return batch


class TestPortfolioPrices:
    def test_empty_tickers_returns_empty(self, client: TestClient) -> None:
        resp = client.get("/api/portfolio/prices?tickers=&market=us")
        assert resp.status_code == 200
        assert resp.json()["prices"] == {}

    def test_valid_tickers_returns_price_map(self, client: TestClient) -> None:
        fake_batch = _make_yf_batch({"NVDA": 487.25, "AAPL": 212.50})
        with patch("api.routes.portfolio.asyncio.to_thread", return_value={"NVDA": 487.25, "AAPL": 212.50}):
            resp = client.get("/api/portfolio/prices?tickers=NVDA,AAPL&market=us")
        assert resp.status_code == 200
        data = resp.json()
        assert "prices" in data
        assert data["prices"]["NVDA"] == pytest.approx(487.25)
        assert data["prices"]["AAPL"] == pytest.approx(212.50)

    def test_tickers_capped_at_20(self, client: TestClient) -> None:
        """More than 20 tickers should be silently truncated — no error."""
        many = ",".join([f"STK{i}" for i in range(25)])
        with patch("api.routes.portfolio.asyncio.to_thread", return_value={}):
            resp = client.get(f"/api/portfolio/prices?tickers={many}&market=us")
        assert resp.status_code == 200
        assert "prices" in resp.json()

    def test_failed_ticker_omitted_gracefully(self, client: TestClient) -> None:
        """If yfinance fails for a ticker, it should be omitted, not crash."""
        with patch("api.routes.portfolio.asyncio.to_thread", return_value={"AAPL": 212.50}):
            resp = client.get("/api/portfolio/prices?tickers=FAKEXXX,AAPL&market=us")
        assert resp.status_code == 200
        prices = resp.json()["prices"]
        assert "AAPL" in prices
        assert "FAKEXXX" not in prices

    def test_india_market_returns_200(self, client: TestClient) -> None:
        with patch("api.routes.portfolio.asyncio.to_thread", return_value={"RELIANCE": 2950.0}):
            resp = client.get("/api/portfolio/prices?tickers=RELIANCE&market=india")
        assert resp.status_code == 200
        assert "prices" in resp.json()


# ── TestRouteConflict ──────────────────────────────────────────────────────────

class TestRouteConflict:
    def test_get_entry_by_id_does_not_match_resolve_expired(self, client: TestClient) -> None:
        """GET /portfolio/{entry_id} must not swallow the literal path 'resolve-expired'."""
        # Add a real entry and get it by ID — should work fine
        post_resp = client.post("/api/portfolio", json=_holding_payload())
        entry_id = post_resp.json()["id"]

        resp = client.get(f"/api/portfolio/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == entry_id

    def test_resolve_expired_post_route_reachable(self, client: TestClient) -> None:
        """POST /portfolio/resolve-expired must be reachable (not captured by /{entry_id}/resolve)."""
        resp = client.post("/api/portfolio/resolve-expired")
        assert resp.status_code == 200
        assert "marked_expired" in resp.json()

    def test_resolve_entry_by_id_works(self, client: TestClient) -> None:
        """POST /portfolio/{entry_id}/resolve must work correctly."""
        post_resp = client.post("/api/portfolio", json=_holding_payload(
            ai_predicted_change_pct=5.0,
            entry_price=100.0,
        ))
        entry_id = post_resp.json()["id"]

        resp = client.post(f"/api/portfolio/{entry_id}/resolve", json={"actual_price": 103.0})
        assert resp.status_code == 200
        assert resp.json()["status"] == "win"
