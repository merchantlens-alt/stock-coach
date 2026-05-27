# StockCoach AI — System Architecture

## What we are building

An AI-powered stock analysis and learning application that:
- Automatically discovers Indian stocks worth analysing (NSE/BSE universe, not just Nifty 500)
- Analyses company fundamentals (PE, ROE, debt, revenue growth, promoter holding)
- Monitors company news AND geopolitical/macro signals (RBI, oil, USD/INR, sector policy)
- Makes 1-month predictions with plain-English reasoning so I can learn why
- Validates its own predictions after 30 days and improves from mistakes automatically
- Teaches me fundamental analysis through every prediction it makes

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| AI model | Vertex AI Gemini 1.5 Pro / Flash | GCP credits, strong reasoning, function calling |
| Embeddings | text-embedding-gecko (Vertex AI) | For RAG memory |
| Vector store | Vertex AI Vector Search | Semantic memory for past predictions |
| Database | Firestore | Episodic memory, prediction logs, user progress |
| Backend | Python 3.11 + FastAPI | Cloud Run deployment |
| Agents | LangGraph | Agent orchestration and state management |
| Message bus | Google Cloud Pub/Sub | Async agent communication |
| Scheduler | Cloud Scheduler | Nightly screener, monthly validation |
| Tracing | LangFuse | Observability across all agents |
| Frontend | React (later phase) | Dashboard and learning UI |
| Data APIs | NSE Python lib, Screener.in, Yahoo Finance | Fundamentals and price data |
| News | Google Search grounding + NewsAPI | Company and geopolitical news |

## GCP project structure

```
stockcoach-ai/                    ← GCP Project
├── Cloud Run services/
│   ├── orchestrator-agent        ← Main coordinator
│   ├── screener-agent            ← Stock discovery
│   ├── fundamentals-agent        ← PE, ROE, debt analysis
│   ├── news-agent                ← News sentiment + geopolitical
│   ├── macro-agent               ← RBI, oil, FX signals
│   └── validation-agent          ← Post-prediction scoring
├── Firestore collections/
│   ├── predictions               ← Every prediction with full reasoning
│   ├── validations               ← Outcome vs prediction records
│   ├── stocks                    ← Stock universe cache
│   └── user_progress             ← Learning log, quiz scores
├── Vertex AI Vector Search/
│   └── prediction-postmortems    ← Semantic memory index
├── Cloud Pub/Sub topics/
│   ├── stock.analyse             ← Trigger analysis
│   ├── stock.result              ← Agent results
│   └── stock.validate            ← Trigger validation
└── Cloud Scheduler jobs/
    ├── nightly-screener          ← 11pm daily
    └── monthly-validation        ← 1st of each month
```

## Python project structure (local)

```
stockcoach/
├── pyproject.toml                ← Poetry dependency management
├── .env                          ← GCP credentials, API keys (never commit)
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py           ← LangGraph orchestration
│   ├── screener.py               ← Stock discovery agent
│   ├── fundamentals.py           ← Fundamentals analysis agent
│   ├── news.py                   ← News + sentiment agent
│   ├── macro.py                  ← Macro signals agent
│   └── validation.py             ← Self-evaluation agent
├── tools/
│   ├── __init__.py
│   ├── nse_tools.py              ← NSE data fetching functions
│   ├── news_tools.py             ← News fetching functions
│   └── firestore_tools.py        ← Database read/write functions
├── models/
│   ├── __init__.py
│   ├── prediction.py             ← Pydantic output schemas
│   └── fundamentals.py           ← Pydantic data schemas
├── memory/
│   ├── __init__.py
│   ├── episodic.py               ← Firestore read/write
│   └── semantic.py               ← Vector search + embeddings
├── prompts/
│   ├── fundamentals_system.txt   ← System prompts stored as files
│   ├── news_system.txt
│   └── synthesis_system.txt
└── main.py                       ← FastAPI app entry point
```

## Agent responsibilities

### Screener Agent
- Runs nightly via Cloud Scheduler
- Filters NSE universe (all ~2000 stocks) by:
  - PE ratio below sector average
  - Promoter holding above 40%
  - Revenue growth above 10% YoY
  - Debt/equity below 2.0
  - Minimum daily trading volume ₹5 crore
- Expands universe dynamically when news agent detects sector themes (e.g. "PLI scheme for electronics" → search all electronics manufacturers)
- Outputs shortlist of 5–15 stocks for deep analysis
- Requires human approval before deep analysis runs (HITL)

### Fundamentals Agent (ReAct loop)
- Input: approved stock ticker
- Tools: get_pe_ratio, get_roe, get_debt_equity, get_revenue_growth, get_promoter_holding, get_sector_averages
- Compares each metric against sector average
- Outputs structured JSON with metric values, sector benchmarks, and plain-English interpretation of each
- Uses CoT: reasons through each metric before synthesising

