/**
 * GlossaryPage — plain-English dictionary of every concept in StockCoach AI.
 *
 * Structured for two audiences:
 *  • Beginner: the "what it means" line — no jargon, real-world analogy
 *  • Experienced: the "dig deeper" line — precise definition, thresholds, formulas
 *
 * Sections:
 *   Stock Basics · Valuation Metrics · Growth Metrics · Financial Health ·
 *   App Features · Recovery Signals · Reverse DCF · Technical Indicators ·
 *   Scoring Systems · Portfolio Terms
 */

import { BookOpen, Search, X } from "lucide-react";
import { useMemo, useState } from "react";

// ── Data model ────────────────────────────────────────────────────────────────

interface GlossaryEntry {
  id: string;
  emoji: string;
  term: string;
  plain: string;        // one sentence — zero jargon
  deeper?: string;      // technical definition / formula / threshold
  category: Category;
}

type Category =
  | "basics"
  | "valuation"
  | "growth"
  | "health"
  | "features"
  | "signals"
  | "rdcf"
  | "technicals"
  | "scoring"
  | "portfolio";

const CATEGORY_META: Record<Category, { label: string; color: string; bg: string }> = {
  basics:     { label: "Stock Basics",        color: "text-blue-700",   bg: "bg-blue-50 border-blue-200"   },
  valuation:  { label: "Valuation Metrics",   color: "text-indigo-700", bg: "bg-indigo-50 border-indigo-200" },
  growth:     { label: "Growth Metrics",      color: "text-green-700",  bg: "bg-green-50 border-green-200"  },
  health:     { label: "Financial Health",    color: "text-teal-700",   bg: "bg-teal-50 border-teal-200"    },
  features:   { label: "App Features",        color: "text-violet-700", bg: "bg-violet-50 border-violet-200"},
  signals:    { label: "Recovery Signals",    color: "text-amber-700",  bg: "bg-amber-50 border-amber-200"  },
  rdcf:       { label: "Reverse DCF",         color: "text-purple-700", bg: "bg-purple-50 border-purple-200"},
  technicals: { label: "Technical Indicators",color: "text-rose-700",   bg: "bg-rose-50 border-rose-200"    },
  scoring:    { label: "Scoring Systems",     color: "text-orange-700", bg: "bg-orange-50 border-orange-200"},
  portfolio:  { label: "Portfolio Tracker",   color: "text-gray-700",   bg: "bg-gray-100 border-gray-200"   },
};

// ── Glossary entries ──────────────────────────────────────────────────────────

