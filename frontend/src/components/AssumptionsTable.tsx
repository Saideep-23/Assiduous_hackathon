import React from "react";

export function AssumptionsTable({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Input</th>
          <th className="num">Value</th>
          <th>Source</th>
          <th>Classification</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td>{String(r.input)}</td>
            <td className="num">{typeof r.value === "number" ? String(r.value) : String(r.value)}</td>
            <td style={{ fontSize: "0.82rem", color: "var(--muted)" }}>{String(r.source)}</td>
            <td>
              <span
                style={{
                  display: "inline-block",
                  padding: "0.2rem 0.5rem",
                  borderRadius: "6px",
                  fontSize: "0.72rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  background:
                    String(r.classification) === "model_assumption"
                      ? "rgba(167, 139, 250, 0.15)"
                      : String(r.classification) === "historical_average"
                        ? "rgba(45, 212, 191, 0.12)"
                        : "rgba(56, 189, 248, 0.12)",
                  color: "var(--text)",
                }}
              >
                {String(r.classification)}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
