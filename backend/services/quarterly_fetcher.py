"""
QuarterlyFetcher — pulls quarterly financial results for any stock.

India : scrapes screener.in (the same site the user was manually reading).
        12–13 quarters of Sales, OPM%, Net Profit, EPS with YoY growth.
US    : uses yfinance quarterly_income_stmt (works well for large/mid caps).

Cache TTL : 24 h — results only change once a quarter; daily refresh
            catches any late filings we'd otherwise miss.

The formatted text block is injected directly into the GainerAnalystAgent
prompt — no new Gemini call required, zero extra latency (runs in parallel
with fundamentals + news + candles).
"""
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from typing import Optional

import httpx

from core.config import Settings
from core.logging import get_logger
from models.schemas import Market, QuarterlyResult, QuarterlySnapshot

log = get_logger(__name__)

_SCREENER_BASE = "https://www.screener.in/company"
_TIMEOUT = 10.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── HTML parser ───────────────────────────────────────────────────────────────

class _QuartersTableParser(HTMLParser):
    """
    Minimal SAX-style parser for screener.in quarterly results table.
    Looks for <section id="quarters"> and extracts the data-table inside it.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_section = False
        self._depth = 0          # track nesting inside the section
        self._in_thead = False
        self._in_tbody = False
        self._in_cell = False    # th or td
        self._cell_text = ""

        self.headers: list[str] = []                         # quarter labels
        self.rows: list[tuple[str, list[Optional[str]]]] = []  # (metric, [values])
        self._cur_row: list[str] = []

    # ── Tag open ─────────────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "section" and attr.get("id") == "quarters":
            self._in_section = True
            self._depth = 0
            return
        if not self._in_section:
            return
        if tag == "section":
            self._depth += 1          # nested section — keep counting
        elif tag == "thead":
            self._in_thead = True
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "tr":
            self._cur_row = []
        elif tag in ("th", "td"):
            self._in_cell = True
            self._cell_text = ""

    # ── Tag close ────────────────────────────────────────────────────────────

    def handle_endtag(self, tag: str) -> None:
        if not self._in_section:
            return
        if tag == "section":
            if self._depth == 0:
                self._in_section = False
            else:
                self._depth -= 1
        elif tag == "thead":
            self._in_thead = False
        elif tag == "tbody":
            self._in_tbody = False
        elif tag in ("th", "td"):
            text = self._cell_text.strip()
            self._in_cell = False
            if self._in_thead and tag == "th":
                self.headers.append(text)
            elif self._in_tbody and tag == "td":
                self._cur_row.append(text)
        elif tag == "tr" and self._in_tbody:
            if len(self._cur_row) >= 2:
                metric = self._cur_row[0]
                values: list[Optional[str]] = self._cur_row[1:]
                self.rows.append((metric, values))
            self._cur_row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text += data


# ── Number helpers ────────────────────────────────────────────────────────────

def _num(s: Optional[str]) -> Optional[float]:
    """Parse screener.in number strings: '1,201.23', '-45.6', '--' → float | None."""
    if not s:
        return None
    s = s.replace(",", "").replace("%", "").strip()
    if not s or s in ("-", "--", "—", "N/A", "n/a"):
        return None
    # Parentheses = negative in some formats
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


# ── Core parser ───────────────────────────────────────────────────────────────

def _parse_screener_html(html: str) -> tuple[list[str], dict[str, list[Optional[str]]]]:
    """
    Returns (quarter_names_oldest_first, {metric: [value, ...]}).
    Values align with quarter_names (index 0 = oldest quarter).
    """
    p = _QuartersTableParser()
    p.feed(html)

    # First header is usually empty ("") — drop it, rest are "Sep 2024" etc.
    quarter_labels = [h for h in p.headers[1:] if h.strip()]

    data: dict[str, list[Optional[str]]] = {}
    for metric, vals in p.rows:
        if not metric:
            continue
        # Align length to number of quarters
        padded: list[Optional[str]] = (list(vals) + [None] * len(quarter_labels))[: len(quarter_labels)]
        data[metric] = padded

    return quarter_labels, data


def _build_results_newest_first(
    quarters: list[str], data: dict[str, list[Optional[str]]]
) -> list[QuarterlyResult]:
    """
    Build QuarterlyResult list from screener.in data (oldest-first input)
    and return it newest-first.  YoY growth is computed by comparing
    newest_first[i] with newest_first[i+4] (same quarter a year ago).
    """
    # Identify metric keys — screener uses slightly varied labels
    def _find(candidates: list[str]) -> Optional[str]:
        for k in data:
            for c in candidates:
                if c.lower() in k.lower():
                    return k
        return None

    sales_key = _find(["Sales", "Revenue"])
    op_key = _find(["Operating Profit"])
    opm_key = _find(["OPM"])
    pat_key = _find(["Net Profit"])
    eps_key = _find(["EPS"])

    # Build oldest-first list
    results: list[QuarterlyResult] = []
    for i, q in enumerate(quarters):
        def _get(key: Optional[str]) -> Optional[float]:
            if key is None or i >= len(data[key]):
                return None
            return _num(data[key][i])

        results.append(QuarterlyResult(
            period=q,
            revenue=_get(sales_key),
            operating_profit=_get(op_key),
            opm_pct=_get(opm_key),
            net_profit=_get(pat_key),
            eps=_get(eps_key),
        ))

    # Reverse → newest first
    results = list(reversed(results))

    # Compute YoY growth: compare results[i] with results[i+4]
    for i, r in enumerate(results):
        prev_idx = i + 4
        if prev_idx >= len(results):
            continue
        prev = results[prev_idx]
        if r.revenue is not None and prev.revenue and prev.revenue != 0:
            r.revenue_growth_yoy = (r.revenue - prev.revenue) / abs(prev.revenue) * 100
        if r.net_profit is not None and prev.net_profit and prev.net_profit != 0:
            r.pat_growth_yoy = (r.net_profit - prev.net_profit) / abs(prev.net_profit) * 100

    return results


# ── Trend computation ─────────────────────────────────────────────────────────

def _revenue_trend(results: list[QuarterlyResult]) -> str:
    vals = [r.revenue_growth_yoy for r in results[:4] if r.revenue_growth_yoy is not None]
    if len(vals) < 2:
        return "unknown"
    latest = vals[0]
    prior_avg = sum(vals[1:]) / len(vals[1:])
    if latest > 0 and prior_avg <= 0:
        return "recovering"
    if latest > prior_avg + 4:
        return "accelerating"
    if latest < prior_avg - 4:
        return "decelerating" if latest >= 0 else "declining"
    return "stable"


def _margin_trend(results: list[QuarterlyResult]) -> str:
    vals = [r.opm_pct for r in results[:4] if r.opm_pct is not None]
    if len(vals) < 2:
        return "unknown"
    if vals[0] > vals[-1] + 1.5:
        return "expanding"
    if vals[0] < vals[-1] - 1.5:
        return "compressing"
    return "stable"


def _earnings_trend(results: list[QuarterlyResult]) -> str:
    vals = [r.pat_growth_yoy for r in results[:4] if r.pat_growth_yoy is not None]
    if len(vals) < 2:
        return "unknown"
    latest = vals[0]
    prior_avg = sum(vals[1:]) / len(vals[1:])
    if latest > 0 and prior_avg <= 0:
        return "recovering"
    if latest > prior_avg + 5:
        return "accelerating"
    if latest < prior_avg - 5:
        return "decelerating" if latest >= 0 else "declining"
    return "stable"


# ── Quarterly insight (plain-English verdict shown in the UI) ─────────────────

def _compute_quarterly_insight(
    revenue_trend: str,
    margin_trend: str,
    earnings_trend: str,
    quarters: list[QuarterlyResult],
) -> str:
    """
    Warren Buffett-style 1–2 sentence plain-English verdict.
    Generated from trend labels + latest YoY numbers — no AI call required.
    """
    latest = quarters[0] if quarters else None

    def _pat_str() -> str:
        if latest and latest.pat_growth_yoy is not None:
            sign = "+" if latest.pat_growth_yoy >= 0 else ""
            return f" ({sign}{latest.pat_growth_yoy:.0f}% YoY)"
        return ""

    def _rev_str() -> str:
        if latest and latest.revenue_growth_yoy is not None:
            sign = "+" if latest.revenue_growth_yoy >= 0 else ""
            return f" ({sign}{latest.revenue_growth_yoy:.0f}% YoY)"
        return ""

    # ── Best cases ────────────────────────────────────────────────────────────
    if earnings_trend == "accelerating" and margin_trend == "expanding":
        return (
            f"Earnings accelerating{_pat_str()} with expanding margins — "
            "each rupee of revenue is turning into more profit than before. "
            "This is the compounding flywheel Buffett looks for: pricing power plus operating leverage."
        )
    if earnings_trend == "accelerating":
        return (
            f"Earnings momentum is building{_pat_str()}. "
            f"Margins are {margin_trend} — growth is flowing through to the bottom line. "
            "Strong execution; watch whether margins hold as growth continues."
        )
    if earnings_trend == "recovering" and margin_trend in ("expanding", "stable"):
        return (
            f"Earnings recovering{_pat_str()} with "
            f"{'improving' if margin_trend == 'expanding' else 'stable'} margins. "
            "The turnaround is showing in the numbers, not just the narrative — "
            "a meaningful distinction when separating hope from reality."
        )
    if earnings_trend == "stable" and margin_trend == "expanding":
        return (
            "Consistent earnings with improving margins — the business is getting more efficient. "
            "Buffett's definition of quality: predictable profits, improving returns on capital, "
            "no drama."
        )
    if earnings_trend == "stable" and margin_trend == "stable":
        return (
            "Steady, predictable earnings with stable margins. "
            "Boring — and that's exactly what long-term investors should want. "
            "Reliable cash flow with no unpleasant surprises is worth more than volatile growth."
        )

    # ── Warning cases ─────────────────────────────────────────────────────────
    if earnings_trend == "declining" and margin_trend == "compressing":
        return (
            f"Double squeeze: profits falling{_pat_str()} AND margins compressing. "
            "Costs are rising faster than revenue can cover. "
            "Buffett's red flag — a business earning less each quarter while becoming less efficient "
            "is actively eroding its competitive advantage."
        )
    if earnings_trend == "declining" and margin_trend == "expanding":
        return (
            f"Earnings declining{_pat_str()} despite improving margins — "
            "profitability is fine but the top line is the problem. "
            "Revenue needs to recover before profits follow; "
            "watch whether demand is cyclically weak or structurally impaired."
        )
    if earnings_trend == "declining":
        return (
            f"Earnings in decline{_pat_str()} with {margin_trend} margins. "
            "The business is earning less than a year ago. "
            "Key question: is this cyclical (expect recovery) or structural (pricing power eroded)? "
            "The answer determines whether today's price is an opportunity or a value trap."
        )
    if earnings_trend == "decelerating" and margin_trend == "compressing":
        return (
            "Growth is slowing while margins thin — the business is losing operating leverage. "
            "Rising costs are absorbing revenue growth before it reaches the bottom line. "
            "Not in crisis, but the direction requires monitoring."
        )
    if earnings_trend == "decelerating":
        return (
            f"Earnings growth is decelerating{_pat_str()}. "
            f"Revenue is {revenue_trend}, margins are {margin_trend}. "
            "Still profitable and growing, but the pace is slowing — "
            "a temporary plateau or the early signal of a longer slowdown."
        )
    if revenue_trend == "declining":
        return (
            f"Top-line revenue shrinking{_rev_str()} with {earnings_trend} earnings. "
            "When revenue falls, everything downstream follows eventually. "
            "Watch for signs that volume or pricing is recovering."
        )

    # ── Limited history (US stocks often have only 4-5 quarters → 1 YoY point) ─
    # 1 YoY point is too few for trend detection (returns "unknown") but still
    # meaningful: state what the latest quarter actually shows.
    if earnings_trend == "unknown" or revenue_trend == "unknown":
        if latest:
            pieces: list[str] = []
            if latest.pat_growth_yoy is not None:
                direction = "growing" if latest.pat_growth_yoy >= 0 else "declining"
                pieces.append(f"earnings {direction}{_pat_str()}")
            if latest.revenue_growth_yoy is not None:
                direction = "growing" if latest.revenue_growth_yoy >= 0 else "declining"
                pieces.append(f"revenue {direction}{_rev_str()}")
            if pieces:
                margin_note = (
                    f" with {margin_trend} margins" if margin_trend != "unknown" else ""
                )
                all_positive = all(
                    (v >= 0)
                    for v in [latest.revenue_growth_yoy, latest.pat_growth_yoy]
                    if v is not None
                )
                tone = (
                    "Business expanding year-over-year across the board."
                    if all_positive
                    else "Mixed year-over-year performance."
                )
                return (
                    f"Latest quarter: {' and '.join(pieces)}{margin_note}. "
                    f"{tone} "
                    "Insufficient quarterly history to assess multi-period trend — "
                    "results factored into the AI's 30-day prediction."
                )
        return (
            "Quarterly data available but insufficient history to assess trend direction. "
            "Results have been factored into the AI's 30-day prediction."
        )

    # ── Default ───────────────────────────────────────────────────────────────
    return (
        f"Revenue: {revenue_trend} · Margins: {margin_trend} · Earnings: {earnings_trend}. "
        "Quarterly results have been factored into the AI's 30-day prediction."
    )


# ── Prompt formatter ──────────────────────────────────────────────────────────

def format_for_prompt(snap: QuarterlySnapshot) -> str:
    """
    Format quarterly snapshot as a compact text block for the Gemini prompt.
    Designed to be injected right before the final analysis instruction.
    """
    n = len(snap.quarters)
    lines = [
        f"QUARTERLY RESULTS ({snap.currency}{snap.unit}, last {n} quarters, most recent first):"
    ]

    for r in snap.quarters:
        parts = [f"  {r.period}:"]
        if r.revenue is not None:
            s = f"Rev {snap.currency}{r.revenue:,.0f}{snap.unit}"
            if r.revenue_growth_yoy is not None:
                sign = "+" if r.revenue_growth_yoy >= 0 else ""
                s += f" ({sign}{r.revenue_growth_yoy:.0f}% YoY)"
            parts.append(s)
        if r.opm_pct is not None:
            parts.append(f"OPM {r.opm_pct:.0f}%")
        if r.net_profit is not None:
            s = f"PAT {snap.currency}{r.net_profit:,.0f}{snap.unit}"
            if r.pat_growth_yoy is not None:
                sign = "+" if r.pat_growth_yoy >= 0 else ""
                s += f" ({sign}{r.pat_growth_yoy:.0f}% YoY)"
            parts.append(s)
        if r.eps is not None:
            parts.append(f"EPS {r.eps:.1f}")
        lines.append(" | ".join(parts))

    # Trend summary — this is what the AI weighs most heavily
    lines += [
        "",
        "EARNINGS TRENDS (weight heavily in 30-day outlook):",
        f"  Revenue trajectory:  {snap.revenue_trend.upper()}",
        f"  Margin trajectory:   {snap.margin_trend.upper()}",
        f"  Earnings trajectory: {snap.earnings_trend.upper()}",
    ]

    # Contextual hints to help the AI interpret the trends correctly
    if snap.earnings_trend in ("accelerating", "recovering") and snap.margin_trend == "expanding":
        lines.append("  → Strong fundamental tailwind: earnings + margins both improving.")
    elif snap.earnings_trend in ("decelerating", "declining"):
        lines.append("  → Caution: earnings momentum weakening — assess if today's price move is sustainable.")
    if snap.margin_trend == "compressing":
        lines.append("  → Margin compression is a structural headwind; factor into downside risk.")

    return "\n".join(lines)


# ── Fetcher class ─────────────────────────────────────────────────────────────

class QuarterlyFetcher:
    """
    Fetch quarterly results for any ticker.
    Returns None gracefully on any failure — never blocks the analysis flow.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch(self, ticker: str, market: Market) -> Optional[QuarterlySnapshot]:
        try:
            if market == "india":
                return await self._fetch_screener(ticker)
            return await self._fetch_yfinance_us(ticker)
        except Exception as exc:
            log.warning("quarterly.fetch_error", ticker=ticker, market=market, error=str(exc))
            return None

    # ── India: screener.in ────────────────────────────────────────────────────

    async def _fetch_screener(self, ticker: str) -> Optional[QuarterlySnapshot]:
        """
        Scrape screener.in — the same site the user was manually reading.
        Tries consolidated first, falls back to standalone.
        """
        for suffix in ("consolidated/", ""):
            url = f"{_SCREENER_BASE}/{ticker}/{suffix}"
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                    resp = await client.get(url, headers=_HEADERS)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()

                quarters, data = _parse_screener_html(resp.text)
                if not quarters or not data:
                    continue

                results = _build_results_newest_first(quarters, data)
                if not results:
                    continue

                rev_trend = _revenue_trend(results)
                mar_trend = _margin_trend(results)
                ear_trend = _earnings_trend(results)
                snap = QuarterlySnapshot(
                    ticker=ticker,
                    market="india",
                    quarters=results[:6],
                    revenue_trend=rev_trend,
                    margin_trend=mar_trend,
                    earnings_trend=ear_trend,
                    currency="₹",
                    unit="Cr",
                    quarterly_insight=_compute_quarterly_insight(
                        rev_trend, mar_trend, ear_trend, results[:6]
                    ),
                )
                log.info(
                    "quarterly.screener_ok",
                    ticker=ticker,
                    quarters=len(snap.quarters),
                    rev_trend=snap.revenue_trend,
                    earn_trend=snap.earnings_trend,
                )
                return snap

            except httpx.TimeoutException:
                log.warning("quarterly.screener_timeout", ticker=ticker, url=url)
            except httpx.HTTPStatusError as exc:
                log.warning("quarterly.screener_http_error", ticker=ticker, status=exc.response.status_code)
            except Exception as exc:
                log.warning("quarterly.screener_parse_error", ticker=ticker, error=str(exc))

        return None

    # ── US: yfinance ──────────────────────────────────────────────────────────

    async def _fetch_yfinance_us(self, ticker: str) -> Optional[QuarterlySnapshot]:
        """yfinance quarterly_income_stmt — reliable for US large/mid caps."""
        try:
            import yfinance as yf
            import pandas as pd

            ticker_obj = yf.Ticker(ticker)
            q_stmt: pd.DataFrame = await asyncio.wait_for(
                asyncio.to_thread(lambda: ticker_obj.quarterly_income_stmt),
                timeout=12.0,
            )
            if q_stmt is None or q_stmt.empty:
                return None

            cols = list(q_stmt.columns)[:8]  # up to 8 quarters, newest first
            results: list[QuarterlyResult] = []

            for col in cols:
                period = col.strftime("%b '%y") if hasattr(col, "strftime") else str(col)[:7]

                def _yf_val(row: str) -> Optional[float]:
                    if row not in q_stmt.index:
                        return None
                    v = q_stmt.loc[row, col]
                    import math
                    if v is None or (isinstance(v, float) and math.isnan(v)):
                        return None
                    return float(v) / 1_000_000  # to $M

                revenue = _yf_val("Total Revenue")
                net_profit = _yf_val("Net Income")
                ebitda = _yf_val("EBITDA")

                opm_pct: Optional[float] = None
                if revenue and ebitda and revenue != 0:
                    opm_pct = ebitda / revenue * 100

                eps_raw = None
                if "Basic EPS" in q_stmt.index:
                    v = q_stmt.loc["Basic EPS", col]
                    import math
                    if v is not None and not (isinstance(v, float) and math.isnan(v)):
                        eps_raw = float(v)

                results.append(QuarterlyResult(
                    period=period,
                    revenue=revenue,
                    operating_profit=ebitda,
                    opm_pct=opm_pct,
                    net_profit=net_profit,
                    eps=eps_raw,
                ))

            # Compute YoY growth (results already newest-first from yfinance)
            for i, r in enumerate(results):
                prev_idx = i + 4
                if prev_idx >= len(results):
                    continue
                prev = results[prev_idx]
                if r.revenue is not None and prev.revenue and prev.revenue != 0:
                    r.revenue_growth_yoy = (r.revenue - prev.revenue) / abs(prev.revenue) * 100
                if r.net_profit is not None and prev.net_profit and prev.net_profit != 0:
                    r.pat_growth_yoy = (r.net_profit - prev.net_profit) / abs(prev.net_profit) * 100

            rev_trend = _revenue_trend(results)
            mar_trend = _margin_trend(results)
            ear_trend = _earnings_trend(results)
            snap = QuarterlySnapshot(
                ticker=ticker,
                market="us",
                quarters=results[:6],
                revenue_trend=rev_trend,
                margin_trend=mar_trend,
                earnings_trend=ear_trend,
                currency="$",
                unit="M",
                quarterly_insight=_compute_quarterly_insight(
                    rev_trend, mar_trend, ear_trend, results[:6]
                ),
            )
            log.info(
                "quarterly.yfinance_ok",
                ticker=ticker,
                quarters=len(snap.quarters),
                rev_trend=snap.revenue_trend,
            )
            return snap

        except asyncio.TimeoutError:
            log.warning("quarterly.yfinance_timeout", ticker=ticker)
            return None
        except Exception as exc:
            log.warning("quarterly.yfinance_error", ticker=ticker, error=str(exc))
            return None
