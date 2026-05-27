# StockCoach

AI-powered stock analysis app. Shows today's top US and India gainers, explains *why* they moved, and gives a 30-day outlook — all in plain English.

Built with **FastAPI + React**, deployed on **Google Cloud Run**.

---

## What it does

| Feature | Detail |
|---|---|
| Top gainers | Real-time US (NYSE/NASDAQ) and India (NSE) top movers via Gemini + Google Search grounding |
| AI market narrative | One-paragraph summary of what's driving the market today |
| Stock analysis | Why it gained · key catalysts · sustainability assessment |
| 30-day outlook | Predicted move % · tailwinds · risks · valuation signal |
| Related beneficiaries | Other tickers likely to follow the same catalyst |
| Comparison mode | Search any ticker — AI compares it against today's top gainers |
| Quality scores | 0–10 rule-based score (price, volume, change%, ticker length) |
| Search | Analyse any ticker, not just the gainer list |

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Backend | Python 3.11 + FastAPI + Pydantic v2 |
| AI | Vertex AI Gemini 2.5 Flash (direct REST, no SDK) |
| Market data | Gemini + Google Search grounding (real-time) |
| Fundamentals | yfinance |
| News | NewsAPI.org |
| Cache | In-memory (dev) / Redis (prod) |
| Deployment | Docker + Google Cloud Run |

---

## Local setup

### Prerequisites

- **Python 3.11+** and **Poetry** (`pip install poetry`)
- **Node.js 20+** and **npm**
- A code editor (VS Code recommended)

> **No GCP account needed for local dev** — set `MOCK_AI=true` and the app runs entirely locally with fake AI responses.

### 1 — Clone and install

```bash
git clone https://github.com/merchantlens-alt/stock-coach.git
cd stock-coach

# Install backend dependencies
cd backend
poetry install
cd ..

# Install frontend dependencies
cd frontend
npm install
cd ..
```

### 2 — Configure environment

```bash
cp .env.example backend/.env
```

Open `backend/.env` and set at minimum:

```env
MOCK_AI=true          # Skip GCP entirely — AI returns hardcoded responses
NEWS_API_KEY=         # Leave empty — news is skipped when key is missing
REDIS_URL=            # Leave empty — uses fast in-memory cache
```

### 3 — Run locally

Open **two terminals**:

**Terminal 1 — backend:**
```bash
cd backend
poetry run uvicorn main:app --reload --port 8080
```

**Terminal 2 — frontend:**
```bash
cd frontend
npm run dev
```

Open http://localhost:5173 — the app loads with mock AI data.

---

## Local setup with real GCP

Use this when you want to test actual Gemini responses locally.

### Prerequisites (additional)

- Google Cloud SDK: https://cloud.google.com/sdk/docs/install
- A GCP project with billing enabled

### 1 — Enable APIs

```bash
gcloud config set project YOUR_PROJECT_ID

gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

### 2 — Authenticate locally

```bash
gcloud auth application-default login
```

This writes credentials to `~/.config/gcloud/application_default_credentials.json`.
The backend uses these automatically via Google ADC.

### 3 — Configure `.env`

```env
MOCK_AI=false
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_REGION=asia-south1
VERTEX_AI_MODEL_FLASH=gemini-2.5-flash
NEWS_API_KEY=your-newsapi-key   # Free tier: newsapi.org
```

### 4 — Run the same way

```bash
# backend
poetry run uvicorn main:app --reload --port 8080

# frontend (separate terminal)
npm run dev
```

---

## Deploy to Google Cloud Run

The entire app (frontend + backend) ships as a single Docker container.

### One-time setup

```bash
PROJECT=your-gcp-project-id
REGION=asia-south1
REPO=stockcoach-repo
SERVICE=stockcoach

# Create Artifact Registry repository
gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT

# Grant Cloud Build permission to push images
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$(gcloud projects describe $PROJECT --format='value(projectNumber)')@cloudbuild.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# Grant the compute service account permission to call Vertex AI
SA="$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/aiplatform.user"
```

### Build and deploy

Run this from the repository root (where `Dockerfile` lives):

```bash
PROJECT=your-gcp-project-id
REGION=asia-south1
REPO=stockcoach-repo
SERVICE=stockcoach
IMAGE=$REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:latest

# Build image using Cloud Build (no local Docker needed)
gcloud builds submit --tag $IMAGE --project=$PROJECT

# Deploy to Cloud Run
gcloud run deploy $SERVICE \
  --image $IMAGE \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 120 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_REGION=$REGION,MOCK_AI=false,NEWS_API_KEY=your-key,TOP_GAINERS_COUNT=20" \
  --project=$PROJECT
