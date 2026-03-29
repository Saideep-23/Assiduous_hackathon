import React, { useMemo } from "react";

const CORE_COLUMNS = ["metric_name", "period_label", "value", "is_ttm", "is_derived"];

function isTruthyFlag(v: unknown): boolean {
  return v === true || v === 1 || Number(v) === 1;
}

function formatCell(k: string, v: unknown): string {
  if (k === "is_ttm" || k === "is_derived") {
    if (v == null || v === "") return "—";
    return isTruthyFlag(v) ? "Yes" : "No";
  }
  return String(v ?? "");
}

export function MetricsTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return <p style={{ color: "var(--muted)" }}>No metrics yet. Run ingestion.</p>;

  const keys = useMemo(() => {
    const all = new Set<string>();
    for (const r of rows) {
      Object.keys(r).forEach((k) => all.add(k));
    }
    return CORE_COLUMNS.filter((k) => all.has(k));
  }, [rows]);

  const isNumeric = (k: string) => k === "value" || k.includes("id");

  return (
    <div className="data-table-wrap">
      <p className="stale" style={{ fontSize: "0.82rem", margin: "0 0 0.75rem", lineHeight: 1.45 }}>
        <strong>Flags:</strong> Fiscal-year and quarterly values are taken straight from SEC Company Facts, so{" "}
        <code>is ttm</code> and <code>is derived</code> are <strong>No</strong>. Trailing-twelve-month rows use{" "}
        <code>period_label</code> like <code>TTM_total_revenue</code> and show <strong>Yes</strong> for both (computed in
        transform).
      </p>
      <table className="data-table">
        <thead>
          <tr>
            {keys.map((k) => (
              <th key={k}>{k.replace(/_/g, " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 96).map((r, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k} className={isNumeric(k) ? "num" : undefined}>
                  {formatCell(k, (r as Record<string, unknown>)[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
