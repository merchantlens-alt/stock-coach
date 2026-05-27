# StockCoach AI — Learning Roadmap

This document tracks my progress learning agentic system development through the StockCoach AI project. I am building an AI-powered stock analysis and learning app on GCP using Vertex AI Gemini.

---

## My learning goal

I want to become an investor who understands fundamental analysis, AND learn agentic AI system development at the same time — using one real project. I am a beginner at both investing and AI engineering. I learn better through practical examples and visuals, not theory.

---

## Phase 1 — Foundations (Week 1–2)

**What I build:** GCP project setup, first Vertex AI Gemini call, connect NSE fundamentals API, store results in Firestore.

### Concepts to learn
- **LLM** — Large Language Model. A model trained on vast text that generates human-like responses.
- **Prompt engineering** — The skill of writing instructions that reliably get the output you want from an LLM.
- **Context window** — The maximum amount of text (input + output) an LLM can process in one call. Like short-term memory.
- **System prompt** — Instructions given to the model before the conversation begins. Defines role, behaviour, constraints, output format. Invisible to end user. Persists for the whole session.
- **Temperature** — Controls randomness of output. 0 = deterministic/consistent. 1 = creative/varied. Use 0 for financial analysis.
- **Token** — The basic unit LLMs process. Roughly 0.75 words. Billing is per token.
- **Grounding** — Connecting LLM output to a verifiable external source of truth instead of relying on training memory.
- **Zero-shot vs few-shot** — Zero-shot: task with no examples. Few-shot: task with 1–5 worked examples included in the prompt.

### Interview Q&As

**Q: What is a system prompt?**
Opening: A system prompt is a set of instructions given to an LLM before the conversation begins — it defines the model's role, behaviour, constraints, and output format. Unlike a user message, the system prompt persists across the entire session and is invisible to the end user. Think of it as the job description you hand the model before it starts work.
Example: In StockCoach, the Fundamentals Agent's system prompt says: "You are a financial analysis assistant specialising in Indian equities. Always respond in structured JSON. Never recommend buying or selling — only describe what the data shows. Cite the specific data point behind every claim. If data is missing, say so explicitly rather than guessing."
Depth: System prompt design is one of the highest-leverage skills in production LLM systems. A vague system prompt causes inconsistent outputs, hallucinations, and unsafe behaviour. Senior engineers own the system prompt as carefully as they own the codebase.
Closer: "The system prompt is where you encode your product's intelligence — get it wrong and no amount of runtime prompt engineering fixes it."

**Q: What is temperature in LLMs?**
Opening: Temperature controls how random or deterministic the model's output is. Range 0–1. At 0, the model always picks the highest-probability token — consistent and predictable. At 1, it samples broadly — varied and creative.
Example: Financial analysis agents need temperature near 0. Consistent, reproducible reasoning about a PE ratio is required — not creative interpretation. The learning coach explaining concepts can use 0.3–0.5 for a more natural tone.
Depth: Temperature does not make the model smarter — it only changes sampling behaviour. A high temperature on a weak model gives weak answers, just more varied ones. Clarifying this distinction stands out in interviews.
Closer: "Temperature controls confidence in word choice, not quality of reasoning — for factual structured tasks always push it toward 0."

**Q: Difference between zero-shot and few-shot?**
Opening: Zero-shot — task with no examples, just instructions. Few-shot — 1 to 5 worked examples of input + expected output included in the prompt before the real task.
Example: Few-shot the Fundamentals Agent with 2 example analyses — showing exactly which fields to populate, how to express uncertainty, how to explain ratios — teaches the format far better than describing it in words.
Depth: One-shot is exactly one example. Chain-of-thought few-shot includes explicit reasoning steps in each example, not just input-output pairs. Most powerful prompting technique for complex analytical tasks.
Closer: "Zero-shot tests what the model knows. Few-shot teaches it what you want. For production systems with consistent output requirements, few-shot almost always wins."

