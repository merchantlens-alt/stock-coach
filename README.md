# StockCoach AI

AI-powered stock research platform. Surfaces the day's top US and India movers, explains *why* they moved using real fundamentals + technicals + news, gives a 30-day AI outlook, and lets you build conviction theses backed by live market data.

Built with **FastAPI + React**, deployed on **Google Cloud Run**.

---

## High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Browser (React + Vite + Tailwind)                                          │
│                                                                             │
│  ┌──────────┐  ┌───────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  PULSE   │  │  CandleChart  │  │  AnalysisPanel  │  │  CONVICTION    │  │
│  │  tab     │  │  lightweight- │  │  Fundamentals + │  │  tab           │  │
│  │  Gainers │  │  charts v5    │  │  Technical panel│  │  Thesis input  │  │
│  │  list    │  │  SMA20/50     │  │  30-day outlook │  │  Instruments   │  │
│  └────┬─────┘  └───────┬───────┘  └────────┬────────┘  └───────┬────────┘  │
└───────┼────────────────┼───────────────────┼────────────────────┼───────────┘
        │ React Query    │ /history           │ /analyse           │ POST /conviction
        ▼                ▼                   ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  FastAPI backend  (Cloud Run — single instance, 2 vCPU, 2 GB)              │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  routes/gainers.py                                                   │  │
│  │  GET /gainers/{market}?period=          → list + market summary     │  │
│  │  GET /gainers/{market}/{ticker}         → detail (fast, no AI)      │  │
│  │  GET /gainers/{market}/{ticker}/analyse → full AI (slow, cached)    │  │
│  │  GET /gainers/{market}/{ticker}/history → OHLCV candles             │  │
│  └─────────────────────┬──────────────────────────────────────────────┘  │
│                         │                                                  │
│  ┌──────────────────────▼───────┐  ┌────────────────────────────────────┐ │
│  │  routes/conviction.py        │  │  Cache (Redis prod / in-mem dev)   │ │
│  │  POST /conviction/analyse    │  │  · Gainers list  TTL: 2h (mkt hrs) │ │
│  └──────────────────────┬───────┘  │  · Analysis      TTL: 24h          │ │
│                         │          │  · Conviction    TTL: 24h          │ │
│                         │          │  · Price history TTL: 30min        │ │
│  ┌──────────────────────▼──────────▼──────────────────────────────────┐ │
│  │  Agents                                                             │ │
│  │  GainerAnalystAgent  — analysis + 30-day prediction (1 Gemini call)│ │
│  │  MarketAnalystAgent  — market narrative + themes                    │ │
│  │  ThesisAnalystAgent  — conviction thesis builder                    │ │
│  └──────────────────────┬────────────────────────────────────────────┘ │
│                         │                                                  │
│  ┌──────────────────────▼────────────────────────────────────────────┐  │
│  │  Services                                                          │  │
│  │  market_data.py  — Gemini + Google Search grounding (gainers)     │  │
│  │  news_fetcher.py — NewsAPI.org (headlines per ticker)             │  │
│  │  technicals.py   — RSI/MACD/SMA/volume (pure Python, zero API $) │  │
│  └──────────────────────┬────────────────────────────────────────────┘  │
└─────────────────────────┼──────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼──────────────────────┐
        ▼                 ▼                      ▼
  Vertex AI          yfinance              NewsAPI.org
  Gemini 2.5 Flash   (fundamentals,        (headlines,
  (analysis,          OHLCV history,        summaries)
   conviction)        52-week range)
```

### Request flow — stock analysis

```
User clicks ticker
      │
      ├─→ GET /gainers/{market}/{ticker}         fast: yfinance fundamentals + news (~2s)
      │
      ├─→ GET /gainers/{market}/{ticker}/analyse  slow: parallel fetch — yfinance + news +
      │         │                                 yfinance 3-month OHLCV
      │         │                                 → compute RSI/MACD/SMA/volume in Python
      │         │                                 → one Gemini call (analysis + prediction)
      │         │                                 → cached 24h
      │         └─→ technicals injected into Gemini prompt
      │                   ↑ same signals shown in TechnicalPanel below the chart
      │
      └─→ GET /gainers/{market}/{ticker}/history  OHLCV candles → client computes SMA lines
