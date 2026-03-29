from fastapi import APIRouter

from database.connection import init_db
from ingestion.edgar import run_edgar_ingestion
from ingestion.embeddings import run_embeddings_from_db
from ingestion.qualitative import ingest_qualitative_sections
from ingestion.transform import run_transform
from ingestion.treasury import run_treasury_ingestion
from ingestion.yfinance_client import run_yfinance_ingestion

router = APIRouter()


@router.post("/ingest/msft")
async def ingest_msft():
    init_db()
    ed = await run_edgar_ingestion()
    run_transform()
    await run_treasury_ingestion()
    try:
        yf_result = await run_yfinance_ingestion()
    except ValueError as e:
        yf_result = {"error": str(e)}
    q = await ingest_qualitative_sections()
    emb = {"chunks": 0}
    try:
        emb = await run_embeddings_from_db()
    except Exception as e:
        emb = {"chunks": 0, "error": str(e)}
    from database.connection import get_connection

    with get_connection() as conn:
        w = conn.execute("SELECT COUNT(*) FROM ingestion_warnings").fetchone()[0]
        mcount = conn.execute("SELECT COUNT(*) FROM financial_metrics").fetchone()[0]
    status = "ok" if "error" not in yf_result else "degraded"
    return {
        "status": status,
        "edgar": ed,
        "transform_metrics": mcount,
        "yfinance": yf_result,
        "qualitative": q,
        "embeddings": emb,
        "warnings_logged": w,
    }
