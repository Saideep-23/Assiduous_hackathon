"""Human-readable methodology for API consumers and judges."""

from __future__ import annotations

from financial.dcf_helpers import FORECAST_YEARS, TERMINAL_FADE_YEARS, TOTAL_EXPLICIT_YEARS

# Keep in sync with financial/engine.py
TERMINAL_GROWTH_CAP = 0.025
MIN_TERMINAL_GROWTH_FLOOR = 0.005
SYNTHETIC_RF_SPREAD_2Y_VS_10Y = 0.0045


def methodology_narrative() -> dict[str, str | list[str]]:
    """
    Structured narrative explaining modelling choices (not company-specific numbers).
    """
    return {
        "title": "Microsoft Corporate Finance Autopilot — valuation methodology",
        "summary": (
            "The model is a single-name (MSFT) discounted cash flow with segment-sourced growth and margin scenarios, "
            "explicit free cash flows, and a terminal value. It is deterministic: all dollar inputs come from ingestion "
            "or stated methodology constants; nothing is invented in the UI."
        ),
        "explicit_horizon": (
            f"The explicit revenue path uses {FORECAST_YEARS} years at scenario growth and margin assumptions, "
            f"followed by {TERMINAL_FADE_YEARS} years where revenue growth linearly fades toward the terminal growth rate "
            f"(total pre-perpetuity horizon = {TOTAL_EXPLICIT_YEARS} years). This reduces reliance on a single jump from "
            "year-5 revenue to a perpetuity versus a shorter explicit window."
        ),
        "terminal_growth_cap": (
            f"Long-run growth is capped at {TERMINAL_GROWTH_CAP:.1%} (TERMINAL_GROWTH_CAP). The terminal rate used is "
            f"the lesser of that cap and the base consolidated revenue growth implied by segments, floored at "
            f"{MIN_TERMINAL_GROWTH_FLOOR:.1%} for numerical stability in the Gordon growth formula (WACC − g > 0). "
            "The cap is a model discipline device—judges should treat terminal value as sensitive to g and WACC."
        ),
        "wacc_and_term_structure": (
            "Cost of equity uses CAPM with a stated US equity risk premium (Damodaran-style constant in code). "
            "The risk-free rate is interpolated between a short end (Treasury Bills average rate ingested as "
            "risk_free_rate_2y—legacy key name; not a broker 2Y CMT—otherwise 10Y minus a "
            f"fixed {SYNTHETIC_RF_SPREAD_2Y_VS_10Y:.2%} spread) and the ingested 10Y rate across the explicit horizon, "
            "so WACC varies by year instead of applying one long rate to every cash flow date. Cost of debt prefers a "
            "three-fiscal-year average of interest expense over total debt when aligned; otherwise TTM on book debt. "
            "Operating and finance lease liabilities (when ingested) are added to book debt for capital-structure weights."
        ),
        "working_capital": (
            "When Accounts Receivable, Inventory, and Accounts Payable (current) are available for the same fiscal "
            "labels as revenue, the model uses Δ(AR + Inventory − AP) / ΔRevenue for the NWC cash drag. Otherwise it "
            "falls back to Δ(Current assets − Current liabilities) / ΔRevenue. The operating definition better "
            "matches economic working capital for many industrials and tech names."
        ),
        "capex_and_segments": (
            "Consolidated capex is taken as a ratio to revenue from filings. For the DCF, that ratio is scaled by a "
            "revenue-weighted intensity factor that allocates higher capital intensity to the Intelligent Cloud segment "
            "(documented constant) to reflect that cloud infrastructure capex is often disproportionate to revenue share."
        ),
        "macro_stress": (
            "Macro-style scenarios combine (1) flat WACC shocks in basis points, (2) a proportional shock to revenue level "
            "for the entire path, and (3) a heuristic 'multiple compression' adjustment applied to the implied equity "
            "value. These are approximations for judge/demo use—not a full macro equilibrium model."
        ),
        "limitations_bullets": [
            "Segment iXBRL extraction depends on MSFT filing structure; ingestion logs warnings if parsing is thin.",
            "MSFT/SPY prices and beta come from Alpha Vantage; Treasury rates from Fiscal Data API — observation timestamps can lag real-time.",
            "The sensitivity grid uses a flat WACC per cell for speed; scenario valuations use the year-by-year WACC path.",
        ],
    }


def methodology_markdown() -> str:
    """Single markdown block for README or export."""
    d = methodology_narrative()
    lines = [f"# {d['title']}", "", str(d["summary"]), ""]
    for k in (
        "explicit_horizon",
        "terminal_growth_cap",
        "wacc_and_term_structure",
        "working_capital",
        "capex_and_segments",
        "macro_stress",
    ):
        lines.append(f"## {k.replace('_', ' ').title()}")
        lines.append(str(d[k]))
        lines.append("")
    lines.append("## Limitations")
    for b in d["limitations_bullets"]:
        lines.append(f"- {b}")
    return "\n".join(lines)
