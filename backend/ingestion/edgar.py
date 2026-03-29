"""
SEC EDGAR Company Facts API + MSFT ixBR segment extraction.
User-Agent required by SEC.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from database.connection import get_connection
from ingestion import msft_xbrl_tags as T

# SEC www.sec.gov/Archives returns 403 unless User-Agent includes a contact email (plain form).
SEC_HEADERS = {
    "User-Agent": "MSFTCorporateFinanceAutopilot/1.0 hackathon@example.com",
    "Accept-Encoding": "gzip, deflate",
}

COMPANY_FACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{T.CIK}.json"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{T.CIK}.json"

# Consolidated tags to pull (namespace:key as stored in companyfacts paths)
CONSOLIDATED_TAGS = [
    # Post–ASC 606 MSFT reports contract revenue; legacy `Revenues` in Company Facts stops ~2011.
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "total_revenue"),
    ("us-gaap", "OperatingIncomeLoss", "operating_income"),
    ("us-gaap", "NetIncomeLoss", "net_income"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "operating_cash_flow"),
    ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", "capital_expenditure"),
    # MSFT Company Facts expose `Depreciation` (USD); `DepreciationDepletionAndAmortization` is absent.
    ("us-gaap", "Depreciation", "depreciation_amortization"),
    ("us-gaap", "InterestExpense", "interest_expense"),
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "cash_and_equivalents"),
    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "diluted_shares_outstanding"),
    ("us-gaap", "SegmentReportingReconcilingItemForOperatingProfitLossFromSegmentToConsolidatedAmount", "corporate_unallocated_oi"),
    ("us-gaap", "IncomeTaxExpenseBenefit", "income_tax_expense"),
    (
        "us-gaap",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "income_before_tax",
    ),
    ("us-gaap", "AssetsCurrent", "assets_current"),
    ("us-gaap", "LiabilitiesCurrent", "liabilities_current"),
    ("us-gaap", "AccountsReceivableNetCurrent", "accounts_receivable_net"),
    ("us-gaap", "InventoryNet", "inventory_net"),
    ("us-gaap", "AccountsPayableCurrent", "accounts_payable_current"),
    ("us-gaap", "OperatingLeaseLiability", "operating_lease_liability"),
    ("us-gaap", "FinanceLeaseLiability", "finance_lease_liability"),
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", "basic_shares_outstanding"),
]

DEBT_TAGS = [
    ("us-gaap", "LongTermDebtNoncurrent", "long_term_debt_noncurrent"),
    ("us-gaap", "ShortTermBorrowings", "short_term_borrowings"),
    ("us-gaap", "LongTermDebtCurrent", "long_term_debt_current"),
]


def _composite_key(
    filing_id: str,
    tag: str,
    p_start: Optional[str],
    p_end: Optional[str],
    unit: str,
    segment_key: Optional[str] = None,
) -> str:
    raw = f"{filing_id}|{tag}|{p_start or ''}|{p_end or ''}|{unit}"
    if segment_key:
        raw += f"|segment:{segment_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    r = await client.get(url, headers=SEC_HEADERS, timeout=120.0)
    r.raise_for_status()
    return r.json()


def _usd_rows(facts: dict[str, Any], ns: str, tag: str) -> list[dict[str, Any]]:
    block = facts.get(ns, {}).get(tag, {})
    return block.get("units", {}).get("USD", [])


# Company Facts unit per tag (most consolidated facts are USD; share counts use "shares").
TAG_FACT_UNITS: dict[str, str] = {
    "WeightedAverageNumberOfDilutedSharesOutstanding": "shares",
}


def _fact_rows_for_tag(facts: dict[str, Any], ns: str, tag: str) -> tuple[list[dict[str, Any]], str]:
    block = facts.get(ns, {}).get(tag, {})
    unit = TAG_FACT_UNITS.get(tag, "USD")
    rows = block.get("units", {}).get(unit, [])
    return rows, unit


def _dedupe_facts_latest_filed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SEC repeats the same fiscal period across many filings; keep the most recently *filed* row."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        k = (row.get("start") or "", row.get("end") or "")
        cur = by_key.get(k)
        filed, cur_filed = row.get("filed") or "", (cur or {}).get("filed") or ""
        if not cur or filed > cur_filed:
            by_key[k] = row
    return list(by_key.values())


def insert_raw_metric(
    conn,
    filing_id: str,
    xbrl_tag: str,
    period_start: Optional[str],
    period_end: Optional[str],
    unit: str,
    value: Optional[float],
    pulled_at: str,
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[str] = None,
    segment_key: Optional[str] = None,
) -> bool:
    ck = _composite_key(filing_id, xbrl_tag, period_start, period_end, unit, segment_key)
    try:
        conn.execute(
            """
            INSERT INTO raw_metrics (filing_id, xbrl_tag, period_start, period_end, unit, value, pulled_at,
                fiscal_year, fiscal_period, composite_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (filing_id, xbrl_tag, period_start, period_end, unit, value, pulled_at, fiscal_year, fiscal_period, ck),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def get_raw_metric_id(
    conn,
    filing_id: str,
    xbrl_tag: str,
    period_start: Optional[str],
    period_end: Optional[str],
    unit: str,
    segment_key: Optional[str] = None,
) -> Optional[int]:
    ck = _composite_key(filing_id, xbrl_tag, period_start, period_end, unit, segment_key)
    row = conn.execute("SELECT id FROM raw_metrics WHERE composite_key = ?", (ck,)).fetchone()
    return int(row[0]) if row else None


def ensure_filing_row(conn, filing_id: str, form: str, filed: str, period_end: Optional[str], url: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO raw_filings (filing_id, ticker, form_type, filed_date, period_of_report, source_url)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (filing_id, T.TICKER, form, filed, period_end, url),
    )


async def ingest_company_facts_consolidated(client: httpx.AsyncClient) -> int:
    data = await fetch_json(client, COMPANY_FACTS_URL)
    facts = data.get("facts", {})
    pulled_at = _now_iso()
    count = 0
    consolidated_xbrl_tags = [f"{ns}:{tag}" for ns, tag, _ in CONSOLIDATED_TAGS + DEBT_TAGS]
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            f"DELETE FROM raw_metrics WHERE xbrl_tag IN ({','.join('?' * len(consolidated_xbrl_tags))})",
            consolidated_xbrl_tags,
        )
        conn.execute("PRAGMA foreign_keys = ON")
        for ns, tag, _ in CONSOLIDATED_TAGS + DEBT_TAGS:
            rows, fact_unit = _fact_rows_for_tag(facts, ns, tag)
            rows = _dedupe_facts_latest_filed(rows)
            for row in rows:
                accn = row.get("accn")
                if not accn:
                    continue
                filing_id = accn
                form = row.get("form", "")
                filed = row.get("filed", "")
                p_start = row.get("start")
                p_end = row.get("end")
                val = row.get("val")
                if isinstance(val, (int, float)):
                    v = float(val)
                else:
                    v = None
                url = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={T.CIK}&accession_number={accn.replace('-', '')}"
                ensure_filing_row(conn, filing_id, form, filed, p_end, url)
                full_tag = f"{ns}:{tag}"
                fy = row.get("fy")
                fp = row.get("fp")
                if insert_raw_metric(conn, filing_id, full_tag, p_start, p_end, fact_unit, v, pulled_at, fy, fp, None):
                    count += 1
    return count


