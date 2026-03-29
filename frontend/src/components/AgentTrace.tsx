import React from "react";

export function AgentTrace({ events, busy }: { events: Record<string, unknown>[]; busy?: boolean }) {
  return (
    <div className="trace-panel">
      {events.length === 0 && !busy && (
        <div className="trace-empty">
          <p className="trace-empty-title">Trace idle</p>
          <ol className="trace-empty-steps">
            <li>Tool calls (RAG, memo sections) stream here in order.</li>
            <li>Each card shows the tool name and a short reasoning line.</li>
            <li>When the run completes, the memo panel fills from the final event.</li>
          </ol>
        </div>
      )}
      {events.length === 0 && busy && (
        <div className="trace-waiting">
          <span className="trace-pulse" aria-hidden />
          <span>Connecting to agent stream…</span>
        </div>
      )}
      {events.map((e, i) => (
        <div key={i} className="trace-card" style={{ animation: `fadeUp 0.35s ease ${Math.min(i, 8) * 0.04}s both` }}>
          <div className="trace-head">
            <span>{String(e.tool || e.tool_name || "")}</span>
            {e.status === "complete" ? (
              <span className="ok" aria-label="complete">
                ✓
              </span>
            ) : e.status === "in_progress" ? (
              <span className="trace-pulse" aria-label="in progress" />
            ) : null}
          </div>
          <p>{String(e.reasoning_summary || e.reasoning_text || "")}</p>
          {e.rag_query ? <small className="rag">RAG: {String(e.rag_query)}</small> : null}
        </div>
      ))}
    </div>
  );
}

