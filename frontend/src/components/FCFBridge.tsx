import React from "react";

export function FCFBridge({
  tree,
}: {
  tree: {
    steps: Record<string, unknown>[];
    nwc_methodology?: Record<string, string>;
  };
}) {
  if (!tree?.steps) return null;
  const nw = tree.nwc_methodology;
  return (
    <>
      <ol className="fcf-bridge">
        {tree.steps.map((s, i) => (
          <li key={i} className="fcf-step">
            <span className="fcf-step__idx">{i + 1}</span>
            <div className="fcf-step__body">
              <strong>{String(s.name)}</strong>
              <div className="fcf-step__meta">
                {s.ratio != null && <span>ratio {String(s.ratio)} · </span>}
                {s.ratio_consolidated != null && s.ratio_in_dcf != null && (
                  <span>
                    consolidated {String(s.ratio_consolidated)} → DCF {String(s.ratio_in_dcf)} ·{" "}
                  </span>
                )}
                {s.rate != null && <span>rate {String(s.rate)} · </span>}
                {s.ratio_of_revenue_change != null && (
                  <span>ΔRev coeff {String(s.ratio_of_revenue_change)} · </span>
                )}
                {s.source_periods != null && <span>{String(s.source_periods)} · </span>}
                {s.formula != null && <span>{String(s.formula)}</span>}
              </div>
            </div>
          </li>
        ))}
      </ol>
      {nw && (
        <div className="fcf-nwc-note">
          <strong>NWC &amp; capex methodology</strong>
          {"mode" in nw && nw.mode != null && <p className="stale">Mode: {String(nw.mode)}</p>}
          <p>{String(nw.balance_sheet_proxy ?? "")}</p>
          <p>{String(nw.interpretation ?? "")}</p>
          {nw.limitation != null && nw.limitation !== "" ? (
            <p className="stale">{String(nw.limitation)}</p>
          ) : null}
          {(nw.capex_in_dcf != null && nw.capex_in_dcf !== "") ||
          (nw.capex_allocation != null && nw.capex_allocation !== "") ? (
            <p className="stale">
              {nw.capex_in_dcf != null ? String(nw.capex_in_dcf) : String(nw.capex_allocation)}
            </p>
          ) : null}
        </div>
      )}
    </>
  );
}
