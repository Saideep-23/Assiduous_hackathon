"""US Treasury Fiscal Data API (fiscaldata.treasury.gov) — long-end Treasury rate proxy."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from database.connection import get_connection

# v2 endpoint verified 2026-03 — v1 path returns 404 for this table.
# We use the latest row for "Treasury Notes" (published average interest rate on outstanding notes).
# README: this is a Treasury Fiscal Data series; for a daily 10Y CMT, swap the endpoint when exposed.
TREASURY_AVG_RATES_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates"
    "?filter=security_desc:eq:Treasury%20Notes&sort=-record_date&page[size]=1"
)
# Short-end proxy for term structure. Fiscal Data no longer exposes a `contains:2-Year` filter (400);
# use Treasury Bills (published average rate) as the short leg — engine still labels it risk_free_rate_2y.
TREASURY_SHORT_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates"
    "?filter=security_desc:eq:Treasury%20Bills&sort=-record_date&page[size]=1"
)


async def fetch_treasury_long_rate() -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        r = await client.get(TREASURY_AVG_RATES_URL, timeout=60.0)
        r.raise_for_status()
        data = r.json()
    rows = data.get("data", [])
    if not rows:
        raise RuntimeError("Treasury avg_interest_rates returned no Treasury Notes rows")
    row = rows[0]
    pct = float(row.get("avg_interest_rate_amt", 0))
    record_date = row.get("record_date", "")
    return {"yield_percent": pct, "record_date": record_date, "raw": row}


async def fetch_treasury_short_rate_optional() -> Optional[dict[str, Any]]:
    """Short-end Treasury Bills row for WACC term structure; None if API fails or returns nothing."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(TREASURY_SHORT_URL, timeout=60.0)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return None
    rows = data.get("data", [])
    if not rows:
        return None
    row = rows[0]
    pct = float(row.get("avg_interest_rate_amt", 0))
    record_date = row.get("record_date", "")
    return {"yield_percent": pct, "record_date": record_date, "raw": row}


def store_treasury_2y(yield_percent: float, record_date: str) -> None:
    """Persist short-end leg for WACC term structure; value is from Treasury Bills (avg rate), not a 2Y CMT."""
    pulled_at = datetime.now(timezone.utc).isoformat()
    stale = _is_stale(record_date, pulled_at)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO market_data (ticker, metric_name, value, pulled_at, is_stale, observation_date)
            VALUES ('MSFT', 'risk_free_rate_2y', ?, ?, ?, ?)
            ON CONFLICT(ticker, metric_name) DO UPDATE SET
              value=excluded.value, pulled_at=excluded.pulled_at, is_stale=excluded.is_stale, observation_date=excluded.observation_date
            """,
            (yield_percent / 100.0, pulled_at, 1 if stale else 0, record_date),
        )


def store_treasury_yield(yield_percent: float, record_date: str) -> None:
    pulled_at = datetime.now(timezone.utc).isoformat()
    stale = _is_stale(record_date, pulled_at)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO market_data (ticker, metric_name, value, pulled_at, is_stale, observation_date)
            VALUES ('MSFT', 'risk_free_rate_10y', ?, ?, ?, ?)
            ON CONFLICT(ticker, metric_name) DO UPDATE SET
              value=excluded.value, pulled_at=excluded.pulled_at, is_stale=excluded.is_stale, observation_date=excluded.observation_date
            """,
            (yield_percent / 100.0, pulled_at, 1 if stale else 0, record_date),
        )


def _is_stale(obs_date: str, pulled_at: str) -> bool:
    try:
        od = datetime.fromisoformat(obs_date).replace(tzinfo=timezone.utc)
        pt = datetime.fromisoformat(pulled_at.replace("Z", "+00:00"))
        return (pt - od).total_seconds() > 24 * 3600
    except Exception:
        return True


async def run_treasury_ingestion() -> dict[str, Any]:
    y = await fetch_treasury_long_rate()
    store_treasury_yield(y["yield_percent"], y["record_date"])
    out: dict[str, Any] = {"long_end": y}
    s2 = await fetch_treasury_short_rate_optional()
    if s2:
        store_treasury_2y(s2["yield_percent"], s2["record_date"])
        out["short_end_2y"] = s2
    else:
        out["short_end_2y"] = None
    return out