const ENTRIES: GlossaryEntry[] = [

  // ── Stock Basics ─────────────────────────────────────────────────────────────
  {
    id: "stock",
    category: "basics",
    emoji: "🏢",
    term: "Stock / Share",
    plain: "A tiny piece of ownership in a company. Buy 1 share of Apple and you own a microscopic slice of the business — if Apple does well, your slice becomes worth more.",
    deeper: "Common equity representing a proportional claim on assets, earnings, and voting rights. Most retail investors hold common shares via exchange-listed instruments.",
  },
  {
    id: "market-cap",
    category: "basics",
    emoji: "💰",
    term: "Market Cap",
    plain: "The total price tag the stock market puts on a company right now — simply the share price × number of shares. Large-cap (>$10B) = safer but slower growth. Small-cap (<$2B) = riskier but more upside.",
    deeper: "Free-float market capitalisation = shares outstanding × current price. Large-cap >$10B, mid-cap $2-10B, small-cap <$2B. Does not include net debt — see EV for that.",
  },
  {
    id: "bull-bear",
    category: "basics",
    emoji: "🐂",
    term: "Bull vs Bear Market",
    plain: "Bull = prices are rising and investors are optimistic. Bear = prices are falling and fear is spreading. Named for how the animals attack: bulls thrust upward, bears swipe down.",
    deeper: "Conventional definition: bull market = index up 20%+ from a recent low; bear market = index down 20%+ from a recent high. Average bear market lasts ~9–14 months; average bull ~32 months.",
  },
  {
    id: "volume",
    category: "basics",
    emoji: "📦",
    term: "Volume",
    plain: "How many shares were bought and sold today. High volume on a big price move = real, conviction-backed move. High volume on a tiny move = indecision. Low volume = no one cares yet.",
    deeper: "Compare against 20-day average volume. Volume ratio >2× = institutional or news-driven activity. The app filters Top Movers to ≥200K daily volume to exclude illiquid stocks.",
  },
  {
    id: "volatility",
    category: "basics",
    emoji: "🌊",
    term: "Volatility",
    plain: "How wildly a stock's price swings. A boring utility stock might move 0.5% a day; a biotech might move 15%. High volatility = bigger potential gain AND bigger potential loss.",
    deeper: "Quantified as standard deviation of daily returns (historical) or implied volatility from options pricing. The app uses average daily range and RSI as practical proxies.",
  },
  {
    id: "sector",
    category: "basics",
    emoji: "🏭",
    term: "Sector / Industry",
    plain: "The type of business the company is in. Sector is broad (e.g., Technology). Industry is specific (e.g., Semiconductor Equipment). Stocks in the same sector often move together on macro news.",
    deeper: "GICS (Global Industry Classification Standard) defines 11 sectors: Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples, Health Care, Financials, IT, Communication Services, Utilities, Real Estate.",
  },
  {
    id: "us-india",
    category: "basics",
    emoji: "🌍",
    term: "US vs India Markets",
    plain: "StockCoach covers two markets. US stocks trade on NYSE/NASDAQ in dollars. Indian stocks trade on NSE/BSE in rupees. Each market has different average valuations, growth rates, and risk profiles.",
    deeper: "US market average trailing P/E ~20-22×; Indian market historically 18-22×. The app applies market-specific P/E thresholds throughout — e.g., Recovery scanner uses 22× for US, 18× for India.",
  },

  // ── Valuation Metrics ─────────────────────────────────────────────────────────
  {
    id: "pe",
    category: "valuation",
    emoji: "🏷️",
    term: "P/E Ratio (Price-to-Earnings)",
    plain: "How much you pay for every $1 of the company's annual profit. P/E of 20 means you pay $20 for each $1 of earnings. Lower P/E generally = cheaper. The market average hovers around 18-22×.",
    deeper: "Current share price ÷ trailing-twelve-month (TTM) EPS. A P/E of 15 implies payback in 15 years at current earnings with no growth. Sector context matters: tech trades at 30-40×; banks at 10-15×.",
  },
  {
    id: "forward-pe",
    category: "valuation",
    emoji: "🔭",
    term: "Forward P/E",
    plain: "Same as P/E, but uses next year's estimated earnings instead of last year's actuals. A company growing fast will have a lower forward P/E — meaning you're actually getting it cheaper than the headline number suggests.",
    deeper: "Price ÷ NTM (next-twelve-months) consensus EPS estimate. More relevant for growth companies. When forward P/E < trailing P/E, the stock is on a P/E compression path — earnings are growing faster than price.",
  },
  {
    id: "pe-contraction",
    category: "valuation",
    emoji: "📉",
    term: "P/E Contraction",
    plain: "When a company's forward P/E is noticeably lower than its trailing P/E, it means earnings are growing faster than the stock price has moved. The market hasn't re-priced the improved earnings yet — that gap is opportunity.",
    deeper: "Contraction % = (trailing P/E − forward P/E) ÷ trailing P/E × 100. The Recovery Scanner requires ≥5% contraction to fire the pe_contracting signal. Larger contraction → stronger re-rating potential.",
  },
  {
    id: "pb",
    category: "valuation",
    emoji: "📚",
    term: "P/B Ratio (Price-to-Book)",
    plain: "Compares the stock price to the company's accounting value (assets minus debts). P/B below 1 means you can buy the company for less than what it owns on paper — extremely cheap (or in serious trouble).",
    deeper: "Price per share ÷ book value per share. Book value = total assets − total liabilities. Particularly useful for banks and asset-heavy industrials where tangible assets dominate earnings power.",
  },
  {
    id: "ev-ebitda",
    category: "valuation",
    emoji: "🏭",
    term: "EV/EBITDA",
    plain: "A more complete valuation metric than P/E. It compares the total company value (including its debt) to operating profits before accounting adjustments — so you can compare companies with very different borrowing levels.",
    deeper: "Enterprise Value (market cap + net debt) ÷ EBITDA (Earnings Before Interest, Tax, Depreciation, Amortization). Removes leverage and tax distortions from P/E. Below 10× is broadly considered cheap.",
  },
  {
    id: "analyst-target",
    category: "valuation",
    emoji: "🎯",
    term: "Analyst Price Target",
    plain: "Where professional Wall Street analysts think the stock will be in 12 months, based on their detailed models. The Recovery Scanner only shows stocks with ≥15% upside to this target — lower-conviction picks are filtered out.",
    deeper: "Consensus of all covering analysts' 12-month DCF / comparable-company targets. The app uses the median estimate. Analyst targets have mixed accuracy but are a useful sentiment anchor for institutional money flows.",
  },
  {
    id: "upside",
    category: "valuation",
    emoji: "📐",
    term: "Upside to Target",
    plain: "The gap between the current price and the analyst price target, expressed as a percentage. +25% upside means analysts collectively think the stock will rise 25% from here over the next year.",
    deeper: "Upside % = (target − current price) ÷ current price × 100. The Recovery Scanner filters to ≥15% upside only. Negative upside means the stock is above the analyst consensus target — potential downside.",
  },

  // ── Growth Metrics ────────────────────────────────────────────────────────────
  {
    id: "eps",
    category: "growth",
    emoji: "💵",
    term: "EPS (Earnings Per Share)",
    plain: "The company's total profit divided by the number of shares. If a company earns $100M with 50M shares outstanding, EPS = $2. Stock prices tend to follow EPS over the long run.",
    deeper: "Net income attributable to common shareholders ÷ weighted average diluted shares outstanding. GAAP EPS includes all costs; Adjusted EPS strips out one-time items — both are shown by companies.",
  },
  {
    id: "eps-growth",
    category: "growth",
    emoji: "📈",
    term: "EPS Growth YoY",
    plain: "How much more the company earned per share compared to the same period last year. 20% EPS growth means the company is 20% more profitable than a year ago — that's strong sustained growth.",
    deeper: "Trailing YoY: TTM EPS vs prior-year TTM EPS. The Recovery Scanner fires the eps_growing signal when EPS growth ≥8% YoY. The signal score also factors magnitude — 50%+ growth earns maximum points.",
  },
  {
    id: "revenue",
    category: "growth",
    emoji: "💸",
    term: "Revenue (Top Line)",
    plain: "The total money flowing into a company from its products and services before any expenses are deducted. Revenue tells you if the business is growing its customers and sales — you can have great revenue but still lose money if costs are out of control.",
    deeper: "Also called 'top line' as it sits at the top of the income statement. Organic revenue growth (excluding acquisitions and currency effects) is the cleanest signal of genuine business momentum.",
  },
  {
    id: "revenue-growth",
    category: "growth",
    emoji: "🚀",
    term: "Revenue Growth YoY",
    plain: "How much more revenue the company generated compared to last year. Consistent 10-15%+ revenue growth is a hallmark of a healthy, expanding business in a growing market.",
    deeper: "The Recovery Scanner fires the revenue_growing signal when revenue growth ≥5% YoY. Decelerating revenue growth (even if still positive) can be an early warning before earnings disappoint.",
  },
  {
    id: "roe",
    category: "growth",
    emoji: "🔄",
    term: "ROE (Return on Equity)",
    plain: "How efficiently management turns shareholders' money into profit. ROE of 15% means for every $100 of owner capital, the company generates $15 of annual profit. Buffett uses this as his primary competitive moat indicator.",
    deeper: "Net income ÷ average shareholders' equity. Sustained ROE >15% over 5+ years typically indicates pricing power or structural cost advantage. Watch for ROE inflated by high leverage — check D/E alongside it.",
  },
  {
    id: "cagr",
    category: "growth",
    emoji: "📊",
    term: "CAGR (Compound Annual Growth Rate)",
    plain: "The smoothed average yearly growth rate over multiple years. Much more honest than picking a single great year. Revenue CAGR of 18% over 5 years means the business consistently grew 18%/year on average.",
    deeper: "CAGR = (ending value ÷ starting value)^(1/n) − 1, where n = years. 3-year and 5-year revenue/EPS CAGRs shown in the Growth Triggers deep-dive. More reliable than single-year comparisons which can be distorted by one-time items.",
  },

  // ── Financial Health ──────────────────────────────────────────────────────────
  {
    id: "de-ratio",
    category: "health",
    emoji: "⚖️",
    term: "Debt-to-Equity (D/E) Ratio",
    plain: "How much the company owes versus how much it owns. D/E of 0.5 means for every $1 of shareholder equity, there's $0.50 of debt. Low D/E = strong, resilient balance sheet. Very high D/E = risky if business slows.",
    deeper: "Total debt ÷ total shareholders' equity. The Recovery Scanner requires D/E <0.8× to fire the low_debt signal. Note: yfinance reports D/E in percentage units — a value of 80 = 0.8× actual ratio.",
  },
  {
    id: "profit-margin",
    category: "health",
    emoji: "📊",
    term: "Profit Margin (Net Margin)",
    plain: "What percentage of each dollar of revenue actually becomes profit after all expenses. Margin of 10% means the company keeps $0.10 for every $1 of sales. Software companies can hit 30-40%; supermarkets often run 2-3%.",
    deeper: "Net income ÷ total revenue. The Recovery Scanner fires the profitable signal when net margin ≥8%. Margin expansion (margin growing year over year) is an even stronger signal than absolute level.",
  },
  {
    id: "fcf",
    category: "health",
    emoji: "💧",
    term: "Free Cash Flow (FCF)",
    plain: "Real money flowing into the company after all costs and investments. Earnings can be dressed up with accounting adjustments; FCF is much harder to fake. Companies with growing FCF consistently are the best long-term holds.",
    deeper: "Operating cash flow − capital expenditures. FCF yield (FCF ÷ market cap) is a direct comparison to dividend yield or bond yield. FCF-to-EPS >1 means earnings are fully backed by real cash.",
  },
  {
    id: "interest-coverage",
    category: "health",
    emoji: "🛡️",
    term: "Interest Coverage Ratio",
    plain: "How comfortably the company can pay the interest on its loans. Coverage of 5× means earnings are 5 times higher than the interest bill. Below 2× = danger zone — the company might struggle to service debt.",
    deeper: "EBIT ÷ interest expense. The Growth Triggers deep-dive shows this for each analysed stock. Below 1.5× is a red flag. Trending down is an early warning even if still above 2×.",
  },

  // ── App Features ──────────────────────────────────────────────────────────────
  {
    id: "top-movers",
    category: "features",
    emoji: "🔥",
    term: "Top Movers (Market Tab)",
    plain: "The stocks moving the most today — filtered to companies above $5 (no penny stocks), with at least 200K shares traded, and up 5%+. The AI then explains WHY each stock moved and whether the move is likely to hold.",
    deeper: "US screener: price >$5, volume >200K, change >5%. India screener uses equivalent rupee/volume thresholds. Post-filter removes any stock that slipped below $5 since the screener ran. Quality Score badge shows fundamental backing.",
  },
  {
    id: "value-recovery",
    category: "features",
    emoji: "♻️",
    term: "Value Recovery Scanner",
    plain: "Scans for quality companies whose stock price has fallen behind their actual financial performance. These stocks have improving earnings but the market hasn't noticed yet — they're cheap relative to what the business is actually worth.",
    deeper: "Applies PE thresholds (US ≤22×, India ≤18×), requires at least 2 of 8 signals, scores each stock 0-100. Cached for 2 hours; use the ↺ refresh button to force a fresh scan after deployment. Forward PE anchor uses a 0.85 discount factor to avoid false positives when trailing P/E is unavailable (common in Indian markets).",
  },
  {
    id: "dip-scanner",
    category: "features",
    emoji: "📉",
    term: "Dip Scanner",
    plain: "Finds stocks that have pulled back significantly from their recent highs but still have strong fundamentals. The idea is simple: buy a genuinely good company when it's temporarily on sale.",
    deeper: "Scans for stocks ≥8% below their 3-month high, RSI <60 (not in overbought territory), and with positive analyst consensus. Dip score weights pullback depth, RSI oversold extent, and upside-to-analyst-target.",
  },
  {
    id: "catalyst-scanner",
    category: "features",
    emoji: "⚡",
    term: "Catalyst Scanner",
    plain: "Detects stocks with unusual volume or price action suggesting something is happening — an earnings beat, a product launch, sector rotation. The AI rates each move as 'strong' (confirmed catalyst), 'emerging' (early signs), 'potential' (worth watching), or 'noise' (ignore).",
    deeper: "Volume ratio >1.5× 20-day average is the primary trigger. Momentum score combines volume ratio, intraday change %, and AI confidence. The scanner is embedded inside the Market tab — switch to the Catalyst view mode.",
  },
  {
    id: "radar",
    category: "features",
    emoji: "📡",
    term: "Radar",
    plain: "Scans news and market data to surface emerging investment themes before they go mainstream — things like 'AI infrastructure buildout' or 'India capex cycle.' Each theme comes with specific stock tickers to watch.",
    deeper: "Powered by Gemini AI scanning recent market headlines and cross-referencing sector data. Themes come with conviction score (0-1), timeframe, and evidence summary. Click 'Find Moving' to cross-reference with the Catalyst Scanner.",
  },
  {
    id: "growth-triggers",
    category: "features",
    emoji: "🌱",
    term: "Growth Triggers",
    plain: "A deep AI analysis of one specific stock: what future events or milestones could dramatically increase the company's value? Generates a HIGH/MEDIUM/OPTIONALITY conviction scorecard with specific things to 'watch for' before each trigger confirms.",
    deeper: "Gemini analyses company filings, sector trends, and news. Output includes: company snapshot, 3-7 triggers with P&L impact and timeline, risk items, and a multi-dimension scorecard. Cached per ticker. Costs ~15s the first time.",
  },
  {
    id: "conviction-thesis",
    category: "features",
    emoji: "💡",
    term: "Conviction Thesis",
    plain: "You type a belief ('I think India's defence sector will boom') and the AI builds a structured investment thesis: which stocks benefit, what would confirm the thesis is playing out, what would invalidate it, and when to exit.",
    deeper: "Outputs: belief → thesis summary → instruments (3 risk tiers) → confirmers with status → entry signal (strong/fair/wait) → exit triggers → time horizon. Saved locally and searchable in portfolio context.",
  },
  {
    id: "portfolio-tracker",
    category: "features",
    emoji: "🎯",
    term: "Portfolio Tracker (PLAYS)",
    plain: "Track your real positions and AI-generated predictions side by side. Each entry has a 30-day prediction clock — the AI's directional call (up or down) is scored as a win or loss after 30 days based solely on whether the direction was correct.",
    deeper: "Stored in Redis with 10-year TTL. Entry price = stock price when you added the prediction (the anchor). Purchase average = your actual cost basis (separate field). Resolution: direction_correct = (predicted_change ≥ 0) == (actual_change ≥ 0).",
  },

  // ── Recovery Signals ──────────────────────────────────────────────────────────
  {
    id: "sig-eps",
    category: "signals",
    emoji: "📈",
    term: "Signal: EPS Growing",
    plain: "The company's earnings per share grew more than 8% year-over-year. This is the core signal that the underlying business is improving — not just cost-cutting, but real profit growth.",
    deeper: "Fires when TTM EPS growth ≥8%. Recovery score earns up to 15 bonus points based on magnitude: 8-15% = small boost; 30%+ = maximum. Requires non-negative EPS (loss-making companies can't fire this).",
  },
  {
    id: "sig-rev",
    category: "signals",
    emoji: "💹",
    term: "Signal: Revenue Growing",
    plain: "Revenue increased more than 5% year-over-year. This confirms the business is genuinely expanding, not just cutting costs to temporarily boost earnings — which is the 'fake' version of improvement.",
    deeper: "Fires when YoY revenue growth ≥5%. Combined with EPS Growing, it indicates both top-line expansion and bottom-line leverage — a high-quality recovery signature.",
  },
  {
    id: "sig-pe",
    category: "signals",
    emoji: "🔭",
    term: "Signal: P/E Contracting",
    plain: "The forward P/E (next-year estimate) is at least 5% lower than the trailing P/E (last-year actual). Earnings are growing faster than the stock price has moved — the multiple is compressing 'for free' as earnings catch up.",
    deeper: "Fires when (trailing P/E − forward P/E) / trailing P/E ≥5%. The pe_contraction_pct is also displayed on the card as a progress bar showing how far forward earnings have grown relative to the current price.",
  },
  {
    id: "sig-roe",
    category: "signals",
    emoji: "🏆",
    term: "Signal: Strong ROE",
    plain: "Return on equity is above 13%, meaning management generates strong returns on the capital shareholders have entrusted to them. This is Buffett's favourite moat indicator — a high, stable ROE is hard to fake.",
    deeper: "Fires when TTM ROE ≥13%. Unlike EPS growth which can be one-year noise, sustained ROE >15% over multiple years typically indicates pricing power, customer lock-in, or structural cost advantage.",
  },
  {
    id: "sig-debt",
    category: "signals",
    emoji: "🏦",
    term: "Signal: Low Debt",
    plain: "The debt-to-equity ratio is below 0.8×. A clean balance sheet means the company can weather downturns, invest in growth, or return cash to shareholders — without being strangled by interest payments.",
    deeper: "Fires when D/E <0.8 (note: yfinance returns D/E in percentage units — the threshold is applied as <80 in raw data). Conservative threshold vs. the 1.5× that some screens use, intentionally.",
  },
  {
    id: "sig-profit",
    category: "signals",
    emoji: "💰",
    term: "Signal: Profitable",
    plain: "The net profit margin is above 8% — the business actually converts revenue into real profit. This filter protects against 'value traps': cheap stocks that look attractive but are slowly burning through cash.",
    deeper: "Fires when net profit margin ≥8%. Excludes 'growth story' businesses that are unprofitable by design. Particularly important in the Indian market where many listed companies have very thin or inconsistent margins.",
  },
  {
    id: "sig-analyst",
    category: "signals",
    emoji: "📋",
    term: "Signal: Analyst Bullish",
    plain: "Wall Street's consensus recommendation is Buy, Outperform, or Strong Buy. Professional analysts have studied this company in detail and are telling institutional investors to accumulate.",
    deeper: "Fires when analyst_consensus ∈ {buy, strong_buy, outperform, overweight}. Represents the median call across all sell-side analysts covering the stock. Hold, Sell, and Underperform-rated stocks are excluded from the scanner entirely.",
  },
  {
    id: "sig-rdcf",
    category: "signals",
    emoji: "◈",
    term: "Signal: rDCF Gap (Reverse DCF Mispriced)",
    plain: "The most powerful signal. It fires when the stock market is implicitly pricing in far less EPS growth than the company is actually delivering — a 20+ percentage point gap. The market is systematically wrong about this company's earnings trajectory.",
    deeper: "Implied EPS CAGR is computed from the current PE (see Reverse DCF section). Fires when (actual EPS growth % − implied growth %) ≥20 percentage points. A 20pp gap means the market is under-pricing earnings by ~2×.",
  },

  // ── Reverse DCF ───────────────────────────────────────────────────────────────
  {
    id: "rdcf-what",
    category: "rdcf",
    emoji: "🔄",
    term: "What Is Reverse DCF?",
    plain: "Normal DCF asks: 'Given expected future earnings, what is this company worth?' Reverse DCF flips it: 'Given the current stock price and P/E ratio, what earnings growth rate is the market assuming?' If the market's implied assumption is wildly pessimistic vs. what the company is actually delivering — you've found a mispricing.",
    deeper: "Formula: implied_growth = (PE × 1.10^5 ÷ 15)^(1/5) − 1. Parameters: 5-year horizon, 10% discount rate, 15× terminal P/E. Price and current EPS cancel out — the result depends only on the P/E multiple.",
  },
  {
    id: "rdcf-example",
    category: "rdcf",
    emoji: "📐",
    term: "Reverse DCF: Worked Example",
    plain: "A stock trading at P/E 12× implies the market expects only ~2% annual EPS growth over the next 5 years. If the company is actually growing EPS at 25% per year, the market is assuming 23 percentage points less growth than reality. That gap — when it closes — drives the stock re-rating upward.",
    deeper: "At PE=12: ratio = 12 × 1.61 ÷ 15 = 1.288, implied growth = 1.288^0.2 − 1 ≈ 5.2%. The rDCF Gap signal fires when (actual EPS growth %) − 5.2% > 20pp, i.e., actual growth >25.2%. The purple '◈' card row shows both numbers live.",
  },
  {
    id: "rdcf-why",
    category: "rdcf",
    emoji: "💡",
    term: "Why the rDCF Gap Matters",
    plain: "The market can misprice a stock for months or even years — especially mid-cap and small-cap stocks with limited analyst coverage. When the earnings trajectory eventually becomes undeniable (e.g., three consecutive strong quarters), institutional investors update their models and the stock re-rates sharply upward.",
    deeper: "The gap quantifies exactly how much pessimism is baked into the current price. A 25pp gap means you have a 25pp buffer of wrong-market-assumption before the thesis breaks. Combined with pe_contracting, it creates a powerful compounding setup: price stays flat, earnings grow, multiple eventually re-rates.",
  },

  // ── Technical Indicators ──────────────────────────────────────────────────────
  {
    id: "rsi",
    category: "technicals",
    emoji: "📊",
    term: "RSI (Relative Strength Index)",
    plain: "A momentum gauge from 0 to 100. Above 70 = stock is 'overbought' — it's run up fast and may be due for a rest. Below 30 = 'oversold' — it's been sold down hard and may bounce. Most useful when combined with fundamental analysis.",
    deeper: "Wilder's RSI: 14-period. RSI = 100 − (100 ÷ (1 + avg_gain/avg_loss)). The Dip Scanner targets RSI <60 to avoid catching falling knives in overbought conditions. Not predictive in isolation — use as a timing overlay on a fundamentally strong stock.",
  },
  {
    id: "macd",
    category: "technicals",
    emoji: "📉",
    term: "MACD",
    plain: "Tracks whether short-term price momentum is stronger or weaker than long-term momentum. A 'bullish cross' (MACD line crossing above its signal line) suggests momentum is turning positive — traders use this as an early entry signal.",
    deeper: "MACD line = EMA(12) − EMA(26). Signal line = EMA(9) of MACD. Histogram = MACD − signal. Bullish cross: MACD rises above signal. The app shows MACD direction and cross events in the Analysis Panel technicals section.",
  },
  {
    id: "sma",
    category: "technicals",
    emoji: "〰️",
    term: "Moving Average (SMA 20 / SMA 50)",
    plain: "The average stock price over the last 20 or 50 days. Price above the 50-day average = stock is in an uptrend. Price below the 50-day average = downtrend. Moving averages smooth out daily noise to show the underlying direction.",
    deeper: "Simple Moving Average = sum of closing prices over N days ÷ N. SMA20 is more responsive (short-term trend); SMA50 is the medium-term trend. The app computes both and shows price-vs-SMA20 and price-vs-SMA50 signals.",
  },
  {
    id: "golden-cross",
    category: "technicals",
    emoji: "✨",
    term: "Golden Cross",
    plain: "When the 50-day moving average crosses above the 200-day moving average — historically a bullish long-term signal. It means short-term momentum has become stronger than the long-term trend, suggesting a sustained uptrend may be starting.",
    deeper: "Death cross (opposite: 50d crosses below 200d) is the bearish equivalent. Golden cross tends to be a lagging signal — the move has often already happened by the time it fires. Most powerful in conjunction with increasing volume.",
  },
  {
    id: "support-resistance",
    category: "technicals",
    emoji: "🧱",
    term: "Support & Resistance",
    plain: "Support = a price level where buyers consistently step in and stop the stock from falling further. Resistance = a price level where sellers consistently step in and cap the stock's rise. Breaking through resistance with high volume is a bullish signal.",
    deeper: "Computed as recent swing lows (support) and swing highs (resistance) over 20-day lookback. The app displays both in the price chart and technicals panel. A prior resistance level, once broken, often becomes a new support level.",
  },
  {
    id: "52w",
    category: "technicals",
    emoji: "📏",
    term: "52-Week High / Low",
    plain: "The highest and lowest price the stock has traded at over the past year. Stocks near their 52-week low might be on sale. Stocks breaking to new 52-week highs are often in strong momentum. The app shows '% of 52-week range' as a 0-100 scale.",
    deeper: "pct_of_52w_range = (current − 52w_low) ÷ (52w_high − 52w_low) × 100. A value of 20 = near the low. A value of 80 = near the high. The Dip Scanner uses this alongside RSI to identify deep-but-not-broken pullbacks.",
  },

  // ── Scoring Systems ───────────────────────────────────────────────────────────
  {
    id: "recovery-score",
    category: "scoring",
    emoji: "🏅",
    term: "Recovery Score (0-100)",
    plain: "The composite score in the Value Recovery Scanner. A higher score = more signals firing + deeper valuation discount + stronger growth + bullish analyst consensus. Score ≥65 shows as a teal 'Value Recovery' card. Score 40-64 shows as an amber 'Emerging' card.",
    deeper: "Breakdown: valuation depth (up to 30pts — how far below market-average P/E) + signal count × 5pts each (up to 40pts) + EPS growth magnitude (up to 15pts) + analyst consensus quality (up to 15pts). Maximum = 100.",
  },
  {
    id: "quality-score",
    category: "scoring",
    emoji: "⭐",
    term: "Quality Score",
    plain: "Used in the Top Movers list. A composite of revenue growth, profitability, ROE, and debt — tells you if the company has solid fundamentals behind today's price move. A high-quality mover is more likely to sustain its gain.",
    deeper: "Combines 5 factors: EPS growth rate, revenue growth rate, ROE level, D/E ratio, and profit margin. Output: Strong (teal) / Moderate (blue) / Watch (amber) / Risky (red). Displayed as a badge on each Gainer Card.",
  },
  {
    id: "momentum-score",
    category: "scoring",
    emoji: "⚡",
    term: "Momentum Score",
    plain: "Used in the Catalyst Scanner. Combines today's volume relative to normal levels, the size of the price move, and the strength of the AI's catalyst confidence. A momentum score of 80+ means something real and significant is happening.",
    deeper: "Weighted sum: volume_ratio × weight + |change_pct| × weight + ai_confidence × weight. All components normalised to 0-100. High momentum + fundamental quality (from Quality Score) = the best setup.",
  },
  {
    id: "signal-tier",
    category: "scoring",
    emoji: "🎖️",
    term: "Signal Tier",
    plain: "A three-tier classification on each mover: 'Confirmed' = strong fundamentals AND catalyst. 'Catalyst' = strong catalyst but mixed fundamentals. 'Mover' = price action only — weaker fundamental backing. Focus on Confirmed tier for highest conviction.",
    deeper: "Assigned by combining Quality Score tier and AI catalyst confidence. Confirmed = quality ≥ Moderate + AI confidence ≥0.7. Catalyst = quality any + AI confidence ≥0.7. Mover = quality any + AI confidence <0.7.",
  },

  // ── Portfolio Terms ───────────────────────────────────────────────────────────
  {
    id: "entry-price",
    category: "portfolio",
    emoji: "🎯",
    term: "Entry Price",
    plain: "In the Portfolio Tracker, this is the stock price at the moment you added the prediction. It's the anchor for measuring whether the AI's directional call was right — completely separate from what you actually paid.",
    deeper: "Set automatically to the live price at time of entry. Used as the baseline for actual_change_pct calculation. The prediction evaluation uses this price, not purchase_avg — important distinction when predicting stocks you don't own.",
  },
  {
    id: "purchase-avg",
    category: "portfolio",
    emoji: "💵",
    term: "Purchase Average",
    plain: "Your actual cost per share — what you really paid. Separate from Entry Price so you can track both your real P&L and the AI's prediction accuracy independently. You might enter a prediction at $50 but have bought at $45 — both are tracked.",
    deeper: "Optional field. Used to calculate real unrealised P&L (purchase_avg × shares vs. current price × shares). Does not affect AI prediction scoring, which only uses entry_price and actual_price at resolution.",
  },
  {
    id: "direction-correct",
    category: "portfolio",
    emoji: "✅",
    term: "Direction Correct",
    plain: "How the AI's prediction is judged. Only the direction matters — up or down — not the magnitude. If the AI predicted +15% and the stock went up even 1%, that's a win. If it predicted -10% and the stock went down, that's also a win.",
    deeper: "direction_correct = (predicted_change_pct ≥ 0) === (actual_change_pct ≥ 0). Phase 1 metric — direction only. Phase 2 (50+ entries) will add magnitude and magnitude-weighted accuracy using vector DB for RAG context.",
  },
  {
    id: "status",
    category: "portfolio",
    emoji: "🔄",
    term: "Entry Status",
    plain: "Every prediction goes through these stages: Active (within the 30-day window), then one of three outcomes: Win (direction was right), Loss (direction was wrong), or Expired (30 days passed without a final price being recorded).",
    deeper: "Status flow: active → expired (past target_date with no actual_price entered) → win or loss (once actual_price is resolved). Expired entries can still be resolved manually. The PLAYS tab shows win rate across all resolved predictions.",
  },
  {
    id: "30day-clock",
    category: "portfolio",
    emoji: "⏱️",
    term: "30-Day Prediction Clock",
    plain: "All AI directional predictions run on a 30-day window from the date you add them. Short enough to stay relevant, long enough for a thesis to play out. At day 30, you record the final price and the AI's call gets scored.",
    deeper: "entry_date = when added; target_date = entry_date + 30 days. Clock visible in the tracker as a progress bar. Entries approaching target_date turn amber to remind you to record the final price.",
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

const ALL_CATEGORIES = Object.keys(CATEGORY_META) as Category[];

export function GlossaryPage() {
  const [query,    setQuery]    = useState("");
  const [activeCategory, setActiveCategory] = useState<Category | "all">("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    return ENTRIES.filter(e => {
      const matchCat = activeCategory === "all" || e.category === activeCategory;
      if (!q) return matchCat;
      return matchCat && (
        e.term.toLowerCase().includes(q) ||
        e.plain.toLowerCase().includes(q) ||
        (e.deeper?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [query, activeCategory]);

  // Group by category for display
  const grouped = useMemo(() => {
    const map = new Map<Category, GlossaryEntry[]>();
    for (const entry of filtered) {
      if (!map.has(entry.category)) map.set(entry.category, []);
      map.get(entry.category)!.push(entry);
    }
    return map;
  }, [filtered]);

  function toggleExpand(id: string) {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-hidden">

      {/* ── Sticky header ─────────────────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 md:px-6 py-3 space-y-3 shrink-0">

        {/* Title row */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center shrink-0">
            <BookOpen size={16} className="text-indigo-600" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-gray-900">Glossary</h2>
            <p className="text-[11px] text-gray-400">Every metric, signal, and feature explained — beginner to advanced</p>
          </div>
          <span className="ml-auto text-[11px] text-gray-400">{filtered.length} terms</span>
        </div>

        {/* Search */}
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            type="text"
            placeholder={'Search terms, e.g. "P/E", "RSI", "Reverse DCF"…'}
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="w-full pl-8 pr-8 py-2 text-xs rounded-xl border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-transparent placeholder:text-gray-400"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <X size={13} />
            </button>
          )}
        </div>

        {/* Category pills */}
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setActiveCategory("all")}
            className={[
              "text-[10px] font-semibold px-2.5 py-1 rounded-full border transition-all",
              activeCategory === "all"
                ? "bg-indigo-600 text-white border-indigo-600"
                : "bg-white text-gray-500 border-gray-200 hover:border-gray-300",
            ].join(" ")}
          >
            All
          </button>
          {ALL_CATEGORIES.map(cat => {
            const meta = CATEGORY_META[cat];
            const isActive = activeCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat === activeCategory ? "all" : cat)}
                className={[
                  "text-[10px] font-semibold px-2.5 py-1 rounded-full border transition-all",
                  isActive
                    ? `${meta.bg} ${meta.color} border-current`
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-300",
                ].join(" ")}
              >
                {meta.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Content ───────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-8">

        {filtered.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <BookOpen size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm font-medium">No terms match "{query}"</p>
            <p className="text-xs mt-1">Try a shorter word or clear the search</p>
          </div>
        )}

        {ALL_CATEGORIES.filter(cat => grouped.has(cat)).map(cat => {
          const entries = grouped.get(cat)!;
          const meta = CATEGORY_META[cat];
          return (
            <section key={cat}>
              {/* Section heading */}
              <div className="flex items-center gap-2 mb-3">
                <span className={`text-[10px] font-bold uppercase tracking-widest ${meta.color}`}>
                  {meta.label}
                </span>
                <span className="flex-1 h-px bg-gray-100" />
                <span className="text-[10px] text-gray-400">{entries.length} terms</span>
              </div>

              {/* 2-col grid on medium+, single col on mobile */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {entries.map(entry => {
                  const isExpanded = expanded.has(entry.id);
                  return (
                    <div
                      key={entry.id}
                      className={`rounded-xl border bg-white p-4 transition-shadow hover:shadow-sm ${meta.bg.replace("bg-", "border-").replace("50", "100")} border`}
                    >
                      {/* Term header */}
                      <div className="flex items-start gap-2.5 mb-1.5">
                        <span className="text-xl leading-none mt-0.5 shrink-0">{entry.emoji}</span>
                        <div className="flex-1 min-w-0">
                          <h3 className={`text-xs font-bold leading-tight ${meta.color}`}>
                            {entry.term}
                          </h3>
                          <span className={`inline-block mt-0.5 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded-full ${meta.bg} ${meta.color}`}>
                            {meta.label}
                          </span>
                        </div>
                      </div>

                      {/* Plain explanation */}
                      <p className="text-[11px] text-gray-700 leading-relaxed">
                        {entry.plain}
                      </p>

                      {/* Deeper note */}
                      {entry.deeper && (
                        <>
                          {isExpanded && (
                            <p className="mt-2 text-[10px] text-gray-500 leading-relaxed border-t border-gray-100 pt-2">
                              {entry.deeper}
                            </p>
                          )}
                          <button
                            onClick={() => toggleExpand(entry.id)}
                            className={`mt-2 text-[10px] font-semibold transition-colors ${meta.color} hover:opacity-70`}
                          >
                            {isExpanded ? "▲ Less" : "▼ Dig deeper"}
                          </button>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}

        {/* Footer */}
        <div className="py-6 text-center text-[10px] text-gray-400 border-t border-gray-100">
          {ENTRIES.length} terms across {ALL_CATEGORIES.length} categories ·
          Each "Dig deeper" section shows the precise formula, threshold, or implementation detail
        </div>
      </div>
    </div>
  );
}
