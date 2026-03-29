import React, { useEffect, useState } from "react";
import { apiUrl, fetchJson } from "@/lib/api";

const API = {
  financials: apiUrl("/financials/msft"),
  model: apiUrl("/model/msft"),
  methodology: apiUrl("/model/methodology"),
  docs: apiUrl("/docs"),
};

type OverviewMarket = {
  risk_free_rate_10y?: { value?: number | null } | null;
  beta_5y_monthly?: { value?: number | null } | null;
  spot_price?: { value?: number | null } | null;
};

type FinResponse = {
  overview?: { market?: OverviewMarket; segment_latest_revenue?: { segment_name: string; revenue: number | null }[] };
  financial_metrics?: { metric_name: string; is_ttm: number; value: number | null }[];
};

type ModelResponse = {
  wacc_components?: { wacc?: number; wacc_path_mean?: number };
  assumptions_table?: { input: string; value: unknown }[];
  fcf_bridge_tree?: { steps?: { name?: string; ratio?: number; ratio_of_revenue_change?: number }[] };
  scenarios?: { Base?: Record<string, unknown> };
};

function fmtPct(x: number | null | undefined, digits = 2): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

function fmtNum(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "—";
  if (Math.abs(x) >= 1e9) return `${(x / 1e9).toFixed(2)}B`;
  if (Math.abs(x) >= 1e6) return `${(x / 1e6).toFixed(2)}M`;
  return x.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function ProvenanceContent() {
  const [fin, setFin] = useState<FinResponse | null>(null);
  const [model, setModel] = useState<ModelResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    Promise.all([
      fetchJson<FinResponse>("/financials/msft").catch(() => null),
      fetchJson<ModelResponse>("/model/msft", { method: "POST" }).catch(() => null),
    ])
      .then(([f, m]) => {
        if (!cancelled) {
          setFin(f);
          setModel(m);
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const mkt = fin?.overview?.market;
  const rf = mkt?.risk_free_rate_10y?.value;
  const beta = mkt?.beta_5y_monthly?.value;
  const spot = mkt?.spot_price?.value;
  const diluted = fin?.financial_metrics?.find(
    (r) => r.metric_name === "diluted_shares_outstanding" && r.is_ttm === 1,
  )?.value;
  const segs = fin?.overview?.segment_latest_revenue ?? [];
  const wacc = model?.wacc_components?.wacc ?? model?.wacc_components?.wacc_path_mean;
  const terminalRow = model?.assumptions_table?.find((r) => String(r.input).includes("Terminal growth used"));
  const terminalG = terminalRow?.value;
  const steps = model?.fcf_bridge_tree?.steps ?? [];
  const da = steps.find((s) => String(s.name).includes("D&A"));
  const capex = steps.find((s) => String(s.name).includes("Capex"));
  const nwc = steps.find((s) => String(s.name).includes("NWC"));

  return (
    <div className="prov-body">
      <h2 className="prov-title">Six core valuation drivers</h2>
      <p className="prov-lead">
        Live values from <a href={API.financials}>GET {API.financials}</a> and{" "}
        <a href={API.model}>POST {API.model}</a> (loaded when you open this panel). Methodology without a DB:{" "}
        <a href={API.methodology}>GET {API.methodology}</a>.
      </p>
      {loading && <p className="stale">Loading ingestion + model snapshot…</p>}
      {err && <p className="stale">{err}</p>}

      {!loading && (
        <dl className="prov-dl">
          <div>
            <dt>Risk-free (10Y)</dt>
            <dd>{rf != null ? fmtPct(rf, 3) : "—"}</dd>
          </div>
          <div>
            <dt>Beta (5Y monthly vs SPY)</dt>
            <dd>{beta != null ? beta.toFixed(3) : "—"}</dd>
          </div>
          <div>
            <dt>Spot / diluted shares</dt>
            <dd>
              {spot != null ? `$${spot.toFixed(2)}` : "—"} / {diluted != null ? fmtNum(diluted) : "—"} sh
            </dd>
          </div>
          <div>
            <dt>Segment revenue (latest FY in DB)</dt>
            <dd>
              {segs.length === 0 ? (
                "—"
              ) : (
                <ul className="prov-mini">
                  {segs.map((s) => (
                    <li key={s.segment_name}>
                      {s.segment_name}: {s.revenue != null ? `$${fmtNum(s.revenue)}` : "—"}
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
          <div>
            <dt>FCF bridge (headline ratios)</dt>
            <dd>
              D&amp;A {da?.ratio != null ? fmtPct(da.ratio) : "—"} · Capex{" "}
              {capex?.ratio != null || (capex as { ratio_in_dcf?: number })?.ratio_in_dcf != null
                ? fmtPct((capex as { ratio_in_dcf?: number }).ratio_in_dcf ?? (capex as { ratio?: number }).ratio)
                : "—"}{" "}
              · NWC coeff {nwc?.ratio_of_revenue_change != null ? fmtPct(nwc.ratio_of_revenue_change) : "—"}
            </dd>
          </div>
          <div>
            <dt>WACC (headline) / terminal growth (used)</dt>
            <dd>
              {wacc != null ? fmtPct(wacc) : "—"} /{" "}
              {typeof terminalG === "number" ? fmtPct(terminalG) : terminalG != null ? String(terminalG) : "—"}
            </dd>
          </div>
        </dl>
      )}

      <p className="prov-meta">
        <a href={API.docs}>OpenAPI UI</a> — full schemas. Filing IDs and raw metrics remain in the JSON responses.
      </p>
    </div>
  );
}
