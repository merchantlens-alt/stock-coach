# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci --silent

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Install Python dependencies ──────────────────────────────────────
FROM python:3.11-slim AS python-builder

WORKDIR /app

RUN pip install --no-cache-dir poetry==1.8.3

COPY backend/pyproject.toml ./
RUN poetry config virtualenvs.in-project true && \
    poetry install --only main --no-root --no-interaction

# ── Stage 3: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Python deps
COPY --from=python-builder /app/.venv ./.venv

# Backend code
COPY backend/ ./

# Frontend build output — served by FastAPI as static files
COPY --from=frontend-builder /frontend/dist ./static

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080

EXPOSE 8080

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
