"""Focused frozen-cohort checks for the descriptive entry controls."""

import importlib.util
from pathlib import Path


def test_entry_controls_preserve_prior_negative_result():
    path = Path(__file__).with_name("analyze.py")
    spec = importlib.util.spec_from_file_location("temporal_analysis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.build()
    assert result["visible_units"] == 18
    assert result["class_counts"] == {"true_safe": 7, "false_safe": 7, "true_positive": 4}
    assert result["exact_opposite_label_aliases"] == 0
    assert result["entry_contract_limit_rule"] == {
        "status": "post_hoc_contract_derived_descriptive_control",
        "definition": "abs(entry heading)>frozen heading limit OR abs(entry lateral)>frozen lateral limit",
        "agreement_with_prior_jev_binary": 18,
        "accuracy": 11,
        "false_safe": 7,
        "false_alarm": 0,
    }
    assert result["always_risk_control"] == {"accuracy": 11, "false_safe": 0, "false_alarm": 7}