**Q: What is grounding?**
Opening: Grounding connects an LLM's response to a specific verifiable source of truth rather than letting it answer from training memory. Without grounding, the model might hallucinate or use outdated facts. With grounding, you supply real data at the moment it is needed and the model reasons from that data.
Example: Ask an ungrounded model for Tata Motors' current PE ratio — it hallucinates or says it doesn't know. Ground it by fetching the actual PE from an API and injecting it into the prompt — now it gives an accurate current answer. The model's job shifts from remembering facts to reasoning about facts you provided.
Depth: Three forms: retrieval grounding (RAG — retrieve documents and inject as context), tool grounding (agent calls a live API mid-reasoning), search grounding (Vertex AI lets the model query Google Search in real time). StockCoach uses all three.
Closer: "Grounding is how you turn a confident guesser into a reasoner working from real evidence — the single most important pattern for making LLMs production-safe."

---

## Phase 2 — First Agent (Week 3–4)

**What I build:** Fundamentals Agent as a ReAct loop — reason, call a tool, observe result, reason again, produce structured output.

### Concepts to learn
- **ReAct pattern** — Reasoning + Acting. Agent alternates Thought → Action → Observation until it has enough to answer.
- **Tool use / function calling** — LLM outputs a structured JSON intent to call an external function. Runtime calls the function and feeds result back.
- **Agent loop** — The cycle of reasoning and acting that continues until a stopping condition.
- **Observation** — The result returned to the agent after a tool call.
- **Chain of Thought (CoT)** — Prompting the model to show step-by-step reasoning before giving a final answer.
- **Structured output** — Constraining the model to produce valid JSON matching a defined schema.
- **JSON mode** — API feature that guarantees the model only outputs valid JSON.
- **Hallucination guard** — Techniques (Pydantic validation, self-check prompts, retry logic) that catch false outputs before they reach users.

### Interview Q&As

**Q: What is the ReAct pattern?**
Opening: ReAct stands for Reasoning plus Acting. The model alternates between Thought (what do I need?), Action (call a tool), Observation (here is what came back), Thought again — cycling until it has enough to answer.
Example: Agent receives "Analyse Tata Motors." Thought: need PE ratio. Action: call get_pe_ratio("TATAMOTORS"). Observation: PE=7.2, sector avg=12. Thought: undervaluation signal. Now need news. Action: call get_news("Tata Motors", days=30). Observation: EV deal signed. Final answer: structured analysis.
Depth: The model never actually calls the tool — it outputs a structured intent, your runtime calls the function, you feed the result back. Understanding that boundary is critical for debugging. This is the substrate of LangChain agents and LangGraph.
Closer: "ReAct is the heartbeat of every agent — it turns a static LLM call into a dynamic reasoning loop that can interact with the real world."

**Q: What is function calling in LLMs?**
Opening: Function calling is the ability of an LLM to output a structured JSON request for an external function mid-reasoning. Your runtime intercepts it, calls the real function, and feeds the result back. The model never executes code — it only expresses intent.
Example: You define get_pe_ratio(ticker: str) as a tool. The model outputs {"name": "get_pe_ratio", "arguments": {"ticker": "TATAMOTORS"}}. Your Python code runs the actual function, gets 7.2, sends it back. The model continues reasoning with that result.
Depth: Validate the function name against your registered tool list before calling anything — never blindly execute whatever the model outputs. This is the security boundary.
Closer: "Function calling is the bridge between language and action — it lets an LLM reach beyond its context window while keeping a human-controlled execution layer in between."

**Q: How do you prevent hallucinations in structured output?**
Opening: Three layers. Constrain the format via JSON mode or Gemini structured output. Validate every output with Pydantic — define schema as a Python dataclass, parse through it, retry if it fails. Add a self-check in the prompt.
Example: Prompt addition: "After generating your analysis, verify: does every claim cite a specific data point? If any claim lacks a source, remove it or flag it as unverified."
Depth: Pattern is constrain → validate → retry. On failure, send the model a specific error message: "Your output failed validation: the debt_equity field was missing. Please regenerate with all required fields." Models fix this on the first retry.
Closer: "You cannot eliminate hallucinations but you can make them detectable and recoverable — structured output plus Pydantic validation catches most failures before they reach production."

