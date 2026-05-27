# StockCoach AI — Dev Guide

This is my step-by-step coding guide. Each phase builds on the previous. Every code block here is meant to be understood line-by-line, not just copy-pasted.

---

## Phase 1 — GCP setup and first Gemini call

### Step 1: Install tools on Mac

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.11
brew install python@3.11

# Install Poetry (dependency manager)
curl -sSL https://install.python-poetry.org | python3 -

# Install Google Cloud CLI
brew install --cask google-cloud-sdk

# Verify
python3.11 --version
poetry --version
gcloud --version
```

### Step 2: GCP project setup

```bash
# Login to GCP
gcloud auth login

# Create new project
gcloud projects create stockcoach-ai-[YOUR-INITIALS] --name="StockCoach AI"

# Set as active project
gcloud config set project stockcoach-ai-[YOUR-INITIALS]

# Enable required APIs
gcloud services enable aiplatform.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable pubsub.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable cloudscheduler.googleapis.com

# Create application default credentials (so Python can call GCP)
gcloud auth application-default login
```

### Step 3: Create Python project

```bash
mkdir stockcoach && cd stockcoach
poetry init --name stockcoach --python "^3.11"

# Add core dependencies
poetry add google-cloud-aiplatform
poetry add google-cloud-firestore
poetry add python-dotenv
poetry add pydantic

# Enter the virtual environment
poetry shell
```

### Step 4: Project folder structure

```bash
mkdir -p agents tools models memory prompts
touch agents/__init__.py tools/__init__.py models/__init__.py memory/__init__.py
touch main.py .env
```

### Step 5: Environment variables

Create `.env` file — never commit this to Git:
```
GOOGLE_CLOUD_PROJECT=stockcoach-ai-[YOUR-INITIALS]
GOOGLE_CLOUD_REGION=asia-south1
```

### Step 6: First Gemini call — understand every line

Create `main.py`:

```python
# Import the Vertex AI SDK
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Initialise Vertex AI with your project and region
# This tells the SDK where to send API calls
vertexai.init(
    project=os.getenv("GOOGLE_CLOUD_PROJECT"),
    location=os.getenv("GOOGLE_CLOUD_REGION")
)

# Load the Gemini 1.5 Flash model
# Flash = cheaper + faster, good for simple tasks
# Pro = more capable, use for complex analysis
model = GenerativeModel("gemini-1.5-flash-002")

# Define a system prompt — this is the model's "job description"
# It persists for the whole conversation
SYSTEM_PROMPT = """You are a financial analysis assistant specialising in Indian equities.
You explain your reasoning in plain English so a beginner investor can learn from it.
Never recommend buying or selling — only describe what the data shows.
Always cite the specific data point behind every observation."""

# The actual call
def analyse_stock_simple(ticker: str, pe_ratio: float, sector_pe: float) -> str:
    # Construct the user message
    user_message = f"""
    Analyse this Indian stock for a beginner investor:
    
    Ticker: {ticker}
    PE Ratio: {pe_ratio}
    Sector Average PE: {sector_pe}
    
    Explain in 3 sentences what this PE ratio means and what signal it gives.
    """
    
    # Send to Gemini
    # The model parameter passes our system instructions
    response = model.generate_content(
        contents=user_message,
        # System instruction sets the model's behaviour
        generation_config={
            "temperature": 0.1,    # Low = consistent, not creative
            "max_output_tokens": 300,  # Limit response length = control cost
        }
    )
    
    # response.text contains the model's reply as a string
    return response.text

# Run it
if __name__ == "__main__":
    result = analyse_stock_simple(
        ticker="TATAMOTORS",
        pe_ratio=7.2,
        sector_pe=12.0
    )
    print(result)
```

Run it:
```bash
python main.py
```

What to observe:
- The model explains the PE ratio in plain English
- Try changing temperature to 0.9 and run again — notice how the answer style changes
- Try changing the system prompt — see how it changes the model's behaviour

### Step 7: Store result in Firestore

```python
# Add to main.py
from google.cloud import firestore
from datetime import datetime

