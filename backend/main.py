import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.connection import init_db
from routers import agent, financials, ingest, model

app = FastAPI(
    title="Microsoft Corporate Finance Autopilot",
    version="1.0.0",
    description="MSFT-only REST API: SEC ingestion, deterministic DCF (`POST /model/msft`), methodology "
    "(`GET /model/methodology`), optional cached demo (`GET /model/msft/demo` when ASSIDUOS_DEMO=1), "
    "financials snapshot (`GET /financials/msft`), and agent SSE (`POST /agent/run`). "
    "Interactive OpenAPI: `/docs` and `/redoc`.",
)

def _cors_origins() -> list[str]:
    raw = os.environ.get("FRONTEND_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Browser may use localhost or 127.0.0.1; agent SSE bypasses Next /api and needs CORS to :8000.
    primary = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000").strip()
    out = [primary, "http://127.0.0.1:3000", "http://localhost:3000"]
    return list(dict.fromkeys(out))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="", tags=["ingest"])
app.include_router(financials.router, prefix="", tags=["financials"])
app.include_router(model.router, prefix="", tags=["model"])
app.include_router(agent.router, prefix="", tags=["agent"])


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
