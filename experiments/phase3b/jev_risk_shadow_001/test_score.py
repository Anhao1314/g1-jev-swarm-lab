"""Offline tests for scoring and safety-relevant failure accounting."""

import unittest
import json
from pathlib import Path

from score import score
from run_scored import _validate_protocol


def _bench():
    units = [
        {"paired_unit_id": f"unit{i}", "strict_violation": i < 11,
         "source_cell_ids": [f"cell{i}"], "source_case_ids": [f"case{i}"]}
        for i in range(18)
    ]
    return {"assessment_units": {v: units for v in ("geometry_only", "geometry_plus_velocity")}}


def _call(index, probability=None, variant="geometry_only", confidence=0.9):
    available = probability is not None
    return {"variant": variant, "paired_unit_id": f"unit{index}", "record": {
        "availability": available, "failure": None if available else "HTTP_503",
        "latency_s": 0.2, "transport_attempts": 1,
        "result": None if not available else {
            "choice": "STRICT_VIOLATION" if probability >= 0.5 else "STRICT_PASS",
            "probability_strict_violation": probability, "confidence": confidence,
            "usage": {"input_tokens": 10, "output_tokens": 2}, "model": "jev-latest",
        },
    }}


class ScoreTests(unittest.TestCase):
    def test_frozen_protocol_matches_runner(self):
        protocol = json.loads((Path(__file__).parent / "protocol.json").read_text(encoding="utf-8"))
        _validate_protocol(protocol)
        changed = dict(protocol)
        changed["decision_threshold"] = 0.4
        with self.assertRaises(ValueError):
            _validate_protocol(changed)

    def test_false_safe_false_alarm_brier_and_missing(self):
        output = score(_bench(), [_call(0, 0.1), _call(11, 0.9), _call(1, None),
                                   _call(2, 0.7, confidence=0.2)])
        summary = output["summary"]["geometry_only"]
        self.assertEqual(summary["false_safe_count"], 1)
        self.assertEqual(summary["false_alarm_count"], 1)
        self.assertEqual(summary["available"], 3)
        self.assertEqual(summary["unavailable"], 1)
        self.assertEqual(summary["not_attempted"], 14)
        self.assertEqual(summary["low_confidence_count"], 1)
        self.assertAlmostEqual(summary["brier_mean"], (0.81 + 0.81 + 0.09) / 3)
        self.assertEqual(summary["transport_attempts"], 4)
        self.assertEqual(summary["reported_input_tokens"], 30)

    def test_threshold_equal_half_is_risk(self):
        rows = score(_bench(), [_call(0, 0.5)])["rows"]
        self.assertTrue(rows[0]["predicted_strict_violation"])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            score(_bench(), [_call(0, 0.8), _call(0, 0.8)])

    def test_unavailable_not_scored_as_abstention(self):
        output = score(_bench(), [_call(0, None)])
        row = output["rows"][0]
        self.assertFalse(row["availability"])
        self.assertNotIn("correct", row)
        self.assertNotIn("low_confidence", row)


if __name__ == "__main__":
    unittest.main()
