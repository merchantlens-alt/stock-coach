# StockCoach AI — Coding Standards

This file is read automatically by Claude Code before every session.
Follow every rule here without being asked.

---

## Project layout

```
backend/           FastAPI app (Python 3.11)
  agents/          Gemini AI agents (one file per feature)
  api/
    routes/        FastAPI routers — one file per domain
    deps.py        Module-level singletons injected via Depends()
  core/            config, auth, logging, exceptions
  models/          Pydantic schemas (schemas.py) + domain models
  services/        Non-AI business logic (cache, market_data, etc.)
  tests/           pytest — class-based, no live AI/network calls
  main.py          create_app() factory

frontend/          React + Vite + TypeScript
  src/
    api/client.ts  Single api object, fetchJSON helper
    components/    Reusable UI pieces
    hooks/         react-query hooks
    pages/         Full-page components
    types/index.ts Single source of truth for all types
```

---

## Python rules

### Every file starts with
```python
from __future__ import annotations
```

### Logging — always structured, never print()
```python
from core.logging import get_logger
log = get_logger(__name__)

log.info("module.event_name", ticker=ticker, market=market)
log.warning("module.something_wrong", error=str(exc))
log.error("module.hard_failure", status=resp.status_code, body=resp.text[:500])
```
Log key: `"<module>.<snake_case_event>"` — no spaces, no capitals.

### Pydantic models
- Use `BaseModel` from `pydantic`, not dataclasses
- `from __future__ import annotations` required for forward refs
- Use `Optional[X]` not `X | None` in model fields (Pydantic v2 compat)
- Enums: inherit `str, Enum` so they serialise to strings

### FastAPI routes
```python
router = APIRouter(tags=["domain"])

@router.get("/path", response_model=MyModel)
async def handler(
    dep: Annotated[DepType, Depends(get_dep)],
) -> MyModel:
    ...
```
- Use `Annotated[T, Depends(...)]` — never `dep: T = Depends(...)`
- Return type annotation required on every route handler
- 204 responses return `None` with `status_code=204`

### Singletons in deps.py
```python
_my_service: MyService | None = None

def get_my_service(settings: Annotated[Settings, Depends(get_settings)]) -> MyService:
    global _my_service
    if _my_service is None:
        _my_service = MyService(settings)
    return _my_service
```
Add `deps._my_service = None` to `reset_singletons` fixture in `tests/conftest.py`.

### Gemini API calls (agents)
- Remove `thinkingConfig` entirely — `thinkingBudget: 0` breaks Gemini 2.5 Flash
- Log non-200 HTTP responses BEFORE raising:
  ```python
  if resp.status_code != 200:
      log.error("agent_name.gemini_http_error", status=resp.status_code, body=resp.text[:500])
  resp.raise_for_status()
  ```
- Use `@retry(stop=stop_after_attempt(N), wait=wait_exponential(...))` from tenacity on `_call_gemini`
- Mock fallback: catch all exceptions at the route level, log `"feature.ai_failed"`, use mock agent

### Async patterns
- `asyncio.gather(..., return_exceptions=True)` for parallel IO — always check for Exception instances in results
- `await asyncio.wait_for(coro, timeout=N)` on all external network calls
- `await asyncio.to_thread(sync_fn)` for blocking calls (yfinance, auth tokens)

### Error handling
- Never swallow exceptions silently — log at minimum `log.warning`
- `raise_for_status()` on all HTTP responses
- Use `core/exceptions.py` for domain-specific errors (`AIAgentError`, etc.)

---

## Testing rules

**Every code change must include updated or new tests.**

### Test file conventions
```python
class TestFeatureName:
    def test_happy_path(self, client: TestClient) -> None: ...
    def test_edge_case(self, client: TestClient) -> None: ...
    def test_error_returns_4xx(self, client: TestClient) -> None: ...
```

