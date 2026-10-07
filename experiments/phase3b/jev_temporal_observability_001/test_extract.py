"""Focused integrity checks for read-only historical snapshot extraction."""

import importlib.util
import unittest
from collections import Counter
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("extract.py")
spec = importlib.util.spec_from_file_location("temporal_extract", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SnapshotTests(unittest.TestCase):
    def test_fixed_snapshot_requires_recorded_pre_endpoint_sample(self):
        row = {"node_index": 0, "elapsed_s": 1.0000000000000002,
               **{key: 0 for key in module.RECORDED}}
        self.assertTrue(module.fixed_snapshot([row], 0, 1.0, 3.0)["available"])
        self.assertFalse(module.fixed_snapshot([row], 0, 2.0, 3.0)["available"])
        self.assertFalse(module.fixed_snapshot([row], 0, 3.0, 3.0)["available"])

    def test_full_frozen_cohort_and_no_geometry_in_snapshot(self):
        result = module.build()
        self.assertEqual(result["source_cells"], 24)
        self.assertEqual(result["prior_assessment_units"], 18)
        self.assertEqual(result["snapshots_elapsed_s"], [0.0, 1.0, 2.0])
        self.assertEqual(Counter(c["prior_jev_class"] for c in result["cells"]),
                         {"true_safe": 13, "false_safe": 7, "true_positive": 4})
        self.assertEqual(len({c["prior_paired_unit_id"] for c in result["cells"]}), 18)
        self.assertEqual(len(result["source_hashes"]), 24)
        for cell in result["cells"]:
            self.assertEqual(len(cell["snapshots"]), 3)
            for snap in cell["snapshots"]:
                self.assertTrue(snap["available"])
                self.assertEqual(set(snap["recorded"]), set(module.RECORDED))
                self.assertEqual(set(snap["unavailable"]), set(module.UNAVAILABLE))
                self.assertFalse(set(module.UNAVAILABLE) & set(snap["recorded"]))


if __name__ == "__main__":
    unittest.main()
