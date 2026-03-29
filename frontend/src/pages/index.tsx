import React, { useEffect, useMemo, useState } from "react";
import { fetchJson } from "@/lib/api";
import { MetricsTable } from "@/components/MetricsTable";
import { SegmentTable } from "@/components/SegmentTable";
import { MarketDataPanel } from "@/components/MarketDataPanel";
import { OverviewKpiTable, type OverviewPayload } from "@/components/OverviewKpiTable";

const KPI_ORDER = [
  "total_revenue",
  "operating_income",
  "net_income",
  "operating_cash_flow",
  "capital_expenditure",
] as const;

/** When the API has no `overview`, derive the same shape from raw metrics (older backends). */
function clientOverviewFromMetrics(fm: Record<string, unknown>[]): OverviewPayload | null {
  if (!fm.length) return null;
  const ttm: Record<string, number | null> = {};
  for (const key of KPI_ORDER) {
    const row = fm.find((r) => r.metric_name === key && isTtmRow(r.is_ttm));
    ttm[key] = row?.value != null ? Number(row.value) : null;
  }
  const fySet = new Set<string>();
  for (const r of fm) {
    const pl = String(r.period_label ?? "");
    if (r.metric_name === "total_revenue" && !isTtmRow(r.is_ttm) && pl.startsWith("FY")) fySet.add(pl);
  }
  const fy_labels = [...fySet].sort((a, b) => parseInt(a.slice(2, 6), 10) - parseInt(b.slice(2, 6), 10)).slice(-3);
  const fy_by_metric: Record<string, Record<string, number | null>> = {};
  for (const key of KPI_ORDER) {
    fy_by_metric[key] = {};
    for (const pl of fy_labels) {
      const row = fm.find((r) => r.metric_name === key && String(r.period_label) === pl && !isTtmRow(r.is_ttm));
      fy_by_metric[key][pl] = row?.value != null ? Number(row.value) : null;
    }
  }
  return {
    kpi_metrics_order: [...KPI_ORDER],
    fy_labels,
    ttm,
    fy_by_metric,
  };
}

