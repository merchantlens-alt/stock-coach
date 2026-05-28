from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any, Optional

import httpx
import yfinance as yf

from core.auth import get_cached_token
from core.config import Settings
from core.exceptions import MarketDataError, TickerNotFoundError
from core.logging import get_logger
from models.schemas import FundamentalsData, Market, SignalTier, StockGainer, compute_quality_score

log = get_logger(__name__)

# ── Yahoo Finance search (company name → ticker) ───────────────────────────────
_YF_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_US_EXCHANGES = {"NMS", "NYQ", "NGM", "PCX", "BATS", "ASE", "OPR"}

# ── Gemini + Google Search prompts ────────────────────────────────────────────
# We ask Gemini to output a pipe-delimited table instead of JSON.
# Reason: Vertex AI blocks responseSchema when googleSearch grounding is active
# (returns HTTP 400). Prose is hard to parse. Pipe-delimited text is easy to
# parse deterministically in Python with no second AI call needed.

_TABLE_FORMAT = """
Output ONLY a pipe-delimited data table — no headers, no prose, no markdown.
One stock per line in this exact format:
TICKER|NAME|PRICE|CHANGE_PCT|CHANGE_ABS|VOLUME|SECTOR|HAS_CATALYST

CHANGE_PCT: total percentage gain for the requested time window (not just today's session).
HAS_CATALYST: Y if a specific news catalyst exists (FDA/regulatory approval, government contract, \
earnings beat, major partnership, acquisition, licensing deal), N if no clear catalyst.

Example:
ASTC|Astrotech Corporation|6.55|165.2|4.08|500000|Industrials|Y
NVDA|NVIDIA Corporation|950.00|8.5|74.50|45000000|Technology|N

Output at least 20 stocks. Sort by CHANGE_PCT descending."""

# Maps Period → human-readable window used inside prompts
_PERIOD_WINDOW: dict[str, dict[str, str]] = {
    "1d": {"gainers": "most recent trading session (last 24 hours)", "catalyst": "last 24 hours"},
    "1w": {"gainers": "past 5 trading days (1 week)", "catalyst": "past 7 days"},
    "1m": {"gainers": "past 20 trading days (1 month)", "catalyst": "past 30 days"},
}


def _us_nyse_prompt(period: str = "1d") -> str:
    w = _PERIOD_WINDOW[period]["gainers"]
    return (
        f"Use Google Search to find the top 25 US stock gainers on NYSE over the {w}.\n\n"
        "Only include stocks where ALL of these are true:\n"
        "- Listed on NYSE (not OTC or pink sheets)\n"
        "- Price above $5\n"
        "- Session volume above 500,000 shares\n"
        "- Ticker symbol is 5 characters or fewer\n"
        "- Not a warrant/right/unit (ticker does not end in W, R, or U)\n\n"
        + _TABLE_FORMAT
    )


def _us_nasdaq_prompt(period: str = "1d") -> str:
    w = _PERIOD_WINDOW[period]["gainers"]
    return (
        f"Use Google Search to find the top 25 US stock gainers on NASDAQ over the {w}.\n\n"
        "Only include stocks where ALL of these are true:\n"
        "- Listed on NASDAQ (not OTC or pink sheets)\n"
        "- Price above $5\n"
        "- Session volume above 500,000 shares\n"
        "- Ticker symbol is 5 characters or fewer\n"
        "- Not a warrant/right/unit (ticker does not end in W, R, or U)\n\n"
        + _TABLE_FORMAT
    )


def _india_gainers_prompt(period: str = "1d") -> str:
    w = _PERIOD_WINDOW[period]["gainers"]
    return (
        f"Use Google Search to find the top 50 NSE (National Stock Exchange of India) "
        f"stock gainers over the {w}.\n\n"
        "Only include stocks where ALL of these are true:\n"
        "- Listed on NSE India\n"
        "- Price above ₹50\n"
        "- Session volume above 100,000 shares\n\n"
        "Use the NSE ticker symbol WITHOUT the .NS suffix.\n"
        "Use INR values for PRICE and CHANGE_ABS.\n\n"
        + _TABLE_FORMAT
    )