```

After deploy, Cloud Run prints the service URL, e.g.:
```
https://stockcoach-<hash>-<region>.run.app
```

### Redeploy after code changes

```bash
gcloud builds submit --tag $IMAGE --project=$PROJECT && \
gcloud run deploy $SERVICE --image $IMAGE --region $REGION --project=$PROJECT
```

---

## Environment variables reference

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | *(required in prod)* | GCP project ID |
| `GOOGLE_CLOUD_REGION` | `asia-south1` | Vertex AI region |
| `VERTEX_AI_MODEL_FLASH` | `gemini-2.5-flash` | Model for analysis + data fetching |
| `VERTEX_AI_MODEL_PRO` | `gemini-2.5-flash` | Model for predictions |
| `NEWS_API_KEY` | `""` | NewsAPI.org key — news silently skipped if empty |
| `REDIS_URL` | `""` | Redis URL; blank = in-memory cache |
| `GAINERS_LIST_TTL` | `1800` | Gainer list cache TTL (seconds) |
| `ANALYSIS_TTL` | `21600` | Per-ticker analysis cache TTL (seconds) |
| `MOCK_AI` | `false` | `true` = skip all Gemini calls, use hardcoded responses |
| `TOP_GAINERS_COUNT` | `20` | Number of gainers to show per market |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated allowed origins |

---

## Running tests

```bash
cd backend
poetry run pytest -v
```

Coverage report is printed automatically. All tests use `MOCK_AI=true` and mock HTTP — no GCP credentials needed.

---

## Project structure

```
stock-coach/
├── Dockerfile              # Multi-stage: node build → python runtime
├── .env.example            # Copy to backend/.env and fill in values
│
├── backend/
│   ├── main.py             # FastAPI app factory, health endpoint, SPA serving
│   ├── agents/
│   │   ├── gainer_analyst.py   # Combined analysis + prediction in one Gemini call
│   │   ├── market_analyst.py   # Market narrative AI agent
│   │   └── predictor.py        # Standalone predictor (kept for reference)
│   ├── api/
│   │   ├── deps.py             # Singleton service dependencies
│   │   └── routes/gainers.py   # /api/gainers routes
│   ├── core/
│   │   ├── auth.py             # Shared ADC token cache (avoids per-call refresh)
│   │   ├── config.py           # Pydantic settings
│   │   ├── exceptions.py       # Custom HTTP exceptions
│   │   └── logging.py          # structlog setup
│   ├── models/schemas.py       # All Pydantic models + quality score function
│   ├── services/
│   │   ├── cache.py            # Redis / in-memory cache backends
│   │   ├── market_data.py      # Gemini + Google Search grounding for gainers
│   │   └── news_fetcher.py     # NewsAPI.org wrapper
│   └── tests/                  # pytest test suite
│
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── AnalysisPanel.tsx   # Full analysis view (analysis + prediction)
    │   │   ├── GainerCard.tsx      # Card with quality badge
    │   │   ├── MarketNarrative.tsx # AI market pulse banner
    │   │   ├── MarketToggle.tsx    # US / India toggle
    │   │   └── SearchBar.tsx       # Ticker search input
    │   ├── hooks/useGainers.ts     # React Query hooks
    │   ├── pages/Dashboard.tsx     # Main layout
    │   └── types/index.ts          # TypeScript types (mirrors backend schemas)
    └── vite.config.ts
```

---

## Architecture notes

### Why one Gemini call instead of two?

Originally the app made two sequential Gemini calls per stock detail (analyst then predictor, ~20-30 s total). These are now merged into a single call in `GainerAnalystAgent.analyse_full()` that returns both the analysis and prediction in one JSON response (~12-18 s). The Vertex AI round-trip is the dominant cost, not token count.

### Why not use the Vertex AI SDK?

The `google-cloud-aiplatform` package is ~600 MB and adds 10-15 minutes to Docker build times. The app uses `google-auth` + raw `httpx` calls instead — same API surface, millisecond import, tiny image.

### Why can't I use JSON mode with Google Search grounding?

Vertex AI rejects requests that combine `responseMimeType: "application/json"` (controlled generation) with `googleSearch` grounding. The market-data service embeds format instructions in the prompt instead and uses a robust multi-strategy JSON extractor (`_extract_json_list`).

### Cache strategy

- Gainer list: 30-minute TTL — fresh enough for intraday moves
- Per-ticker analysis: 6-hour TTL — expensive AI call, catalyst doesn't change mid-day
- In-memory cache is fine for a single Cloud Run instance; swap for Redis if you scale to multiple instances
