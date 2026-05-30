from __future__ import annotations

import asyncio
import math
import re
from datetime import date
from typing import Any, Optional

import httpx
import yfinance as yf
from yfinance.screener.screener import screen as _yf_screen
from yfinance.screener.query import EquityQuery as _YFEquityQuery

from core.auth import get_cached_token
from core.config import Settings
from core.exceptions import MarketDataError, TickerNotFoundError
from core.logging import get_logger
from models.schemas import FundamentalsData, Market, SignalTier, StockGainer, compute_quality_score

log = get_logger(__name__)

_US_EXCHANGES = {"NMS", "NYQ", "NGM", "PCX", "BATS", "ASE", "OPR"}

# ── Curated ticker universes ───────────────────────────────────────────────────
# yf.download handles Yahoo Finance auth internally, avoiding 429s from direct
# API calls. We maintain a curated list of ~110 US and ~60 India NSE tickers
# and compute period returns from downloaded OHLCV data.

_US_TICKER_UNIVERSE: dict[str, dict[str, str]] = {
    # ── Technology / Semiconductors ────────────────────────────────────────────
    "AAPL":  {"name": "Apple Inc",                  "sector": "Technology"},
    "MSFT":  {"name": "Microsoft Corporation",      "sector": "Technology"},
    "NVDA":  {"name": "NVIDIA Corporation",         "sector": "Technology"},
    "AMD":   {"name": "Advanced Micro Devices",     "sector": "Technology"},
    "INTC":  {"name": "Intel Corporation",          "sector": "Technology"},
    "QCOM":  {"name": "Qualcomm",                   "sector": "Technology"},
    "AVGO":  {"name": "Broadcom Inc",               "sector": "Technology"},
    "TXN":   {"name": "Texas Instruments",          "sector": "Technology"},
    "AMAT":  {"name": "Applied Materials",          "sector": "Technology"},
    "KLAC":  {"name": "KLA Corporation",            "sector": "Technology"},
    "LRCX":  {"name": "Lam Research",               "sector": "Technology"},
    "MRVL":  {"name": "Marvell Technology",         "sector": "Technology"},
    "SMCI":  {"name": "Super Micro Computer",       "sector": "Technology"},
    "DELL":  {"name": "Dell Technologies",          "sector": "Technology"},
    "HPQ":   {"name": "HP Inc",                     "sector": "Technology"},
    "HPE":   {"name": "Hewlett Packard Enterprise", "sector": "Technology"},
    "ACMR":  {"name": "ACM Research",               "sector": "Technology"},
    # ── Software / Cloud ───────────────────────────────────────────────────────
    "CRM":   {"name": "Salesforce Inc",             "sector": "Technology"},
    "ADBE":  {"name": "Adobe Inc",                  "sector": "Technology"},
    "NOW":   {"name": "ServiceNow",                 "sector": "Technology"},
    "SNOW":  {"name": "Snowflake Inc",              "sector": "Technology"},
    "PLTR":  {"name": "Palantir Technologies",      "sector": "Technology"},
    "DDOG":  {"name": "Datadog Inc",                "sector": "Technology"},
    "ZS":    {"name": "Zscaler Inc",                "sector": "Technology"},
    "CRWD":  {"name": "CrowdStrike Holdings",       "sector": "Technology"},
    "PANW":  {"name": "Palo Alto Networks",         "sector": "Technology"},
    "OKTA":  {"name": "Okta Inc",                   "sector": "Technology"},
    "S":     {"name": "SentinelOne Inc",            "sector": "Technology"},
    "SHOP":  {"name": "Shopify Inc",                "sector": "Technology"},
    # ── Consumer Tech / Internet ───────────────────────────────────────────────
    "META":  {"name": "Meta Platforms",             "sector": "Communication Services"},
    "GOOGL": {"name": "Alphabet Inc",               "sector": "Communication Services"},
    "AMZN":  {"name": "Amazon.com",                 "sector": "Consumer Discretionary"},
    "NFLX":  {"name": "Netflix Inc",                "sector": "Communication Services"},
    "TSLA":  {"name": "Tesla Inc",                  "sector": "Consumer Discretionary"},
    "UBER":  {"name": "Uber Technologies",          "sector": "Technology"},
    "LYFT":  {"name": "Lyft Inc",                   "sector": "Technology"},
    "ABNB":  {"name": "Airbnb Inc",                 "sector": "Consumer Discretionary"},
    "SNAP":  {"name": "Snap Inc",                   "sector": "Communication Services"},
    "PINS":  {"name": "Pinterest Inc",              "sector": "Communication Services"},
    "SPOT":  {"name": "Spotify Technology",         "sector": "Communication Services"},
    "RBLX":  {"name": "Roblox Corporation",         "sector": "Communication Services"},
    "TTWO":  {"name": "Take-Two Interactive",       "sector": "Communication Services"},
    "EA":    {"name": "Electronic Arts",            "sector": "Communication Services"},
    # ── Fintech / Crypto ──────────────────────────────────────────────────────
    "COIN":  {"name": "Coinbase Global",            "sector": "Financial Services"},
    "HOOD":  {"name": "Robinhood Markets",          "sector": "Financial Services"},
    "SQ":    {"name": "Block Inc",                  "sector": "Financial Services"},
    "PYPL":  {"name": "PayPal Holdings",            "sector": "Financial Services"},
    "AFRM":  {"name": "Affirm Holdings",            "sector": "Financial Services"},
    "MARA":  {"name": "MARA Holdings",              "sector": "Technology"},
    "RIOT":  {"name": "Riot Platforms",             "sector": "Technology"},
    "CLSK":  {"name": "CleanSpark Inc",             "sector": "Technology"},
    "IREN":  {"name": "Iris Energy",                "sector": "Technology"},
    # ── Financial Services ────────────────────────────────────────────────────
    "V":     {"name": "Visa Inc",                   "sector": "Financial Services"},
    "MA":    {"name": "Mastercard",                 "sector": "Financial Services"},
    "AXP":   {"name": "American Express",           "sector": "Financial Services"},
    "JPM":   {"name": "JPMorgan Chase",             "sector": "Financial Services"},
    "GS":    {"name": "Goldman Sachs",              "sector": "Financial Services"},
    "BAC":   {"name": "Bank of America",            "sector": "Financial Services"},
    "C":     {"name": "Citigroup Inc",              "sector": "Financial Services"},
    "WFC":   {"name": "Wells Fargo",                "sector": "Financial Services"},
    "MS":    {"name": "Morgan Stanley",             "sector": "Financial Services"},
    "BLK":   {"name": "BlackRock Inc",              "sector": "Financial Services"},
    "SCHW":  {"name": "Charles Schwab",             "sector": "Financial Services"},
    # ── Healthcare / Biotech ─────────────────────────────────────────────────
    "JNJ":   {"name": "Johnson & Johnson",          "sector": "Healthcare"},
    "PFE":   {"name": "Pfizer Inc",                 "sector": "Healthcare"},
    "MRNA":  {"name": "Moderna Inc",                "sector": "Healthcare"},
    "BNTX":  {"name": "BioNTech SE",                "sector": "Healthcare"},
    "REGN":  {"name": "Regeneron Pharmaceuticals",  "sector": "Healthcare"},
    "GILD":  {"name": "Gilead Sciences",            "sector": "Healthcare"},
    "BIIB":  {"name": "Biogen Inc",                 "sector": "Healthcare"},
    "AMGN":  {"name": "Amgen Inc",                  "sector": "Healthcare"},
    "ABBV":  {"name": "AbbVie Inc",                 "sector": "Healthcare"},
    "BMY":   {"name": "Bristol-Myers Squibb",       "sector": "Healthcare"},
    "ALNY":  {"name": "Alnylam Pharmaceuticals",    "sector": "Healthcare"},
    "INCY":  {"name": "Incyte Corporation",         "sector": "Healthcare"},
    "EXAS":  {"name": "Exact Sciences",             "sector": "Healthcare"},
    "ILMN":  {"name": "Illumina Inc",               "sector": "Healthcare"},
    "HALO":  {"name": "Halozyme Therapeutics",      "sector": "Healthcare"},
    # ── Energy ───────────────────────────────────────────────────────────────
    "XOM":   {"name": "Exxon Mobil",                "sector": "Energy"},
    "CVX":   {"name": "Chevron Corporation",        "sector": "Energy"},
    "SLB":   {"name": "SLB",                        "sector": "Energy"},
    "OXY":   {"name": "Occidental Petroleum",       "sector": "Energy"},
    "MPC":   {"name": "Marathon Petroleum",         "sector": "Energy"},
    "VLO":   {"name": "Valero Energy",              "sector": "Energy"},
    "PSX":   {"name": "Phillips 66",                "sector": "Energy"},
    "EOG":   {"name": "EOG Resources",              "sector": "Energy"},
    "COP":   {"name": "ConocoPhillips",             "sector": "Energy"},
    # ── Consumer ─────────────────────────────────────────────────────────────
    "WMT":   {"name": "Walmart Inc",                "sector": "Consumer Staples"},
    "TGT":   {"name": "Target Corporation",         "sector": "Consumer Discretionary"},
    "COST":  {"name": "Costco Wholesale",           "sector": "Consumer Staples"},
    "HD":    {"name": "Home Depot",                 "sector": "Consumer Discretionary"},
    "LOW":   {"name": "Lowe's Companies",           "sector": "Consumer Discretionary"},
    "NKE":   {"name": "Nike Inc",                   "sector": "Consumer Discretionary"},
    "LULU":  {"name": "Lululemon Athletica",        "sector": "Consumer Discretionary"},
    "ROST":  {"name": "Ross Stores",                "sector": "Consumer Discretionary"},
    "TJX":   {"name": "TJX Companies",              "sector": "Consumer Discretionary"},
    # ── Industrials / Defense ────────────────────────────────────────────────
    "BA":    {"name": "Boeing Company",             "sector": "Industrials"},
    "CAT":   {"name": "Caterpillar Inc",            "sector": "Industrials"},
    "GE":    {"name": "GE Aerospace",               "sector": "Industrials"},
    "HON":   {"name": "Honeywell International",    "sector": "Industrials"},
    "LMT":   {"name": "Lockheed Martin",            "sector": "Defense"},
    "RTX":   {"name": "RTX Corporation",            "sector": "Defense"},
    "NOC":   {"name": "Northrop Grumman",           "sector": "Defense"},
    "GD":    {"name": "General Dynamics",           "sector": "Defense"},
    # ── Space / EV / Emerging Tech ───────────────────────────────────────────
    "RKLB":  {"name": "Rocket Lab USA",             "sector": "Industrials"},
    "LUNR":  {"name": "Intuitive Machines",         "sector": "Industrials"},
    "ASTS":  {"name": "AST SpaceMobile",            "sector": "Communication Services"},
    "RDW":   {"name": "Redwire Corporation",        "sector": "Industrials"},
    "IONQ":  {"name": "IonQ Inc",                   "sector": "Technology"},
    "RGTI":  {"name": "Rigetti Computing",          "sector": "Technology"},
    "RIVN":  {"name": "Rivian Automotive",          "sector": "Consumer Discretionary"},
    "LCID":  {"name": "Lucid Group",                "sector": "Consumer Discretionary"},
    "NIO":   {"name": "NIO Inc",                    "sector": "Consumer Discretionary"},
    # ── High-volatility small-caps (space, AI, biotech) ──────────────────────
    "ASTC":  {"name": "Astrotech Corporation",      "sector": "Industrials"},
    "ACHR":  {"name": "Archer Aviation",            "sector": "Industrials"},
    "JOBY":  {"name": "Joby Aviation",              "sector": "Industrials"},
    "SOUN":  {"name": "SoundHound AI",              "sector": "Technology"},
    "BBAI":  {"name": "BigBear.ai Holdings",        "sector": "Technology"},
    "QUBT":  {"name": "Quantum Computing Inc",      "sector": "Technology"},
    "ARQQ":  {"name": "Arqit Quantum",              "sector": "Technology"},
    "MANU":  {"name": "Manchester United",          "sector": "Communication Services"},
    "OKLO":  {"name": "Oklo Inc",                   "sector": "Utilities"},
    "SMR":   {"name": "NuScale Power",              "sector": "Utilities"},
    "DY":    {"name": "Dycom Industries",           "sector": "Industrials"},
    "PENN":  {"name": "PENN Entertainment",         "sector": "Consumer Discretionary"},
}