# Initialise Firestore client
db = firestore.Client()

def save_analysis(ticker: str, analysis_text: str):
    # Create a new document in the "analyses" collection
    # Firestore is a NoSQL document database — no schema required
    doc_ref = db.collection("analyses").document()
    
    doc_ref.set({
        "ticker": ticker,
        "analysis": analysis_text,
        "created_at": datetime.utcnow(),
        "phase": "1_basic_call"  # Tagging for our own tracking
    })
    
    print(f"Saved to Firestore with ID: {doc_ref.id}")
    return doc_ref.id
```

**What you learned in Phase 1:**
- How Vertex AI SDK initialises and authenticates
- What system prompt vs user message means in code
- How temperature changes output behaviour
- How Firestore stores unstructured data

---

## Phase 2 — First Agent (ReAct loop)

### Step 1: Add LangGraph

```bash
poetry add langgraph langchain-google-vertexai
```

### Step 2: Define your tools — plain Python functions

Create `tools/nse_tools.py`:

```python
# These are the functions the agent can call
# Each function = one tool = one capability
# The docstring is important — the LLM reads it to understand when to use the tool

from pydantic import BaseModel
from typing import Optional
import yfinance as yf  # Free price + basic data

def get_pe_ratio(ticker: str) -> dict:
    """
    Fetch the current PE ratio for an Indian stock listed on NSE.
    Use this when you need the price-to-earnings ratio for fundamental analysis.
    
    Args:
        ticker: NSE ticker symbol e.g. TATAMOTORS, INFY, HDFCBANK
    
    Returns:
        dict with pe_ratio and sector_average_pe
    """
    # Add .NS for NSE stocks in Yahoo Finance
    stock = yf.Ticker(f"{ticker}.NS")
    info = stock.info
    
    pe = info.get("trailingPE", None)
    
    # Sector PE averages (approximate — you will refine these)
    sector_averages = {
        "auto": 15.0,
        "it": 25.0,
        "banking": 12.0,
        "pharma": 20.0,
        "fmcg": 50.0,
        "default": 20.0
    }
    
    sector = info.get("sector", "default").lower()
    sector_pe = sector_averages.get(sector, sector_averages["default"])
    
    return {
        "ticker": ticker,
        "pe_ratio": round(pe, 2) if pe else None,
        "sector_average_pe": sector_pe,
        "signal": "undervalued" if pe and pe < sector_pe else "overvalued"
    }


def get_revenue_growth(ticker: str) -> dict:
    """
    Fetch the year-over-year revenue growth for an Indian stock.
    Use this to assess whether a company is growing its business.
    
    Args:
        ticker: NSE ticker symbol
    
    Returns:
        dict with revenue_growth_pct as a percentage
    """
    stock = yf.Ticker(f"{ticker}.NS")
    financials = stock.financials
    
    if financials.empty or len(financials.columns) < 2:
        return {"ticker": ticker, "revenue_growth_pct": None, "error": "Insufficient data"}
    
    # Revenue is typically the first row in financials
    recent = financials.iloc[0, 0]   # Most recent year
    previous = financials.iloc[0, 1]  # Year before
    
    growth = ((recent - previous) / abs(previous)) * 100
    
    return {
        "ticker": ticker,
        "revenue_growth_pct": round(growth, 2),
        "signal": "growing" if growth > 10 else "slow" if growth > 0 else "declining"
    }
```

### Step 3: Build the ReAct agent

Create `agents/fundamentals.py`:

```python
from langgraph.graph import StateGraph, END
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from typing import TypedDict, Annotated, Sequence
import operator
import json

from tools.nse_tools import get_pe_ratio, get_revenue_growth

# State is what flows through the agent graph
# Every node reads from state and writes back to state
class AgentState(TypedDict):
    messages: Annotated[Sequence, operator.add]  # Conversation history
    ticker: str
    final_analysis: str

# Initialise the model WITH tools bound to it
# This tells Gemini about the tools it can call
llm = ChatVertexAI(model="gemini-1.5-pro-002", temperature=0.1)
tools = [get_pe_ratio, get_revenue_growth]
llm_with_tools = llm.bind_tools(tools)