**Q: What is Chain of Thought prompting?**
Opening: CoT instructs the model to show reasoning step by step before giving a final answer. Adding "think step by step" or showing examples with explicit reasoning dramatically improves accuracy on complex tasks.
Example: Without CoT: "Tata Motors outlook: positive." With CoT: "PE 7.2 vs sector 12 — undervaluation signal. ROE 18% — healthy efficiency. Debt/equity 1.8 — elevated risk. Net: fundamentally attractive with a debt risk flag. Prediction: cautiously positive."
Depth: Two forms — zero-shot CoT (just add "think step by step") and few-shot CoT (show 2–3 examples with reasoning written out). Few-shot CoT is stronger for domain-specific tasks where you want reasoning to follow a specific structure.
Closer: "CoT does not just improve answers — it makes them auditable. In a financial context, reading the model's reasoning and spotting a flawed assumption is worth as much as the answer itself."

---

## Phase 3 — Multi-Agent System (Week 5–6)

**What I build:** Orchestrator delegates to News Agent, Fundamentals Agent, Macro Agent via Pub/Sub in parallel. Orchestrator synthesises all outputs.

### Concepts to learn
- **Orchestrator pattern** — Agent that manages other agents: decomposes tasks, delegates, collects results, synthesises.
- **Specialist agents** — Agents with a single focused responsibility.
- **Agent communication** — How agents pass information: message queues, direct API calls, shared state.
- **Task decomposition** — Breaking a complex task into smaller well-defined subtasks with clear inputs and outputs.
- **Parallelism** — Running independent tasks simultaneously to reduce total time.
- **Message bus** — Pub/Sub or Kafka — agents communicate via topics without direct coupling.
- **Event-driven agents** — Agents that activate in response to events (messages, schedules, triggers) rather than direct calls.
- **Fan-out fan-in** — Orchestrator sends work to N parallel agents (fan-out), waits for all results, then synthesises (fan-in).

### Interview Q&As

**Q: What is an orchestrator agent?**
Opening: An orchestrator receives a high-level task, breaks it into subtasks, delegates each to a specialist agent, collects results, and synthesises a final output. It does not do the specialist work itself — its intelligence is in decomposition and synthesis.
Example: StockCoach Orchestrator receives "Analyse INFY." Sends three parallel tasks: News Agent, Fundamentals Agent, Macro Agent. Waits for all three. Calls Gemini to synthesise: "Given these fundamentals, this news sentiment, and these macro signals, what is a reasoned 30-day outlook?"
Depth: Orchestration failure modes: race conditions when one agent is slow, conflicting signals from two agents, cascading failures. Senior answer addresses these — timeouts, default values, explicit conflict-resolution logic in the synthesis prompt.
Closer: "The orchestrator is the conductor, not the musician — its value is coordination and synthesis, and its failure modes are about workflow reliability rather than domain accuracy."

**Q: How do agents communicate in a distributed system?**
Opening: Three patterns. Message queue (Pub/Sub) — async, decoupled, slow agents don't block others. Direct API calls — sync, simple, but tight coupling. Shared state via database — agents read/write to Firestore or Redis.
Example: In StockCoach the right pattern is Pub/Sub. Orchestrator publishes a "stock.analyse" event. Each specialist subscribes, processes independently, publishes result to "stock.result". Orchestrator subscribes to results, waits for all three, triggers synthesis. No agent directly knows about any other.
Depth: If one agent fails to publish its result: set a deadline. If Orchestrator does not receive a result within 30 seconds, retry that agent, use a cached result, or mark the prediction low-confidence. Never let one agent's failure silently poison the whole prediction.
Closer: "Pub/Sub gives you the decoupling that makes multi-agent systems resilient — agents can be deployed, scaled, and fail independently."