_INDIA_TICKER_UNIVERSE: dict[str, dict[str, str]] = {
    # ── Large Cap (Nifty 50) ─────────────────────────────────────────────────
    "RELIANCE":   {"name": "Reliance Industries",            "sector": "Energy"},
    "TCS":        {"name": "Tata Consultancy Services",      "sector": "Technology"},
    "HDFCBANK":   {"name": "HDFC Bank",                      "sector": "Financial Services"},
    "ICICIBANK":  {"name": "ICICI Bank",                     "sector": "Financial Services"},
    "INFY":       {"name": "Infosys",                        "sector": "Technology"},
    "KOTAKBANK":  {"name": "Kotak Mahindra Bank",            "sector": "Financial Services"},
    "SBIN":       {"name": "State Bank of India",            "sector": "Financial Services"},
    "BHARTIARTL": {"name": "Bharti Airtel",                  "sector": "Communication Services"},
    "LT":         {"name": "Larsen & Toubro",                "sector": "Industrials"},
    "ITC":        {"name": "ITC Limited",                    "sector": "Consumer Staples"},
    "WIPRO":      {"name": "Wipro Limited",                  "sector": "Technology"},
    "AXISBANK":   {"name": "Axis Bank",                      "sector": "Financial Services"},
    "MARUTI":     {"name": "Maruti Suzuki India",            "sector": "Consumer Discretionary"},
    "SUNPHARMA":  {"name": "Sun Pharmaceutical",             "sector": "Healthcare"},
    "ULTRACEMCO": {"name": "UltraTech Cement",               "sector": "Materials"},
    "TITAN":      {"name": "Titan Company",                  "sector": "Consumer Discretionary"},
    "NTPC":       {"name": "NTPC Limited",                   "sector": "Utilities"},
    "POWERGRID":  {"name": "Power Grid Corporation",         "sector": "Utilities"},
    "COALINDIA":  {"name": "Coal India",                     "sector": "Energy"},
    "ONGC":       {"name": "Oil & Natural Gas Corporation",  "sector": "Energy"},
    "BPCL":       {"name": "Bharat Petroleum",               "sector": "Energy"},
    "BAJFINANCE": {"name": "Bajaj Finance",                  "sector": "Financial Services"},
    "BAJAJFINSV": {"name": "Bajaj Finserv",                  "sector": "Financial Services"},
    "HDFCLIFE":   {"name": "HDFC Life Insurance",            "sector": "Financial Services"},
    "SBILIFE":    {"name": "SBI Life Insurance",             "sector": "Financial Services"},
    "NESTLEIND":  {"name": "Nestle India",                   "sector": "Consumer Staples"},
    "HINDUNILVR": {"name": "Hindustan Unilever",             "sector": "Consumer Staples"},
    "DIVISLAB":   {"name": "Divi's Laboratories",            "sector": "Healthcare"},
    "DRREDDY":    {"name": "Dr. Reddy's Laboratories",      "sector": "Healthcare"},
    "CIPLA":      {"name": "Cipla Limited",                  "sector": "Healthcare"},
    "TATASTEEL":  {"name": "Tata Steel",                     "sector": "Materials"},
    "JSWSTEEL":   {"name": "JSW Steel",                      "sector": "Materials"},
    "HINDALCO":   {"name": "Hindalco Industries",            "sector": "Materials"},
    "TECHM":      {"name": "Tech Mahindra",                  "sector": "Technology"},
    "HCLTECH":    {"name": "HCL Technologies",               "sector": "Technology"},
    "MPHASIS":    {"name": "Mphasis Limited",                "sector": "Technology"},
    "LTIM":       {"name": "LTIMindtree",                    "sector": "Technology"},
    "TATAMOTORS": {"name": "Tata Motors",                    "sector": "Consumer Discretionary"},
    "APOLLOHOSP": {"name": "Apollo Hospitals",               "sector": "Healthcare"},
    "ASIANPAINT": {"name": "Asian Paints",                   "sector": "Materials"},
    "EICHERMOT":  {"name": "Eicher Motors",                  "sector": "Consumer Discretionary"},
    "GRASIM":     {"name": "Grasim Industries",              "sector": "Materials"},
    "INDUSINDBK": {"name": "IndusInd Bank",                  "sector": "Financial Services"},
    "VEDL":       {"name": "Vedanta Limited",                "sector": "Materials"},
    "HINDPETRO":  {"name": "Hindustan Petroleum",            "sector": "Energy"},
    "TATAPOWER":  {"name": "Tata Power Company",             "sector": "Utilities"},
    "BIOCON":     {"name": "Biocon Limited",                 "sector": "Healthcare"},
    "OFSS":       {"name": "Oracle Financial Services",      "sector": "Technology"},
    "PERSISTENT": {"name": "Persistent Systems",             "sector": "Technology"},
    "COFORGE":    {"name": "Coforge Limited",                "sector": "Technology"},
    # ── Mid Cap / Growth ─────────────────────────────────────────────────────
    "ZOMATO":     {"name": "Zomato Limited",                 "sector": "Consumer Discretionary"},
    "IRCTC":      {"name": "IRCTC",                          "sector": "Consumer Discretionary"},
    "CHOLAFIN":   {"name": "Cholamandalam Investment",       "sector": "Financial Services"},
    "MUTHOOTFIN": {"name": "Muthoot Finance",                "sector": "Financial Services"},
    "PIIND":      {"name": "PI Industries",                  "sector": "Materials"},
    "SAIL":       {"name": "Steel Authority of India",       "sector": "Materials"},
    "ADANIENT":   {"name": "Adani Enterprises",              "sector": "Industrials"},
    "ADANIPORTS": {"name": "Adani Ports & SEZ",             "sector": "Industrials"},
    "CONCOR":     {"name": "Container Corporation of India", "sector": "Industrials"},
    "DABUR":      {"name": "Dabur India",                    "sector": "Consumer Staples"},
    "MARICO":     {"name": "Marico Limited",                 "sector": "Consumer Staples"},
}