def _us_catalyst_prompt(period: str = "1d") -> str:
    w = _PERIOD_WINDOW[period]["catalyst"]
    return (
        f"Use Google Search to find US stocks (NYSE or NASDAQ) that have significant news catalysts "
        f"published in the {w}. Focus on catalysts that open new markets or represent "
        "structural changes — not just short-term pops.\n\n"
        "Target catalyst types: FDA or government regulatory approvals, government contracts or grants, "
        "major partnerships or licensing deals, clinical trial results, index inclusions, "
        "earnings surprises, acquisition announcements.\n\n"
        "Include stocks with ANY positive price change (even 1–5%) — the catalyst matters more than "
        "the current % gain.\n\n"
        "Only include stocks where ALL of these are true:\n"
        "- Listed on NYSE or NASDAQ (not OTC or pink sheets)\n"
        "- Price above $3\n"
        "- Ticker symbol is 5 characters or fewer\n"
        "- Has a specific, identifiable news catalyst\n\n"
        + _TABLE_FORMAT
    )


def _india_catalyst_prompt(period: str = "1d") -> str:
    w = _PERIOD_WINDOW[period]["catalyst"]
    return (
        f"Use Google Search to find NSE India stocks that have significant news catalysts "
        f"published in the {w}. Focus on catalysts that represent structural changes "
        "or material business events.\n\n"
        "Target catalyst types: SEBI or government approvals, major government contracts, "
        "FII investments or block deals, earnings surprises, major partnerships, "
        "sector policy changes.\n\n"
        "Include stocks with ANY positive price change (even 1–5%) — the catalyst matters more than "
        "the current % gain.\n\n"
        "Only include NSE-listed stocks. Use ticker WITHOUT the .NS suffix. "
        "Use INR values for PRICE and CHANGE_ABS.\n\n"
        + _TABLE_FORMAT
    )


