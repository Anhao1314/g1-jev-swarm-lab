"""Synthetic branch checks; synthetic cells are not scientific benchmark evidence."""

import copy
import unittest

from oracle import CONTRACT_ID, context_fingerprint, decide, state_fingerprint


def state():
    return {
        "state_id": "synthetic-state-1",
        "context": {
            "case_id": "synthetic", "seed": 0, "decision_epoch": "first_walk_entry",
            "skill": "Walk8m", "transition": "Stand->Walk8m", "alpha": 0.5,
            "origin": "actual-start", "reference_id": "reference-synthetic",
            "controller_id": "controller-synthetic", "evaluator_id": "evaluator-synthetic",
            "policy_id": "policy-synthetic", "residual_bounds_id": "bounds-synthetic",
            "recovery_contract_id": CONTRACT_ID,
        },
        "observables": {
            "local_lateral_error_m": 0.0, "local_heading_error_deg": 0.0,
            "route_x_error_m": 0.1, "route_y_error_m": -0.2,
            "route_heading_error_deg": -2.0, "reference_heading_deg": -1.0,
            "instantaneous_strict_margin_m": 0.28, "remaining_distance_m": 8.0,
            "previous_recovery": None,
        },
    }


def outcome(strict=False, norm=1.2, lateral=-1.0, heading=-1.0, physical=True):
    return {
        "nominal": True, "physical": physical, "all_strict": strict,
        "final_world_x_error_m": 0.5, "final_world_y_error_m": -1.0,
        "final_lateral_error_m": lateral, "final_heading_error_deg": heading,
        "endpoint_norm_m": norm, "evidence_source": "SYNTHETIC_TEST_ONLY",
    }


def catalog(s, off, lateral=None, yaw=None, combined=None):
    return {
        "state_id": s["state_id"], "context_fingerprint": context_fingerprint(s["context"]),
        "state_fingerprint": state_fingerprint(s),
        "outcomes": {"CONTINUE": off, "LATERAL_RECOVERY": lateral,
                     "YAW_RECOVERY": yaw, "COMBINED_RECOVERY": combined},
    }


class OracleTest(unittest.TestCase):
    def test_continue_preferred_when_off_admissible(self):
        s = state()
        c = catalog(s, outcome(strict=True))
        self.assertEqual(decide(s, c), {"mode": "CONTINUE", "reason": "OFF_ADMISSIBLE"})

    def test_no_admissible_fixed_16m_shape(self):
        s = state()
        c = catalog(s, outcome(), outcome(norm=1.21), outcome(norm=1.23),
                    outcome(strict=True, norm=1.26))
        self.assertEqual(decide(s, c), {"mode": "ABSTAIN", "reason": "NO_ADMISSIBLE_RECOVERY"})

    def test_unique_admissible_recovery(self):
        s = state()
        c = catalog(s, outcome(), outcome(strict=True, norm=1.1),
                    outcome(norm=1.1), outcome(strict=True, norm=1.3))
        self.assertEqual(decide(s, c), {"mode": "LATERAL_RECOVERY", "reason": "UNIQUE_ADMISSIBLE_RECOVERY"})

    def test_missing_cell_prevents_unique_claim(self):
        s = state()
        c = catalog(s, outcome(), outcome(strict=True, norm=1.1), None,
                    outcome(strict=True, norm=1.3))
        self.assertEqual(decide(s, c)["reason"], "MISSING_RECOVERY_EVIDENCE")

    def test_missing_off_comparator(self):
        s = state()
        self.assertEqual(decide(s, catalog(s, None))["reason"], "MISSING_OFF_COMPARATOR")

    def test_ambiguous_candidates_abstain(self):
        s = state()
        c = catalog(s, outcome(), outcome(strict=True, norm=1.1),
                    outcome(strict=True, norm=1.15), outcome())
        self.assertEqual(decide(s, c)["reason"], "AMBIGUOUS_ADMISSIBLE_RECOVERY")

    def test_global_lateral_or_heading_regression_rejected(self):
        s = state()
        c = catalog(s, outcome(), outcome(strict=True, norm=1.1, lateral=-1.1),
                    outcome(strict=True, norm=1.1, heading=-1.1), outcome())
        self.assertEqual(decide(s, c)["reason"], "NO_ADMISSIBLE_RECOVERY")

    def test_tiny_norm_gain_not_scientific_improvement(self):
        s = state()
        c = catalog(s, outcome(), outcome(strict=True, norm=1.2 - 5e-11), outcome(), outcome())
        self.assertEqual(decide(s, c)["reason"], "NO_ADMISSIBLE_RECOVERY")

    def test_context_and_state_mismatch(self):
        s = state()
        c = catalog(s, outcome(strict=True))
        changed = copy.deepcopy(s)
        changed["context"]["reference_id"] = "another-reference"
        self.assertEqual(decide(changed, c)["reason"], "CONTEXT_MISMATCH")
        changed = copy.deepcopy(s)
        changed["state_id"] = "other-state"
        self.assertEqual(decide(changed, c)["reason"], "CONTEXT_MISMATCH")
        changed = copy.deepcopy(s)
        changed["observables"]["route_x_error_m"] += 0.01
        self.assertEqual(decide(changed, c)["reason"], "CONTEXT_MISMATCH")

    def test_future_outcome_field_rejected_from_state(self):
        s = state()
        s["observables"]["final_endpoint_norm_m"] = 0.0
        with self.assertRaises(ValueError):
            decide(s, None)

    def test_recovery_only_first_walk8m_entry(self):
        s = state()
        s["context"]["skill"] = "Turn"
        c = catalog(s, outcome(), outcome(strict=True, norm=1.1), outcome(), outcome())
        self.assertEqual(decide(s, c)["reason"], "RECOVERY_OUT_OF_SCOPE")
        c["outcomes"]["CONTINUE"] = outcome(strict=True)
        self.assertEqual(decide(s, c)["mode"], "CONTINUE")
        primitive = state()
        primitive["context"]["transition"] = "Start->Walk8m"
        primitive_catalog = catalog(primitive, outcome(), outcome(strict=True, norm=1.1), outcome(), outcome())
        self.assertEqual(decide(primitive, primitive_catalog)["reason"], "RECOVERY_OUT_OF_SCOPE")
        primitive_catalog["outcomes"]["CONTINUE"] = outcome(strict=True)
        self.assertEqual(decide(primitive, primitive_catalog)["mode"], "CONTINUE")

    def test_nonfinite_and_unknown_mode_rejected(self):
        s = state()
        s["observables"]["route_x_error_m"] = float("nan")
        with self.assertRaises(ValueError):
            decide(s, None)
        s = state()
        c = catalog(s, outcome())
        c["outcomes"]["new-unproven-mode"] = outcome(strict=True, norm=0.0)
        with self.assertRaises(ValueError):
            decide(s, c)


if __name__ == "__main__":
    unittest.main()
