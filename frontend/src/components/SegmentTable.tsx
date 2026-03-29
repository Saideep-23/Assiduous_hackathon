import React from "react";

export function SegmentTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) {
    return <p style={{ color: "var(--muted)" }}>No segment data.</p>;
  }
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Segment</th>
            <th>Metric</th>
            <th>Period</th>
            <th className="num">Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 80).map((r, i) => (
            <tr key={i}>
              <td>{String(r.segment_name)}</td>
              <td>
                <code style={{ fontSize: "0.78rem", color: "var(--accent)" }}>{String(r.metric_name)}</code>
              </td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>{String(r.period_label)}</td>
              <td className="num">{String(r.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