**Q: What is task decomposition?**
Opening: Breaking a complex task into smaller well-defined subtasks — each with a clear input, a clear output format, and a single responsibility.
Example: Bad: "Analyse this stock" to one agent. Good: (1) "Fetch fundamentals for TICKER, return structured JSON with PE, ROE, debt, revenue growth." (2) "Summarise news sentiment — return positive/negative/neutral plus 3 key events." (3) "Identify macro signals for SECTOR this week, return 2–3 signals." Each is independently testable.
Depth: Each subtask should be testable with a unit test — fixed input, predictable output, single purpose. If a subtask's output format is vague, synthesis becomes guesswork. Good decomposition is good API design applied to agents.
Closer: "Good decomposition is good API design applied to agents — clear contracts between components is what makes the system debuggable, testable, and improvable."

**Q: When would you use parallel agents vs sequential?**
Opening: Parallel when tasks are independent — neither needs the other's output. Sequential when each step depends on the previous step's output.
Example: Data gathering is parallel — news, fundamentals, macro have no dependency on each other. Synthesis is sequential after all data is ready. Validation is sequential after 30 days.
Depth: The combined pattern is fan-out fan-in. Orchestrator fans out to N parallel agents, waits at a join point for all results, then fans into sequential synthesis. In LangGraph you model this as a parallel branch followed by a join node.
Closer: "The question to ask is always: does task B need task A's output? If yes, sequential. If no, parallel. Getting this right is the difference between a 3-second prediction and a 9-second one."

---

## Phase 4 — Memory (Week 7–8)

**What I build:** In-context memory (last 5 predictions as history), episodic memory in Firestore, semantic memory in Vertex AI Vector Search with RAG retrieval.

### Concepts to learn
- **Short-term memory** — Information held in the active context window. Disappears after the session.
- **Long-term memory** — Persistent storage outside the context window. Firestore or vector DB.
- **Episodic memory** — Memory of specific events tied to a time and place. Every prediction with its date, reasoning, and outcome.
- **Semantic memory** — Generalised knowledge abstracted from events into reusable patterns. "High-debt stocks underperform during rate hikes."
- **RAG (Retrieval Augmented Generation)** — Retrieve relevant documents from external store at query time, inject as context, model reasons from retrieved evidence.
- **Vector embeddings** — Numerical representation of text such that semantically similar texts produce numerically similar vectors.
- **Cosine similarity** — Metric measuring similarity between two vectors by calculating the cosine of the angle between them. 1 = identical, 0 = unrelated, -1 = opposite.
- **In-context learning from experience** — Agent improves by retrieving past lessons into context, not by retraining weights.

### Interview Q&As

**Q: What is RAG and why does it matter?**
Opening: RAG — Retrieval Augmented Generation. Instead of relying on training data, you retrieve relevant documents from an external store at query time, inject them into the prompt, and the model reasons from that retrieved evidence. Solves two fundamental LLM limits: training cutoff and context window size.
Example: StockCoach Prediction Agent uses RAG to retrieve the last 3 times it analysed a high-debt auto stock. Finds post-mortem: "Predicted +8%, actual +2%, overestimated because debt risk materialised faster." Agent now reasons: "I should apply a debt penalty to my current estimate." Without RAG, every prediction starts from scratch.
Depth: Three components: indexer (embeds documents, stores vectors), retriever (embeds query, finds similar vectors), generator (LLM receives retrieved docs + question, produces grounded answer). In Vertex AI: text-embedding-gecko for embeddings, Vertex AI Vector Search as the store.
Closer: "RAG is how you give an LLM a long-term memory that scales beyond its context window — the most important pattern for building AI systems that get better over time."

