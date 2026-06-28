"""
SectorService — fetches and ranks top stocks per market sector.

Data strategy:
  - Sector definitions and sort_score are static metadata (curated, macro-informed)
  - Stock price / return data is fetched from yfinance, cached 24 h
  - Within each sector, stocks are ranked by 1yr return (descending)
  - Top 5 stocks per sector are returned
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from core.logging import get_logger
from models.schemas import SectorInfo, SectorScanResponse, SectorStock
from services.fundamental_scoring import get_fundamental_score

log = get_logger(__name__)

_SECTOR_TTL = 24 * 3600  # 24 h

# ── Sector definitions ─────────────────────────────────────────────────────────
# sort_score = secular_growth × 3 + defensiveness × 2 − cyclicality × 2 + macro_tailwind_bonus
# Sorted highest first = best sectors to look at for long-term SIP

_INDIA_SECTORS: list[dict[str, Any]] = [
    {
        "name": "Information Technology & SaaS",
        "sort_score": 92,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "AI services exports, digital transformation; ~35% of Nifty IT revenue from US clients",
        "tickers": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", "LTIM.NS"],
    },
    {
        "name": "Pharmaceuticals & Healthcare",
        "sort_score": 89,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "Generic drug exports to US/EU, rising domestic health expenditure, CDSCO approvals",
        "tickers": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS", "MANKIND.NS"],
    },
    {
        "name": "Defense & Aerospace",
        "sort_score": 87,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "Make in India PLI; ₹6.2L Cr defence capex plan to 2029; rising defence export order book",
        "tickers": ["HAL.NS", "BEL.NS", "BHEL.NS", "GRSE.NS", "COCHINSHIP.NS", "MAZDOCK.NS"],
    },
    {
        "name": "Renewable Energy & Solar",
        "sort_score": 85,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "500 GW renewable target by 2030; INR 2.4L Cr green energy budget; solar PLI subsidies",
        "tickers": ["ADANIGREEN.NS", "TATAPOWER.NS", "NHPC.NS", "SJVN.NS", "INOXWIND.NS", "SUZLON.NS"],
    },
    {
        "name": "Water Treatment & Utilities",
        "sort_score": 84,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "Jal Jeevan Mission ₹2.87L Cr; piped water to 192M households; AMRUT 2.0 infra push",
        "tickers": ["WABAG.NS", "IONEXCHANG.NS", "THERMAX.NS", "KIRLOSENG.NS", "VOLTAS.NS"],
    },
    {
        "name": "FMCG & Consumer Staples",
        "sort_score": 83,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "Rural demand recovery, premiumisation wave, volume growth across categories",
        "tickers": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS", "MARICO.NS"],
    },
    {
        "name": "Banking & Private NBFCs",
        "sort_score": 76,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "Credit growth 14-16%, low NPA cycle; RBI rate cuts to boost NIMs in 2025",
        "tickers": ["HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS", "BAJFINANCE.NS"],
    },
    {
        "name": "Capital Goods & Industrial Machinery",
        "sort_score": 74,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "Record ₹11.1L Cr govt capex; private capex cycle revival; infrastructure supercycle",
        "tickers": ["LT.NS", "SIEMENS.NS", "ABB.NS", "CUMMINSIND.NS", "THERMAX.NS", "BHEL.NS"],
    },
    {
        "name": "Specialty Chemicals",
        "sort_score": 72,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "China+1 sourcing shift; agrochemical intermediates; fluorochemical exports",
        "tickers": ["PIDILITIND.NS", "SRF.NS", "VINATIORGA.NS", "ATUL.NS", "DEEPAKFERT.NS", "GALAXYSURF.NS"],
    },
    {
        "name": "Logistics & Supply Chain",
        "sort_score": 70,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "GST normalisation, PM Gati Shakti multimodal network; e-comm logistics boom",
        "tickers": ["DELHIVERY.NS", "BLUEDART.NS", "MAHLOG.NS", "ALLCARGO.NS", "CONCOR.NS"],
    },
    {
        "name": "Insurance & Wealth Management",
        "sort_score": 69,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "Low insurance penetration (4% vs 11% global avg); SIP AUM at ₹60L Cr and rising",
        "tickers": ["HDFCLIFE.NS", "SBILIFE.NS", "ICICIGI.NS", "BAJAJFINSV.NS", "LICI.NS"],
    },
    {
        "name": "EV & Auto Ancillaries",
        "sort_score": 68,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "EV penetration at 7%; FAME III subsidies; auto ancillary exports rising",
        "tickers": ["TATAMOTORS.NS", "BAJAJ-AUTO.NS", "TVSMOTOR.NS", "MOTHERSON.NS", "EXIDEIND.NS", "AMARAJABAT.NS"],
    },
    {
        "name": "Telecom & Digital Infrastructure",
        "sort_score": 65,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "5G rollout, ARPU expansion, data consumption 2x by 2028; tower REITs emerging",
        "tickers": ["BHARTIARTL.NS", "INDUSINDBK.NS", "RAILTEL.NS", "HCLTECH.NS", "TATACOMM.NS"],
    },
    {
        "name": "Agri-Tech & Food Processing",
        "sort_score": 62,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "PM AASHA, PLI for food processing; precision agriculture adoption; exports push",
        "tickers": ["UPL.NS", "PIIND.NS", "RALLIS.NS", "KAVERI.NS", "DHANUKA.NS", "BECTORFOOD.NS"],
    },
    {
        "name": "Retail & E-Commerce",
        "sort_score": 60,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "Organised retail share rising (12% → 20% by 2030); quick commerce disruption",
        "tickers": ["TRENT.NS", "DMART.NS", "VMART.NS", "NYKAA.NS", "SHOPPERST.NS"],
    },
    {
        "name": "Power & Utilities (PSU)",
        "sort_score": 58,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "Peak demand 250GW by 2030; smart metering rollout; AT&C loss reduction",
        "tickers": ["POWERGRID.NS", "NTPC.NS", "CESC.NS", "TORNTPOWER.NS", "TATAPOWER.NS"],
    },
    {
        "name": "Infrastructure & Construction",
        "sort_score": 52,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "National Infrastructure Pipeline ₹111L Cr; highway awards record 12,000 km/yr",
        "tickers": ["LT.NS", "NCC.NS", "IRB.NS", "KNRCON.NS", "ASHOKA.NS", "PSP.NS"],
    },
    {
        "name": "Real Estate & REITs",
        "sort_score": 50,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Rate-cut cycle tailwind; affordable housing push; REIT yields 6-7%",
        "tickers": ["DLF.NS", "GODREJPROP.NS", "OBEROIREAL.NS", "PRESTIGE.NS", "BRIGADE.NS"],
    },
    {
        "name": "Oil & Gas & Petrochemicals",
        "sort_score": 47,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Domestic demand growth; Reliance new energy pivot; ONGC deepsea exploration",
        "tickers": ["RELIANCE.NS", "ONGC.NS", "GAIL.NS", "IOC.NS", "BPCL.NS"],
    },
    {
        "name": "Cement & Building Materials",
        "sort_score": 44,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Housing + infra demand but overcapacity; price discipline fragile",
        "tickers": ["ULTRACEMCO.NS", "SHREECEM.NS", "AMBUJACEMENT.NS", "ACC.NS", "DALMIACEMENTB.NS"],
    },
    {
        "name": "Education & EdTech",
        "sort_score": 44,
        "cyclicality": "mid",
        "growth_tag": "Emerging",
        "macro_theme": "NEP 2020 reform; K-12 hybrid model; NEP vocational training push",
        "tickers": ["CAREEREDGE.NS", "MTARTECH.NS", "NAVNETEDUL.NS", "PRAXIS.NS"],
    },
    {
        "name": "Metals & Mining",
        "sort_score": 40,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "China demand overhang; domestic infra consumption; steel cycle volatile",
        "tickers": ["TATASTEEL.NS", "HINDALCO.NS", "JSWSTEEL.NS", "SAIL.NS", "NMDC.NS", "VEDL.NS"],
    },
    {
        "name": "Textiles & Apparel",
        "sort_score": 35,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "China+1 limited so far; PLI textile yet to materialise; currency risk for exports",
        "tickers": ["PAGEIND.NS", "RAYMOND.NS", "KITEX.NS", "NITIN.NS"],
    },
    {
        "name": "Hospitality & Travel",
        "sort_score": 32,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Post-COVID recovery largely complete; RevPAR growth moderating",
        "tickers": ["INDHOTEL.NS", "EIHOTEL.NS", "LEMONTREE.NS", "MAHINDRAHOLIDAYS.NS"],
    },
    {
        "name": "Media & Entertainment",
        "sort_score": 28,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "OTT disruption of linear TV; ad market cyclical; consolidation in progress",
        "tickers": ["ZEEL.NS", "SUNTV.NS", "PVRINOX.NS", "TIPS.NS"],
    },
]

_US_SECTORS: list[dict[str, Any]] = [
    {
        "name": "AI & Semiconductors",
        "sort_score": 95,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "Generative AI capex supercycle; HBM memory, CoWoS packaging demand surge",
        "tickers": ["NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU"],
    },
    {
        "name": "Cloud Computing & SaaS",
        "sort_score": 92,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "AI workload migration to cloud; consumption-based models inflecting; multi-cloud standard",
        "tickers": ["MSFT", "AMZN", "GOOGL", "CRM", "NOW", "SNOW"],
    },
    {
        "name": "Cybersecurity",
        "sort_score": 88,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "Ransomware frequency 2× YoY; AI-powered attacks driving platform consolidation",
        "tickers": ["CRWD", "PANW", "FTNT", "ZS", "S", "OKTA"],
    },
    {
        "name": "Healthcare & Biotech",
        "sort_score": 86,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "GLP-1 obesity drugs expanding TAM; ageing demographics; patent cliff creating generics opportunity",
        "tickers": ["LLY", "JNJ", "UNH", "ABBV", "MRK", "AMGN"],
    },
    {
        "name": "Defense & Aerospace",
        "sort_score": 85,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "NATO 2% GDP spending re-commitment; Ukraine-driven procurement surge; F-35 multi-decade program",
        "tickers": ["RTX", "LMT", "NOC", "GD", "LHX", "HII"],
    },
    {
        "name": "Water & Environmental Services",
        "sort_score": 83,
        "cyclicality": "low",
        "growth_tag": "High Growth",
        "macro_theme": "PFAS remediation mandates; water scarcity infrastructure; EPA tightening discharge rules",
        "tickers": ["AWK", "XYL", "TTEK", "ECL", "WTRG", "PNR"],
    },
    {
        "name": "Consumer Staples",
        "sort_score": 80,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "Pricing power normalising; volume growth returning; emerging market penetration",
        "tickers": ["PG", "KO", "PEP", "WMT", "COST", "CL"],
    },
    {
        "name": "Financial Services & Fintech",
        "sort_score": 74,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "Rate cuts boosting loan demand; embedded finance; deregulation tailwind",
        "tickers": ["JPM", "V", "MA", "GS", "MS", "BAC"],
    },
    {
        "name": "EV & Clean Energy",
        "sort_score": 73,
        "cyclicality": "mid",
        "growth_tag": "High Growth",
        "macro_theme": "IRA credits extending through 2032; grid battery storage 10× by 2030",
        "tickers": ["TSLA", "ENPH", "FSLR", "NEE", "CEG", "PLUG"],
    },
    {
        "name": "Industrials & Automation",
        "sort_score": 71,
        "cyclicality": "mid",
        "growth_tag": "Cyclical-Mod",
        "macro_theme": "Reshoring of manufacturing; robotics adoption; nearshoring supply chain build-out",
        "tickers": ["GE", "HON", "CAT", "DE", "ROK", "CARR"],
    },
    {
        "name": "Telecom & Communication Services",
        "sort_score": 68,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "5G monetisation; fixed wireless access broadband; AI-native network upgrades",
        "tickers": ["T", "VZ", "TMUS", "CMCSA", "CHTR"],
    },
    {
        "name": "Gene Therapy & Precision Medicine",
        "sort_score": 67,
        "cyclicality": "low",
        "growth_tag": "Emerging",
        "macro_theme": "FDA accelerated pathway for rare diseases; CRISPR therapies reaching commercial approval",
        "tickers": ["MRNA", "BNTX", "VRTX", "REGN", "BEAM", "EDIT"],
    },
    {
        "name": "Space Technology",
        "sort_score": 64,
        "cyclicality": "low",
        "growth_tag": "Emerging",
        "macro_theme": "LEO constellation economics; satellite internet monetisation; government payload backlog",
        "tickers": ["RKLB", "ASTS", "SPIR", "BWXT", "KTOS"],
    },
    {
        "name": "Consumer Discretionary & Retail",
        "sort_score": 52,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Consumer spend resilient but rate-sensitive; luxury bifurcation; Amazon dominance",
        "tickers": ["AMZN", "HD", "TGT", "MCD", "SBUX", "LOW"],
    },
    {
        "name": "Traditional Energy (Oil & Gas)",
        "sort_score": 48,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "OPEC+ supply discipline; long-term demand plateau 2030; energy security premium",
        "tickers": ["XOM", "CVX", "COP", "SLB", "EOG", "HAL"],
    },
    {
        "name": "Real Estate REITs",
        "sort_score": 47,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Rate-sensitive; data centre REITs outperforming; office vacancy headwind",
        "tickers": ["AMT", "PLD", "EQIX", "O", "SPG", "WPC"],
    },
    {
        "name": "Utilities",
        "sort_score": 46,
        "cyclicality": "low",
        "growth_tag": "Defensive",
        "macro_theme": "Rate-cut beneficiary; AI data centre power demand secular tailwind",
        "tickers": ["NEE", "D", "DUK", "SO", "AEP", "XEL"],
    },
    {
        "name": "Materials & Mining",
        "sort_score": 40,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "China demand uncertain; copper structural deficit from electrification",
        "tickers": ["LIN", "APD", "SHW", "NEM", "FCX", "ALB"],
    },
    {
        "name": "Travel & Hospitality",
        "sort_score": 36,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Post-COVID peak behind us; leisure demand moderating; business travel recovering",
        "tickers": ["MAR", "HLT", "CCL", "DAL", "UAL", "BKNG"],
    },
    {
        "name": "Media & Entertainment",
        "sort_score": 32,
        "cyclicality": "high",
        "growth_tag": "Cyclical",
        "macro_theme": "Streaming profitability inflection; linear TV structural decline; ad revenue volatile",
        "tickers": ["DIS", "NFLX", "WBD", "PARA", "FOX"],
    },
]


async def _fetch_stock_data(ticker: str) -> dict | None:
    """Fetch 1yr return + basic metrics from yfinance. Returns None on failure."""
    try:
        import yfinance as yf

        def _sync_fetch() -> dict | None:
            t = yf.Ticker(ticker)
            info = t.info or {}
            hist = t.history(period="1y")
            if hist.empty or len(hist) < 5:
                return None

            start_price = float(hist["Close"].iloc[0])
            end_price   = float(hist["Close"].iloc[-1])
            change_1yr  = round((end_price - start_price) / start_price * 100, 1) if start_price > 0 else None

            # 6m return (approx: last 126 trading days)
            mid_idx = max(0, len(hist) - 126)
            mid_price = float(hist["Close"].iloc[mid_idx])
            change_6m = round((end_price - mid_price) / mid_price * 100, 1) if mid_price > 0 else None

            price     = info.get("currentPrice") or info.get("regularMarketPrice") or end_price
            pe        = info.get("trailingPE")
            mktcap    = info.get("marketCap")
            hi52      = info.get("fiftyTwoWeekHigh")
            lo52      = info.get("fiftyTwoWeekLow")
            name      = info.get("shortName") or info.get("longName") or ticker

            # Convert market cap to crores for India (.NS suffix) or USD millions for US
            if ticker.endswith(".NS") or ticker.endswith(".BO"):
                mktcap_display = round(mktcap / 1e7, 0) if mktcap else None  # rupees → crores
            else:
                mktcap_display = round(mktcap / 1e6, 0) if mktcap else None  # USD → millions

            pct_from_high = None
            if price and hi52 and hi52 > 0:
                pct_from_high = round((float(price) - float(hi52)) / float(hi52) * 100, 1)

            return {
                "ticker": ticker,
                "name": name,
                "price": round(float(price), 2) if price else None,
                "change_1yr_pct": change_1yr,
                "change_6m_pct": change_6m,
                "pe_ratio": round(float(pe), 1) if pe and pe > 0 else None,
                "market_cap_cr": mktcap_display,
                "fifty_two_week_high": round(float(hi52), 2) if hi52 else None,
                "fifty_two_week_low": round(float(lo52), 2) if lo52 else None,
                "pct_from_52w_high": pct_from_high,
            }

        return await asyncio.wait_for(asyncio.to_thread(_sync_fetch), timeout=12.0)
    except Exception as exc:
        log.warning("sector_service.fetch_failed", ticker=ticker, error=str(exc))
        return None


def _dip_bonus(pct_from_high: float | None) -> float:
    """0–10 bonus score for how attractive the current price dip is."""
    if pct_from_high is None:
        return 0.0
    if pct_from_high <= -30:
        return 10.0
    if pct_from_high <= -20:
        return 8.0
    if pct_from_high <= -15:
        return 6.5
    if pct_from_high <= -10:
        return 5.0
    if pct_from_high <= -5:
        return 2.5
    return 0.0


async def _build_sector(
    sector_def: dict,
    rank: int,
    cache: Any,
    max_stocks: int = 5,
) -> SectorInfo:
    """Fetch price data + fundamental scores for all tickers; rank by both fundamental quality and dip opportunity."""
    tickers = sector_def["tickers"]
    market  = "india" if any(t.endswith(".NS") or t.endswith(".BO") for t in tickers) else "us"
    sem = asyncio.Semaphore(4)

    async def _fetch_all(ticker: str) -> dict | None:
        async with sem:
            price_data = await _fetch_stock_data(ticker)
            if price_data is None:
                return None
            # Enrich with fundamental score (uses cache — fast if already scored)
            try:
                fscore_data = await asyncio.wait_for(
                    get_fundamental_score(ticker, market, "moderate", cache),
                    timeout=15.0,
                )
            except Exception:
                fscore_data = None
            result = dict(price_data)
            if fscore_data:
                result["fundamental_score"] = fscore_data.get("fundamental_score")
                result["grade"] = fscore_data.get("grade")
            return result

    raw = await asyncio.gather(*[_fetch_all(t) for t in tickers], return_exceptions=True)
    stocks: list[dict] = [r for r in raw if isinstance(r, dict) and r is not None]

    if not stocks:
        return SectorInfo(
            name=sector_def["name"], rank=rank,
            sort_score=sector_def["sort_score"], cyclicality=sector_def["cyclicality"],
            growth_tag=sector_def["growth_tag"], macro_theme=sector_def["macro_theme"],
            top_stocks=[],
        )

    # ── Fundamental rank: by fundamental_score desc, fallback 1yr return ──────
    def _fscore(s: dict) -> float:
        return s.get("fundamental_score") or (s.get("change_1yr_pct") or -999) / 100

    stocks_by_fundamental = sorted(stocks, key=_fscore, reverse=True)
    fundamental_rank_map = {s["ticker"]: i + 1 for i, s in enumerate(stocks_by_fundamental)}

    # ── Opportunity rank: fundamental quality × 0.6 + dip attractiveness × 0.4 ─
    def _opportunity_score(s: dict) -> float:
        fscore = s.get("fundamental_score") or 5.0  # neutral default
        dip    = _dip_bonus(s.get("pct_from_52w_high"))
        return fscore * 0.6 + dip * 0.4

    stocks_by_opportunity = sorted(stocks, key=_opportunity_score, reverse=True)
    opportunity_rank_map  = {s["ticker"]: i + 1 for i, s in enumerate(stocks_by_opportunity)}

    # Final display order = opportunity rank
    top_stocks = []
    for s in stocks_by_opportunity[:max_stocks]:
        f_rank = fundamental_rank_map[s["ticker"]]
        o_rank = opportunity_rank_map[s["ticker"]]
        top_stocks.append(SectorStock(
            ticker=s["ticker"],
            name=s["name"],
            price=s["price"],
            change_1yr_pct=s["change_1yr_pct"],
            change_6m_pct=s["change_6m_pct"],
            pe_ratio=s["pe_ratio"],
            market_cap_cr=s["market_cap_cr"],
            fifty_two_week_high=s["fifty_two_week_high"],
            fifty_two_week_low=s["fifty_two_week_low"],
            pct_from_52w_high=s.get("pct_from_52w_high"),
            fundamental_score=s.get("fundamental_score"),
            grade=s.get("grade"),
            fundamental_rank=f_rank,
            opportunity_rank=o_rank,
            is_dip_opportunity=(o_rank < f_rank and (s.get("pct_from_52w_high") or 0) < -8),
        ))

    return SectorInfo(
        name=sector_def["name"],
        rank=rank,
        sort_score=sector_def["sort_score"],
        cyclicality=sector_def["cyclicality"],
        growth_tag=sector_def["growth_tag"],
        macro_theme=sector_def["macro_theme"],
        top_stocks=top_stocks,
    )


async def get_sector_scan(market: str, cache: Any, refresh: bool = False) -> SectorScanResponse:
    """Return full sector scan for market. Cached 24 h."""
    cache_key = f"sectors:{market}"

    if not refresh:
        cached = await cache.get(cache_key)
        if cached:
            log.info("sector_service.cache_hit", market=market)
            response = SectorScanResponse.model_validate(cached)
            response.from_cache = True
            return response

    sector_defs = _INDIA_SECTORS if market == "india" else _US_SECTORS

    log.info("sector_service.fetch_start", market=market, sectors=len(sector_defs))

    # Fetch sectors concurrently (each sector fetches its tickers internally)
    # Limit concurrent sectors to avoid yfinance rate limits
    sector_sem = asyncio.Semaphore(3)

    async def _guarded_sector(defn: dict, rank: int) -> SectorInfo:
        async with sector_sem:
            return await _build_sector(defn, rank, cache)

    results = await asyncio.gather(
        *[_guarded_sector(s, i + 1) for i, s in enumerate(sector_defs)],
        return_exceptions=True,
    )

    sectors: list[SectorInfo] = []
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            log.warning("sector_service.sector_failed", sector=sector_defs[i]["name"], error=str(res))
            # Include sector with empty stocks so the list is still complete
            sectors.append(SectorInfo(
                name=sector_defs[i]["name"],
                rank=i + 1,
                sort_score=sector_defs[i]["sort_score"],
                cyclicality=sector_defs[i]["cyclicality"],
                growth_tag=sector_defs[i]["growth_tag"],
                macro_theme=sector_defs[i]["macro_theme"],
                top_stocks=[],
            ))
        else:
            sectors.append(res)

    response = SectorScanResponse(
        market=market,  # type: ignore[arg-type]
        sectors=sectors,
        from_cache=False,
        generated_at=datetime.utcnow(),
    )

    await cache.set(cache_key, response.model_dump(mode="json"), _SECTOR_TTL)
    log.info("sector_service.fetch_done", market=market, sectors=len(sectors))
    return response
