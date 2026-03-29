"""Second-pass validator — deterministic checks on memo text."""

from __future__ import annotations

import json
import re
from typing import Any

QUALIFIERS = (
    "projected",
    "estimated",
    "assumes",
    "forecast",
    "scenario",
    "expected",
    "implied",
)


def _nums_in_payload(payload: Any) -> set[str]:
    s = json.dumps(payload, default=str)
    return set(re.findall(r"-?\d+\.?\d*", s))


def _floats_in_payload(payload: Any) -> list[float]:
    out: list[float] = []
    s = json.dumps(payload, default=str)
    for m in re.findall(r"-?\d+\.?\d*", s):
        try:
            out.append(float(m))
        except ValueError:
            continue
    return out


def _matches_any_payload_float(memo_num: str, payload_vals: list[float]) -> bool:
    """Stricter than loose 0.02 tolerance: tight for small numbers, absolute band for large."""
    try:
        x = float(memo_num)
    except ValueError:
        return False
    for pv in payload_vals:
        if max(abs(x), abs(pv)) >= 100:
            if abs(x - pv) < 0.5:
                return True
        else:
            if abs(x - pv) < 0.005:
                return True
    return False


def validate_memo(memo: str, payload: dict[str, Any]) -> dict[str, Any]:
    issues = []
    payload_nums = _nums_in_payload(payload)
    payload_floats = _floats_in_payload(payload)
    memo_nums = set(re.findall(r"-?\d+\.?\d*[bmBM%]?", memo))
    memo_nums_clean = set()
    for n in memo_nums:
        n2 = re.sub(r"[bmBM%]", "", n)
        if n2:
            memo_nums_clean.add(n2)
    for mn in memo_nums_clean:
        if mn not in payload_nums and mn.replace(".", "", 1).replace("-", "", 1).isdigit():
            if not _matches_any_payload_float(mn, payload_floats):
                issues.append({"check": "number_in_memo_not_in_payload", "number": mn})

    for sent in re.split(r"(?<=[.!?])\s+", memo):
        if "%" in sent and "change" in sent.lower():
            if not re.search(r"\d.*to.*\d|from \d", sent, re.I):
                issues.append({"check": "pct_change_missing_endpoints", "sentence": sent[:200]})
        low = sent.lower()
        if any(w in low for w in ["will", "expects", "outlook", "guidance"]):
            if not any(q in low for q in QUALIFIERS):
                issues.append({"check": "forward_looking_qualifier", "sentence": sent[:200]})

    return {"passed": len(issues) == 0, "issues": issues}