# Custom EquityQuery for US high-movers — catches small/micro-caps (e.g. ASTC)
# that Yahoo's predefined 'day_gainers' screener silently excludes due to its
# own market-cap / liquidity criteria. Runs alongside day_gainers; results merged.
_US_HIGH_MOVERS_QUERY = _YFEquityQuery('and', [
    _YFEquityQuery('eq',  ['region',        'us']),
    _YFEquityQuery('gt',  ['intradayprice',  1]),       # exclude penny stocks
    _YFEquityQuery('gt',  ['dayvolume',      50_000]),  # low bar — big % moves matter more
    _YFEquityQuery('gt',  ['percentchange',  10]),      # only significant movers (≥10%)
])

# Predefined EquityQuery for NSE India gainers — built once at module load.
# exchange='NSI' is Yahoo Finance's code for the National Stock Exchange of India.
_INDIA_NSE_SCREENER_QUERY = _YFEquityQuery('and', [
    _YFEquityQuery('eq',    ['region',       'in']),
    _YFEquityQuery('is-in', ['exchange',     'NSI']),
    _YFEquityQuery('gt',    ['intradayprice', 50]),
    _YFEquityQuery('gt',    ['dayvolume',     100_000]),
    _YFEquityQuery('gt',    ['percentchange', 0]),
])