```

---

## Features

| Feature | Detail |
|---|---|
| Top gainers | Gemini + Google Search grounding — real-time US (NYSE/NASDAQ) and India (NSE) movers |
| Signal tiers | **Confirmed** (has catalyst + quality ≥ 5.5) · **Catalyst** · **Mover** |
| Quality score | 0–10 rule-based: price tier + volume tier + change % sweet-spot + ticker length |
| Market narrative | AI one-paragraph summary of what's driving the market |
| Why it moved | Catalyst type, sustainability verdict, related beneficiaries, confidence |
| 30-day outlook | Predicted % move · tailwinds · risks · valuation/growth/debt signals |
| Candlestick chart | lightweight-charts v5: candles + volume histogram + **SMA20 (orange) + SMA50 (blue)** overlays |
| Technical signals | RSI-14, MACD direction/cross, golden/death cross, volume trend ratio, 5d/20d momentum, support/resistance |
| Technicals → AI | RSI/MACD/SMA formatted as plain text and **injected into the Gemini prompt** — the AI 30-day prediction factors in the same signals the chart displays |
| Conviction tab | State a belief ("AI memory demand is structural") → AI maps it to 3 instruments (lower/focused/higher risk), conviction score 0–100, confirmers, entry signal, exit triggers |
| Thesis × PULSE | When a saved conviction thesis ticker appears as a gainer, the card shows the theme tag |
| 52-week range bar | Visual position bar with analyst target price |
| India support | NSE tickers (`.NS` suffix handled server-side), ₹ currency |
| Period modes | 1d / 1w / 1m with labeled returns — no ambiguity about which return is shown |
| Last-known-good | Gainer list never goes blank — stale data served on Gemini outage, LKG TTL up to 2 weeks |
| Prewarm | Top-5 gainers per market pre-fetched in background after list loads (max 3 concurrent) |

---

## Non-Functional Requirements

### Performance

| Endpoint | Cold (first load) | Cached |
|---|---|---|
| `GET /gainers/{market}` | ≤ 15s (Gemini + grounding) | ≤ 50ms |
| `GET /gainers/{market}/{ticker}` | ≤ 5s (yfinance + news) | ≤ 50ms |
| `GET /gainers/{market}/{ticker}/analyse` | ≤ 20s (Gemini) | ≤ 50ms |
| `GET /{market}/{ticker}/history` | ≤ 3s (yfinance) | ≤ 50ms |
| `POST /conviction/analyse` | ≤ 20s (Gemini) | ≤ 50ms |

### Reliability

- **Never blank**: Last-known-good (LKG) cache ensures gainers list shows stale data rather than an empty page on Gemini failures
- **Graceful degradation**: Partial results returned if fundamentals or news fail — AI analysis still proceeds
- **Mock mode**: `MOCK_AI=true` runs the entire app without any GCP credentials — safe for local dev and CI
- **No automatic retry on AI calls**: Prevents duplicate billing on transient failures

### Cost efficiency (₹1 lakh ≈ $1,200 USD budget)

| Cost driver | Daily estimate | Notes |
|---|---|---|
| Google Search grounding (gainer lists) | $0.21–0.35 | ~6–10 list refreshes/day; dominant cost |
| Gemini analysis calls | $0.01–0.03 | ~10 cold calls/day; rest served from 24h cache |
| Gemini conviction calls | $0.003 | Low frequency; 24h cache per belief |
| yfinance / NewsAPI / technicals | $0 | Free tier / pure Python |
| **Total daily** | **$0.25–0.40** | **Budget lasts ~8–13 years at this rate** |

> ⚠️ **`thinkingBudget: 0` must be explicitly set** on all Gemini API calls. Gemini 2.5 Flash has adaptive thinking enabled by default. Thinking tokens cost $3.50/1M vs $0.60/1M for regular output — an unguarded analysis call on a "complex" prompt can cost 5–10× more than expected. For structured JSON extraction, thinking adds zero value and pure cost.

> ⚠️ **1w / 1m list TTL** should be extended to 12–24h. Weekly/monthly top movers don't change intraday — refreshing them every 2h wastes ~60% of the grounding budget.

### Security

- No user authentication (public read-only app)
- CORS locked to configured origins
- No PII in cache — keys are tickers and SHA-256(belief) hashes only
- All AI outputs labelled as educational, not financial advice

### Scalability

- Single Cloud Run instance handles expected solo/small-team load (in-memory cache)
- Swap `REDIS_URL` for multi-instance scale — cache layer is already abstracted behind an interface
- `PREWARM_CONCURRENCY` knob (default: 3) caps parallel Gemini calls on cold list loads

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Charts | lightweight-charts v5.2 (TradingView OSS) |
| State / data fetching | TanStack Query (React Query) v5 |
| Backend | Python 3.11 + FastAPI + Pydantic v2 |
| AI | Vertex AI Gemini 2.5 Flash (direct REST — no SDK, saves 600 MB image size) |
| Market data | Gemini + Google Search grounding (real-time gainers list) |
| Fundamentals + OHLCV | yfinance (free) |
| News | NewsAPI.org (free tier) |
| Technical indicators | Pure Python — RSI-14, MACD, SMA-20/50, volume trend, momentum |
| Cache | In-memory dict (dev) / Redis (prod) |
| Deployment | Docker multi-stage + Google Cloud Run |
| Tests | pytest + pytest-asyncio — 254 tests, all mocked, no GCP credentials needed |

---

## Local setup

### Prerequisites

- **Python 3.11+** and **Poetry** (`pip install poetry`)
- **Node.js 20+** and **npm**

> No GCP account needed — set `MOCK_AI=true` and the app runs entirely locally.

### 1 — Clone and install

```bash
git clone https://github.com/merchantlens-alt/stock-coach.git
cd stock-coach
cd backend && poetry install && cd ..
cd frontend && npm install && cd ..
```

### 2 — Configure environment

```bash
cp .env.example backend/.env
```

Minimum for local dev:

```env
MOCK_AI=true
NEWS_API_KEY=      # Leave empty — news skipped when missing
REDIS_URL=         # Leave empty — uses in-memory cache
```

### 3 — Run

**Terminal 1:**
```bash
cd backend && poetry run uvicorn main:app --reload --port 8080
```

**Terminal 2:**
```bash
cd frontend && npm run dev
```

Open http://localhost:5173

---

## Local setup with real GCP

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud auth application-default login
```