SYSTEM_PROMPT = """You are a fundamental analysis agent for Indian stocks.
You have tools to fetch PE ratio and revenue growth data.
Use them to analyse the given stock, then provide a structured assessment.
Think step by step: first get PE ratio, then revenue growth, then synthesise."""

# Node 1: Agent reasoning — decides whether to call a tool or finish
def agent_node(state: AgentState):
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

# Node 2: Tool execution — actually calls the function the agent requested
def tool_node(state: AgentState):
    last_message = state["messages"][-1]
    tool_results = []
    
    for tool_call in last_message.tool_calls:
        # Look up which function to call
        tool_map = {
            "get_pe_ratio": get_pe_ratio,
            "get_revenue_growth": get_revenue_growth
        }
        func = tool_map[tool_call["name"]]
        
        # Call it with the arguments the model specified
        result = func(**tool_call["args"])
        
        # Package result as a ToolMessage so the model can read it
        tool_results.append(
            ToolMessage(
                content=json.dumps(result),
                tool_call_id=tool_call["id"]
            )
        )
    
    return {"messages": tool_results}

# Router: after agent node, should we call tools or are we done?
def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    
    # If the last message has tool_calls, the agent wants to use a tool
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    
    # Otherwise the agent is done — it produced a final answer
    return END

# Build the graph
workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")  # After tools, go back to agent to reason

app = workflow.compile()

# Run the agent
def run_fundamentals_agent(ticker: str) -> str:
    initial_state = {
        "messages": [HumanMessage(content=f"Analyse the fundamentals of {ticker}")],
        "ticker": ticker,
        "final_analysis": ""
    }
    
    result = app.invoke(initial_state)
    
    # The last message is the agent's final response
    return result["messages"][-1].content
```

### Step 4: Add Pydantic output validation

Create `models/prediction.py`:

```python
from pydantic import BaseModel, field_validator
from typing import Literal, Optional
from datetime import datetime

class FundamentalsOutput(BaseModel):
    ticker: str
    pe_ratio: Optional[float]
    pe_signal: Literal["undervalued", "fairly_valued", "overvalued"]
    revenue_growth_pct: Optional[float]
    growth_signal: Literal["growing", "slow", "declining"]
    overall_signal: Literal["strong", "moderate", "weak"]
    plain_english_summary: str  # For the learning dashboard
    
    @field_validator("plain_english_summary")
    @classmethod
    def summary_must_be_educational(cls, v):
        # Ensure summary is long enough to be educational
        if len(v) < 50:
            raise ValueError("Summary must be at least 50 characters to be educational")
        return v
    
    @field_validator("pe_ratio")
    @classmethod
    def pe_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("PE ratio must be positive")
        return v
```

**What you learned in Phase 2:**
- How to define Python functions as agent tools (docstrings matter!)
- The ReAct cycle in LangGraph: agent → tools → agent → END
- The difference between tool_calls (model intent) and actual function execution
- How Pydantic validates structured outputs

---

## Phase 3 — Multi-Agent System

### Step 1: Add Pub/Sub

```bash
poetry add google-cloud-pubsub
```

### Step 2: Create Pub/Sub topics

```bash
gcloud pubsub topics create stock.analyse
gcloud pubsub topics create stock.result
gcloud pubsub subscriptions create fundamentals-sub --topic=stock.analyse
gcloud pubsub subscriptions create news-sub --topic=stock.analyse
gcloud pubsub subscriptions create macro-sub --topic=stock.analyse
gcloud pubsub subscriptions create orchestrator-results-sub --topic=stock.result
```

### Step 3: Orchestrator agent

Create `agents/orchestrator.py`:

```python
from google.cloud import pubsub_v1
import json
import time
from datetime import datetime

publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()

PROJECT_ID = "your-project-id"

