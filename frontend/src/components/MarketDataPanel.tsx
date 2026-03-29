import React from "react";

const LABELS: Record<string, string> = {
  spot_price: "Spot price",
  beta_5y_monthly: "5Y monthly β (vs SPY)",
  risk_free_rate_10y: "Risk-free (10Y proxy)",
};

export function MarketDataPanel({ data }: { data: Record<string, unknown>[] }) {
  if (!data.length) {
    return <p style={{ color: "var(--muted)" }}>No market rows yet.</p>;
  }
  return (
    <ul className="market-panel">
      {data.map((r, i) => {
        const name = String(r.metric_name);
        const label = LABELS[name] || name.replace(/_/g, " ");
        const stale = Boolean(r.is_stale);
        return (
          <li key={i}>
            <strong>{label}</strong>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.95rem" }}>{String(r.value)}</span>
            {stale ? <span className="stale">Stale</span> : <span style={{ color: "var(--success)", fontSize: "0.75rem" }}>Live</span>}
            <small style={{ color: "var(--muted)", width: "100%", flexBasis: "100%" }}>
              Obs: {String(r.observation_date || "—")} · pulled {String(r.pulled_at || "").slice(0, 19)}
            </small>
          </li>
        );
      })}
    </ul>
  );
}
