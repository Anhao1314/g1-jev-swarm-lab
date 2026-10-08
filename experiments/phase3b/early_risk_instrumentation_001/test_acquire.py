"""Protocol checks that do not run physics or call providers."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("early_risk_acquire", HERE / "acquire.py")
acquire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acquire)


def test_protocol_membership_and_source_hashes():
    protocol, cases, historical = acquire.validate_membership()
    assert len(cases) == 7
    assert sum(len(nodes) for _, nodes in cases) == 8
    assert len(protocol["selected_nodes"]) == 8
    assert all(f"{case['id']}:node-{i}" in historical for case, nodes in cases for i in nodes)


def test_strict_label_or_missing_checkpoint_stops():
    _, cases, historical = acquire.validate_membership()
    case, nodes = cases[0]
    index = next(iter(nodes))
    node = {"skill": "walk_forward", "strict_success": historical[f"{case['id']}:node-{index}"]["strict_violation"],
            "duration_s": 5.0}
    arm = {"record": {"case_id": case["id"], "treatment": "frozen_baseline", "nodes": [node]},
           "observer": {"observer_enabled": True, "snapshots": {}}}
    try:
        acquire.validate_observation(case, nodes, arm, historical)
    except AssertionError as exc:
        assert "label drift" in str(exc)
    else:
        raise AssertionError("Changed historical label accepted")