### News Agent
- Fetches company-specific news (last 30 days): earnings calls, management changes, new contracts, promoter buy/sell, regulatory actions
- Fetches geopolitical/macro news relevant to the stock's sector: RBI policy, oil price for auto/aviation, USD/INR for IT exporters, government policy for defence/infra
- Outputs sentiment (positive/negative/neutral) with 3 key events as bullet points

### Macro Agent
- Monitors: RBI repo rate and stance, crude oil price trend, USD/INR rate, Nifty 50 trend, FII/DII flow data
- Maps macro signals to sector impact: e.g. "rate hike → negative for real estate and auto loans"
- Outputs 2–3 macro headwinds or tailwinds relevant to the stock's sector

### Orchestrator Agent (LangGraph)
- Receives approved ticker from screener
- Fans out to Fundamentals, News, and Macro agents in parallel via Pub/Sub
- Waits for all three results (timeout: 60 seconds per agent)
- Calls Gemini synthesis prompt with all three outputs
- Retrieves top 3 semantically similar past predictions from vector store (RAG)
- Generates: prediction (% upside/downside, 1 month), confidence score, plain-English reasoning (3–5 sentences for learning), key risk factors
- Writes full prediction to Firestore
- Sends prediction to user dashboard

### Validation Agent (runs monthly)
- Fetches all predictions from Firestore where prediction_date is 30+ days ago and not yet validated
- Fetches actual price outcome for each
- Computes: error magnitude, directional accuracy (did it call direction correctly?), which signals were accurate
- Writes structured post-mortem to Firestore
- Embeds post-mortem into Vertex AI Vector Search for RAG retrieval
- Updates prediction record with validation_score

## Data models (Pydantic)

```python
class FundamentalsOutput(BaseModel):
    ticker: str
    pe_ratio: float
    pe_sector_avg: float
    pe_signal: Literal["undervalued", "fairly_valued", "overvalued"]
    roe: float
    roe_signal: Literal["strong", "average", "weak"]
    debt_equity: float
    debt_signal: Literal["low", "moderate", "high"]
    revenue_growth_yoy: float
    promoter_holding_pct: float
    overall_fundamental_signal: Literal["strong", "moderate", "weak"]
    plain_english_summary: str  # 2–3 sentences for learning dashboard

class PredictionRecord(BaseModel):
    id: str
    ticker: str
    prediction_date: datetime
    predicted_upside_pct: float
    confidence_score: float  # 0.0 to 1.0
    reasoning: str  # Plain English for learning
    key_risks: list[str]
    fundamentals: FundamentalsOutput
    news_sentiment: Literal["positive", "negative", "neutral"]
    news_key_events: list[str]
    macro_signals: list[str]
    validated: bool = False
    actual_outcome_pct: Optional[float] = None
    validation_score: Optional[float] = None
```

## Memory architecture

```
Short-term memory (in-context):
  └── Last 5 predictions for this ticker passed as conversation history

Episodic memory (Firestore):
  └── Every prediction + validation record, append-only, queryable by ticker/date/sector

Semantic memory (Vertex AI Vector Search):
  └── Post-mortem embeddings indexed by:
      - Sector + fundamental pattern (e.g. "high debt auto stock rate hike environment")
      - Retrieval at prediction time gives agent lessons from similar past situations
```

## Cost estimates (GCP credits)

| Component | Monthly estimate | Notes |
|---|---|---|
| Vertex AI Gemini Flash (screener) | ~₹200 | 500 stocks × 30 days = 15,000 calls |
| Vertex AI Gemini Pro (deep analysis) | ~₹800 | 10 stocks/day × 30 days |
| Vertex AI Vector Search | ~₹500 | Vector index + queries |
| Firestore | ~₹100 | Read/write volume |
| Cloud Run | ~₹200 | Per-request billing |
| Pub/Sub | ~₹50 | Message volume |
| **Total** | **~₹1,850/month** | Well within ₹1 lakh credit budget |

## Key design decisions

1. **Fundamentals-first, technical optional** — The core analysis is fundamental. Candlestick/technical analysis may be added in a later phase but is not required to start.

2. **Stock universe** — Start with NSE 500 for reliability. Screener agent can search broader NSE universe (2000+ stocks) triggered by news signals. Filter by minimum trading volume to stay in data-rich zone.

3. **Human-in-the-loop at two points** — Screener shortlist approval (before deep analysis), and prediction review before logging as official.

4. **Self-improvement via RAG, not fine-tuning** — Post-mortems embedded in vector store. No model weight updates needed. Continuous, automatic, cost-free improvement.

5. **Plain-English reasoning is mandatory** — Every prediction must include a 3–5 sentence explanation written for a beginner investor. This is the learning mechanism.
