# Microsoft Corporate Finance Autopilot

End-to-end **Microsoft (MSFT)–only** pipeline: SEC EDGAR ingestion → SQLite → deterministic DCF and WACC → optional Chroma RAG → **Claude** investment memo with validation → **Next.js** UI (Overview, Model, Agent).

**Educational / hackathon demo — not investment advice.**

---

## Table of contents

1. [Requirements](#requirements)  
2. [GitHub clone — mentors & collaborators](#github-clone--mentors--collaborators)  
3. [Quick start (Docker)](#quick-start-docker)  
4. [Environment variables](#environment-variables)  
5. [Architecture](#architecture)  
6. [API reference](#api-reference)  
7. [Operations](#operations)  
8. [Agent page & streaming (important)](#agent-page--streaming-important)  
9. [Limitations](#limitations)  
10. [Troubleshooting](#troubleshooting)  
11. [Development without Docker](#development-without-docker)  
12. [Data sources](#data-sources)  
13. [Disclaimer](#disclaimer)

---

## Requirements

- **Docker** and **Docker Compose** (recommended path)  
- **Anthropic API key** for `POST /agent/run` (memo generation)  
- Optional: **Alpha Vantage** API key if Yahoo Finance rate-limits your network (common from cloud/Docker IPs)

---

## GitHub clone — mentors & collaborators

This repository **does not** include `.env` or API keys. After cloning:

1. **Copy the template:** `cp .env.example .env`
2. **Add your keys** in `.env` (at minimum `ANTHROPIC_API_KEY` for the Agent page).
3. **Never commit** `.env` — it is listed in `.gitignore`.

Optional keys are documented in the **Environment variables** section below. The app runs ingestion and the model **without** Anthropic; only **`POST /agent/run`** (memo generation) requires `ANTHROPIC_API_KEY`.

---

## Quick start (Docker)

```bash
git clone <your-repo-url> assiduos
cd assiduos
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY=... (required for the Agent page)
# Optional: ALPHA_VANTAGE_API_KEY=... if Yahoo returns HTTP 429 during ingestion
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend (FastAPI) | http://localhost:8000 |
| ChromaDB | http://localhost:8001 (internal to Compose; backend uses `CHROMA_URL`) |
| OpenAPI | http://localhost:8000/docs |

**Load data** (large SEC pull; often **several minutes**):

```bash
curl -X POST http://localhost:8000/ingest/msft
```

Then open the **Overview** and **Model** pages. Use **Agent** after ingestion completes and `ANTHROPIC_API_KEY` is set.

---

## Environment variables

Create **`.env`** in the **project root** (same folder as `docker-compose.yml`). Compose passes it to the **backend** container.

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | **Yes** for Agent | Claude API for memo sections |
| `ALPHA_VANTAGE_API_KEY` | No | Fallback monthly prices if Yahoo chart API returns HTTP 429 |
| `ASSIDUOS_DEMO` | No | Set to `1` with `backend/demo/demo_model_response.json` to enable `GET /model/msft/demo` |
| `FRONTEND_ORIGINS` | No | Comma-separated CORS origins; defaults include `http://localhost:3000` and `http://127.0.0.1:3000` |

Docker Compose also sets `DATABASE_PATH`, `CHROMA_URL`, and `FRONTEND_ORIGIN` for the backend — see `docker-compose.yml`.

**Security:** Never commit `.env`. A root **`.gitignore`** ignores `.env` files. If a key was ever committed or shared, **rotate it** in the provider’s console (e.g. Anthropic) and use only `.env.example` as the template.

---

## Architecture

### 1. Ingestion

- **SEC Company Facts** (`data.sec.gov`) → `raw_metrics` → **transform** → `financial_metrics` (TTM, effective tax, debt totals, etc.).
- **Inline XBRL** from 10-K/10-Q HTML → **segment** revenue and operating income.
- **Yahoo** chart API (v5/v8) for MSFT/SPY monthly adjusted closes → spot + **5Y monthly beta** vs SPY; optional **Alpha Vantage** fallback.
- **Treasury Fiscal Data API v2** `avg_interest_rates`: **Treasury Notes** → `risk_free_rate_10y`; **Treasury Bills** → stored as `risk_free_rate_2y` (legacy metric name — short-end **Bills** average, not a broker 2Y CMT).
- **Qualitative** sections from latest 10-K; **chunks + embeddings** into **ChromaDB** (FastEmbed `BAAI/bge-small-en-v1.5`).

### 2. Deterministic model (`financial/engine.py`)

- Segment-based growth/margin scenarios; **7-year** explicit path + **3-year** fade to terminal **g**; Gordon terminal value.
- **CAPM** WACC with term-structured risk-free (short→long); **Damodaran-style US ERP** constant in code.
- **FCF bridge** from last 3 FY; NWC: **Δ(AR + Inventory − AP) / ΔRevenue** when tags align, else **Δ(current assets − current liabilities) / ΔRevenue**; **segment capex intensity** scales consolidated capex in the DCF.
- **5×5** sensitivity grid (flat WACC vs terminal **g**).
- Methodology: **`GET /model/methodology`**.

### 3. RAG + agent

- **Claude** (`claude-sonnet-4-20250514`) writes memo sections with tool payloads; **single `build_model()`** per run for context bundle.
- **SSE** (`text/event-stream`) trace events + final memo + validation JSON.

### 4. Frontend

- **Next.js** rewrites `/api/*` → FastAPI for same-origin calls **except** the Agent run: the browser must **`POST` directly to `http://localhost:8000/agent/run`** (or `127.0.0.1:8000`) so **SSE is not buffered** by the Next proxy. The Agent page implements this automatically on localhost.

---

## API reference

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/ingest/msft` | Full ingestion pipeline |
| `GET` | `/financials/msft` | Financial + segment + market snapshot |
| `POST` | `/model/msft` | Full DCF JSON |
| `GET` | `/model/methodology` | Structured + markdown methodology (no DB) |
| `GET` | `/model/msft/demo` | Cached demo JSON if `ASSIDUOS_DEMO=1` and demo file present |
| `POST` | `/agent/run` | SSE stream of trace events + final memo |
| `GET` | `/health` | Liveness |

---

## Operations

- **Logs:** `docker compose logs -f backend` (or `frontend`, `chroma`).
- **Reset DB + Chroma volumes:** `docker compose down -v` (destructive).
- **Rebuild after code changes:** `docker compose up --build -d`.

---

## Agent page & streaming (important)

- **Expected duration:** about **5–15 minutes** — multiple Claude calls (one per memo section) plus one DCF snapshot up front.
- **UI:** While the agent runs, a **status panel** shows **elapsed time** and **latest trace activity** so users know work is in progress.
- **Technical:** The Next.js **`/api` rewrite buffers streaming responses**. The Agent page therefore uses **`http://<host>:8000/agent/run`** from the browser when the site is served from `localhost` or `127.0.0.1`. FastAPI **CORS** allows both `http://localhost:3000` and `http://127.0.0.1:3000`.

---

## Limitations

- **Single ticker (MSFT)** — tags and segment parsers are issuer-specific.
- **TTM** — `FY(n−1) + latest quarter − same quarter prior year` where Company Facts expose `fy`/`fp`.
- **Treasury** — See Architecture; not a live **CMT** strip; suitable for a teaching WACC curve.
- **Yahoo** — Unofficial; use Alpha Vantage fallback when rate-limited.
- **FCF bridge** — Simplified; not a full cash flow statement.
- **Outputs are not investment advice.**

---

## Troubleshooting

| Symptom | Things to check |
|---------|------------------|
| Agent returns 401/403 from Anthropic | `ANTHROPIC_API_KEY` in root `.env`; restart `docker compose` |
| Ingest fails on Treasury | Backend uses Bills for short end; check logs for HTTP errors |
| Yahoo 429 during ingest | Add `ALPHA_VANTAGE_API_KEY`, re-run `POST /ingest/msft` |
| Model errors | Run ingest first; open `POST /model/msft` JSON for `error` / `model_warnings` |
| Agent trace empty for minutes | Ensure you are on **localhost/127.0.0.1** so the UI hits **port 8000** directly; see [Agent page & streaming](#agent-page--streaming-important) |
| `docker compose` frontend build fails on Google Fonts | Retry build when network allows `fonts.googleapis.com`, or build frontend on a machine with access |

---

## Development without Docker

- **Backend:** Python 3.11+, `pip install -r backend/requirements.txt`, `uvicorn` with `PYTHONPATH=backend` from repo root.  
- **Frontend:** `cd frontend && npm install && npm run dev` — set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` if needed.  
- **Database:** default SQLite path is configurable via `DATABASE_PATH` (see `database/connection.py`).

---

## Data sources (official / public)

- SEC EDGAR: https://www.sec.gov/edgar  
- US Treasury Fiscal Data API: https://fiscaldata.treasury.gov/api-documentation/  
- Yahoo Finance (unofficial chart endpoints); optional Alpha Vantage.

---

## Disclaimer

This software is for **education and demonstration** only. It does **not** provide investment advice. Model and memo outputs depend on assumptions and public data; verify figures against **primary filings** and your own judgment.
