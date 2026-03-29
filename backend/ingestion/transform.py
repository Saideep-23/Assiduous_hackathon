"""
Transform raw_metrics into financial_metrics (including TTM).
TTM formula (per user spec, applied consistently):
  TTM = most_recent_full_FY_value + latest_quarter_value - same_fiscal_quarter_one_year_ago
This replaces the overlapping quarter in the annual window with the latest quarter, yielding
twelve months ending on the latest quarter end date.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from database.connection import get_connection

SEGMENT_NAMES = (
    "Productivity and Business Processes",
    "Intelligent Cloud",
    "More Personal Computing",
)

TAG_TO_METRIC = {
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": "total_revenue",
    "us-gaap:OperatingIncomeLoss": "operating_income",
    "us-gaap:NetIncomeLoss": "net_income",
    "us-gaap:NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment": "capital_expenditure",
    "us-gaap:Depreciation": "depreciation_amortization",
    "us-gaap:InterestExpense": "interest_expense",
    "us-gaap:CashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",
    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding": "diluted_shares_outstanding",
    "us-gaap:SegmentReportingReconcilingItemForOperatingProfitLossFromSegmentToConsolidatedAmount": "corporate_unallocated_oi",
    "us-gaap:IncomeTaxExpenseBenefit": "income_tax_expense",
    "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": "income_before_tax",
    "us-gaap:AssetsCurrent": "assets_current",
    "us-gaap:LiabilitiesCurrent": "liabilities_current",
    "us-gaap:LongTermDebtNoncurrent": "long_term_debt_noncurrent",
    "us-gaap:ShortTermBorrowings": "short_term_borrowings",
    "us-gaap:LongTermDebtCurrent": "long_term_debt_current",
    "us-gaap:OperatingLeaseLiability": "operating_lease_liability",
    "us-gaap:FinanceLeaseLiability": "finance_lease_liability",
    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic": "basic_shares_outstanding",
    "us-gaap:AccountsReceivableNetCurrent": "accounts_receivable_net",
    "us-gaap:InventoryNet": "inventory_net",
    "us-gaap:AccountsPayableCurrent": "accounts_payable_current",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_transform() -> dict[str, Any]:
    pulled_at = _now()
    with get_connection() as conn:
        conn.execute("DELETE FROM financial_metrics")
        rows = conn.execute(
            """
            SELECT id, filing_id, xbrl_tag, period_start, period_end, value, fiscal_year, fiscal_period
            FROM raw_metrics WHERE xbrl_tag IN ({})
            """.format(",".join("?" * len(TAG_TO_METRIC))),
            list(TAG_TO_METRIC.keys()),
        ).fetchall()

        by_metric: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            mname = TAG_TO_METRIC.get(r["xbrl_tag"])
            if not mname or r["value"] is None:
                continue
            by_metric[mname].append(
                {
                    "raw_id": r["id"],
                    "filing_id": r["filing_id"],
                    "period_start": r["period_start"],
                    "period_end": r["period_end"],
                    "value": float(r["value"]),
                    "fy": r["fiscal_year"],
                    "fp": r["fiscal_period"],
                }
            )

        # One value per (metric, period_label): SEC facts repeat the same period across filings; keep latest filing.
        by_metric_deduped: dict[str, list[dict]] = {}
        for mname, lst in by_metric.items():
            by_pl: dict[str, dict] = {}
            for item in sorted(lst, key=lambda x: x["filing_id"], reverse=True):
                pl = _period_label(item["fy"], item["fp"], item["period_end"])
                if pl not in by_pl:
                    by_pl[pl] = item
            by_metric_deduped[mname] = list(by_pl.values())

        inserted = 0
        for mname, lst in by_metric_deduped.items():
            for item in lst:
                v = item["value"]
                if mname == "capital_expenditure":
                    v = abs(v)
                pl = _period_label(item["fy"], item["fp"], item["period_end"])
                conn.execute(
                    """
                    INSERT INTO financial_metrics (raw_metric_id, metric_name, period_label, value, is_ttm, is_derived, derivation_formula, is_estimated, pulled_at)
                    VALUES (?, ?, ?, ?, 0, 0, NULL, 0, ?)
                    """,
                    (item["raw_id"], mname, pl, v, pulled_at),
                )
                inserted += 1

        _insert_debt_totals(conn, by_metric_deduped, pulled_at)
        _insert_ebitda(conn, pulled_at)
        _insert_effective_tax(conn, pulled_at)
        _insert_corporate_unallocated_derived(conn, pulled_at)
        _insert_lease_liabilities_total(conn, pulled_at)
        _insert_ttm_rows(conn, pulled_at)

    return {"financial_metrics_rows": inserted}


def _period_label(fy: Optional[int], fp: Optional[str], period_end: Optional[str]) -> str:
    if fy and fp == "FY":
        return f"FY{fy}"
    if fy and fp and fp.startswith("Q"):
        return f"{fp}FY{fy}"
    return period_end or "unknown"


def _insert_debt_totals(conn, by_metric: dict, pulled_at: str) -> None:
    """Sum debt components by period_end."""
    comps = ["long_term_debt_noncurrent", "short_term_borrowings", "long_term_debt_current"]
    ends: set[str] = set()
    for c in comps:
        for x in by_metric.get(c, []):
            if x["period_end"]:
                ends.add(x["period_end"])
    for end in sorted(ends):
        s = 0.0
        raw_ids = []
        for c in comps:
            for x in by_metric.get(c, []):
                if x["period_end"] == end:
                    s += x["value"]
                    raw_ids.append(x["raw_id"])
        if not raw_ids:
            continue
        conn.execute(
            """
            INSERT INTO financial_metrics (raw_metric_id, metric_name, period_label, value, is_ttm, is_derived, derivation_formula, is_estimated, pulled_at)
            VALUES (?, 'total_debt', ?, ?, 0, 1, 'LongTermDebtNoncurrent + ShortTermBorrowings + LongTermDebtCurrent (us-gaap tags)', 0, ?)
            """,
            (raw_ids[0], f"FY_end_{end}", s, pulled_at),
        )


def _insert_ebitda(conn, pulled_at: str) -> None:
    oi = {x["period_label"]: (x["value"], x["id"]) for x in _fm_rows(conn, "operating_income")}
    da = {x["period_label"]: (x["value"], x["id"]) for x in _fm_rows(conn, "depreciation_amortization")}
    for pl in set(oi) & set(da):
        ebitda = oi[pl][0] + da[pl][0]
        conn.execute(
            """
            INSERT INTO financial_metrics (raw_metric_id, metric_name, period_label, value, is_ttm, is_derived, derivation_formula, is_estimated, pulled_at)
            VALUES (?, 'ebitda', ?, ?, 0, 1, 'operating_income + depreciation_amortization', 0, ?)
            """,
            (oi[pl][1], pl, ebitda, pulled_at),
        )


def _insert_lease_liabilities_total(conn, pulled_at: str) -> None:
    """Sum operating + finance lease liabilities by FY period_label (capital structure adjustment)."""
    op = {x["period_label"]: x["value"] for x in _fm_rows(conn, "operating_lease_liability")}
    fn = {x["period_label"]: x["value"] for x in _fm_rows(conn, "finance_lease_liability")}
    if not op and not fn:
        return
    for pl in set(op) | set(fn):
        if not str(pl).startswith("FY"):
            continue
        s = float(op.get(pl, 0) or 0) + float(fn.get(pl, 0) or 0)
        conn.execute(
            """
            INSERT INTO financial_metrics (raw_metric_id, metric_name, period_label, value, is_ttm, is_derived, derivation_formula, is_estimated, pulled_at)
            VALUES (NULL, 'lease_liabilities_total', ?, ?, 0, 1, 'OperatingLeaseLiability + FinanceLeaseLiability (us-gaap)', 0, ?)
            """,
            (pl, s, pulled_at),
        )


def _insert_corporate_unallocated_derived(conn, pulled_at: str) -> None:
    """Corporate / elimination OI = consolidated operating income minus sum of segment OI (MSFT FY ends June 30)."""
    conn.execute("DELETE FROM financial_metrics WHERE metric_name = 'corporate_unallocated_oi'")
    rows = conn.execute(
        """
        SELECT period_label, value FROM financial_metrics
        WHERE metric_name = 'operating_income' AND period_label LIKE 'FY%'
        ORDER BY period_label DESC
        """
    ).fetchall()
    for pl, cons_oi in rows:
        if not pl.startswith("FY") or len(pl) < 6:
            continue
        try:
            fy_year = int(pl[2:6])
        except ValueError:
            continue
        period_end = f"{fy_year}-06-30"
        total_seg = 0.0
        missing = False
        for seg in SEGMENT_NAMES:
            row = conn.execute(
                """
                SELECT MAX(value) FROM segment_metrics
                WHERE segment_name = ? AND metric_name = 'segment_operating_income' AND period_label = ?
                """,
                (seg, period_end),
            ).fetchone()
            if row is None or row[0] is None:
                missing = True
                break
            total_seg += float(row[0])
        if missing:
            continue
        unalloc = float(cons_oi) - total_seg
        conn.execute(
            """
            INSERT INTO financial_metrics (raw_metric_id, metric_name, period_label, value, is_ttm, is_derived, derivation_formula, is_estimated, pulled_at)
            VALUES (NULL, 'corporate_unallocated_oi', ?, ?, 0, 1, ?, 0, ?)
            """,
            (
                pl,
                unalloc,
                "operating_income - sum(segment_operating_income) for FY period ending "
                + period_end
                + " (three reportable segments)",
                pulled_at,
            ),
        )


def _insert_effective_tax(conn, pulled_at: str) -> None:
    tax = {x["period_label"]: x["value"] for x in _fm_rows(conn, "income_tax_expense")}
    pre = {x["period_label"]: x["value"] for x in _fm_rows(conn, "income_before_tax")}
    for pl in set(tax) & set(pre):
        if abs(pre[pl]) < 1e-6:
            continue
        rate = tax[pl] / pre[pl]
        conn.execute(
            """
            INSERT INTO financial_metrics (raw_metric_id, metric_name, period_label, value, is_ttm, is_derived, derivation_formula, is_estimated, pulled_at)
            VALUES (NULL, 'effective_tax_rate', ?, ?, 0, 1, 'income_tax_expense / income_before_tax', 0, ?)
            """,
            (pl, rate, pulled_at),
        )


def _fm_rows(conn, name: str) -> list[dict]:
    cur = conn.execute(
        "SELECT id, period_label, value FROM financial_metrics WHERE metric_name = ? AND is_ttm = 0",
        (name,),
    )
    return [{"id": r[0], "period_label": r[1], "value": r[2]} for r in cur.fetchall()]


def _insert_ttm_rows(conn, pulled_at: str) -> None:
    """TTM per consolidated metric using FY + Q - Q_prior_year_same."""
    metrics = [
        "total_revenue",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "capital_expenditure",
        "depreciation_amortization",
        "interest_expense",
        "diluted_shares_outstanding",  # weighted average diluted; same TTM rule as other flow metrics
        "basic_shares_outstanding",
    ]
    raw_rows = conn.execute(
        """
        SELECT xbrl_tag, value, fiscal_year, fiscal_period, period_end
        FROM raw_metrics
        WHERE fiscal_year IS NOT NULL AND fiscal_period IS NOT NULL
        """
    ).fetchall()
    by_tag: dict[str, list] = defaultdict(list)
    for r in raw_rows:
        m = TAG_TO_METRIC.get(r["xbrl_tag"])
        if not m or m not in metrics:
            continue
        if r["value"] is None:
            continue
        by_tag[m].append(
            {
                "value": abs(float(r["value"])) if m == "capital_expenditure" else float(r["value"]),
                "fy": r["fiscal_year"],
                "fp": r["fiscal_period"],
                "end": r["period_end"],
            }
        )

    fp_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}

    def _qsort_key(x):
        return (x["fy"], fp_order.get(x["fp"], 0))

    for mname in metrics:
        lst = by_tag.get(mname, [])
        fy_rows = [x for x in lst if x["fp"] == "FY"]
        q_rows = [x for x in lst if x["fp"] and x["fp"].startswith("Q")]
        if not fy_rows or not q_rows:
            continue
        latest_q = max(q_rows, key=_qsort_key)
        annual_fy = latest_q["fy"] - 1
        fy_row = next((x for x in fy_rows if x["fy"] == annual_fy), None)
        if not fy_row:
            continue
        prior_q = next(
            (x for x in q_rows if x["fp"] == latest_q["fp"] and x["fy"] == latest_q["fy"] - 1),
            None,
        )
        if not prior_q:
            continue
        # TTM = most_recent_annual + latest_quarter - same_quarter_prior_year
        ttm_val = fy_row["value"] + latest_q["value"] - prior_q["value"]
        formula = (
            f"TTM = FY{annual_fy} annual + {latest_q['fp']}FY{latest_q['fy']} - {prior_q['fp']}FY{prior_q['fy']} "
            f"(annual + latest quarter - same quarter prior year)"
        )
        conn.execute(
            """
            INSERT INTO financial_metrics (raw_metric_id, metric_name, period_label, value, is_ttm, is_derived, derivation_formula, is_estimated, pulled_at)
            VALUES (NULL, ?, ?, ?, 1, 1, ?, 0, ?)
            """,
            (mname, f"TTM_{mname}", ttm_val, formula, pulled_at),
        )
