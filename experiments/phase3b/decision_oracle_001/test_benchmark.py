"""Targeted integrity checks for the three retained decision fixtures."""

import json
import unittest
from pathlib import Path

from build_benchmark import COMPONENT, ROOT, digest, make_state, outcome_from_row, read_results
from oracle import context_fingerprint, decide, state_fingerprint, validate_state

BENCHMARK = Path(__file__).with_name("benchmark.json")


class BenchmarkEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
        cls.states = {item["state_id"]: item for item in cls.benchmark["states"]}
        cls.catalog = {item["state_id"]: item for item in cls.benchmark["catalog"]}

    def test_source_sha_pins_and_state_fingerprints(self):
        b = self.benchmark
        self.assertEqual(set(self.states), set(self.catalog))
        for source in (*b["artifact_sources"].values(), *b["state_sources"].values()):
            self.assertEqual(digest(Path(source["path"])), source["sha256"])
        for sid, state in self.states.items():
            validate_state(state)
            entry = self.catalog[sid]
            self.assertEqual(context_fingerprint(state["context"]), entry["context_fingerprint"])
            self.assertEqual(state_fingerprint(state), entry["state_fingerprint"])
            self.assertEqual(state["observables"]["previous_recovery"], None)
            for outcome in entry["outcomes"].values():
                path, rest = outcome["evidence_source"].split("#sha256=", 1)
                self.assertEqual(digest(Path(path)), rest.split(";", 1)[0])

    def test_oracle_labels_and_missing_cells(self):
        for sid, state in self.states.items():
            entry = self.catalog[sid]
            expected = self.benchmark["coverage"]["expected_offline_oracle_modes"][sid]
            self.assertEqual(decide(state, entry)["mode"], expected)
            missing = sorted(set(("LATERAL_RECOVERY", "YAW_RECOVERY", "COMBINED_RECOVERY")) - set(entry["outcomes"]))
            self.assertEqual(missing, self.benchmark["coverage"]["missing_modes_by_state"][sid])

    def test_predecision_states_recompute_from_traces(self):
        parameters = {
            "primitive-walk-8": (0, 8.0, 0.28, "Start->Walk8m"),
            "sequence-mixed-12m": (1, 4.0, 0.20, "Stand->Walk4m"),
            "sequence-mixed-16m": (1, 8.0, 0.28, "Stand->Walk8m"),
        }
        for sid, state in self.states.items():
            case = state["context"]["case_id"]
            source = self.benchmark["state_sources"][sid]
            self.assertEqual(digest(Path(source["path"])), source["sha256"])
            recomputed = make_state(case, Path(source["path"]), *parameters[case])
            self.assertEqual(recomputed, state)

    def test_off_outcomes_recompute_from_original_rows(self):
        rows = read_results()
        for case, row in rows.items():
            sid = f"{case}:first-walk-entry:alpha0.5:seed0"
            stored = self.catalog[sid]["outcomes"]["CONTINUE"]
            self.assertEqual(outcome_from_row(row, stored["evidence_source"]), stored)

    def test_16m_four_cells_recompute_from_raw_results(self):
        sid = "sequence-mixed-16m:first-walk-entry:alpha0.5:seed0"
        outcomes = self.catalog[sid]["outcomes"]
        mapping = {
            "CONTINUE": "off", "LATERAL_RECOVERY": "lateral",
            "YAW_RECOVERY": "yaw", "COMBINED_RECOVERY": "combined",
        }
        analysis = json.loads((ROOT / COMPONENT).read_text(encoding="utf-8"))
        for mode, arm in mapping.items():
            expected = outcomes[mode]
            source = analysis["evidence_sources"][arm]["result"]
            self.assertEqual(digest(Path(source["path"])), source["sha256"])
            raw = json.loads((ROOT / source["path"]).read_text(encoding="utf-8"))
            recomputed = outcome_from_row(raw, expected["evidence_source"])
            self.assertEqual(recomputed, expected)


if __name__ == "__main__":
    unittest.main()
