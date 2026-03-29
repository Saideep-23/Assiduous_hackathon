import React from "react";

const LABELS: Record<string, string> = {
  total_revenue: "Total revenue",
  operating_income: "Operating income",
  net_income: "Net income",
  operating_cash_flow: "Operating cash flow",
  capital_expenditure: "Capital expenditure",
};

function fmtUsd(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export type MarketField = {
  value: number | null;
  is_stale?: boolean;
  observation_date?: string | null;
  pulled_at?: string | null;
} | null;

export type OverviewPayload = {
  kpi_metrics_order: string[];
  fy_labels: string[];
  ttm: Record<string, number | null>;
  fy_by_metric: Record<string, Record<string, number | null>>;
  market?: Record<string, MarketField>;
  segment_latest_revenue?: { segment_name: string; period_label: string | null; revenue: number | null }[];
};

export function OverviewKpiTable({ overview }: { overview: OverviewPayload }) {
  const { kpi_metrics_order, fy_labels, ttm, fy_by_metric } = overview;
  const hasAnyFy = fy_labels.length > 0;

  return (
    <div className="data-table-wrap kpi-table-wrap">
      <table className="data-table kpi-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="num">TTM</th>
            {hasAnyFy ? (
              fy_labels.map((pl) => (
                <th key={pl} className="num">
                  {pl}
                </th>
              ))
            ) : (
              <th className="num stale">FY</th>
            )}
          </tr>
        </thead>
        <tbody>
          {kpi_metrics_order.map((key) => (
            <tr key={key}>
              <td>{LABELS[key] || key.replace(/_/g, " ")}</td>
              <td className="num kpi-strong">{fmtUsd(ttm[key])}</td>
              {hasAnyFy ? (
                fy_labels.map((pl) => (
                  <td key={pl} className="num">
                    {fmtUsd(fy_by_metric[key]?.[pl])}
                  </td>
                ))
              ) : (
                <td className="num stale">—</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {!hasAnyFy && (
        <p className="stale" style={{ margin: "0.75rem 0 0", fontSize: "0.85rem" }}>
          No fiscal-year columns yet — run consolidated ingestion (EDGAR) so FY metrics populate.
        </p>
      )}
    </div>
  );
}
