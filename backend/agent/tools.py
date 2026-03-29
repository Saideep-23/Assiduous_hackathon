"""Agent tools — database and Chroma-backed retrieval."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import chromadb
from chromadb.utils import embedding_functions

from database.connection import get_connection
from financial.engine import build_model


def tool_get_segment_financials() -> dict[str, Any]:
    with get_connection() as conn:
        sm = [dict(r) for r in conn.execute("SELECT * FROM segment_metrics").fetchall()]
    model = build_model()
    if model.get("error"):
        model = {"error": model["error"]}
    return {"segment_metrics_table": sm, "model_segment_inputs": model.get("segment_inputs"), "historical": model.get("historical_snapshot")}


def tool_get_consolidated_financials() -> dict[str, Any]:
    with get_connection() as conn:
        fm = [dict(r) for r in conn.execute("SELECT * FROM financial_metrics").fetchall()]
        md = [dict(r) for r in conn.execute("SELECT * FROM market_data").fetchall()]
    m = build_model()
    wacc = m.get("wacc_components", {}) if not m.get("error") else {}
    fcf = m.get("fcf_bridge_tree", {}) if not m.get("error") else {}
    return {"financial_metrics": fm, "market_data": md, "wacc_components": wacc, "fcf_bridge": fcf}


def tool_get_qualitative_sections(query: str) -> dict[str, Any]:
    chroma_url = os.environ.get("CHROMA_URL", "http://localhost:8000")
    u = urlparse(chroma_url)
    host, port = u.hostname or "localhost", u.port or 8000
    try:
        client = chromadb.HttpClient(host=host, port=port)
        try:
            ef = embedding_functions.FastEmbedEmbeddingFunction(model_name="BAAI/bge-small-en-v1.5")
        except Exception:
            ef = embedding_functions.DefaultEmbeddingFunction()
        coll = client.get_collection("msft_10k_chunks", embedding_function=ef)
        res = coll.query(query_texts=[query], n_results=3)
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        out = [{"text": docs[i], "metadata": metas[i]} for i in range(len(docs))]
        return {"passages": out, "rag_query": query, "source": "chroma"}
    except Exception as e:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT section_name, filing_id, raw_text FROM qualitative_sections LIMIT 20"
            ).fetchall()
        chunks = [{"text": r[2][:1500], "metadata": {"section_name": r[0], "filing_id": r[1]}} for r in rows]
        return {"passages": chunks[:3], "rag_query": query, "source": "qualitative_sections_fallback", "warning": str(e)}


def tool_get_dcf_output() -> dict[str, Any]:
    return build_model()


def build_agent_context_bundle() -> dict[str, Any]:
    """
    Single build_model() pass for the memo agent payload.
    `_bundle()` previously called segment + DCF tools separately → 2× full DCF per run and no SSE until both
    finished (UI stuck on "Connecting…" for many minutes).
    """
    model = build_model()
    with get_connection() as conn:
        sm = [dict(r) for r in conn.execute("SELECT * FROM segment_metrics").fetchall()]
    if model.get("error"):
        m_seg = {"error": model["error"]}
    else:
        m_seg = model
    segment_financials = {
        "segment_metrics_table": sm,
        "model_segment_inputs": m_seg.get("segment_inputs"),
        "historical": m_seg.get("historical_snapshot"),
    }
    return {"segment_financials": segment_financials, "dcf": model}


def tool_write_memo_section(section_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"section_name": section_name, "payload_keys": list(payload.keys()), "ok": True}


TOOLS_SPEC = [
    {"name": "get_segment_financials", "description": "Segment revenue/OI history and model projections.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_consolidated_financials", "description": "Consolidated metrics, WACC inputs, FCF bridge.", "input_schema": {"type": "object", "properties": {}}},
    {
        "name": "get_qualitative_sections",
        "description": "Semantic search over 10-K chunks; pass a specific query string.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {"name": "get_dcf_output", "description": "Full DCF scenarios, grid, consistency checks.", "input_schema": {"type": "object", "properties": {}}},
    {
        "name": "write_memo_section",
        "description": "Record memo section draft from structured payload.",
        "input_schema": {
            "type": "object",
            "properties": {"section_name": {"type": "string"}, "payload": {"type": "object"}},
            "required": ["section_name", "payload"],
        },
    },
]


def dispatch_tool(name: str, tool_input: dict[str, Any]) -> Any:
    if name == "get_segment_financials":
        return tool_get_segment_financials()
    if name == "get_consolidated_financials":
        return tool_get_consolidated_financials()
    if name == "get_qualitative_sections":
        return tool_get_qualitative_sections(tool_input.get("query", ""))
    if name == "get_dcf_output":
        return tool_get_dcf_output()
    if name == "write_memo_section":
        return tool_write_memo_section(tool_input.get("section_name", ""), tool_input.get("payload", {}))
    return {"error": "unknown tool"}
