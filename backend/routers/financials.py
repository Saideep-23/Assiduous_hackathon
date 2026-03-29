"""MSFT-only financials API with a structured overview snapshot (avoids null-heavy raw rows in the UI)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter

from database.connection import get_connection

router = APIRouter()

KPI_METRICS = [
    "total_revenue",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capital_expenditure",
]

SEGMENT_NAMES = (
    "Productivity and Business Processes",
    "Intelligent Cloud",
    "More Personal Computing",
)


def _overview_snapshot(conn) -> dict[str, Any]:
    """TTM + last three FY columns + market + latest segment revenue (server-side, typed)."""
    ttm: dict[str, Optional[float]] = {}
    for m in KPI_METRICS:
        row = conn.execute(
            """
            SELECT value FROM financial_metrics
            WHERE metric_name = ? AND is_ttm = 1
            ORDER BY id DESC LIMIT 1
            """,
            (m,),
        ).fetchone()
        if row and row[0] is not None:
            ttm[m] = float(row[0])
        else:
            ttm[m] = None

    rev_fy = conn.execute(
        """
        SELECT DISTINCT period_label FROM financial_metrics
        WHERE metric_name = 'total_revenue' AND is_ttm = 0 AND period_label LIKE 'FY%'
        """
    ).fetchall()
    fy_labels = sorted({r[0] for r in rev_fy if r[0]}, key=lambda pl: int(pl[2:6]))[-3:]

    fy_by_metric: dict[str, dict[str, Optional[float]]] = {}
    for m in KPI_METRICS:
        fy_by_metric[m] = {}
        for pl in fy_labels:
            row = conn.execute(
                """
                SELECT value FROM financial_metrics
                WHERE metric_name = ? AND period_label = ? AND is_ttm = 0
                LIMIT 1
                """,
                (m, pl),
            ).fetchone()
            fy_by_metric[m][pl] = float(row[0]) if row and row[0] is not None else None

    market: dict[str, Any] = {}
    for name in ("spot_price", "beta_5y_monthly", "risk_free_rate_10y", "risk_free_rate_2y"):
        row = conn.execute(
            """
            SELECT value, is_stale, observation_date, pulled_at
            FROM market_data WHERE ticker = 'MSFT' AND metric_name = ?
            """,
            (name,),
        ).fetchone()
        if row:
            market[name] = {
                "value": float(row[0]) if row[0] is not None else None,
                "is_stale": bool(row[1]),
                "observation_date": row[2],
                "pulled_at": row[3],
            }
        else:
            market[name] = None

    segment_latest: list[dict[str, Any]] = []
    for seg in SEGMENT_NAMES:
        row = conn.execute(
            """
            SELECT period_label, value FROM segment_metrics
            WHERE segment_name = ? AND metric_name = 'segment_revenue'
            ORDER BY period_label DESC LIMIT 1
            """,
            (seg,),
        ).fetchone()
        if row:
            segment_latest.append(
                {"segment_name": seg, "period_label": row[0], "revenue": float(row[1]) if row[1] is not None else None}
            )
        else:
            segment_latest.append({"segment_name": seg, "period_label": None, "revenue": None})

    return {
        "kpi_metrics_order": KPI_METRICS,
        "fy_labels": fy_labels,
        "ttm": ttm,
        "fy_by_metric": fy_by_metric,
        "market": market,
        "segment_latest_revenue": segment_latest,
    }


@router.get("/financials/msft")
def get_financials():
    with get_connection() as conn:
        fm = [dict(r) for r in conn.execute("SELECT * FROM financial_metrics").fetchall()]
        sm = [dict(r) for r in conn.execute("SELECT * FROM segment_metrics").fetchall()]
        md = [dict(r) for r in conn.execute("SELECT * FROM market_data").fetchall()]
        qs = [
            dict(r)
            for r in conn.execute(
                "SELECT filing_id, section_name, pulled_at, LENGTH(raw_text) as text_len FROM qualitative_sections"
            ).fetchall()
        ]
        item1_row = conn.execute(
            "SELECT raw_text FROM qualitative_sections WHERE section_name = 'item_1_business' ORDER BY pulled_at DESC LIMIT 1"
        ).fetchone()
        item1_excerpt = None
        if item1_row and item1_row[0]:
            t = item1_row[0]
            item1_excerpt = t[:2400] + ("…" if len(t) > 2400 else "")
        freshness = {
            "edgar_last": conn.execute("SELECT MAX(pulled_at) FROM raw_metrics").fetchone()[0],
            "market_last": conn.execute("SELECT MAX(pulled_at) FROM market_data").fetchone()[0],
        }
        overview = _overview_snapshot(conn)
    return {
        "financial_metrics": fm,
        "segment_metrics": sm,
        "market_data": md,
        "qualitative_sections_meta": qs,
        "item_1_excerpt": item1_excerpt,
        "overview": overview,
        "freshness": freshness,
    }
