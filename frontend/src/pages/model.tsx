import React, { useEffect, useState } from "react";
import { fetchJson } from "@/lib/api";
import { ScenarioCard } from "@/components/ScenarioCard";
import { SensitisationTable } from "@/components/SensitisationTable";
import { FCFBridge } from "@/components/FCFBridge";
import { AssumptionsTable } from "@/components/AssumptionsTable";

function downloadSensitivityCsv(
  waccAxis: number[],
  tgAxis: number[],
  grid: number[][],
) {
  const header = ["WACC \\ terminal g", ...tgAxis.map((g) => `${(g * 100).toFixed(1)}%`)];
  const rows = grid.map((row, i) => [`${(waccAxis[i] * 100).toFixed(2)}%`, ...row.map((c) => String(c))]);
  const body = [header.join(","), ...rows.map((r) => r.join(","))].join("\n");
  const blob = new Blob([body], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "msft_sensitivity_grid.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function ModelPage() {
  const [m, setM] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const run = () => {
    setLoading(true);
    setErr(null);
    fetchJson<Record<string, unknown>>("/model/msft", { method: "POST" })
      .then(setM)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    run();
  }, []);

  if (!loading && err && !m) {
    return (
      <main className="page">
        <div className="page-hero">
          <h1>Model</h1>
          <p className="lead">Could not reach the API.</p>
        </div>
        <p className="stale">{err}</p>
        <button type="button" className="btn btn-primary" onClick={run}>
          Retry
        </button>
      </main>
    );
  }

  if (loading && !m) {
    return (
      <main className="page">
        <div className="page-hero">
          <h1>Valuation model</h1>
          <p className="lead">Running deterministic DCF, WACC, and sensitivity…</p>
        </div>
        <div className="section-card">
          <div className="skeleton skeleton-line" style={{ width: "60%" }} />
          <div className="skeleton skeleton-block" />
        </div>
      </main>
    );
  }

  if (m?.error) {
    return (
      <main className="page">
        <div className="page-hero">
          <h1>Model</h1>
          <p className="lead">The model refused to run until data checks pass.</p>
        </div>
        <div className="section-card" style={{ borderColor: "rgba(248, 113, 113, 0.35)" }}>
          <pre className="stale" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: "0.85rem" }}>
            {JSON.stringify(m.error, null, 2)}
          </pre>
        </div>
        <button type="button" className="btn btn-primary" onClick={run}>
          Retry
        </button>
      </main>
    );
  }

  const scenarios = m?.scenarios as Record<string, Record<string, unknown>> | undefined;
  const sens = m?.sensitisation as
    | { wacc_axis: number[]; terminal_growth_axis: number[]; implied_share_price_grid: number[][] }
    | undefined;
  const wacc = m?.wacc_components as Record<string, unknown> | undefined;
  const tvWarn =
    scenarios && Object.values(scenarios).some((s) => Number(s.terminal_value_pct_of_ev) > 70);

  const methodologyNotes = m?.methodology_notes as string[] | undefined;
  const modelWarnings = m?.model_warnings as { rule?: string; note?: string }[] | undefined;
  const stressScenarios = m?.stress_scenarios as Record<string, { implied_share_price?: number; description?: string }> | undefined;
  const macroStressExtended = m?.macro_stress_extended as
    | Record<string, { implied_share_price?: number; description?: string }>
    | undefined;
  const methodologyNarrative = m?.methodology_narrative as Record<string, unknown> | undefined;
  const positionGuidance = m?.position_guidance as { summary?: string; disclaimer?: string } | undefined;
  const segmentCapexProxy = m?.segment_capex_proxy as { segment: string; revenue_share: number; implied_capex_proxy_ttm: number }[] | undefined;
  const shareCountAnalysis = m?.share_count_analysis as Record<string, unknown> | null | undefined;

  const scenarioOrder: { key: "Base" | "Upside" | "Downside"; variant: "base" | "upside" | "downside" }[] = [
    { key: "Base", variant: "base" },
    { key: "Upside", variant: "upside" },
    { key: "Downside", variant: "downside" },
  ];

  return (
    <main className="page">
      <div className="page-hero">
        <h1>Deterministic valuation</h1>
        <p className="lead">
          DCF with term-structured WACC (short→long RF), explicit years plus a terminal-growth fade, lease-adjusted debt
          weights when lease liabilities are ingested, and macro-style stress checks. Export the sensitivity grid as CSV.
        </p>
      </div>

      {err && <p className="stale">{err}</p>}

      <section className="section-card model-narrative">
        <h2>How to read this page</h2>
        <ul className="model-readme">
          <li>
            <strong>Scenario cards</strong> — implied price after explicit years, a linear fade of growth toward
            terminal <em>g</em>, then a Gordon perpetuity. <strong>Base</strong> uses trailing segment CAGR and mean
            margins; upside/downside use historical YoY extrema where available.
          </li>
          <li>
            <strong>Sensitivity grid</strong> — flat WACC (single discount rate all years) vs terminal growth columns for
            quick stress; not identical to the scenario engine’s year-by-year WACC path. Hover to cross-highlight.
          </li>
          <li>
            <strong>FCF bridge</strong> — ratios from the last three fiscal years applied to forecast revenue; NWC uses
            a consolidated balance-sheet proxy (see limitations below).
          </li>
        </ul>
      </section>

      {methodologyNotes && methodologyNotes.length > 0 && (
        <section className="section-card">
          <h2>Methodology (limitations)</h2>
          <ul className="methodology-list">
            {methodologyNotes.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </section>
      )}

      {modelWarnings && modelWarnings.length > 0 && (
        <section className="section-card" style={{ borderColor: "rgba(251, 191, 36, 0.4)" }}>
          <h2>Model warnings</h2>
          <ul className="methodology-list">
            {modelWarnings.map((w, i) => (
              <li key={i}>
                <code>{String(w.rule)}</code> — {w.note ? String(w.note) : JSON.stringify(w)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {wacc?.wacc_degraded_warning ? (
        <p className="banner stale">WACC may be degraded: stale risk-free rate or beta.</p>
      ) : null}
      {tvWarn ? (
        <p className="banner stale">Terminal value exceeds 70% of enterprise value in one or more scenarios.</p>
      ) : null}

      {positionGuidance?.summary && (
        <section className="section-card">
          <h2>Position sizing (heuristic)</h2>
          <p className="model-readme" style={{ color: "var(--muted)", marginTop: 0 }}>
            {positionGuidance.summary}
          </p>
          {positionGuidance.disclaimer && (
            <p className="stale" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
              {positionGuidance.disclaimer}
            </p>
          )}
        </section>
      )}

      {stressScenarios && Object.keys(stressScenarios).length > 0 && (
        <section className="section-card">
          <h2>Macro-style stress (approximate)</h2>
          <p className="stale" style={{ fontSize: "0.85rem", marginTop: 0 }}>
            Flat WACC shocks vs headline path; terminal growth shock on the last row. Full scenario engine uses a
            year-by-year WACC curve — these are for directional stress only.
          </p>
          <ul className="methodology-list">
            {Object.entries(stressScenarios).map(([k, v]) => (
              <li key={k}>
                <code>{k}</code> — implied ${v.implied_share_price} — {v.description}
              </li>
            ))}
          </ul>
        </section>
      )}

      {macroStressExtended && Object.keys(macroStressExtended).length > 0 && (
        <section className="section-card">
          <h2>Extended macro stress</h2>
          <p className="stale" style={{ fontSize: "0.85rem", marginTop: 0 }}>
            Revenue level shock (−15%), heuristic multiple compression on base implied price, and severe flat WACC +400 bps
            vs headline mean. See <code>methodology_narrative.macro_stress</code> for intent.
          </p>
          <ul className="methodology-list">
            {Object.entries(macroStressExtended).map(([k, v]) => (
              <li key={k}>
                <code>{k}</code> — implied ${v.implied_share_price} — {v.description}
              </li>
            ))}
          </ul>
        </section>
      )}

      {methodologyNarrative && (
        <section className="section-card">
          <h2>Methodology narrative (API)</h2>
          <p className="stale" style={{ fontSize: "0.85rem", marginTop: 0 }}>
            Same object as <code>GET /model/methodology</code> → <code>structured</code>. Highlights: 7Y explicit + 3Y fade,
            2.5% terminal growth cap, term-structured WACC, operating WC when tags align, segment capex intensity in DCF.
          </p>
          <ul className="methodology-list">
            {[
              ["explicit_horizon", "Explicit horizon"],
              ["terminal_growth_cap", "Terminal growth cap"],
              ["wacc_and_term_structure", "WACC & term structure"],
              ["working_capital", "Working capital"],
              ["capex_and_segments", "Capex & segments"],
              ["macro_stress", "Macro stress"],
            ].map(([key, label]) => {
              const text = methodologyNarrative[key];
              if (typeof text !== "string") return null;
              return (
                <li key={key}>
                  <strong>{label}</strong> — {text}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <div className="scenario-grid">
        {scenarios &&
          scenarioOrder.map(({ key: k, variant }) => {
            const s = scenarios[k];
            if (!s) return null;
            const ka = (s.key_assumptions as { segment: string; growth: number; margin: number }[]) || [];
            return (
              <ScenarioCard
                key={k}
                name={k}
                variant={variant}
                price={Number(s.implied_share_price)}
                disc={Number(s.premium_discount_to_spot_pct)}
                assumptions={ka}
              />
            );
          })}
      </div>

      <section className="section-card">
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", justifyContent: "space-between", gap: "1rem" }}>
          <h2 style={{ margin: 0 }}>Sensitivity — implied share price</h2>
          {sens && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() =>
                downloadSensitivityCsv(sens.wacc_axis, sens.terminal_growth_axis, sens.implied_share_price_grid)
              }
            >
              Export CSV
            </button>
          )}
        </div>
        <p style={{ color: "var(--muted)", fontSize: "0.88rem", marginTop: "0.35rem", marginBottom: "1rem" }}>
          Rows: WACC (±150 bps around headline mean, 75 bp steps). Columns: terminal growth (1.5%–3.5%, 50 bp steps).
        </p>
        {sens && (
          <SensitisationTable waccAxis={sens.wacc_axis} tgAxis={sens.terminal_growth_axis} grid={sens.implied_share_price_grid} />
        )}
      </section>

      {segmentCapexProxy && segmentCapexProxy.length > 0 && (
        <section className="section-card">
          <h2>Segment capex proxy (revenue-weighted)</h2>
          <p className="stale" style={{ fontSize: "0.85rem", marginTop: "-0.25rem" }}>
            Consolidated capex × segment revenue share × intensity — the FCF bridge uses a segment-intensity-adjusted
            consolidated capex ratio in the DCF; this table is for transparency by segment.
          </p>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Segment</th>
                  <th className="num">Revenue share</th>
                  <th className="num">Implied capex proxy (TTM)</th>
                </tr>
              </thead>
              <tbody>
                {segmentCapexProxy.map((r) => (
                  <tr key={r.segment}>
                    <td>{r.segment}</td>
                    <td className="num">{(r.revenue_share * 100).toFixed(2)}%</td>
                    <td className="num">${r.implied_capex_proxy_ttm.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {shareCountAnalysis && (
        <section className="section-card">
          <h2>Share count (basic vs diluted)</h2>
          <pre style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)", whiteSpace: "pre-wrap" }}>
            {JSON.stringify(shareCountAnalysis, null, 2)}
          </pre>
        </section>
      )}

      <section className="section-card">
        <h2>FCF bridge (ratios)</h2>
        {m?.fcf_bridge_tree ? (
          <FCFBridge
            tree={
              m.fcf_bridge_tree as {
                steps: Record<string, unknown>[];
                nwc_methodology?: Record<string, string>;
              }
            }
          />
        ) : null}
      </section>

      <section className="section-card">
        <h2>Assumptions</h2>
        <div className="data-table-wrap">
          {m?.assumptions_table ? (
            <AssumptionsTable rows={m.assumptions_table as Record<string, unknown>[]} />
          ) : null}
        </div>
      </section>

      <button type="button" className="btn btn-primary" onClick={run} disabled={loading}>
        {loading ? "Re-running…" : "Re-run model"}
      </button>
    </main>
  );
}