`.env`:
```env
MOCK_AI=false
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_REGION=asia-south1
VERTEX_AI_MODEL_FLASH=gemini-2.5-flash
NEWS_API_KEY=your-newsapi-key
```

---

## Deploy to Cloud Run

```bash
PROJECT=your-gcp-project-id
REGION=asia-south1
IMAGE=$REGION-docker.pkg.dev/$PROJECT/stockcoach-repo/stockcoach:latest

# Build
gcloud builds submit --tag $IMAGE --project=$PROJECT

# Deploy
gcloud run deploy stockcoach \
  --image $IMAGE --region $REGION --platform managed \
  --allow-unauthenticated --memory 2Gi --cpu 2 --timeout 120 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_REGION=$REGION,\
MOCK_AI=false,NEWS_API_KEY=your-key,TOP_GAINERS_COUNT=20" \
  --project=$PROJECT
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | *(required in prod)* | GCP project ID |
| `GOOGLE_CLOUD_REGION` | `asia-south1` | Vertex AI region |
| `VERTEX_AI_MODEL_FLASH` | `gemini-2.5-flash` | Model for all AI calls |
| `NEWS_API_KEY` | `""` | newsapi.org key — skipped if empty |
| `REDIS_URL` | `""` | Redis URL; blank = in-memory |
| `GAINERS_LIST_TTL` | `7200` | Gainer list cache TTL seconds (market hours) |
| `ANALYSIS_TTL` | `86400` | Per-ticker analysis cache TTL (24h) |
| `MOCK_AI` | `false` | Skip all Gemini calls, use hardcoded responses |
| `TOP_GAINERS_COUNT` | `20` | Gainers per market |
| `PREWARM_CONCURRENCY` | `3` | Max parallel Gemini prewarm calls |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated allowed origins |

---

## Running tests

```bash
cd backend
poetry run pytest -v --override-ini="addopts="
```

All 254 tests use `MOCK_AI=true` and mock HTTP — no GCP credentials needed.

---

## Project structure

```
stock-coach/
├── Dockerfile                     # Multi-stage: node build → python runtime
├── .env.example
│
├── backend/
│   ├── main.py                    # FastAPI app, SPA serving, health endpoint
│   ├── agents/
│   │   ├── gainer_analyst.py      # Combined analysis+prediction (1 Gemini call)
│   │   ├── market_analyst.py      # Market narrative agent
│   │   ├── predictor.py           # Standalone predictor (reference)
│   │   └── thesis_analyst.py      # Conviction thesis builder
│   ├── api/
│   │   ├── deps.py                # Singleton service dependencies
│   │   └── routes/
│   │       ├── gainers.py         # /api/gainers/* — list, detail, analyse, history
│   │       └── conviction.py      # /api/conviction/analyse
│   ├── core/
│   │   ├── auth.py                # ADC token cache (avoids per-call auth refresh)
│   │   ├── config.py              # Pydantic settings (all env vars)
│   │   ├── exceptions.py
│   │   └── logging.py             # structlog JSON logging
│   ├── models/schemas.py          # All Pydantic models + quality score function
│   ├── services/
│   │   ├── cache.py               # Redis / in-memory cache abstraction
│   │   ├── market_data.py         # Gemini + Search grounding for gainers list
│   │   ├── news_fetcher.py        # NewsAPI.org wrapper
│   │   └── technicals.py          # RSI-14, MACD, SMA-20/50, volume, momentum
│   └── tests/                     # 254 tests (pytest)
│
└── frontend/
    └── src/
        ├── components/
        │   ├── AnalysisPanel.tsx   # Full stock view: fundamentals + chart + technicals + AI
        │   ├── CandleChart.tsx     # lightweight-charts v5: candles + volume + SMA overlays
        │   ├── GainerCard.tsx      # Card with tier badge + conviction match tag
        │   ├── Header.tsx          # PULSE / CONVICTION tab navigation
        │   ├── MarketNarrative.tsx # AI market pulse banner
        │   ├── MarketToggle.tsx    # US / India toggle
        │   └── SearchBar.tsx       # Ticker search
        ├── hooks/useGainers.ts     # React Query hooks
        ├── pages/
        │   ├── Dashboard.tsx       # PULSE layout
        │   └── ConvictionPage.tsx  # CONVICTION: belief input + thesis results + localStorage
        └── types/index.ts          # TypeScript types (mirrors backend schemas)