**Q: Difference between episodic and semantic memory in agents?**
Opening: Episodic memory is memory of specific events tied to time and place. Semantic memory is generalised knowledge abstracted from events into reusable patterns. Both serve different purposes architecturally.
Example: Episodic in Firestore: "On April 14 I predicted Tata Motors +8%, actual was +5.8%, miss due to debt risk." Semantic in vector DB: "High-debt auto stocks underperform when RBI raises rates." Agent uses episodic to check its track record, semantic to apply learned patterns.
Depth: Episodic memory is append-only — never change the past record. Semantic memory evolves — new episodes update the patterns. Common mistake: conflating them and putting everything in one store.
Closer: "Episodic memory is your agent's diary. Semantic memory is its wisdom. You need both — the diary gives traceability, the wisdom gives improvement."

**Q: How do vector embeddings work?**
Opening: A vector embedding represents text as a list of numbers such that semantically similar texts produce numerically similar vectors. "RBI raised interest rates" and "central bank increased borrowing costs" map to nearly identical vectors even though the words differ completely.
Example: You embed "what happened last time we saw a high-debt stock in a rising rate environment?" — produces a 768-dimensional vector. Search the vector DB for nearest stored vectors. Finds a post-mortem from six months ago about Bajaj Finance in a rate hike environment because its meaning is geometrically close.
Depth: text-embedding-gecko in Vertex AI produces 768-dimensional embeddings. Quality of RAG depends heavily on what you embed — structured summaries embed better than full articles because the signal-to-noise ratio is better.
Closer: "Vector embeddings are the translation layer between human language and machine similarity search — they make it possible to find relevant memories using meaning rather than keyword matching."

**Q: What is cosine similarity?**
Opening: Cosine similarity measures how similar two vectors are by calculating the cosine of the angle between them. 1 = identical meaning, 0 = unrelated, -1 = opposite meaning.
Example: You embed "high PE stock with strong promoter holding" and search stored past predictions. A post-mortem about "low PE, strong management, bullish outcome" scores 0.82. One about "debt restructuring, promoter selling" scores 0.21. You retrieve the top 3 highest-scoring and inject into the prompt.
Depth: Why cosine over Euclidean distance: cosine is scale-invariant. A one-sentence note and a three-paragraph analysis can have the same meaning but different vector magnitudes. Cosine ignores magnitude and measures only direction — which maps to semantic similarity.
Closer: "Cosine similarity measures the angle of meaning, not the size of the document — exactly what you want when matching concepts across different text lengths."

---

## Phase 5 — Autonomous Loop (Week 9–10)

**What I build:** Cloud Scheduler triggers nightly screener. After 30 days, Validation Agent scores predictions, writes post-mortems, injects into RAG memory. Next cycle is automatically better.

### Concepts to learn
- **Agentic loop** — Fully automated cycle that runs without human intervention.
- **Self-evaluation** — Agent scoring its own outputs against ground truth.
- **AutoEval (automated evaluation)** — System that scores agent output quality automatically at scale.
- **LLM-as-judge** — Using a second LLM to evaluate the quality of the first LLM's reasoning.
- **Feedback loop** — Mechanism where outputs inform future inputs, creating improvement over time.
- **Observability** — Ability to understand what an agent did, why, and where it went wrong — from logs, traces, and metrics.
- **Distributed tracing** — Following one request across all agents and services to see the full execution chain.
- **Dead-letter queue (DLQ)** — Where failed messages go after maximum retry attempts, for inspection and replay.

### Interview Q&As

**Q: How do you evaluate agent quality automatically?**
Opening: AutoEval scores agent outputs without human review. Three approaches used together: reference-based, LLM-as-judge, and metric-based.
Example: Reference-based: compare predicted price direction/magnitude to actual outcome after 30 days — computable automatically. LLM-as-judge: send prediction + actual outcome to a second model and ask it to score reasoning quality 1–10. Metric-based: directional accuracy, calibration, reasoning coverage (did it address PE, ROE, debt, news, macro?).
Depth: LLM-as-judge with rubrics — define 5 criteria scored 0–2, have the judge apply them consistently. Scales to thousands of evaluations per day. Key risk: judge model bias. Mitigation: use a different model family for the judge than the one generating predictions.
Closer: "AutoEval is what turns a one-time demo into a system that improves — without it you are flying blind, and with it you have a continuous feedback loop that compounds over time."