def _segment_name_from_context(ctx_xml: str) -> Optional[str]:
    for suffix, label in T.MEMBER_SUFFIXES.items():
        if suffix in ctx_xml:
            return label
    return None


def parse_ixbrl_segments(html: str, filing_id: str) -> list[dict[str, Any]]:
    """Extract segment revenue and operating income from MSFT inline XBRL (one filing)."""
    soup = BeautifulSoup(html, "lxml")
    contexts: dict[str, str] = {}
    period_by_ctx: dict[str, Optional[str]] = {}
    for ctx in soup.find_all(True):
        if not ctx.name or "context" not in ctx.name.lower():
            continue
        if not ctx.name.lower().endswith("context"):
            continue
        cid = ctx.get("id")
        if not cid:
            continue
        raw = str(ctx)
        sn = _segment_name_from_context(raw)
        if not sn:
            continue
        contexts[cid] = sn
        end: Optional[str] = None
        for tag in ctx.find_all(True):
            if not tag.name:
                continue
            ln = tag.name.lower()
            if ln.endswith("instant") or ln.endswith("enddate"):
                if tag.string:
                    end = tag.string.strip()
                    break
        period_by_ctx[cid] = end

    out: list[dict[str, Any]] = []
    for nf in soup.find_all(True):
        if not nf.name or "nonfraction" not in nf.name.lower():
            continue
        name = nf.get("name") or ""
        cref = nf.get("contextref") or nf.get("contextRef")
        if not cref or cref not in contexts:
            continue
        if "RevenueFromContractWithCustomerExcludingAssessedTax" not in name and "OperatingIncomeLoss" not in name:
            continue
        try:
            scale = int(nf.get("scale", "0") or "0")
        except ValueError:
            scale = 0
        txt = nf.get_text(strip=True).replace(",", "")
        try:
            val = float(txt)
        except ValueError:
            continue
        val *= 10**scale
        if nf.get("sign") == "-":
            val = -val
        metric = "segment_revenue" if "RevenueFromContract" in name else "segment_operating_income"
        out.append(
            {
                "segment": contexts[cref],
                "metric": metric,
                "value": val,
                "context_ref": cref,
                "tag": name.split(":")[-1] if ":" in name else name,
                "period_end": period_by_ctx.get(cref),
            }
        )
    return out


