"""Deterministic assumption checks before DCF."""

from __future__ import annotations

from typing import Any, Optional


def run_checks(
    segment_margins_upside: dict[str, float],
    segment_margins_best_hist: dict[str, float],
    segment_growth_downside: dict[str, float],
    worst_historical_yoy_growth: dict[str, Optional[float]],
    terminal_growth: float,
    base_consolidated_revenue_growth: float,
) -> dict[str, Any]:
    issues = []
    for seg, m in segment_margins_upside.items():
        cap = segment_margins_best_hist.get(seg)
        if cap is not None and m - cap > 1e-6:
            issues.append(
                {
                    "rule": "upside_margin_cap",
                    "segment": seg,
                    "upside_margin": m,
                    "best_historical_margin": cap,
                }
            )
    for seg, g in segment_growth_downside.items():
        worst = worst_historical_yoy_growth.get(seg)
        if worst is None:
            continue
        floor = worst - 0.02
        if g < floor - 1e-9:
            issues.append(
                {
                    "rule": "downside_growth_floor",
                    "segment": seg,
                    "downside_growth": g,
                    "min_allowed": floor,
                }
            )
    # Only enforce when base revenue growth is a positive anchor; if segments imply contraction,
    # terminal g (floored for Gordon stability) cannot be compared to a negative base rate.
    if base_consolidated_revenue_growth > 0 and terminal_growth - base_consolidated_revenue_growth > 1e-6:
        issues.append(
            {
                "rule": "terminal_vs_base_growth",
                "terminal_growth": terminal_growth,
                "base_consolidated_revenue_growth": base_consolidated_revenue_growth,
            }
        )
    return {"passed": len(issues) == 0, "violations": issues}


def run_extended_checks(
    base_year_one_fcf: float,
    total_debt: float,
    ttm_operating_income: Optional[float],
    effective_tax_avg: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Additional guardrails: base-case FCF sign, tax band, leverage context (warning only).
    Returns (violations, warnings) — violations block the model run.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    # Negative bridge FCF is often a ratio-artifact (WC regression, Depreciation vs full D&A), not a solvency signal.
    # Block on tax band; surface negative FCF as a warning so the DCF still runs for review.
    if base_year_one_fcf < 0:
        warnings.append(
            {
                "rule": "base_year_one_fcf_negative",
                "value": base_year_one_fcf,
                "note": "Year-1 FCF from the bridge is negative; check WC coefficient, capex ratio, and D&A tag coverage vs cash flow statement.",
            }
        )

    if not (0.05 <= effective_tax_avg <= 0.45):
        violations.append(
            {
                "rule": "effective_tax_rate_out_of_range",
                "rate": effective_tax_avg,
                "allowed_band": "5% to 45% (historical effective rate from filings)",
            }
        )

    if ttm_operating_income is not None and ttm_operating_income > 1e-6:
        ratio = total_debt / ttm_operating_income
        if ratio > 3.0:
            warnings.append(
                {
                    "rule": "leverage_elevated_vs_ttm_operating_income",
                    "debt_to_ttm_operating_income": round(ratio, 2),
                    "note": "Book debt / TTM operating income > 3×; not a solvency test—review debt tags and OI.",
                }
            )

    return violations, warnings