**Q: What is observability in agentic systems?**
Opening: Observability is the ability to understand what your agent did, why, and where it went wrong — from the outside, using logs, traces, and metrics. In a multi-agent system with 5 agents and 30 tool calls, you need distributed tracing, not just logging.
Example: Without observability: a prediction is wrong and you cannot tell why. With LangSmith/LangFuse: full trace for every prediction — which agent was called, what it received, what it returned, token count, latency. You can pinpoint: "the news agent returned stale data because the API call timed out."
Depth: Three pillars — logs (what happened), traces (full chain of one request across all agents with timing), metrics (aggregate numbers — avg latency, error rate per agent, token cost per run, accuracy rate). In GCP: Cloud Logging, Cloud Trace, Cloud Monitoring, Looker dashboard.
Closer: "Observability is what separates a production system from a prototype — you cannot improve what you cannot measure, and you cannot debug what you cannot see."

**Q: What is a dead-letter queue?**
Opening: A DLQ is where messages go when they fail to be processed after the maximum number of retries. In Pub/Sub, if an agent fails to process a message five times, it does not disappear — it goes to the DLQ for inspection and replay.
Example: Fundamentals Agent crashes on a Monday night screener run. Without DLQ: those stock analysis jobs are silently lost. With DLQ: failed messages accumulate, you get an alert, fix the issue, replay all failed messages — no prediction job is missed.
Depth: DLQs are a foundational reliability pattern. Cloud Pub/Sub supports them natively — set maxDeliveryAttempts on your subscription, configure a dead-letter topic. DLQ is also your debugging treasure chest — messages often reveal bugs you did not know existed: malformed data, edge-case tickers, unexpected API response formats.
Closer: "A dead-letter queue is your safety net for async systems — it guarantees that failure is observable and recoverable rather than silent and permanent."

**Q: How does an agent improve from its own mistakes?**
Opening: The self-improvement loop — the agent stores its reasoning alongside predictions, validates outcomes later, and injects structured lessons from failures into future reasoning context.
Example: Prediction: Tata Motors +8%. Actual: +2%. Validation agent computes miss, identifies cause: debt/equity 1.8 plus rate hike compressed margins. Writes post-mortem: "Overestimated by 6%. Root cause: underweighted debt risk in rising rate environment. Correction: apply 30% discount to upside when debt/equity > 1.5 and rate hike within 45 days." Embeds into vector store. Next time RAG retrieves this lesson.
Depth: This is NOT fine-tuning. Model weights do not change. What changes is the reasoning context — it gets smarter because it has better evidence to reason from. "In-context learning from experience." No GPU time, no redeployment cycle. Continuous and automatic.
Closer: "An agent improves from mistakes not by changing what it knows but by changing what it remembers — structured post-mortems in a vector store are the cheapest and most powerful form of AI self-improvement available today."

---

## Phase 6 — Production Hardening (Week 11–12)

**What I build:** Guardrails (no direct buy/sell advice), retry logic with exponential backoff, cost tracking per run, human-in-the-loop shortlist approval, token budget monitoring.

### Concepts to learn
- **Guardrails** — Constraints that prevent the agent from producing harmful, incorrect, or non-compliant outputs.
- **Human-in-the-loop (HITL)** — Design pattern where a human reviews or approves an agent's decision before a consequential action.
- **Retry / backoff** — On failure, wait and retry. Exponential backoff: wait 1s, 2s, 4s, 8s... up to a max.
- **Rate limiting** — Caps on how many API requests you can make per second/minute/day.
- **Cost-per-run** — Total token cost of one complete prediction pipeline run. A first-class metric.
- **Safety layer** — Post-generation classifier that checks every response before it reaches the user.
- **Content filtering** — Automated detection of harmful, non-compliant, or off-topic outputs.
- **Agent evaluation metrics** — Directional accuracy, calibration, reasoning coverage, latency, cost-per-prediction.