def publish_analysis_request(ticker: str) -> str:
    """Fan out analysis request to all specialist agents."""
    request_id = f"{ticker}-{int(time.time())}"
    
    message = {
        "request_id": request_id,
        "ticker": ticker,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    topic_path = publisher.topic_path(PROJECT_ID, "stock.analyse")
    
    # Publish — all three specialist agents will receive this
    future = publisher.publish(
        topic_path,
        data=json.dumps(message).encode("utf-8")
    )
    future.result()  # Wait for publish to complete
    
    print(f"Published analysis request {request_id} for {ticker}")
    return request_id

def collect_results(request_id: str, timeout_seconds: int = 60) -> dict:
    """Fan in — wait for results from all three specialist agents."""
    subscription_path = subscriber.subscription_path(
        PROJECT_ID, "orchestrator-results-sub"
    )
    
    results = {}
    expected_agents = {"fundamentals", "news", "macro"}
    start_time = time.time()
    
    while len(results) < 3 and (time.time() - start_time) < timeout_seconds:
        response = subscriber.pull(
            request={"subscription": subscription_path, "max_messages": 10}
        )
        
        for msg in response.received_messages:
            data = json.loads(msg.message.data.decode("utf-8"))
            
            if data.get("request_id") == request_id:
                agent_name = data["agent"]
                results[agent_name] = data["result"]
                
                # Acknowledge the message so it is not redelivered
                subscriber.acknowledge(
                    request={"subscription": subscription_path,
                             "ack_ids": [msg.ack_id]}
                )
    
    # Check for missing results after timeout
    missing = expected_agents - set(results.keys())
    if missing:
        print(f"WARNING: Timed out waiting for {missing}. Using partial results.")
    
    return results
```

---

## Phase 4 — Memory (RAG)

### Step 1: Add vector search dependencies

```bash
poetry add google-cloud-aiplatform[prediction]
```

### Step 2: Embedding + vector store

Create `memory/semantic.py`:

```python
import vertexai
from vertexai.language_models import TextEmbeddingModel
from google.cloud import aiplatform
import json

embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")

def embed_text(text: str) -> list[float]:
    """Convert text to a vector embedding."""
    embeddings = embedding_model.get_embeddings([text])
    return embeddings[0].values

def store_postmortem(prediction_id: str, postmortem_text: str, metadata: dict):
    """
    Store a prediction post-mortem in the vector index.
    Called after the validation agent writes a post-mortem.
    """
    vector = embed_text(postmortem_text)
    
    # Upsert to Vertex AI Vector Search
    # The datapoint ID links back to the Firestore record
    index = aiplatform.MatchingEngineIndex("YOUR_INDEX_RESOURCE_NAME")
    index.upsert_datapoints(datapoints=[
        aiplatform.MatchingEngineIndex.Datapoint(
            datapoint_id=prediction_id,
            feature_vector=vector,
            restricts=[
                aiplatform.MatchingEngineIndex.Datapoint.Restriction(
                    namespace="sector",
                    allow_list=[metadata.get("sector", "unknown")]
                )
            ]
        )
    ])

def retrieve_similar_predictions(query: str, top_k: int = 3) -> list[dict]:
    """
    Find past predictions semantically similar to the current situation.
    Called by the prediction agent before generating a new prediction.
    This is the RAG retrieval step.
    """
    query_vector = embed_text(query)
    
    index_endpoint = aiplatform.MatchingEngineIndexEndpoint(
        "YOUR_INDEX_ENDPOINT_RESOURCE_NAME"
    )
    
    # Find nearest neighbours by cosine similarity
    response = index_endpoint.find_neighbors(
        deployed_index_id="YOUR_DEPLOYED_INDEX_ID",
        queries=[query_vector],
        num_neighbors=top_k
    )
    
    # Fetch the actual post-mortem text from Firestore using returned IDs
    from google.cloud import firestore
    db = firestore.Client()
    
    postmortems = []
    for neighbor in response[0]:
        doc = db.collection("validations").document(neighbor.id).get()
        if doc.exists:
            postmortems.append(doc.to_dict())
    
    return postmortems
```

---

## Phase 5 — Autonomous Loop

### Step 1: Cloud Scheduler setup

```bash
# Create nightly screener job (runs at 11pm IST = 17:30 UTC)
gcloud scheduler jobs create http nightly-screener \
  --location=asia-south1 \
  --schedule="30 17 * * *" \
  --uri="https://YOUR-CLOUD-RUN-URL/trigger-screener" \
  --http-method=POST

# Create monthly validation job (runs on 1st of each month at 8am IST)
gcloud scheduler jobs create http monthly-validation \
  --location=asia-south1 \
  --schedule="30 2 1 * *" \
  --uri="https://YOUR-CLOUD-RUN-URL/trigger-validation" \
  --http-method=POST
```

### Step 2: Add LangFuse tracing

```bash
poetry add langfuse
```

```python
# Add to the top of any agent file
from langfuse.callback import CallbackHandler

# This automatically traces every LLM call and tool use
langfuse_handler = CallbackHandler(
    public_key="YOUR_PUBLIC_KEY",
    secret_key="YOUR_SECRET_KEY"
)

# Pass as callback when invoking the agent
result = app.invoke(
    initial_state,
    config={"callbacks": [langfuse_handler]}
)
# Now go to langfuse.com to see the full trace
```

---

## Phase 6 — Production Hardening

### Step 1: Exponential backoff for API calls

```python
import time
import random
from functools import wraps

def with_retry(max_retries: int = 5, base_delay: float = 1.0):
    """
    Decorator that adds exponential backoff retry logic to any function.
    Use this around any external API call.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise  # Last attempt — give up
                    
                    # Exponential backoff with jitter
                    # Jitter = random small offset to avoid all retries hitting at once
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(f"Attempt {attempt+1} failed: {e}. Retrying in {delay:.1f}s")
                    time.sleep(delay)
        return wrapper
    return decorator

# Usage:
@with_retry(max_retries=5, base_delay=1.0)
def get_pe_ratio(ticker: str) -> dict:
    # This will automatically retry up to 5 times if it fails
    ...
```

### Step 2: Output safety guardrail

```python
FORBIDDEN_PHRASES = [
    "you should buy",
    "buy this stock",
    "sell this stock",
    "i recommend buying",
    "i recommend selling",
    "invest in",
    "guaranteed returns",
]

SEBI_DISCLAIMER = """
---
DISCLAIMER: This analysis is generated by an AI system and is for educational purposes only. 
It is not registered investment advice under SEBI regulations. 
Past analysis performance does not guarantee future accuracy. 
Always consult a SEBI-registered investment advisor before making investment decisions.
"""

def apply_safety_guardrail(text: str) -> str:
    """
    Check model output for forbidden financial advice phrases.
    If found, remove the sentence containing the phrase.
    Always append SEBI disclaimer.
    """
    text_lower = text.lower()
    
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text_lower:
            # Log the violation for monitoring
            print(f"GUARDRAIL TRIGGERED: Found '{phrase}' in output")
            
            # Remove the offending sentence
            sentences = text.split(". ")
            text = ". ".join(
                s for s in sentences 
                if phrase not in s.lower()
            )
    
    # Always append disclaimer
    return text + SEBI_DISCLAIMER
```

---

## Progress tracker

- [ ] Phase 1: GCP setup + first Gemini call
- [ ] Phase 2: Fundamentals Agent (ReAct loop)
- [ ] Phase 3: Multi-agent with Pub/Sub
- [ ] Phase 4: RAG memory (Firestore + Vector Search)
- [ ] Phase 5: Autonomous loop + LangFuse tracing
- [ ] Phase 6: Guardrails + cost monitoring

## Commands I use often

```bash
# Enter project virtual environment
cd stockcoach && poetry shell

# Run the app locally
python main.py

# Deploy to Cloud Run
gcloud run deploy stockcoach-api --source . --region asia-south1

# Check Firestore data
gcloud firestore databases list

# Check Pub/Sub messages
gcloud pubsub subscriptions pull orchestrator-results-sub --limit=5

# View Cloud Run logs
gcloud run services logs read stockcoach-api --region asia-south1
```