async def fetch_filing_primary_html(client: httpx.AsyncClient, accn: str) -> Optional[str]:
    """Accession e.g. 0000950170-24-087843 -> path under edgar/data/789019/"""
    accn_nodash = accn.replace("-", "")
    cik_int = int(T.CIK.lstrip("0") or "0")
    idx_url = f"https://data.sec.gov/submissions/CIK{T.CIK}.json"
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/index.json"
    try:
        idx = await fetch_json(client, index_url)
    except Exception:
        return None
    items = idx.get("directory", {}).get("item", [])
    # Prefer msft-*htm main 10-K/10-Q document
    htm_names = [i["name"] for i in items if i["name"].endswith(".htm") and "msft" in i["name"].lower() and "exhibit" not in i["name"].lower()]
    if not htm_names:
        htm_names = [i["name"] for i in items if i["name"].endswith(".htm") and i["name"].lower().startswith("msft")]
    if not htm_names:
        return None
    # Longest `msft-*.htm` is typically the full iXBRL 10-K/10-Q; shortest is often a stub or cover page.
    name = sorted(htm_names, key=len)[-1]
    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/{name}"
    r = await client.get(doc_url, headers=SEC_HEADERS, timeout=180.0)
    r.raise_for_status()
    return r.text


async def ingest_segment_ixbrl_for_filings(client: httpx.AsyncClient, max_filings: int = 24) -> int:
    sub = await fetch_json(client, SUBMISSIONS_URL)
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filed_dates = recent.get("filingDate", [])
    count = 0
    pulled_at = _now_iso()
    seen = 0
    with get_connection() as conn:
        for i in range(len(forms)):
            if forms[i] not in ("10-K", "10-Q"):
                continue
            accn = accessions[i]
            html = await fetch_filing_primary_html(client, accn)
            if not html:
                continue
            rows = parse_ixbrl_segments(html, accn)
            # collapse duplicate segment+metric+period: take last
            keymap: dict[tuple, dict] = {}
            for row in rows:
                pe = row.get("period_end")
                k = (row["segment"], row["metric"], pe)
                keymap[k] = row
            for row in keymap.values():
                tag = f"us-gaap:{row['tag']}"
                filing_id = accn
                ensure_filing_row(
                    conn,
                    filing_id,
                    forms[i],
                    filed_dates[i] if i < len(filed_dates) else "",
                    row.get("period_end"),
                    f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={T.CIK}&accession_number={accn.replace('-', '')}",
                )
                seg_key = f"{row['segment']}|{row['metric']}"
                ins = insert_raw_metric(
                    conn,
                    filing_id,
                    tag,
                    None,
                    row.get("period_end"),
                    "USD",
                    row["value"],
                    pulled_at,
                    segment_key=seg_key,
                )
                if ins:
                    count += 1
                rid = get_raw_metric_id(conn, filing_id, tag, None, row.get("period_end"), "USD", seg_key)
                if rid:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO segment_metrics (raw_metric_id, segment_name, metric_name, period_label, value, is_ttm, pulled_at)
                        VALUES (?, ?, ?, ?, ?, 0, ?)
                        """,
                        (
                            rid,
                            row["segment"],
                            row["metric"],
                            row.get("period_end") or "unknown",
                            row["value"],
                            pulled_at,
                        ),
                    )
            seen += 1
            if seen >= max_filings:
                break
    return count


def _label_period(row: dict[str, Any]) -> str:
    fp = row.get("fp")
    fy = row.get("fy")
    if fp == "FY":
        return f"FY{fy}"
    return f"{fp or 'Q'}{fy}"


async def run_edgar_ingestion() -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        n1 = await ingest_company_facts_consolidated(client)
        n2 = await ingest_segment_ixbrl_for_filings(client)
    return {"company_facts_rows": n1, "segment_rows": n2}
