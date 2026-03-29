"""Chunk 10-K text and embed into ChromaDB (500-token chunks, 50-token overlap)."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import chromadb
import tiktoken
from chromadb.utils import embedding_functions

from database.connection import get_connection

ENC = tiktoken.get_encoding("cl100k_base")
CHUNK = 500
OVERLAP = 50
COLLECTION = "msft_10k_chunks"


def _chunks(text: str) -> list[str]:
    toks = ENC.encode(text)
    out = []
    i = 0
    while i < len(toks):
        seg = toks[i : i + CHUNK]
        out.append(ENC.decode(seg))
        i += CHUNK - OVERLAP
    return [c for c in out if c.strip()]


def _chroma_client():
    chroma_url = os.environ.get("CHROMA_URL", "http://localhost:8000")
    u = urlparse(chroma_url)
    host = u.hostname or "localhost"
    port = u.port or 8000
    return chromadb.HttpClient(host=host, port=port)


def _embedding_fn():
    try:
        return embedding_functions.FastEmbedEmbeddingFunction(model_name="BAAI/bge-small-en-v1.5")
    except Exception:
        return embedding_functions.DefaultEmbeddingFunction()


def embed_10k_to_chroma(filing_id: str, full_text: str) -> int:
    client = _chroma_client()
    ef = _embedding_fn()
    coll = client.get_or_create_collection(name=COLLECTION, embedding_function=ef)
    parts = _chunks(full_text)
    if not parts:
        return 0
    ids = [f"{filing_id}_{i}" for i in range(len(parts))]
    coll.add(
        ids=ids,
        documents=parts,
        metadatas=[{"filing_id": filing_id, "section_name": "full_10k"} for _ in parts],
    )
    return len(parts)


async def run_embeddings_from_db() -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT filing_id, raw_text FROM qualitative_sections
            WHERE section_name = 'item_1_business' ORDER BY pulled_at DESC LIMIT 1
            """
        ).fetchone()
        if not row:
            return {"chunks": 0, "error": "no qualitative text"}
        filing_id = row["filing_id"]
        # Re-fetch full 10-K text: concatenate all sections for filing or use item_1 as proxy
        full = conn.execute(
            "SELECT GROUP_CONCAT(raw_text, '\n\n') FROM qualitative_sections WHERE filing_id = ?",
            (filing_id,),
        ).fetchone()[0]
        if not full:
            full = row["raw_text"]
    n = embed_10k_to_chroma(filing_id, full or "")
    return {"chunks": n, "filing_id": filing_id}