class MarketDataService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._top_n = settings.top_gainers_count

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_gainers(self, market: Market, period: str = "1d") -> list[StockGainer]:
        if market == "us":
            return await self.get_us_gainers(period)
        return await self.get_india_gainers(period)

    async def get_us_gainers(self, period: str = "1d") -> list[StockGainer]:
        try:
            # Three parallel Gemini calls: NYSE, NASDAQ, and a catalyst scanner.
            # NYSE/NASDAQ find stocks by % gain; catalyst scanner finds stocks by news quality.
            nyse_raw, nasdaq_raw, catalyst_raw = await asyncio.gather(
                self._fetch_gainers_gemini(_us_nyse_prompt(period), "us-nyse"),
                self._fetch_gainers_gemini(_us_nasdaq_prompt(period), "us-nasdaq"),
                self._fetch_gainers_gemini(_us_catalyst_prompt(period), "us-catalyst"),
            )
            # Build and deduplicate NYSE+NASDAQ gainers
            gainers = self._build_gainers(nyse_raw + nasdaq_raw, "us")
            seen: set[str] = set()
            deduped: list[StockGainer] = []
            for g in gainers:
                if g.ticker not in seen:
                    seen.add(g.ticker)
                    deduped.append(g)
            gainers = deduped

            # Build catalyst plays and merge — upgrades movers to confirmed, adds new catalyst stocks
            catalyst_plays = self._build_gainers(catalyst_raw, "us")
            merged = self._merge_gainers_and_catalysts(gainers, catalyst_plays)

            log.info(
                "market_data.us_gainers_fetched",
                count=len(merged),
                confirmed=sum(1 for g in merged if g.signal_tier == "confirmed"),
                catalyst=sum(1 for g in merged if g.signal_tier == "catalyst"),
                mover=sum(1 for g in merged if g.signal_tier == "mover"),
            )
            return merged[: self._top_n]
        except Exception as exc:
            log.error("market_data.us_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch US gainers: {exc}") from exc

    async def get_india_gainers(self, period: str = "1d") -> list[StockGainer]:
        try:
            # Two parallel Gemini calls: India gainers + India catalyst scanner
            india_raw, catalyst_raw = await asyncio.gather(
                self._fetch_gainers_gemini(_india_gainers_prompt(period), "india"),
                self._fetch_gainers_gemini(_india_catalyst_prompt(period), "india-catalyst"),
            )
            gainers = self._build_gainers(india_raw, "india")
            catalyst_plays = self._build_gainers(catalyst_raw, "india")
            merged = self._merge_gainers_and_catalysts(gainers, catalyst_plays)

            log.info(
                "market_data.india_gainers_fetched",
                count=len(merged),
                confirmed=sum(1 for g in merged if g.signal_tier == "confirmed"),
                catalyst=sum(1 for g in merged if g.signal_tier == "catalyst"),
                mover=sum(1 for g in merged if g.signal_tier == "mover"),
            )
            return merged[: self._top_n]
        except Exception as exc:
            log.error("market_data.india_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch India gainers: {exc}") from exc

    async def get_fundamentals(self, ticker: str, market: Market) -> FundamentalsData:
        yf_ticker = f"{ticker}.NS" if market == "india" else ticker
        try:
            data = await asyncio.to_thread(self._fetch_fundamentals_sync, yf_ticker)
            return data
        except Exception as exc:
            log.error("market_data.fundamentals_error", ticker=ticker, error=str(exc))
            raise MarketDataError(f"Failed to fetch fundamentals for {ticker}: {exc}") from exc

    # ── Gemini + Google Search (pipe-delimited table) ─────────────────────────

    async def _fetch_gainers_gemini(
        self, prompt: str, market: str
    ) -> list[dict[str, Any]]:
        """
        Ask Gemini (with Google Search grounding) to return a pipe-delimited
        table of today's top gainers.

        Why pipe-delimited instead of JSON?
        Vertex AI rejects requests combining googleSearch grounding with
        responseMimeType/responseSchema (HTTP 400). Prose is unpredictable.
        Pipe-delimited text is structured enough for Gemini to produce
        consistently and trivial to parse in Python — no second AI call needed.
        """
        token = await asyncio.to_thread(get_cached_token)
        project = self._settings.google_cloud_project
        region = self._settings.google_cloud_region
        model = self._settings.vertex_ai_model_flash
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 4096,
                # NOTE: responseMimeType / responseSchema intentionally omitted —
                # Vertex AI returns HTTP 400 when combined with googleSearch.
            },
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            if not resp.is_success:
                log.error(
                    "market_data.gemini_http_error",
                    market=market,
                    status=resp.status_code,
                    body=resp.text[:400],
                )
            resp.raise_for_status()

        data = resp.json()
        parts = data["candidates"][0]["content"].get("parts", [])
        text = "".join(p.get("text", "") for p in parts)

        log.info("market_data.gemini_raw", market=market, chars=len(text), preview=text[:500])
        return _parse_pipe_table(text)

    # ── Builder ───────────────────────────────────────────────────────────────

    def _build_gainers(
        self, raw: list[dict[str, Any]], market: Market
    ) -> list[StockGainer]:
        gainers: list[StockGainer] = []
        for q in raw:
            try:
                ticker = str(q.get("ticker", "")).upper().strip()
                if not ticker:
                    continue
                price = float(q.get("price", 0))
                volume = int(q.get("volume", 0))
                change_pct = float(q.get("change_pct", 0))
                if change_pct <= 0:
                    continue

                has_catalyst = bool(q.get("has_catalyst", False))
                tier: SignalTier = "confirmed" if has_catalyst else "mover"

                score, label = compute_quality_score(price, volume, change_pct, ticker)
                gainers.append(
                    StockGainer(
                        ticker=ticker,
                        name=str(q.get("name", ticker)),
                        market=market,
                        price=price,
                        change_pct=round(change_pct, 2),
                        change_abs=float(q.get("change_abs", 0)),
                        volume=volume,
                        sector=q.get("sector"),
                        quality_score=score,
                        quality_label=label,
                        signal_tier=tier,
                    )
                )
            except Exception:
                continue

        return sorted(gainers, key=lambda g: g.change_pct, reverse=True)

    def _merge_gainers_and_catalysts(
        self,
        gainers: list[StockGainer],
        catalyst_plays: list[StockGainer],
    ) -> list[StockGainer]:
        """
        Merge gainers list with catalyst plays and assign final signal tiers.

        Rules:
          - Gainer whose ticker also appears in catalyst_plays → upgraded to 'confirmed'
          - Catalyst play not in gainers → added as 'catalyst'
          - Gainer not in catalyst_plays → keeps its tier ('confirmed' or 'mover')
        Sort: confirmed first, catalyst second, mover third; within each tier by change_pct desc.
        """
        gainer_tickers = {g.ticker for g in gainers}
        seen = gainer_tickers.copy()

        # Build index for O(1) lookup; reconstruct immutably to avoid mutating cached objects.
        gainer_index: dict[str, int] = {g.ticker: i for i, g in enumerate(gainers)}
        result: list[StockGainer] = list(gainers)

        for cp in catalyst_plays:
            if cp.ticker in gainer_tickers:
                i = gainer_index[cp.ticker]
                result[i] = result[i].model_copy(update={"signal_tier": "confirmed"})
            elif cp.ticker not in seen:
                result.append(cp.model_copy(update={"signal_tier": "catalyst"}))
                seen.add(cp.ticker)

        _TIER_ORDER: dict[SignalTier, int] = {"confirmed": 0, "catalyst": 1, "mover": 2}
        result.sort(key=lambda g: (_TIER_ORDER[g.signal_tier], -g.change_pct))
        return result

    # ── yfinance for fundamentals ─────────────────────────────────────────────

    def _fetch_fundamentals_sync(self, yf_ticker: str) -> FundamentalsData:
        info = yf.Ticker(yf_ticker).info
        if not info:
            raise TickerNotFoundError(yf_ticker)
        return FundamentalsData(
            pe_ratio=_safe_float(info.get("trailingPE")),
            forward_pe=_safe_float(info.get("forwardPE")),
            roe=_safe_float(info.get("returnOnEquity")),
            debt_equity=_safe_float(info.get("debtToEquity")),
            revenue_growth_yoy=_safe_float(info.get("revenueGrowth")),
            earnings_growth_yoy=_safe_float(info.get("earningsGrowth")),
            profit_margin=_safe_float(info.get("profitMargins")),
            fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
            analyst_target_price=_safe_float(info.get("targetMeanPrice")),
            analyst_recommendation=info.get("recommendationKey"),
        )


