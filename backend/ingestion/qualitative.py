"""Extract qualitative sections from MSFT 10-K HTML (EDGAR)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from database.connection import get_connection
from ingestion.edgar import fetch_json, fetch_filing_primary_html
from ingestion.msft_xbrl_tags import CIK

SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"


def _strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _extract_item_1(text: str) -> str:
    m = re.search(r"ITEM\s*1\.\s*BUSINESS(.*?)(?=ITEM\s*1A\.|ITEM\s*2\.)", text, re.I | re.S)
    return m.group(1).strip()[:12000] if m else ""


def _extract_item_1a_risks(text: str) -> list[str]:
    m = re.search(r"ITEM\s*1A\.\s*RISK\s*FACTORS(.*?)(?=ITEM\s*1B\.|ITEM\s*2\.)", text, re.I | re.S)
    if not m:
        return []
    block = m.group(1)
    parts = re.split(r"(?=\n\s*(?:RISK|Risk)\s+[A-Z0-9])|(?=\n\s*\d+\.\s+)", block)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) > 80:
            out.append(p[:2000])
        if len(out) >= 5:
            break
    if len(out) < 5:
        paras = [x.strip() for x in block.split("\n\n") if len(x.strip()) > 100]
        out = (out + paras)[:5]
    return out[:5]


def _extract_item_7_capital(text: str) -> str:
    m = re.search(r"ITEM\s*7\.\s*MANAGEMENT\S\s*DISCUSSION(.*?)(?=ITEM\s*7A\.|ITEM\s*8\.)", text, re.I | re.S)
    if not m:
        return ""
    block = m.group(1)
    cap = re.search(
        r"(.{0,200}(?:capital allocation|share repurchase|dividend|return.{0,40}cash).{0,8000})",
        block,
        re.I | re.S,
    )
    return (cap.group(1) if cap else block[:8000]).strip()


def _segment_blurbs(item1: str) -> dict[str, str]:
    out = {}
    for name, pat in [
        ("Productivity and Business Processes", r"(Productivity and Business Processes.{0,4000}?)(?=Intelligent Cloud|More Personal Computing|\Z)"),
        ("Intelligent Cloud", r"(Intelligent Cloud.{0,4000}?)(?=More Personal Computing|Productivity|\Z)"),
        ("More Personal Computing", r"(More Personal Computing.{0,4000}?)(?=Productivity|Intelligent Cloud|\Z)"),
    ]:
        m = re.search(pat, item1, re.I | re.S)
        if m:
            out[name] = m.group(1).strip()[:6000]
    return out


async def fetch_latest_10k_accession(client: httpx.AsyncClient) -> Optional[str]:
    sub = await fetch_json(client, SUBMISSIONS_URL)
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    for i, f in enumerate(forms):
        if f == "10-K":
            return accs[i]
    return None


async def ingest_qualitative_sections() -> dict[str, int]:
    async with httpx.AsyncClient() as client:
        accn = await fetch_latest_10k_accession(client)
        if not accn:
            return {"sections": 0}
        html = await fetch_filing_primary_html(client, accn)
        if not html:
            return {"sections": 0}
    text = _strip_html(html)
    pulled_at = datetime.now(timezone.utc).isoformat()
    item1 = _extract_item_1(text)
    risks = _extract_item_1a_risks(text)
    capital = _extract_item_7_capital(text)
    seg = _segment_blurbs(item1)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO qualitative_sections (filing_id, section_name, raw_text, pulled_at)
            VALUES (?, 'item_1_business', ?, ?)
            """,
            (accn, item1, pulled_at),
        )
        for k, v in seg.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO qualitative_sections (filing_id, section_name, raw_text, pulled_at)
                VALUES (?, ?, ?, ?)
                """,
                (accn, f"segment_description_{k}", v, pulled_at),
            )
        for i, r in enumerate(risks):
            conn.execute(
                """
                INSERT OR REPLACE INTO qualitative_sections (filing_id, section_name, raw_text, pulled_at)
                VALUES (?, ?, ?, ?)
                """,
                (accn, f"risk_factor_{i+1}", r, pulled_at),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO qualitative_sections (filing_id, section_name, raw_text, pulled_at)
            VALUES (?, 'item_7_capital_allocation', ?, ?)
            """,
            (accn, capital, pulled_at),
        )
    return {"sections": 1 + len(seg) + len(risks) + (1 if capital else 0), "filing_id": accn, "full_text_len": len(text)}