```

---

## Architecture decisions

### Why one Gemini call per stock instead of two?

Originally two sequential calls (analyst + predictor, ~25–35s total). Merged into `GainerAnalystAgent.analyse_full()` — one call returns both analysis and prediction as a single JSON object (~12–18s cold). The Vertex AI round-trip is the dominant latency, not token count.

### Why not use the Vertex AI Python SDK?

`google-cloud-aiplatform` is ~600 MB and adds 10–15 minutes to Docker builds. The app uses `google-auth` + raw `httpx` calls — same API, millisecond import, tiny image size.

### Why pure-Python technicals instead of `ta` or `pandas-ta`?

No additional dependency. RSI-14, MACD, SMA-20/50, volume ratio, and momentum are each ~10 lines of Python. The real benefit: the same computed values are formatted as plain text and injected into the Gemini prompt, so the AI prediction is grounded in the exact same signals displayed in the Technical Signals panel.

### Why can't JSON mode + Google Search grounding be combined?

Vertex AI rejects requests that combine `responseMimeType: "application/json"` with `googleSearch` grounding. The market-data service uses prompt-embedded format instructions and a multi-strategy JSON extractor instead.

### Cache strategy

| Data | TTL | Rationale |
|---|---|---|
| Gainers list (1d) | 2h market hrs / 24h off-hrs | Intraday moves matter; silent overnight |
| Gainers list (1w, 1m) | Should be ≥ 12h | Weekly/monthly movers barely change intraday |
| Per-ticker analysis | 24h | Catalyst doesn't change mid-day; expensive to regenerate |
| Conviction thesis | 24h | Structural thesis; keyed on SHA-256(market:belief) |
| Price history (OHLCV) | 30min | Charts tolerate mild staleness |
| Last-known-good (LKG) | 48h – 2 weeks | List never goes blank on Gemini outage |