def _parse_pipe_table(text: str) -> list[dict[str, Any]]:
    """
    Parse Gemini's pipe-delimited table response into a list of stock dicts.

    Expected line format (Gemini is instructed to produce this):
      TICKER|NAME|PRICE|CHANGE_PCT|CHANGE_ABS|VOLUME|SECTOR

    Tolerant of:
    - Markdown table format with surrounding pipes: | NVDA | NVIDIA | ...
    - Volume with unit suffixes: 45.2M, 500K, 1.2B
    - Extra whitespace / blank lines / missing SECTOR column
    - Header lines (skipped because PRICE is non-numeric)
    - Markdown table separators (---|---|)
    - Markdown bold/italic formatting on ticker: **NVDA**
    """
    results: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        # Skip markdown separators like |---|---| or |:--|--:|
        if re.match(r"^[\s|:\-]+$", line):
            continue

        parts = [p.strip() for p in line.split("|")]

        # ── Handle markdown table rows: | A | B | C | → strip empty edge fields ──
        # When Gemini wraps each row in pipes the split produces an empty string
        # at index 0 and the last position.  Without this fix parts[0] == "" and
        # the ticker check below skips every row → 0 gainers.
        if parts and not parts[0]:
            parts = parts[1:]
        if parts and not parts[-1]:
            parts = parts[:-1]

        if len(parts) < 6:
            continue

        # Strip markdown formatting from ticker (**NVDA** → NVDA)
        raw_ticker = re.sub(r"[^A-Z0-9]", "", parts[0].upper())
        name = parts[1]
        price_str = parts[2]
        change_pct_str = parts[3]
        change_abs_str = parts[4]
        volume_str = parts[5]
        sector = parts[6].strip() if len(parts) > 6 else None
        has_catalyst = parts[7].strip().upper() in ("Y", "YES", "TRUE", "1") if len(parts) > 7 else False

        # Skip header rows (price field is not numeric), blank tickers, and
        # purely numeric strings (e.g. "123") — real tickers have at least one letter.
        if not raw_ticker or len(raw_ticker) > 10 or not any(c.isalpha() for c in raw_ticker):
            continue

        try:
            price = float(
                price_str.replace(",", "").replace("$", "").replace("₹", "").replace(" ", "")
            )
            change_pct = float(
                change_pct_str.replace("%", "").replace("+", "").replace(" ", "")
            )
            change_abs = float(
                change_abs_str.replace(",", "").replace("$", "").replace("₹", "").replace(" ", "")
            )
            volume = _parse_volume(volume_str)
        except (ValueError, AttributeError):
            continue  # header row or malformed — skip

        results.append({
            "ticker": raw_ticker,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "change_abs": change_abs,
            "volume": volume,
            "sector": sector if sector else None,
            "has_catalyst": has_catalyst,
        })

    if results:
        log.info("market_data.pipe_table_parsed", rows=len(results))
    else:
        log.warning(
            "market_data.pipe_table_empty",
            hint="Gemini may have returned an unexpected format — see gemini_raw log for the raw text",
        )
    return results