# ── Real-time catalyst keyword detection ──────────────────────────────────────
# These terms in a stock's latest news headlines indicate a specific, identifiable
# catalyst — the reason a stock moved, not just momentum or sector rotation.
# Used by _classify_catalysts_news() to assign "confirmed" tier in the gainers list.
_CATALYST_KEYWORDS: frozenset[str] = frozenset([
    # Earnings / guidance
    "earnings", "revenue beat", "eps beat", "quarterly result", "guidance raised",
    "above expectation", "profit surge", "record revenue", "record quarter",
    # FDA / medical
    "fda", "approval", "approved", "clearance", "cleared", "clinical trial",
    "nda", "bla", "accelerated approval", "breakthrough therapy",
    # Government / defense contracts
    "contract", "nasa", "dod", "pentagon", "darpa", "air force", "navy", "army",
    "government award", "grant award", "federal contract",
    # Corporate events
    "acquisition", "acquires", "merger", "buyout", "takeover", "partnership",
    "collaboration", "joint venture", "licensing deal", "strategic deal",
    # Capital markets
    "index inclusion", "s&p 500", "nasdaq 100", "russell", "buyback", "special dividend",
    # Major announcements
    "launch", "ipo", "spinoff", "spin-off", "major order", "strategic initiative",
    "moonshot", "lunar", "quantum",   # catches ASTC-type space/tech announcements
])


def _has_catalyst_in_headlines(headlines: list[str]) -> bool:
    """Return True if any headline contains a catalyst keyword (case-insensitive)."""
    combined = " ".join(h.lower() for h in headlines)
    return any(kw in combined for kw in _CATALYST_KEYWORDS)


# Maps app period → (yf download period, use_last_day_change).
# use_last_day_change=True:  change = close[-1]/close[-2]-1  (single trading day)
# use_last_day_change=False: change = close[-1]/close[0]-1   (full period start→end)
# Download 5d for both 1d and 1w so we always have ≥2 rows even across weekends.
_YF_DOWNLOAD_PERIOD: dict[str, tuple[str, bool]] = {
    "1d": ("5d",  True),   # Download 5 trading days → last-day change
    "1w": ("5d",  False),  # Download 5 trading days → start-to-end change
    "1m": ("1mo", False),  # Download 1 month       → start-to-end change
}