function formatNum(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/** SQLite / JSON may expose TTM as 1, true, or "1". */
function isTtmRow(v: unknown): boolean {
  return v === true || v === 1 || Number(v) === 1;
}

export default function OverviewPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"consolidated" | "segments">("consolidated");

  useEffect(() => {
    let cancelled = false;
    fetchJson<Record<string, unknown>>("/financials/msft")
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const fm = (data?.financial_metrics as Record<string, unknown>[]) || [];
  const sm = (data?.segment_metrics as Record<string, unknown>[]) || [];
  const md = (data?.market_data as Record<string, unknown>[]) || [];
  const excerpt = data?.item_1_excerpt as string | undefined;
  const overview = data?.overview as OverviewPayload | undefined;
  const kpiOverview = overview ?? clientOverviewFromMetrics(fm);

  const consolidatedRows = useMemo(() => {
    const core = ["total_revenue", "operating_income", "operating_cash_flow", "capital_expenditure", "net_income"];
    const filtered = fm.filter((r) => core.includes(String(r.metric_name)));
    // TTM rows (is_ttm=1) first so they are visible; raw DB order buries them under years of FY rows.
    return [...filtered].sort((a, b) => {
      const ta = isTtmRow(a.is_ttm);
      const tb = isTtmRow(b.is_ttm);
      if (ta !== tb) return ta ? -1 : 1;
      const plA = String(a.period_label ?? "");
      const plB = String(b.period_label ?? "");
      return plB.localeCompare(plA);
    });
  }, [fm]);

  const ttmRev = useMemo(() => {
    if (overview?.ttm?.total_revenue != null) return overview.ttm.total_revenue;
    const row = fm.find((r) => r.metric_name === "total_revenue" && isTtmRow(r.is_ttm));
    return row?.value != null ? Number(row.value) : null;
  }, [fm, overview]);

  const spot = useMemo(() => {
    const o = overview?.market?.spot_price;
    if (o && typeof o === "object" && "value" in o && o.value != null) return Number(o.value);
    const row = md.find((r) => r.metric_name === "spot_price");
    return row?.value != null ? Number(row.value) : null;
  }, [md, overview]);

  const beta = useMemo(() => {
    const o = overview?.market?.beta_5y_monthly;
    if (o && typeof o === "object" && "value" in o && o.value != null) return Number(o.value);
    const row = md.find((r) => r.metric_name === "beta_5y_monthly");
    return row?.value != null ? Number(row.value) : null;
  }, [md, overview]);

  const rf10 = useMemo(() => {
    const o = overview?.market?.risk_free_rate_10y;
    if (o && typeof o === "object" && "value" in o && o.value != null) return Number(o.value);
    const row = md.find((r) => r.metric_name === "risk_free_rate_10y");
    return row?.value != null ? Number(row.value) : null;
  }, [md, overview]);

  const segmentFilled = overview?.segment_latest_revenue?.filter((s) => s.revenue != null).length ?? sm.length;

  return (
    <main className="page">
      <div className="page-hero">
        <h1>Microsoft Corporation</h1>
        <p className="lead">
          Consolidated KPIs, segment disclosure, and market inputs from your ingestion pipeline. The primary table uses
          server-built snapshots so you see TTM and fiscal years without sparse null columns.
        </p>
      </div>

      <p className="banner">
        Driver-to-JSON mapping for six core inputs is on the <strong>Agent</strong> page (provenance drawer). Full
        inline memo citations are not implemented yet.
      </p>

      {err && <p className="stale">Could not load financials: {err}</p>}

      {!data && !err && (
        <div className="section-card">
          <div className="skeleton skeleton-block" />
        </div>
      )}

      {data && (
        <>
          <div className="stat-grid">
            <div className="stat-card">
              <div className="label">TTM revenue</div>
              <div className="value">{ttmRev != null ? `$${formatNum(ttmRev)}` : "—"}</div>
            </div>
            <div className="stat-card">
              <div className="label">Spot (MSFT)</div>
              <div className="value">{spot != null ? `$${spot.toFixed(2)}` : "—"}</div>
            </div>
            <div className="stat-card">
              <div className="label">5Y β vs SPY</div>
              <div className="value">{beta != null ? beta.toFixed(2) : "—"}</div>
            </div>
            <div className="stat-card">
              <div className="label">10Y Treasury (rf)</div>
              <div className="value">{rf10 != null ? `${(rf10 * 100).toFixed(2)}%` : "—"}</div>
            </div>
          </div>

          {overview?.segment_latest_revenue && overview.segment_latest_revenue.length > 0 && (
            <section className="section-card segment-snapshot">
              <h2>Latest segment revenue (reported)</h2>
              <ul className="segment-snapshot-list">
                {overview.segment_latest_revenue.map((s) => (
                  <li key={s.segment_name}>
                    <span className="seg-name">{s.segment_name}</span>
                    <span className="seg-meta">
                      {s.period_label ?? "—"} ·{" "}
                      {s.revenue != null ? `$${formatNum(s.revenue)}` : "—"}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="stale" style={{ margin: "0.75rem 0 0", fontSize: "0.82rem" }}>
                {segmentFilled} segment series with values · {sm.length} total segment metric rows in DB
              </p>
            </section>
          )}

          <section className="section-card">
            <h2>Business overview (Item 1 excerpt)</h2>
            {excerpt ? (
              <div className="excerpt-box">
                {excerpt.split(/\n\n+/).map((para, i) => (
                  <p key={i}>{para.trim()}</p>
                ))}
              </div>
            ) : (
              <p className="stale">Run POST /ingest/msft to pull Item 1 text from the latest 10-K.</p>
            )}
          </section>

          <section className="section-card">
            <h2>Financials</h2>
            <div className="tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "consolidated"}
                className={`tab ${tab === "consolidated" ? "active" : ""}`}
                onClick={() => setTab("consolidated")}
              >
                Consolidated KPIs
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "segments"}
                className={`tab ${tab === "segments" ? "active" : ""}`}
                onClick={() => setTab("segments")}
              >
                Segments ({sm.length})
              </button>
            </div>
            {tab === "consolidated" ? (
              <>
                {kpiOverview ? (
                  <OverviewKpiTable overview={kpiOverview} />
                ) : (
                  <p className="stale">No consolidated metrics yet. Run ingestion.</p>
                )}
                <h3 className="subhead-table">Ingested rows (core columns)</h3>
                <MetricsTable rows={consolidatedRows} />
              </>
            ) : (
              <SegmentTable rows={sm} />
            )}
          </section>

          <section className="section-card">
            <h2>Market data</h2>
            <MarketDataPanel data={md} />
          </section>

          <footer className="page-footer">
            <strong>Freshness</strong>{" "}
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
              {JSON.stringify(data?.freshness)}
            </span>
          </footer>
        </>
      )}
    </main>
  );
}
