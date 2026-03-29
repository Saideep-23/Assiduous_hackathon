"""Regression tests for MSFT segment iXBRL parsing (no network)."""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    from ingestion.edgar import parse_ixbrl_segments
except ImportError:  # pragma: no cover
    parse_ixbrl_segments = None  # type: ignore[misc, assignment]

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "msft_ixbrl_segment_snippet.xml"


@unittest.skipIf(parse_ixbrl_segments is None, "ingestion.edgar not importable (install backend deps)")
class TestIxbrlSegments(unittest.TestCase):
    def test_parse_fixture_intelligent_cloud_revenue_and_oi(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        rows = parse_ixbrl_segments(html, "test-accession")
        by_m = {(r["segment"], r["metric"]): r for r in rows}
        self.assertIn(("Intelligent Cloud", "segment_revenue"), by_m)
        self.assertIn(("Intelligent Cloud", "segment_operating_income"), by_m)
        # 95000 * 10^6 = 95e9
        self.assertAlmostEqual(by_m[("Intelligent Cloud", "segment_revenue")]["value"], 95_000_000_000.0, delta=1.0)
        self.assertAlmostEqual(
            by_m[("Intelligent Cloud", "segment_operating_income")]["value"],
            21_000_000_000.0,
            delta=1.0,
        )
        self.assertEqual(by_m[("Intelligent Cloud", "segment_revenue")]["period_end"], "2024-06-30")


if __name__ == "__main__":
    unittest.main()
