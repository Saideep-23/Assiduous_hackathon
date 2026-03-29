"""Claude memo generation with trace logging and validation."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import anthropic

from agent import prompts
from agent.tools import build_agent_context_bundle, tool_get_qualitative_sections
from agent.validator import validate_memo
from database.connection import get_connection

MODEL = "claude-sonnet-4-20250514"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_trace(run_id: str, step: int, tool: str, inp: Any, out: Any, reasoning: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_trace (run_id, step_number, tool_name, tool_input_json, tool_output_json, reasoning_text, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step,
                tool,
                json.dumps(inp, default=str)[:8000],
                json.dumps(out, default=str)[:8000],
                reasoning,
                _now(),
            ),
        )


def run_agent_stream():
    run_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO agent_runs (run_id, started_at, status) VALUES (?, ?, ?)",
            (run_id, _now(), "running"),
        )

    client = anthropic.Anthropic()
    # First byte ASAP — then one DCF pass (not two) for the memo bundle.
    yield {
        "step": 0,
        "tool": "agent_start",
        "reasoning_summary": "Session started — running a single DCF snapshot for memo tools (typically 30s–3min).",
        "status": "in_progress",
    }
    bundle = build_agent_context_bundle()
    yield {
        "step": 0,
        "tool": "load_context",
        "reasoning_summary": "DCF + segment financials bundle ready. Generating memo sections…",
        "status": "complete",
    }
    memo_parts: list[str] = []
    step = 0

    sections: list[tuple[str, str, bool]] = [
        ("executive_summary", "Executive summary for Microsoft investment view.", False),
        ("business_overview", "Business overview from filings.", True),
        ("segment_analysis", "Segment revenue and operating income dynamics.", True),
        ("valuation", "DCF and WACC discussion.", False),
        ("scenario_analysis", "Base, upside, and downside scenarios.", False),
        ("advisory", "Capital return, deployment priorities, mispricing vs scenarios.", True),
    ]

    for sec_name, desc, use_rag in sections:
        step += 1
        extra = {}
        if use_rag:
            q = f"Microsoft {desc}"
            extra["rag"] = tool_get_qualitative_sections(q)
            _log_trace(
                run_id,
                step,
                "get_qualitative_sections",
                {"query": q},
                extra["rag"],
                f"RAG query '{q}' to ground {sec_name} in 10-K language.",
            )
            yield {
                "step": step,
                "tool": "get_qualitative_sections",
                "reasoning_summary": f"Retrieved passages for {sec_name}.",
                "rag_query": q,
                "status": "complete",
            }
        payload = {**bundle, **extra}
        prompt = prompts.WRITE_MEMO_SECTION.format(
            section_name=sec_name,
            payload=json.dumps(payload, default=str)[:100000],
        )
        yield {
            "step": step,
            "tool": "claude_request",
            "reasoning_summary": f"Calling Claude for {sec_name.replace('_', ' ')}… (typically 20–90s per section)",
            "section": sec_name,
            "status": "in_progress",
        }
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=prompts.SYSTEM_AGENT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        memo_parts.append(f"## {sec_name.replace('_', ' ').title()}\n\n{text}\n")
        step += 1
        _log_trace(
            run_id,
            step,
            "write_memo_section",
            {"section_name": sec_name},
            {"length": len(text)},
            f"Wrote {sec_name} using payload keys {list(payload.keys())}.",
        )
        yield {
            "step": step,
            "tool": "write_memo_section",
            "reasoning_summary": f"Completed section {sec_name}.",
            "status": "complete",
        }

    step += 1
    rag_sf = tool_get_qualitative_sections("management discussion of risks and growth outlook versus analyst models")
    _log_trace(
        run_id,
        step,
        "get_qualitative_sections",
        {"query": "scenario framing"},
        rag_sf,
        "Passages for scenario framing versus management commentary.",
    )
    yield {"step": step, "tool": "get_qualitative_sections", "reasoning_summary": "Scenario framing RAG.", "rag_query": "management outlook", "status": "complete"}

    prompt = prompts.WRITE_MEMO_SECTION.format(
        section_name="scenario_framing",
        payload=json.dumps({**bundle, "rag": rag_sf}, default=str)[:100000],
    )
    yield {
        "step": step,
        "tool": "claude_request",
        "reasoning_summary": "Calling Claude for scenario framing…",
        "section": "scenario_framing",
        "status": "in_progress",
    }
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=prompts.SYSTEM_AGENT
        + " Only in this section: label base assumptions as conservative, fair, or optimistic relative to management wording.",
        messages=[{"role": "user", "content": prompt}],
    )
    sf = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    memo_parts.append(
        f"## Scenario framing (qualitative judgement)\n\n<div class='scenario-framing'>{sf}</div>\n"
    )
    step += 1
    _log_trace(run_id, step, "write_memo_section", {"section": "scenario_framing"}, {"length": len(sf)}, "Scenario framing judgement.")

    memo_full = (
        "DISCLAIMER: Generated by an automated system for educational purposes; not investment advice. "
        "See Model page for assumptions. Stale market inputs are flagged in the application.\n\n"
        + "\n".join(memo_parts)
    )

    val = validate_memo(memo_full, bundle)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO validation_results (run_id, check_name, passed, detail, timestamp) VALUES (?, ?, ?, ?, ?)",
            (run_id, "validator_suite", 1 if val["passed"] else 0, json.dumps(val), _now()),
        )
        conn.execute("UPDATE agent_runs SET completed_at = ?, status = ? WHERE run_id = ?", (_now(), "complete", run_id))

    yield {
        "final": True,
        "memo": memo_full,
        "validation": val,
        "provenance": {"six_core": "See UI; data from /financials/msft and /model/msft."},
        "run_id": run_id,
    }