# ── Gemini + Google Search prompts ────────────────────────────────────────────
# Used as fallback when yf.download is unavailable or returns too few results.
# We ask Gemini to output a pipe-delimited table instead of JSON.
# Reason: Vertex AI blocks responseSchema when googleSearch grounding is active.

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
            if period == "1d":
                return await self._get_us_gainers_1d()
            return await self._get_us_gainers_period(period)
        except Exception as exc:
            log.error("market_data.us_gainers_error", period=period, error=str(exc))
            raise MarketDataError(f"Failed to fetch US gainers: {exc}") from exc

    async def get_india_gainers(self, period: str = "1d") -> list[StockGainer]:
        try:
            if period == "1d":
                return await self._get_india_gainers_1d()
            return await self._get_india_gainers_period(period)
        except Exception as exc:
            log.error("market_data.india_gainers_error", period=period, error=str(exc))
            raise MarketDataError(f"Failed to fetch India gainers: {exc}") from exc

    async def get_raw_movers(self, market: str) -> list[dict[str, Any]]:
        """
        Return raw mover dicts for the catalyst scanner — no tier assignment or quality
        scoring applied.  Uses the same screener as the gainers list (1d only).
        """
        if market == "us":
            return await self._get_us_gainers_screener()
        return await self._get_india_gainers_screener()

    async def get_fundamentals(self, ticker: str, market: Market) -> FundamentalsData:
        yf_ticker = f"{ticker}.NS" if market == "india" else ticker
        try:
            data = await asyncio.to_thread(self._fetch_fundamentals_sync, yf_ticker)
            return data
        except Exception as exc:
            log.error("market_data.fundamentals_error", ticker=ticker, error=str(exc))
            raise MarketDataError(f"Failed to fetch fundamentals for {ticker}: {exc}") from exc

    # ── Fast path: yfinance Screener (1d) + yf.download (1w/1m) ─────────────
    # 1d path:  yfinance screen() ~1s → direct day gainers from full universe
    # 1w/1m path: yf.download ~8-12s → compute period returns from OHLCV history
    # Both handle Yahoo Finance auth internally — no 429 unlike direct httpx calls.
    # + one Gemini catalyst classify call (~1-2s, parallel) for catalyst tagging.

    async def _get_us_gainers_screener(self) -> list[dict[str, Any]]:
        """
        Fetch US day gainers from two screeners in parallel and merge:
          1. Yahoo's predefined 'day_gainers' — covers liquid large/mid-caps.
          2. Custom EquityQuery (≥10% gain, vol≥50K) — catches small/micro-caps
             like ASTC that Yahoo's screener silently excludes by market-cap.
        Results are deduped by ticker and sorted by change_pct descending.
        """
        async def _run_predefined() -> list[dict]:
            try:
                return (await asyncio.to_thread(_yf_screen, 'day_gainers', count=50)).get('quotes', [])
            except Exception as exc:
                log.warning("market_data.us_predefined_screener_failed", error=str(exc))
                return []

        async def _run_custom() -> list[dict]:
            try:
                return (await asyncio.to_thread(
                    _yf_screen, _US_HIGH_MOVERS_QUERY,
                    count=50, sortField='percentchange', sortAsc=False,
                )).get('quotes', [])
            except Exception as exc:
                log.warning("market_data.us_custom_screener_failed", error=str(exc))
                return []

        predefined_quotes, custom_quotes = await asyncio.gather(
            _run_predefined(), _run_custom()
        )

        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        for q in predefined_quotes + custom_quotes:
            ticker = q.get("symbol", "")
            # Skip foreign cross-listings (dot in symbol), long tickers, duplicates
            if not ticker or "." in ticker or len(ticker) > 5 or ticker in seen:
                continue
            price = float(q.get("regularMarketPrice") or 0)
            change_pct = float(q.get("regularMarketChangePercent") or 0)
            volume = int(q.get("regularMarketVolume") or 0)
            if price < 1 or change_pct <= 0 or volume < 50_000:
                continue
            seen.add(ticker)
            results.append({
                "ticker": ticker,
                "name": q.get("shortName") or q.get("longName") or ticker,
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "change_abs": round(float(q.get("regularMarketChange") or 0), 2),
                "volume": volume,
                "sector": q.get("sector"),
                "has_catalyst": False,
            })

        results.sort(key=lambda r: r["change_pct"], reverse=True)
        log.info("market_data.us_screener_done", count=len(results))
        return results

    async def _get_india_gainers_screener(self) -> list[dict[str, Any]]:
        """
        Fetch NSE India day gainers via yfinance EquityQuery screener.
        Filters: exchange=NSI, price>₹50, volume>100K, positive change.
        Single call, ~1s, handles Yahoo Finance auth internally.
        Returns [] on any failure so the caller can fall back gracefully.
        """
        try:
            result = await asyncio.to_thread(
                _yf_screen,
                _INDIA_NSE_SCREENER_QUERY,
                count=50,
                sortField='percentchange',
                sortAsc=False,
            )
        except Exception as exc:
            log.warning("market_data.india_screener_failed", error=str(exc))
            return []

        results: list[dict[str, Any]] = []
        for q in result.get('quotes', []):
            ticker = q.get("symbol", "")
            # Strip exchange suffix — screener returns RELIANCE.NS format
            if ticker.endswith(".NS"):
                ticker = ticker[:-3]
            elif ticker.endswith(".BO"):
                ticker = ticker[:-3]
            elif "." in ticker:
                continue  # skip other exchange cross-listings

            if not ticker or len(ticker) > 15:
                continue

            price = float(q.get("regularMarketPrice") or 0)
            change_pct = float(q.get("regularMarketChangePercent") or 0)
            volume = int(q.get("regularMarketVolume") or 0)
            if price < 50 or change_pct <= 0 or volume < 100_000:
                continue
            results.append({
                "ticker": ticker,
                "name": q.get("shortName") or q.get("longName") or ticker,
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "change_abs": round(float(q.get("regularMarketChange") or 0), 2),
                "volume": volume,
                "sector": q.get("sector"),
                "has_catalyst": False,
            })

        results.sort(key=lambda r: r["change_pct"], reverse=True)
        log.info("market_data.india_screener_done", count=len(results))
        return results

    async def _get_us_gainers_yf_download(self, period: str) -> list[dict[str, Any]]:
        """
        Download price history for all US universe tickers via yf.download and
        return those with positive period returns, sorted by gain descending.

        yf.download handles Yahoo Finance auth internally — no 429s.
        Falls back to [] on any error so callers can degrade to Gemini gracefully.
        """
        yf_period, use_last_day = _YF_DOWNLOAD_PERIOD[period]
        tickers_str = " ".join(_US_TICKER_UNIVERSE.keys())

        try:
            df = await asyncio.to_thread(
                yf.download,
                tickers_str,
                period=yf_period,
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            log.warning("market_data.yf_download_us_failed", period=period, error=str(exc))
            return []

        if df.empty or len(df) < 2:
            log.warning(
                "market_data.yf_download_us_insufficient_rows",
                rows=len(df),
                period=period,
            )
            return []

        results: list[dict[str, Any]] = []
        for ticker, meta in _US_TICKER_UNIVERSE.items():
            try:
                close_series = df["Close"][ticker].dropna()
                vol_series = df["Volume"][ticker].dropna()

                if len(close_series) < 2:
                    continue

                if use_last_day:
                    first = float(close_series.iloc[-2])
                    last = float(close_series.iloc[-1])
                else:
                    first = float(close_series.iloc[0])
                    last = float(close_series.iloc[-1])

                last_volume = int(vol_series.iloc[-1]) if not vol_series.empty else 0

                if first <= 0:
                    continue

                change_pct = round((last / first - 1) * 100, 2)
                change_abs = round(last - first, 2)

                if last < 5 or last_volume < 500_000 or change_pct <= 0:
                    continue

                results.append({
                    "ticker": ticker,
                    "name": meta["name"],
                    "price": round(last, 2),
                    "change_pct": change_pct,
                    "change_abs": change_abs,
                    "volume": last_volume,
                    "sector": meta.get("sector"),
                    "has_catalyst": False,
                })
            except Exception:
                continue

        results.sort(key=lambda r: r["change_pct"], reverse=True)
        log.info(
            "market_data.yf_download_us_done",
            period=period,
            gainers=len(results),
            top=results[0]["ticker"] if results else None,
        )
        return results

    async def _get_india_gainers_yf_download(self, period: str) -> list[dict[str, Any]]:
        """
        Download price history for all India NSE universe tickers via yf.download.
        Appends .NS suffix for Yahoo Finance; strips it in the results.
        Falls back to [] on any error.
        """
        yf_period, use_last_day = _YF_DOWNLOAD_PERIOD[period]
        # Yahoo Finance requires .NS suffix for NSE stocks
        yf_tickers_str = " ".join(f"{t}.NS" for t in _INDIA_TICKER_UNIVERSE.keys())

        try:
            df = await asyncio.to_thread(
                yf.download,
                yf_tickers_str,
                period=yf_period,
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            log.warning("market_data.yf_download_india_failed", period=period, error=str(exc))
            return []

        if df.empty or len(df) < 2:
            log.warning(
                "market_data.yf_download_india_insufficient_rows",
                rows=len(df),
                period=period,
            )
            return []

        results: list[dict[str, Any]] = []
        for ticker, meta in _INDIA_TICKER_UNIVERSE.items():
            yf_sym = f"{ticker}.NS"
            try:
                close_series = df["Close"][yf_sym].dropna()
                vol_series = df["Volume"][yf_sym].dropna()

                if len(close_series) < 2:
                    continue

                if use_last_day:
                    first = float(close_series.iloc[-2])
                    last = float(close_series.iloc[-1])
                else:
                    first = float(close_series.iloc[0])
                    last = float(close_series.iloc[-1])

                last_volume = int(vol_series.iloc[-1]) if not vol_series.empty else 0

                if first <= 0:
                    continue

                change_pct = round((last / first - 1) * 100, 2)
                change_abs = round(last - first, 2)

                # India filters: ₹50 min price, 100K min volume
                if last < 50 or last_volume < 100_000 or change_pct <= 0:
                    continue

                results.append({
                    "ticker": ticker,   # plain NSE symbol, no .NS
                    "name": meta["name"],
                    "price": round(last, 2),
                    "change_pct": change_pct,
                    "change_abs": change_abs,
                    "volume": last_volume,
                    "sector": meta.get("sector"),
                    "has_catalyst": False,
                })
            except Exception:
                continue

        results.sort(key=lambda r: r["change_pct"], reverse=True)
        log.info(
            "market_data.yf_download_india_done",
            period=period,
            gainers=len(results),
            top=results[0]["ticker"] if results else None,
        )
        return results

    async def _classify_catalysts_news(
        self, tickers: list[str], market: str
    ) -> set[str]:
        """
        Classify which tickers have a real news catalyst by scanning their latest
        headlines from yfinance (Yahoo Finance news — free, real-time, no tokens).

        Replaces the old Gemini training-knowledge approach which always returned
        empty for recent events (training cutoff means 2026 news is unknown to it).

        Fetches news for all tickers in parallel (~1s for 20 tickers), then runs a
        keyword match against _CATALYST_KEYWORDS. Returns the set of tickers whose
        headlines contain at least one catalyst keyword.
        """
        if not tickers:
            return set()

        async def _fetch_headlines(ticker: str) -> tuple[str, list[str]]:
            yf_ticker = f"{ticker}.NS" if market == "india" else ticker
            try:
                news = await asyncio.to_thread(lambda: yf.Ticker(yf_ticker).news)
                titles: list[str] = []
                for item in (news or [])[:6]:
                    # yfinance 1.4 returns nested content dict
                    title = (
                        item.get("content", {}).get("title")
                        or item.get("title", "")
                    )
                    if title:
                        titles.append(title)
                return ticker, titles
            except Exception:
                return ticker, []

        results = await asyncio.gather(*[_fetch_headlines(t) for t in tickers])

        catalyst_tickers: set[str] = set()
        for ticker, headlines in results:
            if _has_catalyst_in_headlines(headlines):
                catalyst_tickers.add(ticker)
                log.info(
                    "market_data.catalyst_detected",
                    ticker=ticker,
                    headline=headlines[0] if headlines else "",
                )

        log.info("market_data.catalyst_news_done",
                 total=len(tickers), confirmed=len(catalyst_tickers))
        return catalyst_tickers

    # ── US fast paths ─────────────────────────────────────────────────────────

    async def _get_us_gainers_1d(self) -> list[StockGainer]:
        """
        Fast path for today's US gainers.
        Screener (~1s) + batch catalyst classify (~1-2s, sequential) = ~2-3s total.
        Falls back to Gemini+Google Search if screener returns < 5 stocks.
        """
        screener_raw = await self._get_us_gainers_screener()

        if len(screener_raw) >= 5:
            tickers = [r["ticker"] for r in screener_raw]
            catalyst_tickers = await self._classify_catalysts_news(tickers, "us")
            for r in screener_raw:
                if r["ticker"] in catalyst_tickers:
                    r["has_catalyst"] = True
            gainers = self._build_gainers(screener_raw, "us")
            log.info("market_data.us_1d_screener_path", count=len(gainers))
            return gainers[: self._top_n]

        log.warning(
            "market_data.us_screener_insufficient_fallback",
            count=len(screener_raw),
        )
        return await self._get_us_gainers_gemini("1d")

    async def _get_us_gainers_period(self, period: str) -> list[StockGainer]:
        """
        Fast path for US 1w/1m gainers.
        yf.download computes period returns directly + catalyst classify → ~10-13s total.
        Falls back to Gemini+Google Search if yf.download returns < 5 stocks.
        """
        yf_raw = await self._get_us_gainers_yf_download(period)

        if len(yf_raw) >= 5:
            tickers = [r["ticker"] for r in yf_raw]
            catalyst_tickers = await self._classify_catalysts_news(tickers, "us")
            for r in yf_raw:
                if r["ticker"] in catalyst_tickers:
                    r["has_catalyst"] = True
            gainers = self._build_gainers(yf_raw, "us")
            log.info("market_data.us_period_yf_path", period=period, count=len(gainers))
            return gainers[: self._top_n]

        log.warning(
            "market_data.us_yf_period_insufficient_fallback",
            period=period,
            count=len(yf_raw),
        )
        return await self._get_us_gainers_gemini(period)

    # ── India fast paths ──────────────────────────────────────────────────────

    async def _get_india_gainers_1d(self) -> list[StockGainer]:
        """
        Fast path for today's India NSE gainers.
        Screener (~1s) + batch catalyst classify (~1-2s, sequential) = ~2-3s total.
        Falls back to Gemini+Google Search if screener returns < 5 stocks.
        """
        screener_raw = await self._get_india_gainers_screener()

        if len(screener_raw) >= 5:
            tickers = [r["ticker"] for r in screener_raw]
            catalyst_tickers = await self._classify_catalysts_news(tickers, "india")
            for r in screener_raw:
                if r["ticker"] in catalyst_tickers:
                    r["has_catalyst"] = True
            gainers = self._build_gainers(screener_raw, "india")
            log.info("market_data.india_1d_screener_path", count=len(gainers))
            return gainers[: self._top_n]

        log.warning(
            "market_data.india_screener_insufficient_fallback",
            count=len(screener_raw),
        )
        return await self._get_india_gainers_gemini("1d")

    async def _get_india_gainers_period(self, period: str) -> list[StockGainer]:
        """
        Fast path for India 1w/1m gainers.
        yf.download computes period returns directly + catalyst classify.
        Falls back to Gemini+Google Search if yf.download returns < 5 stocks.
        """
        yf_raw = await self._get_india_gainers_yf_download(period)

        if len(yf_raw) >= 5:
            tickers = [r["ticker"] for r in yf_raw]
            catalyst_tickers = await self._classify_catalysts_news(tickers, "india")
            for r in yf_raw:
                if r["ticker"] in catalyst_tickers:
                    r["has_catalyst"] = True
            gainers = self._build_gainers(yf_raw, "india")
            log.info("market_data.india_period_yf_path", period=period, count=len(gainers))
            return gainers[: self._top_n]

        log.warning(
            "market_data.india_yf_period_insufficient_fallback",
            period=period,
            count=len(yf_raw),
        )
        return await self._get_india_gainers_gemini(period)

    # ── Legacy paths: Gemini + Google Search (slow, ~30-60s) ─────────────────
    # Used only as fallback when yf.download is unavailable or returns too few results.

    async def _get_us_gainers_gemini(self, period: str) -> list[StockGainer]:
        """Gemini + Google Search for US (slow fallback, also used for 1w/1m)."""
        nyse_raw, nasdaq_raw, catalyst_raw = await asyncio.gather(
            self._fetch_gainers_gemini(_us_nyse_prompt(period), "us-nyse"),
            self._fetch_gainers_gemini(_us_nasdaq_prompt(period), "us-nasdaq"),
            self._fetch_gainers_gemini(_us_catalyst_prompt(period), "us-catalyst"),
        )
        gainers = self._build_gainers(nyse_raw + nasdaq_raw, "us")
        seen: set[str] = set()
        deduped: list[StockGainer] = []
        for g in gainers:
            if g.ticker not in seen:
                seen.add(g.ticker)
                deduped.append(g)
        gainers = deduped
        catalyst_plays = self._build_gainers(catalyst_raw, "us")
        merged = self._merge_gainers_and_catalysts(gainers, catalyst_plays)
        log.info(
            "market_data.us_gainers_gemini_fetched",
            period=period,
            count=len(merged),
            confirmed=sum(1 for g in merged if g.signal_tier == "confirmed"),
            catalyst=sum(1 for g in merged if g.signal_tier == "catalyst"),
            mover=sum(1 for g in merged if g.signal_tier == "mover"),
        )
        return merged[: self._top_n]

    async def _get_india_gainers_gemini(self, period: str) -> list[StockGainer]:
        """Gemini + Google Search for India (slow fallback)."""
        india_raw, catalyst_raw = await asyncio.gather(
            self._fetch_gainers_gemini(_india_gainers_prompt(period), "india"),
            self._fetch_gainers_gemini(_india_catalyst_prompt(period), "india-catalyst"),
        )
        gainers = self._build_gainers(india_raw, "india")
        catalyst_plays = self._build_gainers(catalyst_raw, "india")
        merged = self._merge_gainers_and_catalysts(gainers, catalyst_plays)
        log.info(
            "market_data.india_gainers_gemini_fetched",
            period=period,
            count=len(merged),
            confirmed=sum(1 for g in merged if g.signal_tier == "confirmed"),
            catalyst=sum(1 for g in merged if g.signal_tier == "catalyst"),
            mover=sum(1 for g in merged if g.signal_tier == "mover"),
        )
        return merged[: self._top_n]

    # ── Gemini + Google Search (pipe-delimited table) ─────────────────────────

    async def _fetch_gainers_gemini(
        self, prompt: str, market: str
    ) -> list[dict[str, Any]]:
        """
        Ask Gemini (with Google Search grounding) to return a pipe-delimited
        table of top gainers.

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

                score, label = compute_quality_score(price, volume, change_pct, ticker)

                # Tier assignment:
                #   confirmed = has news catalyst + Moderate-or-better quality (score ≥ 5.5)
                #   catalyst  = has news catalyst but smaller/lower-quality stock (score < 5.5)
                #   mover     = no identifiable news catalyst
                if has_catalyst:
                    tier: SignalTier = "confirmed" if score >= 5.5 else "catalyst"
                else:
                    tier = "mover"
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
            ttm_revenue=_safe_float(info.get("totalRevenue")),
            ebitda_margin=_safe_float(info.get("ebitdaMargins")),
            market_cap_value=_safe_float(info.get("marketCap")),
            insider_holding_pct=_safe_float(info.get("heldPercentInsiders")),
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
      2. yf.Search — fallback. yfinance handles Yahoo Finance auth internally
         so this avoids the 429/403 errors seen with raw httpx calls.
    """
    # ── 1. Gemini (primary — reliable, no external API dependency) ────────────
    result = await _resolve_ticker_via_gemini(query, market)
    if result:
        return result

    # ── 2. yf.Search fallback (handles Yahoo Finance auth internally) ─────────
    try:
        search_result = await asyncio.to_thread(yf.Search, query, max_results=8)
        for q in search_result.quotes:
            if q.get("quoteType") != "EQUITY":
                continue
            symbol: str = q.get("symbol", "")
            exchange: str = q.get("exchange", "")

            if market == "india":
                if symbol.endswith(".NS"):
                    return symbol[:-3]
                if symbol.endswith(".BO"):
                    return symbol[:-3]
                if exchange in ("NSI", "NSE", "BSE"):
                    return symbol
            else:
                if "." not in symbol and len(symbol) <= 5 and exchange in _US_EXCHANGES:
                    return symbol
                if "." not in symbol and len(symbol) <= 5 and not exchange:
                    return symbol
    except Exception as exc:
        log.warning("market_data.yf_search_resolve_failed", query=query, error=str(exc))

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

    exchange_hint = "NASDAQ or NYSE" if market == "us" else "NSE or BSE India"
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
        ttm_revenue=_safe_float(info.get("totalRevenue")),
        ebitda_margin=_safe_float(info.get("ebitdaMargins")),
        market_cap_value=_safe_float(info.get("marketCap")),
        insider_holding_pct=_safe_float(info.get("heldPercentInsiders")),
    )


def _safe_float(v: object) -> Optional[float]:
    """Convert to float, returning None for None, non-numeric, inf, and nan.
    yfinance returns inf/nan for unavailable metrics (e.g. forwardPE on loss-making
    stocks), which Python accepts but json.dumps rejects with ValueError."""
    try:
        result = float(v) if v is not None else None  # type: ignore[arg-type]
        if result is None or not math.isfinite(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _safe_int(v: object) -> Optional[int]:
    try:
        return int(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def today_str() -> str:
    return date.today().isoformat()