def _parse_volume(s: str) -> int:
    """
    Parse a volume string that may include unit suffixes.

    Examples handled:
      "500000"    → 500000
      "500,000"   → 500000
      "500K"      → 500000
      "45.2M"     → 45200000
      "1.2B"      → 1200000000
      "500000.0"  → 500000   (avoids the bug in int(s.replace(".", "")) → 5000000)
    """
    s = s.strip().upper().replace(",", "").replace(" ", "")
    for suffix, mult in [("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)]:
        if s.endswith(suffix):
            return int(float(s[:-1]) * mult)
    return int(float(s))


async def resolve_ticker_by_name(query: str, market: Market) -> str | None:
    """
    Resolve a company name (e.g. "SANDISK") to its ticker (e.g. "SNDK").

    Strategy (in order):
      1. Gemini — primary resolver. Uses training knowledge, no googleSearch,
         no rate limits, ~1 s. Reliable for any well-known company.
      2. Yahoo Finance search — fallback only. Yahoo Finance has previously
         returned 429/403 errors so we don't rely on it as the primary path.
    """
    # ── 1. Gemini (primary — reliable, no external API dependency) ────────────
    result = await _resolve_ticker_via_gemini(query, market)
    if result:
        return result

    # ── 2. Yahoo Finance search (fallback) ────────────────────────────────────
    params = {
        "q": query,
        "quotesCount": 8,
        "newsCount": 0,
        "listsCount": 0,
        "enableFuzzyQuery": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(_YF_SEARCH_URL, params=params, headers=_YF_HEADERS)
            resp.raise_for_status()
        quotes = resp.json().get("quotes", [])

        for q in quotes:
            if q.get("quoteType") != "EQUITY":
                continue
            symbol: str = q.get("symbol", "")
            exchange: str = q.get("exchange", "")

            if market == "india":
                if symbol.endswith(".NS"):
                    return symbol[:-3]
                if symbol.endswith(".BO"):
                    return symbol[:-3]
                if exchange in ("NSE", "BSE"):
                    return symbol
            else:
                if "." not in symbol and len(symbol) <= 5 and exchange in _US_EXCHANGES:
                    return symbol
                if "." not in symbol and len(symbol) <= 5 and not exchange:
                    return symbol
    except Exception as exc:
        log.warning("market_data.yf_name_resolve_failed", query=query, error=str(exc))

    return None


async def _resolve_ticker_via_gemini(query: str, market: str) -> str | None:
    """
    Ask Gemini (without googleSearch) to map a company name to its ticker.
    Uses the model's training knowledge — very fast (~1 s) and no rate limits.
    Returns the ticker string or None if unknown / Gemini not configured.
    """
    from core.config import get_settings as _get_settings  # avoid circular import

    settings = _get_settings()
    if not settings.google_cloud_project:
        return None

    exchange_hint = "NASDAQ or NYSE" if market == "us" else "NSE India"
    prompt = (
        f"What is the {exchange_hint} stock ticker symbol for the company '{query}'?\n"
        "Reply with ONLY the ticker symbol — no explanation, no punctuation.\n"
        "If you are not sure, reply with UNKNOWN."
    )

    try:
        token = await asyncio.to_thread(get_cached_token)
        region = settings.google_cloud_region
        project = settings.google_cloud_project
        model = settings.vertex_ai_model_flash
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 15,  # ticker is at most ~10 chars
            },
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            if not resp.is_success:
                log.warning(
                    "market_data.gemini_ticker_resolve_http_error",
                    status=resp.status_code,
                )
                return None

        parts = resp.json()["candidates"][0]["content"].get("parts", [])
        raw = "".join(p.get("text", "") for p in parts).strip().upper()
        # Validate: must be alphanumeric, 1-10 chars, not "UNKNOWN"
        raw = re.sub(r"[^A-Z0-9]", "", raw)
        if raw and raw != "UNKNOWN" and 1 <= len(raw) <= 10:
            log.info("market_data.gemini_ticker_resolved", query=query, ticker=raw, market=market)
            return raw
    except Exception as exc:
        log.warning("market_data.gemini_ticker_resolve_failed", query=query, error=str(exc))

    return None


def fundamentals_from_info(info: dict[str, Any]) -> FundamentalsData:
    """
    Build a FundamentalsData from an already-fetched yfinance `.info` dict.
    Used to avoid a second `yf.Ticker().info` call when the data was already
    retrieved during gainer resolution.
    """
    return FundamentalsData(
        pe_ratio=_safe_float(info.get("trailingPE")),
        forward_pe=_safe_float(info.get("forwardPE")),
        roe=_safe_float(info.get("returnOnEquity")),
        debt_equity=_safe_float(info.get("debtToEquity")),
        revenue_growth_yoy=_safe_float(info.get("revenueGrowth")),
        earnings_growth_yoy=_safe_float(info.get("earningsGrowth")),
        profit_margin=_safe_float(info.get("profitMargins")),
        fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
        fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
        analyst_target_price=_safe_float(info.get("targetMeanPrice")),
        analyst_recommendation=info.get("recommendationKey"),
    )


def _safe_float(v: object) -> Optional[float]:
    try:
        return float(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(v: object) -> Optional[int]:
    try:
        return int(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def today_str() -> str:
    return date.today().isoformat()