### Interview Q&As

**Q: What is human-in-the-loop and when is it needed?**
Opening: HITL is a design pattern where a human reviews or approves an agent's decision before a consequential action is taken. Not about distrusting AI — about inserting human judgment at the right decision points.
Example: StockCoach HITL at two points: screener surfaces 10 candidates and you approve the shortlist before deep analysis runs (saves cost, keeps you learning). Predictions shown to you with full reasoning before they are logged as official — you can add a note or override.
Depth: When HITL is non-negotiable: (1) high-stakes irreversible actions, (2) low-confidence situations, (3) novel situations outside prior patterns, (4) regulatory requirements. SEBI guidelines around unregistered investment advice make HITL a legal consideration, not just a design preference.
Closer: "HITL is not a limitation on AI capability — it is a design choice about where human judgment adds more value than automation."

**Q: How do you handle rate limits in a multi-agent system?**
Opening: Rate limits are caps on API requests per second/minute. With multiple agents hitting the same API simultaneously, you can breach limits instantly. Four strategies used in combination.
Example: NSE API allows 10 requests/second. Five parallel agents each making 3 calls = 15 in one second. Solution: funnel all NSE calls through a single rate-limited queue. Agents submit requests and wait for results rather than calling the API directly.
Depth: Four strategies: (1) exponential backoff on 429 responses, (2) token bucket — shared counter that refills at the allowed rate, (3) request queue — all calls go through one queue that enforces the rate, (4) caching with TTL — same PE ratio requested by multiple agents within 5 minutes: fetch once, share. Combine (3) and (4) for production.
Closer: "Rate limit handling is table stakes for production multi-agent systems — without it your system works perfectly in testing and breaks on the first real workload."

**Q: What guardrails would you put on a financial AI agent?**
Opening: Strong answer covers four areas — output safety, confidence transparency, data freshness, and legal compliance.
Example: Output guardrails: agent never says "buy this stock" or "sell this stock" — only "the fundamentals suggest X." Safety classifier checks every response before it reaches the user. Confidence thresholds: below 60% confidence, must say "I have limited data — treat this with caution." Data freshness: flag analyses based on earnings data older than 90 days. Legal: every prediction wrapped with SEBI disclaimer — this is not registered investment advice.
Depth: Production pattern is a layered safety stack: system prompt instructs no direct advice, post-generation classifier checks output before delivery, UI layer adds static disclaimer. Each layer catches what the previous might miss. Never rely on a single guardrail.
Closer: "Guardrails are not just about safety — they are about trust. An AI financial tool users trust enough to act on is one that is consistently transparent about uncertainty, freshness, and its own limitations."

**Q: How do you track and control LLM cost in production?**
Opening: LLM costs scale with tokens — every input and output token is billed. Multi-agent systems compound costs. Without active management a nightly screener can cost thousands of rupees per month. With good cost design, under a hundred.
Example: Gemini Flash for screener (simple filtering — cheap model for a cheap task). Gemini Pro only for deep analysis of 10 shortlisted stocks. Compress context — send 3-sentence news summaries, not full articles. Cache fundamentals for 24 hours so 5 agents never fetch the same PE ratio twice in one night.
Depth: Tag every API call with metadata: agent name, task type, stock ticker. Log token counts. Build cost dashboard. Set GCP budget alerts. Cost-per-prediction is a first-class metric — know it as precisely as prediction accuracy.
Closer: "Cost control in LLM systems is just good engineering — right model for the right task, cache aggressively, compress context, instrument everything. Treat token spend like database queries: optimise the hot path, measure everything."

---

## My current phase

**Active:** Phase 1 — setting up GCP and first Gemini call.
**Completed phases:** None yet.
**Last session:** Initial project planning and architecture design.