### Never in tests
- No real Gemini/GCP calls — `MOCK_AI=true` is enforced via `conftest.py`
- No real Redis — `REDIS_URL=""` forces InMemoryCache
- No `time.sleep` — use mocks for time-dependent logic

### Mocking pattern
```python
from unittest.mock import AsyncMock, patch

with patch("services.market_data.MarketDataService.get_gainers",
           new=AsyncMock(return_value=[sample_gainer])):
    resp = client.get("/api/gainers/us")
```
Patch at the **import point** (the module that uses it), not the definition point.

### Running tests
```bash
cd backend
.venv/bin/python -m pytest tests/ --override-ini="addopts=" -q --ignore=tests/test_growth_triggers_live.py
```

---

## TypeScript / React rules

### Types
- All shared types live in `frontend/src/types/index.ts` — single source of truth
- Never inline `interface` in a component file if it's shared across files
- No `any` — use `unknown` + type guards, or proper interfaces

### API calls
- All API calls go through `frontend/src/api/client.ts` using `fetchJSON<T>`
- Add new endpoints to the `api` object — never `fetch()` directly in components

### Data fetching
```typescript
// Read: useQuery
const { data, isLoading, error } = useQuery({
  queryKey: ["feature", param],
  queryFn: () => api.getFeature(param),
});

// Write: useMutation + invalidate
const mutation = useMutation({
  mutationFn: (body: MyRequest) => api.doSomething(body),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ["feature"] }),
});
```

### Styling
- Tailwind only — no inline styles, no CSS modules
- Rounded cards: `rounded-xl border border-gray-100`
- Section label: `text-[10px] font-bold text-gray-500 uppercase tracking-wide`
- Win/positive: `text-green-600 bg-green-50`
- Loss/negative: `text-red-500 bg-red-50`
- Warning/expired: `text-amber-600 bg-amber-50`
- Primary button: `bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl px-4 py-2.5 text-sm`
- Secondary button: `border border-gray-200 hover:bg-gray-50 text-gray-700 font-medium rounded-xl px-3 py-2 text-xs`
- Sticky header: `sticky top-0 z-10 bg-white border-b border-gray-100`

### Icons
- lucide-react only — `import { IconName } from "lucide-react"`
- Common: `TrendingUp`, `TrendingDown`, `ArrowUp`, `ArrowDown`, `X`, `Loader2`, `RefreshCw`, `BookmarkPlus`, `Target`, `Zap`, `Sparkles`

### Cross-tab navigation
Managed in `App.tsx` via props — no global state store. Pattern:
```typescript
function handleSomething(data: X) {
  setSomeState(data);
  setTab("destination");
}
// Pass to source page as onSomething={handleSomething}
// Pass result to destination page as someState={someState}
```

---

## Portfolio tracker — key design decisions

- `entry_price` = stock price at time of adding to tracker (prediction anchor)
- `purchase_avg` = real cost basis for holdings (separate from prediction tracking)
- 30-day clock starts at `entry_date`, ends at `target_date`
- Resolution: `direction_correct = (predicted >= 0) == (actual >= 0)` — direction only, not magnitude
- Status flow: `active` → `expired` (past target_date, no price entered) → `win` or `loss`
- Storage: Redis `portfolio:ids` index + `portfolio:{id}` entries, both with 10-year TTL
- Phase 1 (now): simple table + UI; Phase 2 (50+ entries): vector DB for RAG context

---

## Never do

- Never push commits — user pushes manually
- Never call `thinkingConfig: { thinkingBudget: 0 }` in Gemini payloads
- Never use `print()` for debugging — use structured logging
- Never hardcode `entry_price` targets (+5/-20) — use the AI's `predicted_change_pct`
- Never store sensitive values (API keys, tokens) in code — use environment variables via `Settings`
- Never call `git push` or `git commit` unless the user explicitly requests it
- Never use `any` in TypeScript
- Never skip writing tests when adding backend features
