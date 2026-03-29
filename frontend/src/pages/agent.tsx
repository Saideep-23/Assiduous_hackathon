import React, { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import { AgentTrace } from "@/components/AgentTrace";
import { MemoViewer } from "@/components/MemoViewer";
import { ProvenanceContent } from "@/components/ProvenanceContent";
import { ProvenancePanel } from "@/components/ProvenancePanel";
import { ValidationResults } from "@/components/ValidationResults";

/** Next.js `/api` rewrite buffers SSE; call FastAPI on :8000 directly when on local dev/Docker. */
function agentRunEndpoint(): string {
  if (typeof window === "undefined") return apiUrl("/agent/run");
  const { protocol, hostname } = window.location;
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return `${protocol}//${hostname}:8000/agent/run`;
  }
  return apiUrl("/agent/run");
}

function formatElapsed(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function lastActivityLabel(events: Record<string, unknown>[]): string {
  const vis = events.filter((e) => !e.final);
  if (vis.length === 0) return "Connecting…";
  const e = vis[vis.length - 1];
  const tool = String(e.tool || e.tool_name || "");
  const sum = String(e.reasoning_summary || "").slice(0, 120);
  return tool ? `${tool}${sum ? ` — ${sum}` : ""}` : sum || "Working…";
}

export default function AgentPage() {
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [memo, setMemo] = useState("");
  const [val, setVal] = useState<Record<string, unknown> | null>(null);
  const [prov, setProv] = useState(false);
  const [busy, setBusy] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);

  useEffect(() => {
    if (!busy || runStartedAt == null) return;
    const id = window.setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - runStartedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [busy, runStartedAt]);

  const run = useCallback(() => {
    setBusy(true);
    setRunErr(null);
    setEvents([]);
    setMemo("");
    setVal(null);
    setRunStartedAt(Date.now());
    setElapsedSec(0);
    fetch(agentRunEndpoint(), {
      method: "POST",
      cache: "no-store",
      mode: "cors",
      headers: { Accept: "text/event-stream" },
    })
      .then(async (res) => {
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t ? `HTTP ${res.status}: ${t.slice(0, 400)}` : `HTTP ${res.status}`);
        }
        const reader = res.body?.getReader();
        const dec = new TextDecoder();
        if (!reader) {
          throw new Error("No response body (streaming not supported)");
        }
        let buf = "";
        const flushBlocks = (raw: string) => {
          const parts = raw.split(/\r?\n\r?\n/);
          return { rest: parts.pop() ?? "", blocks: parts };
        };
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const { rest, blocks } = flushBlocks(buf);
          buf = rest;
          for (const block of blocks) {
            for (const line of block.split(/\r?\n/)) {
              const t = line.trim();
              if (!t.startsWith("data: ")) continue;
              try {
                const d = JSON.parse(t.slice(6));
                setEvents((prev) => [...prev, d]);
                if (d.final) {
                  setMemo(d.memo || "");
                  setVal(d.validation || null);
                }
              } catch {
                /* ignore */
              }
            }
          }
        }
      })
      .catch((e) => setRunErr(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setBusy(false);
        setRunStartedAt(null);
      });
  }, []);

  const activity = lastActivityLabel(events);

  return (
    <main className="page">
      <div className="page-hero agent-hero">
        <h1>Investment memo agent</h1>
        <p className="lead">
          Streams tool calls as they run. The memo and validation fill in when the run completes (final SSE event).
          Typical wall time is about <strong>5–15 minutes</strong> — Claude is called once per section.
        </p>
      </div>

      <p className="banner">
        The provenance drawer maps six core valuation drivers to <code>/api/financials/msft</code> and model payload
        fields—click &quot;Sample provenance&quot; for links.
      </p>

      <section className="section-card agent-run-card">
        {runErr && (
          <p className="banner" style={{ borderColor: "rgba(248, 113, 113, 0.4)", marginBottom: "1rem" }}>
            {runErr}
          </p>
        )}

        {busy && (
          <div className="agent-running-panel" role="status" aria-live="polite">
            <div className="agent-running-panel__head">
              <span className="trace-pulse" aria-hidden />
              <strong>Agent is running</strong>
              <span className="agent-running-panel__time">{formatElapsed(elapsedSec)}</span>
            </div>
            <p className="agent-running-panel__hint">
              Safe to leave this tab open. You will see trace steps as they stream; the memo appears when the run
              finishes. If the timer moves but the trace stays empty, confirm the page talks to the API on port{" "}
              <strong>8000</strong> (see README — Next.js <code>/api</code> proxy buffers SSE).
            </p>
            <p className="agent-running-panel__latest">
              <span className="agent-running-panel__label">Latest activity</span>
              {activity}
            </p>
          </div>
        )}

        <div className="agent-run-bar">
          <button type="button" className="btn btn-primary" onClick={run} disabled={busy}>
            {busy ? (
              <span className="btn-running">
                <span className="trace-pulse" aria-hidden />
                Running…
              </span>
            ) : (
              "Run agent"
            )}
          </button>
          {busy && (
            <span className="agent-run-hint">
              <kbd>SSE</kbd> to port 8000 — trace updates live
            </span>
          )}
        </div>

        <div className="agent-layout">
          <aside className="agent-col agent-col--trace">
            <h2 className="agent-col-title">Trace</h2>
            <div className="trace-panel-outer">
              <AgentTrace events={events.filter((e) => !e.final)} busy={busy} />
            </div>
          </aside>
          <div className="agent-col agent-col--memo">
            <h2 className="agent-col-title">Memo</h2>
            <MemoViewer html={memo} />
            {val && <ValidationResults val={val as { passed: boolean; issues?: unknown[] }} />}
            <p className="agent-prov-row">
              <button type="button" className="btn btn-ghost" onClick={() => setProv(true)}>
                Sample provenance (six-core note)
              </button>
            </p>
          </div>
        </div>
      </section>

      <ProvenancePanel open={prov} onClose={() => setProv(false)}>
        <ProvenanceContent />
      </ProvenancePanel>
    </main>
  );
}
