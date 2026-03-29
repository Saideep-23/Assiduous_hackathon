"""
Deterministic MSFT DCF: segment inputs, FCF bridge, WACC, terminal value, sensitisation.
All dollar inputs come from SQLite (ingestion); methodology constants are explicit below.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Optional

from database.connection import get_connection
from financial.consistency import run_checks, run_extended_checks
from financial.methodology import methodology_narrative
from financial.dcf_helpers import (
    FORECAST_YEARS,
    TERMINAL_FADE_YEARS,
    TOTAL_EXPLICIT_YEARS,
    avg_cost_of_debt_from_aligned_fy,
    build_wacc_path,
    scenario_valuation,
    scenario_valuation_flat_wacc,
)

# --- Model methodology (cited assumptions, not company-specific numbers) ---
EQUITY_RISK_PREMIUM = 0.055  # Damodaran US ERP (stated constant in API payload) — also in dcf_helpers
TERMINAL_GROWTH_CAP = 0.025
MIN_TERMINAL_GROWTH_FLOOR = 0.005  # Numerical floor for Gordon growth vs WACC spread
SYNTHETIC_RF_SPREAD_2Y_VS_10Y = 0.0045  # If 2Y Treasury not ingested, short RF = 10Y minus this spread

SEGMENTS = [
    "Productivity and Business Processes",
    "Intelligent Cloud",
    "More Personal Computing",
]

# Revenue-weighted capex intensity (cloud infrastructure is more capex-heavy than revenue share implies).
SEGMENT_CAPEX_INTENSITY: dict[str, float] = {
    "Productivity and Business Processes": 1.0,
    "Intelligent Cloud": 1.12,
    "More Personal Computing": 1.0,
}


def _compute_wc_coefficient(
    labels: list[str],
    revs: list[float],
    ac: dict[str, float],
    lc: dict[str, float],
    ar_rows: list[tuple[str, float]],
    inv_rows: list[tuple[str, float]],
    ap_rows: list[tuple[str, float]],
) -> tuple[float, str, dict[str, Any]]:
    """ΔNWC / ΔRevenue on last two FY; prefer operating WC (AR+Inv−AP) when aligned."""
    dr = revs[-1] - revs[-2]
    if abs(dr) < 1e-9:
        return 0.0, "ΔRevenue≈0", {"mode": "zero_delta_revenue"}

    ar = {pl: float(v) for pl, v in ar_rows}
    inv = {pl: float(v) for pl, v in inv_rows}
    apm = {pl: float(v) for pl, v in ap_rows}

    if (
        labels[-1] in ar
        and labels[-2] in ar
        and labels[-1] in inv
        and labels[-2] in inv
        and labels[-1] in apm
        and labels[-2] in apm
    ):

        def op_nwc(pl: str) -> float:
            return ar[pl] + inv[pl] - apm[pl]

        dnwc = op_nwc(labels[-1]) - op_nwc(labels[-2])
        wc_pct = dnwc / dr
        return wc_pct, "Δ(AR+Inventory−AP)/ΔRevenue", {
            "mode": "operating_working_capital",
            "nwc_fy_prev": op_nwc(labels[-2]),
            "nwc_fy_last": op_nwc(labels[-1]),
        }

    nwc_by = {pl: ac[pl] - lc[pl] for pl in labels}
    dnwc = nwc_by[labels[-1]] - nwc_by[labels[-2]]
    wc_pct = dnwc / dr
    return wc_pct, "Δ(CurrentAssets−CurrentLiabilities)/ΔRevenue", {
        "mode": "gross_current_assets_minus_liabilities",
    }


def _model_error(message: str, missing_fields: list[str]) -> dict[str, Any]:
    return {"error": {"message": message, "missing_fields": missing_fields}}


def _fy_from_period_end(pe: str) -> int:
    if not pe or len(pe) < 10:
        return 0
    y, m = int(pe[0:4]), int(pe[5:7])
    if m >= 7:
        return y + 1
    return y


def _load_consolidated(conn) -> dict[str, list[tuple[str, float]]]:
    cur = conn.execute(
        """
        SELECT metric_name, period_label, value FROM financial_metrics
        WHERE is_ttm = 0 AND metric_name IN (
          'total_revenue','operating_income','depreciation_amortization','capital_expenditure',
          'effective_tax_rate','corporate_unallocated_oi','interest_expense',
          'total_debt','cash_and_equivalents','assets_current','liabilities_current'
        )
        """
    )
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in cur.fetchall():
        if r[2] is not None and math.isfinite(float(r[2])):
            out[r[0]].append((r[1], float(r[2])))
    return out


def _load_segments(conn) -> dict[str, list[tuple[str, float, str]]]:
    cur = conn.execute(
        "SELECT segment_name, period_label, value, metric_name FROM segment_metrics WHERE is_ttm = 0"
    )
    out: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for r in cur.fetchall():
        if r[2] is not None and math.isfinite(float(r[2])):
            out[r[0]].append((r[1], float(r[2]), r[3]))
    return out


def _annualize_segments(
    seg_data: dict[str, list[tuple[str, float, str]]],
) -> dict[str, dict[int, dict[str, float]]]:
    by: dict[str, dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for seg, rows in seg_data.items():
        rev_by_fy: dict[int, list[tuple[str, float]]] = defaultdict(list)
        oi_by_fy: dict[int, list[tuple[str, float]]] = defaultdict(list)
        for pl, val, mn in rows:
            if not pl or "-" not in str(pl):
                continue
            fy = _fy_from_period_end(pl)
            if not fy:
                continue
            if mn == "segment_revenue":
                rev_by_fy[fy].append((pl, val))
            elif mn == "segment_operating_income":
                oi_by_fy[fy].append((pl, val))
        for fy, lst in rev_by_fy.items():
            best = max(lst, key=lambda x: x[0])
            by[seg][fy]["revenue"] = best[1]
        for fy, lst in oi_by_fy.items():
            best = max(lst, key=lambda x: x[0])
            by[seg][fy]["op_income"] = best[1]
    return by


def _cagr_strict(vals: list[tuple[int, float]]) -> float:
    if len(vals) < 2:
        raise ValueError("CAGR requires at least two fiscal years")
    vals = sorted(vals, key=lambda x: x[0])
    y0, v0 = vals[0]
    y1, v1 = vals[-1]
    n = y1 - y0
    if n <= 0 or v0 <= 0 or v1 <= 0:
        raise ValueError("Invalid CAGR inputs: need positive revenue and increasing FY span")
    return (v1 / v0) ** (1.0 / n) - 1.0


def _single_year_growth_rates(vals: list[tuple[int, float]]) -> list[float]:
    vals = sorted(vals, key=lambda x: x[0])
    g = []
    for i in range(1, len(vals)):
        _, v0 = vals[i - 1]
        _, v1 = vals[i]
        if v0 > 0:
            g.append(v1 / v0 - 1.0)
    return g


def _get_ttm(conn, metric_name: str) -> tuple[Optional[float], Optional[str]]:
    row = conn.execute(
        """
        SELECT value FROM financial_metrics
        WHERE metric_name=? AND is_ttm=1 ORDER BY id DESC LIMIT 1
        """,
        (metric_name,),
    ).fetchone()
    if not row or row[0] is None:
        return None, f"financial_metrics TTM {metric_name}"
    v = float(row[0])
    if not math.isfinite(v):
        return None, f"financial_metrics TTM {metric_name}"
    return v, None


def _latest_fy_metric(conn, metric_name: str) -> tuple[Optional[float], Optional[str]]:
    row = conn.execute(
        """
        SELECT value FROM financial_metrics
        WHERE metric_name=? AND is_ttm=0 AND period_label LIKE 'FY%'
        ORDER BY period_label DESC LIMIT 1
        """,
        (metric_name,),
    ).fetchone()
    if not row or row[0] is None:
        return None, f"financial_metrics latest FY {metric_name}"
    v = float(row[0])
    if not math.isfinite(v):
        return None, f"financial_metrics latest FY {metric_name}"
    return v, None


def _fy_year_sort_key(period_label: str) -> int:
    if period_label.startswith("FY") and len(period_label) >= 6:
        try:
            return int(period_label[2:6])
        except ValueError:
            return 0
    return 0


def _fy_vals(conn, metric: str) -> list[tuple[str, float]]:
    cur = conn.execute(
        """
        SELECT period_label, value FROM financial_metrics
        WHERE metric_name=? AND is_ttm=0 AND period_label LIKE 'FY%'
        """,
        (metric,),
    )
    out: list[tuple[str, float]] = []
    for pl, val in cur.fetchall():
        if val is None or not math.isfinite(float(val)):
            continue
        out.append((pl, float(val)))
    out.sort(key=lambda x: _fy_year_sort_key(x[0]))
    return out[-3:]


def _require_market_data(conn) -> tuple[Optional[dict[str, tuple[float, int]]], list[str]]:
    rows = conn.execute(
        """
        SELECT metric_name, value, is_stale FROM market_data
        WHERE ticker='MSFT' AND metric_name IN ('risk_free_rate_10y','beta_5y_monthly','spot_price')
        """
    ).fetchall()
    md: dict[str, tuple[float, int]] = {}
    missing: list[str] = []
    for name in ("risk_free_rate_10y", "beta_5y_monthly", "spot_price"):
        found = None
        for r in rows:
            if r[0] == name and r[1] is not None:
                found = (float(r[1]), int(r[2]))
                break
        if found is None or not math.isfinite(found[0]):
            missing.append(f"market_data MSFT {name}")
        else:
            md[name] = found
    if missing:
        return None, missing
    return md, []


def build_model() -> dict[str, Any]:
    missing: list[str] = []
    rf_2y_observed: Optional[float] = None
    lease_liab_latest = 0.0
    basic_shares_opt: Optional[float] = None

    with get_connection() as conn:
        ttm_rev, e = _get_ttm(conn, "total_revenue")
        if e:
            missing.append(e)
        ttm_oi, e_oi = _get_ttm(conn, "operating_income")
        if e_oi:
            missing.append(e_oi)
        shares, e2 = _get_ttm(conn, "diluted_shares_outstanding")
        if e2:
            missing.append(e2)
        interest, e3 = _get_ttm(conn, "interest_expense")
        if e3:
            missing.append(e3)
        debt, e4 = _latest_fy_metric(conn, "total_debt")
        if e4:
            missing.append(e4)
        cash_v, e5 = _latest_fy_metric(conn, "cash_and_equivalents")
        if e5:
            missing.append(e5)

        md, md_miss = _require_market_data(conn)
        missing.extend(md_miss)

        row_rf2 = conn.execute(
            "SELECT value FROM market_data WHERE ticker='MSFT' AND metric_name='risk_free_rate_2y'"
        ).fetchone()
        if row_rf2 and row_rf2[0] is not None and math.isfinite(float(row_rf2[0])):
            rf_2y_observed = float(row_rf2[0])
        row_lease = conn.execute(
            """
            SELECT value FROM financial_metrics WHERE metric_name='lease_liabilities_total'
            AND is_ttm=0 AND period_label LIKE 'FY%' ORDER BY period_label DESC LIMIT 1
            """
        ).fetchone()
        if row_lease and row_lease[0] is not None and math.isfinite(float(row_lease[0])):
            lease_liab_latest = float(row_lease[0])
        row_basic = conn.execute(
            """
            SELECT value FROM financial_metrics WHERE metric_name='basic_shares_outstanding'
            AND is_ttm=1 ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if row_basic and row_basic[0] is not None and math.isfinite(float(row_basic[0])):
            basic_shares_opt = float(row_basic[0])

        cons = _load_consolidated(conn)
        seg_raw = _load_segments(conn)
        seg_ann = _annualize_segments(seg_raw)

    if missing:
        return _model_error("Incomplete ingested data required for the DCF model.", sorted(set(missing)))

    assert ttm_rev is not None and ttm_oi is not None and shares is not None and interest is not None
    assert debt is not None and cash_v is not None and md is not None
    latest_rev = ttm_rev
    if latest_rev <= 0 or shares <= 0:
        return _model_error("TTM revenue and diluted shares must be positive.", [])

    rf, rf_stale = md["risk_free_rate_10y"]
    beta, b_stale = md["beta_5y_monthly"]
    price, _ = md["spot_price"]
    if price <= 0:
        return _model_error("Spot price from market_data must be positive.", [])

    hist: dict[str, Any] = {}
    proj: dict[str, Any] = {}

    for seg in SEGMENTS:
        sdat = seg_ann.get(seg, {})
        years_all = sorted(sdat.keys())
        if len(years_all) < 3:
            return _model_error(
                f"Segment {seg!r} needs at least three fiscal years with segment revenue and operating income.",
                [f"segment_metrics:{seg}"],
            )
        tail = years_all[-4:] if len(years_all) >= 4 else years_all
        rev: list[tuple[int, float]] = []
        margins_list: list[float] = []
        for y in tail:
            d = sdat.get(y, {})
            if "revenue" not in d or "op_income" not in d:
                continue
            if d["revenue"] <= 0:
                return _model_error(
                    f"Segment {seg!r} has non-positive revenue for a fiscal year in the model window.",
                    [f"segment_metrics:{seg}"],
                )
            rev.append((y, d["revenue"]))
            margins_list.append(d["op_income"] / d["revenue"])
        if len(rev) < 3:
            return _model_error(
                f"Segment {seg!r} needs revenue and operating income for at least three fiscal years.",
                [f"segment_metrics:{seg}"],
            )
        rev3 = rev[-3:]
        margs3 = margins_list[-3:]
        if len(margs3) < 3:
            return _model_error(
                f"Segment {seg!r} needs three operating margins in the trailing window.",
                [f"segment_metrics:{seg}"],
            )

        try:
            cagr_b = _cagr_strict(rev3)
        except ValueError as ex:
            return _model_error(f"Segment {seg!r}: {ex}", [f"segment_metrics:{seg}"])

        syr = _single_year_growth_rates(rev3)
        if syr:
            best_g, worst_g = max(syr), min(syr)
        else:
            best_g = worst_g = cagr_b

        m_base = sum(margs3) / 3
        m_up, m_dn = max(margs3), min(margs3)

        hist[seg] = {"revenue_series": rev, "margins": margins_list}
        proj[seg] = {
            "base_growth": cagr_b,
            "upside_growth": best_g,
            "downside_growth": worst_g,
            "base_margin": m_base,
            "upside_margin": m_up,
            "downside_margin": m_dn,
        }

    tw = 0.0
    wsum = 0.0
    for seg in SEGMENTS:
        revs = hist[seg]["revenue_series"]
        if not revs:
            return _model_error(f"Segment {seg!r} has no revenue series.", [f"segment_metrics:{seg}"])
        last_r = revs[-1][1]
        wsum += last_r * proj[seg]["base_growth"]
        tw += last_r
    if tw <= 0:
        return _model_error("Consolidated segment revenue weights sum to zero.", [])

    base_growth_consolidated = wsum / tw

    terminal_growth_used = min(TERMINAL_GROWTH_CAP, base_growth_consolidated - 1e-6)
    if terminal_growth_used < MIN_TERMINAL_GROWTH_FLOOR:
        terminal_growth_used = MIN_TERMINAL_GROWTH_FLOOR

    worst_yoy: dict[str, Optional[float]] = {}
    for s in SEGMENTS:
        rs = hist[s]["revenue_series"]
        glist = _single_year_growth_rates(rs) if len(rs) >= 2 else []
        worst_yoy[s] = min(glist) if glist else None

    chk = run_checks(
        {s: proj[s]["upside_margin"] for s in SEGMENTS},
        {s: max(hist[s]["margins"]) if hist[s]["margins"] else proj[s]["upside_margin"] for s in SEGMENTS},
        {s: proj[s]["downside_growth"] for s in SEGMENTS},
        worst_yoy,
        terminal_growth_used,
        base_growth_consolidated,
    )

    if not chk["passed"]:
        return {
            "error": {"message": "Consistency checks failed", "violations": chk["violations"]},
            "consistency_checks": chk,
        }

    with get_connection() as conn:
        tr_all = conn.execute(
            "SELECT period_label, value FROM financial_metrics WHERE metric_name='total_revenue' AND is_ttm=0 AND period_label LIKE 'FY%'"
        ).fetchall()
        tr_map = {a: float(b) for a, b in tr_all if b is not None and math.isfinite(float(b))}
        cu = conn.execute(
            "SELECT period_label, value FROM financial_metrics WHERE metric_name='corporate_unallocated_oi' AND is_ttm=0 AND period_label LIKE 'FY%'"
        ).fetchall()

        def fy_vals_named(metric: str) -> list[tuple[str, float]]:
            return _fy_vals(conn, metric)

        rev_rows = fy_vals_named("total_revenue")
        da_rows = fy_vals_named("depreciation_amortization")
        tax_rows = fy_vals_named("effective_tax_rate")
        capex_rows = fy_vals_named("capital_expenditure")
        ac_rows = fy_vals_named("assets_current")
        lc_rows = fy_vals_named("liabilities_current")
        int_fy_rows = fy_vals_named("interest_expense")
        debt_fy_rows = fy_vals_named("total_debt")
        ar_rows = fy_vals_named("accounts_receivable_net")
        inv_rows = fy_vals_named("inventory_net")
        ap_rows = fy_vals_named("accounts_payable_current")

    need3 = [
        ("total_revenue", rev_rows),
        ("depreciation_amortization", da_rows),
        ("effective_tax_rate", tax_rows),
        ("capital_expenditure", capex_rows),
        ("assets_current", ac_rows),
        ("liabilities_current", lc_rows),
    ]
    miss_fcf: list[str] = []
    for name, rows in need3:
        if len(rows) != 3:
            miss_fcf.append(f"financial_metrics FY last-3 {name} (have {len(rows)}, need 3)")
    if miss_fcf:
        return _model_error("FCF bridge requires exactly three fiscal years for each consolidated input.", miss_fcf)

    labels = [r[0] for r in rev_rows]
    ac = dict(ac_rows)
    lc = dict(lc_rows)
    for pl in labels:
        if pl not in ac or pl not in lc:
            return _model_error(
                "assets_current and liabilities_current must cover the same three FY labels as total_revenue.",
                [pl],
            )

    ratios_cu: list[float] = []
    for pl, v in sorted(cu, key=lambda x: x[0]):
        if pl not in tr_map or tr_map[pl] <= 0:
            continue
        if v is None:
            continue
        ratios_cu.append(abs(float(v)) / tr_map[pl])
    if len(ratios_cu) < 3:
        return _model_error(
            "Need corporate_unallocated_oi with matching total_revenue for at least three fiscal years.",
            ["corporate_unallocated_oi vs total_revenue"],
        )
    cu_ratio = sum(ratios_cu[-3:]) / 3

    revs = [float(x[1]) for x in rev_rows]
    das = [float(x[1]) for x in da_rows]
    taxes = [float(x[1]) for x in tax_rows]
    capexs = [abs(float(x[1])) for x in capex_rows]

    if any(r <= 0 for r in revs):
        return _model_error("Last-three-FY total revenue must be positive each year.", [])

    da_pct = sum(das[i] / revs[i] for i in range(3)) / 3
    tax_avg = sum(taxes) / 3
    capex_pct = sum(capexs[i] / revs[i] for i in range(3)) / 3

    total_seg_rev = sum(hist[s]["revenue_series"][-1][1] for s in SEGMENTS)
    capex_intensity_blend = sum(
        (hist[s]["revenue_series"][-1][1] / total_seg_rev) * SEGMENT_CAPEX_INTENSITY.get(s, 1.0)
        for s in SEGMENTS
    )
    capex_pct_dcf = capex_pct * capex_intensity_blend

    wc_pct, wc_formula, wc_detail = _compute_wc_coefficient(labels, revs, ac, lc, ar_rows, inv_rows, ap_rows)

    wc_warnings: list[dict[str, Any]] = []
    wc_pct_raw = wc_pct
    if math.isfinite(wc_pct) and abs(wc_pct) > 0.4:
        wc_pct = max(-0.4, min(0.4, wc_pct))
        wc_detail = {**wc_detail, "wc_pct_raw": wc_pct_raw, "wc_pct_clamped": wc_pct}
        wc_warnings.append(
            {
                "rule": "wc_coefficient_clamped",
                "wc_pct_raw": wc_pct_raw,
                "wc_pct_used": wc_pct,
                "note": "|ΔNWC/ΔRevenue| capped at 0.4 to limit ratio noise from small FY-to-FY revenue changes.",
            }
        )

    g_mix_b = sum(proj[s]["base_growth"] for s in SEGMENTS) / len(SEGMENTS)
    m_bl_b = sum(proj[s]["base_margin"] for s in SEGMENTS) / len(SEGMENTS)
    rev_y1 = latest_rev * (1 + g_mix_b)
    ebit_y1 = rev_y1 * m_bl_b - rev_y1 * cu_ratio
    nopat_y1 = ebit_y1 * (1 - tax_avg)
    fcf_year1_base = nopat_y1 + rev_y1 * da_pct - rev_y1 * capex_pct_dcf - rev_y1 * wc_pct * g_mix_b

    ext_violations, model_warnings = run_extended_checks(fcf_year1_base, debt, ttm_oi, tax_avg)
    model_warnings = wc_warnings + model_warnings
    if ext_violations:
        return {
            "error": {"message": "Extended consistency checks failed", "violations": ext_violations},
            "consistency_checks": chk,
        }

    fcf_tree = {
        "steps": [
            {"name": "D&A add-back", "ratio": da_pct, "source_periods": "last 3 FY", "formula": "avg(D&A / Revenue)"},
            {"name": "Tax on EBIT", "rate": tax_avg, "source_periods": "last 3 FY effective_tax_rate", "formula": "effective tax from EDGAR"},
            {
                "name": "Capex (consolidated ratio × segment intensity)",
                "ratio_consolidated": capex_pct,
                "ratio_in_dcf": capex_pct_dcf,
                "segment_intensity_blend": capex_intensity_blend,
                "source_periods": "last 3 FY",
                "formula": "avg(|Capex|/Revenue) × revenue-weighted segment intensity (cloud uplift)",
            },
            {
                "name": "Change in NWC",
                "ratio_of_revenue_change": wc_pct,
                "source_periods": "last 2 FY in the FY3 window",
                "formula": wc_formula,
                "detail": wc_detail,
            },
        ],
        "nwc_methodology": {
            "mode": wc_detail.get("mode"),
            "balance_sheet_proxy": "Prefer AR + Inventory − AP (us-gaap tags) when all three align on FY labels; else current_assets − current_liabilities.",
            "interpretation": "ΔNWC / ΔRevenue on the last two fiscal years in the revenue window.",
            "capex_in_dcf": "Capex cash drag uses segment-intensity-adjusted ratio so Intelligent Cloud bears a higher share of consolidated capex.",
        },
    }

    debt_cap = float(debt) + float(lease_liab_latest)
    rd_3fy = avg_cost_of_debt_from_aligned_fy(int_fy_rows, debt_fy_rows)
    rd_source = "ttm_interest_over_latest_fy_debt"
    if debt > 0:
        rd_ttm = abs(interest) / float(debt)
        if not math.isfinite(rd_ttm):
            return _model_error("Cost of debt could not be computed from interest and total debt.", [])
        if rd_3fy is not None and math.isfinite(rd_3fy):
            rd = rd_3fy
            rd_source = "three_fy_avg_interest_over_debt"
        else:
            rd = rd_ttm
    else:
        if abs(interest) > 1e-3 * max(1.0, abs(ttm_rev)):
            return _model_error(
                "Interest expense is material but total_debt is zero; reconcile debt tags before WACC.",
                ["interest_expense vs total_debt"],
            )
        rd = 0.0
        rd_source = "zero_debt"

    rf_short = rf_2y_observed if rf_2y_observed is not None else (rf - SYNTHETIC_RF_SPREAD_2Y_VS_10Y)
    rf_short_source = "market_data_2y" if rf_2y_observed is not None else "synthetic_10y_minus_spread"

    re = rf + beta * EQUITY_RISK_PREMIUM
    mcap = price * shares
    tax_c = tax_avg
    denom = mcap + debt_cap
    if denom <= 0:
        return _model_error("Market cap + debt (incl. lease liabilities) must be positive for WACC weights.", [])
    wd = debt_cap / denom
    we = mcap / denom

    wacc_path_base = build_wacc_path(rf_short, rf, beta, we, wd, rd, tax_c, flat_rf=False)
    wacc_headline = sum(wacc_path_base) / len(wacc_path_base)

    scenarios_out: dict[str, Any] = {}
    for scen, gk, mk in [
        ("Base", "base_growth", "base_margin"),
        ("Upside", "upside_growth", "upside_margin"),
        ("Downside", "downside_growth", "downside_margin"),
    ]:
        g_mix = sum(proj[s][gk] for s in SEGMENTS) / len(SEGMENTS)
        m_bl = sum(proj[s][mk] for s in SEGMENTS) / len(SEGMENTS)
        out = scenario_valuation(
            latest_rev,
            g_mix,
            m_bl,
            cu_ratio,
            tax_avg,
            da_pct,
            capex_pct_dcf,
            wc_pct,
            terminal_growth_used,
            wacc_path_base,
            debt_cap,
            cash_v,
            shares,
        )
        if out.get("error"):
            return _model_error(
                "Terminal value denominator (WACC − g) is not positive; check rates and terminal growth.",
                ["wacc", "terminal_growth"],
            )
        implied_px = float(out["implied_share_price"])
        tv_pct = float(out["terminal_value_pct_of_ev"])
        disc = (implied_px - price) / price if price else 0.0
        scenarios_out[scen] = {
            "implied_share_price": round(implied_px, 2),
            "premium_discount_to_spot_pct": round(disc * 100, 2),
            "terminal_value_pct_of_ev": round(tv_pct * 100, 2),
            "key_assumptions": [
                {
                    "segment": s,
                    "growth": proj[s][gk],
                    "margin": proj[s][mk],
                    "growth_source": "Trailing segment revenue (last 3 FY): CAGR and YoY extrema where available",
                }
                for s in SEGMENTS
            ],
        }

    wacc_steps = [wacc_headline - 0.015 + i * 0.0075 for i in range(5)]
    tg_steps = [0.015 + i * 0.005 for i in range(5)]
    grid: list[list[float]] = []
    for wi in wacc_steps:
        row = []
        for tj in tg_steps:
            out_ij = scenario_valuation_flat_wacc(
                latest_rev,
                g_mix_b,
                m_bl_b,
                cu_ratio,
                tax_avg,
                da_pct,
                capex_pct_dcf,
                wc_pct,
                tj,
                wi,
                debt_cap,
                cash_v,
                shares,
            )
            if out_ij.get("error"):
                row.append(0.0)
            else:
                row.append(round(float(out_ij["implied_share_price"]), 2))
        grid.append(row)

    wacc_degraded = bool(rf_stale or b_stale)

    segment_capex_proxy: list[dict[str, Any]] = []
    for s in SEGMENTS:
        r_s = hist[s]["revenue_series"][-1][1]
        w_share = r_s / total_seg_rev if total_seg_rev > 0 else 0.0
        intensity = SEGMENT_CAPEX_INTENSITY.get(s, 1.0)
        segment_capex_proxy.append(
            {
                "segment": s,
                "revenue_share": round(w_share, 4),
                "capex_intensity": intensity,
                "implied_capex_proxy_ttm": round(latest_rev * capex_pct * w_share * intensity, 2),
            }
        )

    stress_scenarios: dict[str, Any] = {}
    for key, w_shock, g_shock in (
        ("wacc_plus_200bps", 0.02, 0.0),
        ("wacc_plus_100bps", 0.01, 0.0),
        ("terminal_growth_minus_100bps", 0.0, -0.01),
    ):
        tg_s = max(MIN_TERMINAL_GROWTH_FLOOR, terminal_growth_used + g_shock)
        out_s = scenario_valuation_flat_wacc(
            latest_rev,
            g_mix_b,
            m_bl_b,
            cu_ratio,
            tax_avg,
            da_pct,
            capex_pct_dcf,
            wc_pct,
            tg_s,
            wacc_headline + w_shock,
            debt_cap,
            cash_v,
            shares,
        )
        if not out_s.get("error"):
            stress_scenarios[key] = {
                "implied_share_price": round(float(out_s["implied_share_price"]), 2),
                "description": f"WACC +{w_shock * 10000:.0f} bps vs headline; terminal g delta {g_shock:+.2%} vs base terminal",
            }

    macro_stress_extended: dict[str, Any] = {}
    out_rev15 = scenario_valuation(
        latest_rev * 0.85,
        g_mix_b,
        m_bl_b,
        cu_ratio,
        tax_avg,
        da_pct,
        capex_pct_dcf,
        wc_pct,
        terminal_growth_used,
        wacc_path_base,
        debt_cap,
        cash_v,
        shares,
    )
    if not out_rev15.get("error"):
        macro_stress_extended["revenue_level_minus_15pct"] = {
            "implied_share_price": round(float(out_rev15["implied_share_price"]), 2),
            "description": "TTM revenue anchor scaled to 85%; segment growth/margins and ratios unchanged vs base path.",
        }
    base_px = float(scenarios_out["Base"]["implied_share_price"])
    macro_stress_extended["multiple_compression_heuristic_18pct_equity_haircut"] = {
        "implied_share_price": round(base_px * 0.82, 2),
        "description": "Heuristic: 18% haircut to base-case implied price as proxy for P/E multiple compression (not a second DCF).",
    }
    out_rates400 = scenario_valuation_flat_wacc(
        latest_rev,
        g_mix_b,
        m_bl_b,
        cu_ratio,
        tax_avg,
        da_pct,
        capex_pct_dcf,
        wc_pct,
        terminal_growth_used,
        wacc_headline + 0.04,
        debt_cap,
        cash_v,
        shares,
    )
    if not out_rates400.get("error"):
        macro_stress_extended["rates_plus_400bps_flat_wacc"] = {
            "implied_share_price": round(float(out_rates400["implied_share_price"]), 2),
            "description": "Flat WACC +400 bps vs headline mean (severe rate shock).",
        }

    base_disc = float(scenarios_out["Base"]["premium_discount_to_spot_pct"])
    if base_disc > 15:
        pg = (
            "Base-case implied price is materially above spot — the model suggests potential upside vs. these "
            "assumptions; sizing remains judgmental and this is not investment advice."
        )
    elif base_disc < -15:
        pg = (
            "Base-case implied price is materially below spot — the model reads rich vs. base assumptions "
            "relative to market; interpret with care."
        )
    else:
        pg = "Base-case implied vs spot is in a moderate band — no strong heuristic sizing signal alone."

    dilution_analysis = None
    if basic_shares_opt is not None and basic_shares_opt > 0 and shares > 0:
        dilution_analysis = {
            "basic_shares_ttm": basic_shares_opt,
            "diluted_shares_ttm": shares,
            "dilution_pct_vs_basic": round((shares - basic_shares_opt) / basic_shares_opt * 100, 3),
        }

    methodology_notes = [
        f"Explicit horizon: {FORECAST_YEARS} years at segment growth, then {TERMINAL_FADE_YEARS} years "
        f"linear fade of growth toward terminal g, then Gordon perpetuity (total explicit + fade = {TOTAL_EXPLICIT_YEARS} years).",
        f"Risk-free term structure: interpolate short ({rf_short_source}) to 10Y ingested rate for each year’s cost of equity; "
        "WACC varies by year before terminal.",
        f"Cost of debt: {rd_source} (see wacc_components).",
        "Lease liabilities (Operating + Finance, when ingested) are added to book debt for capital-structure weights and net debt.",
        "Diluted shares from GAAP diluted weighted average; basic vs diluted share analysis is in share_count_analysis when basic is ingested.",
        "Terminal value remains sensitive to WACC − g; see terminal_value_pct_of_ev per scenario.",
        "NWC cash drag: when AR, inventory, and AP align with revenue on fiscal labels, coefficient uses Δ(AR + Inventory − AP)/ΔRevenue; else consolidated current assets minus current liabilities.",
        "Capex in FCF: consolidated capex/revenue is scaled by a revenue-weighted segment intensity blend (higher for Intelligent Cloud) — see fcf_bridge_tree and segment_capex_proxy.",
    ]

    return {
        "scenarios": scenarios_out,
        "model_warnings": model_warnings,
        "stress_scenarios": stress_scenarios,
        "macro_stress_extended": macro_stress_extended,
        "methodology_narrative": methodology_narrative(),
        "position_guidance": {
            "summary": pg,
            "disclaimer": "Educational heuristic only; not investment advice.",
        },
        "segment_capex_proxy": segment_capex_proxy,
        "methodology_notes": methodology_notes,
        "wacc_components": {
            "risk_free_rate_10y": rf,
            "risk_free_rate_short_for_curve": rf_short,
            "risk_free_short_source": rf_short_source,
            "beta_5y_monthly": beta,
            "equity_risk_premium": EQUITY_RISK_PREMIUM,
            "cost_of_equity_capm_spot": re,
            "cost_of_debt": rd,
            "cost_of_debt_source": rd_source,
            "interest_expense_tag": "us-gaap:InterestExpense",
            "total_debt_book": float(debt),
            "lease_liabilities_latest_fy": lease_liab_latest,
            "debt_for_capital_structure": debt_cap,
            "total_debt_components": "LongTermDebtNoncurrent + ShortTermBorrowings + LongTermDebtCurrent + lease liabilities",
            "tax_rate_for_wacc": tax_c,
            "weight_equity_market_cap": we,
            "weight_debt_book_incl_leases": wd,
            "wacc": wacc_headline,
            "wacc_path_mean": wacc_headline,
            "wacc_year1": wacc_path_base[0],
            "wacc_terminal_year": wacc_path_base[-1],
            "explicit_years": FORECAST_YEARS,
            "terminal_fade_years": TERMINAL_FADE_YEARS,
            "total_explicit_years_before_perpetuity": TOTAL_EXPLICIT_YEARS,
            "wacc_degraded_warning": wacc_degraded,
        },
        "share_count_analysis": dilution_analysis,
        "fcf_bridge_tree": fcf_tree,
        "assumptions_table": [
            {
                "input": "Explicit forecast years",
                "value": FORECAST_YEARS,
                "source": "FCF projection length before terminal value",
                "classification": "model_assumption",
            },
            {
                "input": "Terminal growth cap",
                "value": TERMINAL_GROWTH_CAP,
                "source": "Model cap on long-run growth (stated assumption)",
                "classification": "model_assumption",
            },
            {
                "input": "Terminal growth used",
                "value": terminal_growth_used,
                "source": f"min(cap {TERMINAL_GROWTH_CAP}, base revenue growth) floored at {MIN_TERMINAL_GROWTH_FLOOR} for stability",
                "classification": "model_assumption",
            },
            {
                "input": "ERP (Damodaran US)",
                "value": EQUITY_RISK_PREMIUM,
                "source": "Stated equity risk premium constant",
                "classification": "model_assumption",
            },
            {
                "input": "Corporate unallocated ratio",
                "value": cu_ratio,
                "source": "|unallocated OI| / revenue (last 3 FY pairs)",
                "classification": "historical_average",
            },
            {
                "input": "Risk-free rate series",
                "value": rf,
                "source": "US Treasury Fiscal Data avg_interest_rates (Treasury Notes) → stored as risk_free_rate_10y",
                "classification": "ingested_market",
            },
        ],
        "sensitisation": {"wacc_axis": wacc_steps, "terminal_growth_axis": tg_steps, "implied_share_price_grid": grid},
        "consistency_checks": chk,
        "segment_inputs": proj,
        "historical_snapshot": hist,
    }
