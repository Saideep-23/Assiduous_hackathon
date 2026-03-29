"""
Pure DCF building blocks: term-structured WACC path, explicit + fade horizon, Gordon terminal.
"""

from __future__ import annotations

import math
from typing import Any

# Must match engine.py
FORECAST_YEARS = 7
TERMINAL_FADE_YEARS = 3
TOTAL_EXPLICIT_YEARS = FORECAST_YEARS + TERMINAL_FADE_YEARS
EQUITY_RISK_PREMIUM = 0.055


def growth_for_year(t: int, g_mix: float, g_terminal: float) -> float:
    """Year index t = 1..TOTAL_EXPLICIT_YEARS. Years 1..FORECAST_YEARS use g_mix; then linear fade to g_terminal."""
    if t <= FORECAST_YEARS:
        return g_mix
    k = t - FORECAST_YEARS
    return g_mix + (k / TERMINAL_FADE_YEARS) * (g_terminal - g_mix)


def build_wacc_path(
    rf_short: float,
    rf_long: float,
    beta: float,
    we: float,
    wd: float,
    rd: float,
    tax: float,
    *,
    flat_rf: bool = False,
) -> list[float]:
    """
    Interpolate risk-free rate from short to long end across explicit years; re_t = rf_t + beta*ERP; WACC each year.
    If flat_rf, rf_t = rf_long for all t (legacy single-rate behavior).
    """
    path: list[float] = []
    for t in range(1, TOTAL_EXPLICIT_YEARS + 1):
        if flat_rf:
            rft = rf_long
        else:
            span = max(TOTAL_EXPLICIT_YEARS - 1, 1)
            rft = rf_short + (t - 1) / span * (rf_long - rf_short)
        re_t = rft + beta * EQUITY_RISK_PREMIUM
        w_t = we * re_t + wd * rd * (1 - tax)
        path.append(w_t)
    return path


def discount_product(wacc_path: list[float], t: int) -> float:
    """Product (1+w_i) for i=0..t-1 (year-end discount to t)."""
    d = 1.0
    for i in range(t):
        d *= 1 + wacc_path[i]
    return d


def scenario_valuation(
    latest_rev: float,
    g_mix: float,
    m_bl: float,
    cu_ratio: float,
    tax_avg: float,
    da_pct: float,
    capex_pct: float,
    wc_pct: float,
    g_terminal: float,
    wacc_path: list[float],
    debt_for_net: float,
    cash_v: float,
    shares: float,
) -> dict[str, Any]:
    """
    Enterprise value from explicit + fade FCFs + Gordon terminal.
    WC drag uses each year's revenue growth gy (not constant g_mix).
    """
    if len(wacc_path) != TOTAL_EXPLICIT_YEARS:
        raise ValueError("wacc_path length mismatch")
    rev = latest_rev
    last_fcf = 0.0
    pv_fcfs = 0.0
    for t in range(1, TOTAL_EXPLICIT_YEARS + 1):
        gy = growth_for_year(t, g_mix, g_terminal)
        rev *= 1 + gy
        ebit = rev * m_bl - rev * cu_ratio
        nopat = ebit * (1 - tax_avg)
        fcf = nopat + rev * da_pct - rev * capex_pct - rev * wc_pct * gy
        last_fcf = fcf
        d = discount_product(wacc_path, t)
        pv_fcfs += fcf / d

    wacc_t = wacc_path[-1]
    denom_tv = wacc_t - g_terminal
    if denom_tv <= 0:
        return {"error": "terminal_denominator_non_positive", "wacc_terminal": wacc_t, "g_terminal": g_terminal}
    fcf_n1 = last_fcf * (1 + g_terminal)
    tv = fcf_n1 / denom_tv
    d_tv = discount_product(wacc_path, TOTAL_EXPLICIT_YEARS)
    pv_tv = tv / d_tv
    ev = pv_fcfs + pv_tv
    eq = ev - (debt_for_net - cash_v)
    implied_px = eq / shares if shares and shares > 0 else 0.0
    tv_pct = pv_tv / ev if ev > 0 else 0.0
    return {
        "pv_fcfs": pv_fcfs,
        "pv_tv": pv_tv,
        "ev": ev,
        "equity_value": eq,
        "implied_share_price": implied_px,
        "terminal_value_pct_of_ev": tv_pct,
        "last_explicit_fcf": last_fcf,
    }


def scenario_valuation_flat_wacc(
    latest_rev: float,
    g_mix: float,
    m_bl: float,
    cu_ratio: float,
    tax_avg: float,
    da_pct: float,
    capex_pct: float,
    wc_pct: float,
    g_terminal: float,
    wacc_flat: float,
    debt_for_net: float,
    cash_v: float,
    shares: float,
) -> dict[str, Any]:
    """Sensitivity grid: single WACC for all periods (matches prior 5×5 intuition)."""
    path = [wacc_flat] * TOTAL_EXPLICIT_YEARS
    return scenario_valuation(
        latest_rev,
        g_mix,
        m_bl,
        cu_ratio,
        tax_avg,
        da_pct,
        capex_pct,
        wc_pct,
        g_terminal,
        path,
        debt_for_net,
        cash_v,
        shares,
    )


def avg_cost_of_debt_from_aligned_fy(
    interest_rows: list[tuple[str, float]],
    debt_rows: list[tuple[str, float]],
) -> float | None:
    """Mean of |interest|/debt for FY rows that exist in both series (expects last-3 FY from engine)."""
    dmap = {pl: float(v) for pl, v in debt_rows}
    ratios: list[float] = []
    for pl, iv in interest_rows:
        dv = dmap.get(pl)
        if dv is not None and dv > 0 and math.isfinite(iv):
            ratios.append(abs(float(iv)) / dv)
    if len(ratios) < 3:
        return None
    return sum(ratios) / len(ratios)
