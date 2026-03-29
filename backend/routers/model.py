import json
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from financial.engine import build_model
from financial.methodology import methodology_markdown, methodology_narrative

router = APIRouter()


@router.post("/model/msft")
def run_model():
    return build_model()


@router.get("/model/methodology")
def get_methodology():
    """Structured + markdown methodology for judges and API consumers (no DB required)."""
    return {
        "structured": methodology_narrative(),
        "markdown": methodology_markdown(),
    }


@router.get("/model/msft/demo")
def demo_model():
    """
    Pre-cached model JSON for instant demos. Enable with ASSIDUOS_DEMO=1 and add
    backend/demo/demo_model_response.json (e.g. export from a successful POST /model/msft).
    """
    env = os.environ.get("ASSIDUOS_DEMO", "").strip().lower()
    if env not in ("1", "true", "yes", "on"):
        return JSONResponse(
            {"error": "Demo disabled. Set ASSIDUOS_DEMO=1 to serve cached model JSON."},
            status_code=404,
        )
    root = Path(__file__).resolve().parent.parent
    p = root / "demo" / "demo_model_response.json"
    if not p.is_file():
        return JSONResponse(
            {"error": "Demo file missing. Add backend/demo/demo_model_response.json."},
            status_code=404,
        )
    return json.loads(p.read_text(encoding="utf-8"))
