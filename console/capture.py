"""Offline, explicit historical visualization replay; never a training hook.

Physics runs without a renderer/browser/encoder. Capture copies decimated state
into local memory. Only after the entire replay closes is anything rendered.
Both capture-off/on executions are independently audited at every physics step.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from g1swarm.frame_learning.env import FrameRunner
from g1swarm.frame_learning.campaign import verify_freeze
from g1swarm.transition_learning.env import yaw

SOURCE = "experiments/phase3a/frame_residual_learning_001"
RESULT = SOURCE + "/evidence/evaluation/results.jsonl.gz"
POLICY = "third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt"
FPS = 20


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def tensor_digest(policy):
    digest = hashlib.sha256()
    for key, value in sorted(policy.state_dict().items()):
        digest.update(key.encode())
        digest.update(value.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def subset_equal(derived, original, path=""):
    """Compare scientific fields; exclude wall-clock and publication arm label.

    FrameRunner itself labels its inherited reference mode. The campaign adds
    the residual-off arm label after replay. This annotation is not a score.
    """
    if isinstance(derived, dict):
        return all("wall" in k or k == "treatment_label" or (k in original and subset_equal(v, original[k], path + "/" + k))
                   for k, v in derived.items())
    if isinstance(derived, list):
        return isinstance(original, list) and len(derived) == len(original) and all(
            subset_equal(a, b, path) for a, b in zip(derived, original))
    return derived == original


class CaptureSimulation:
    def __init__(self, sim, runner, capture):
        self.sim, self.runner, self.capture = sim, runner, capture
        self.steps = 0
        self.hash = hashlib.sha256()
        self.states = []
        if capture:
            self.snapshot()

    def __getattr__(self, name):
        return getattr(self.sim, name)

    def snapshot(self):
        r, d = self.runner, self.sim._data
        local = getattr(r, "frame", None)
        reference = None
        if local is not None and r.skill == "walk_forward":
            reference = r.correction.selected_frame(local).initial_yaw_rad
        self.states.append((float(d.time), d.qpos.copy(), d.qvel.copy(), d.ctrl.copy(),
                            r.index, r.planned_origin.copy(), float(r.planned_heading),
                            np.array(local.initial_position[:2]) if local else d.qpos[:2].copy(),
                            float(local.initial_yaw_rad) if local else yaw(self.sim.get_robot_state()),
                            np.nan if reference is None else reference))

    def step(self, control=None):
        state = self.sim.step(control)
        self.steps += 1
        d = self.sim._data
        for value in (np.array([d.time]), d.qpos, d.qvel, d.ctrl):
            self.hash.update(np.asarray(value).tobytes())
        if self.capture and self.steps % 25 == 0:
            self.snapshot()
        return state


class AuditedRunner(FrameRunner):
    def __init__(self, case, alpha, capture):
        super().__init__(case, alpha)
        self.rows = []
        self.audit_hashes = {name: hashlib.sha256() for name in
                             ("commands", "torques", "base_observations", "base_actions", "residual_observations", "rewards")}
        self.audit_counts = dict.fromkeys(self.audit_hashes, 0)
        self.sim = CaptureSimulation(self.sim, self, capture)
        original_torques = self.base.compute_torques
        original_obs = self.base._build_observation

        def observed_torques(**kwargs):
            self.audit_array("commands", kwargs["command"])
            value = original_torques(**kwargs)
            self.audit_array("torques", value)
            self.audit_array("base_actions", self.base._action)
            return value

        def observed_obs(*args, **kwargs):
            value = original_obs(*args, **kwargs)
            self.audit_array("base_observations", value)
            return value

        self.base.compute_torques = observed_torques
        self.base._build_observation = observed_obs

    def audit_array(self, name, value):
        self.audit_counts[name] += 1
        self.audit_hashes[name].update(np.asarray(value).tobytes())

    def observation(self, *args, **kwargs):
        value = super().observation(*args, **kwargs)
        self.audit_array("residual_observations", value)
        return value

    def dense_reward(self):
        value = super().dense_reward()
        self.audit_array("rewards", np.array([value]))
        return value

    def trace(self, row):
        super().trace(row)
        self.rows.append(self.last_command_trace)


def execute(case, alpha, capture):
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    r = AuditedRunner(case, alpha, capture)
    before_tensor = tensor_digest(r.base._policy)
    try:
        record = r.run()
        # Final pose is always retained, independent of video cadence.
        if capture and r.sim.states[-1][0] != r.sim.simulation_time:
            r.sim.snapshot()
        audit = {"physics_state_sha256": r.sim.hash.hexdigest(), "physics_steps": r.sim.steps,
                 "streams": {k: {"sha256": v.hexdigest(), "count": r.audit_counts[k]}
                             for k, v in r.audit_hashes.items()},
                 "initial_policy_tensors_sha256": before_tensor,
                 "final_policy_tensors_sha256": tensor_digest(r.base._policy),
                 "rng_after_sha256": digest_json({"python": repr(random.getstate()),
                     "numpy": repr(np.random.get_state()), "torch": torch.get_rng_state().tolist()}),
                 "trace_sha256": digest_json(r.rows)}
        return record, audit, r.sim.states, r.rows
    finally:
        r.close()


def capture_arm(output, alpha):
    freeze = verify_freeze()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    case_manifest = json.loads((ROOT / SOURCE / "case_manifest.json").read_text())
    case = next(c for c in case_manifest["regression"] if c["id"] == "sequence-mixed-16m")
    lines = gzip.decompress((ROOT / RESULT).read_bytes()).decode().splitlines()
    label = f"alpha{alpha:g}-residual-off"
    matches = [(i + 1, json.loads(line)) for i, line in enumerate(lines)
               if json.loads(line)["case_id"] == case["id"] and json.loads(line)["treatment_label"] == label
               and json.loads(line)["phase"] == "primary"]
    assert len(matches) == 1
    line, source_record = matches[0]
    output.mkdir(parents=True, exist_ok=False)
    off, off_audit, _, off_trace = execute(case, alpha, False)
    on, on_audit, states, on_trace = execute(case, alpha, True)
    trace_path = SOURCE + f"/evidence/evaluation/traces/primary--{label}--{case['id']}.jsonl.gz"
    source_trace = [json.loads(x) for x in gzip.decompress((ROOT / trace_path).read_bytes()).decode().splitlines()]
    certificate = {"capture_off_on_equal": off_audit == on_audit and subset_equal(off, on),
                   "historical_record_exact": subset_equal(on, source_record),
                   "historical_command_trace_exact": on_trace == source_trace,
                   "historical_joint_states_available": False,
                   "scope": "offline residual-off visualization replay, NOT a live PPO training observer",
                   "capture_off": off_audit, "capture_on": on_audit,
                   "no_renderer_encoder_browser_in_physics_process": True,
                   "reward_calls": 0, "optimizer_updates": 0, "checkpoint_written": False}
    write_json(output / "parity.json", certificate)
    write_json(output / "derived_result.json", on)
    write_json(output / "unobserved_result.json", off)
    with (output / "derived_trace.jsonl.gz").open("xb") as handle:
        handle.write(gzip.compress(("\n".join(json.dumps(r, allow_nan=False) for r in on_trace) + "\n").encode(), mtime=0))
    fields = list(zip(*states))
    np.savez_compressed(output / "poses.npz", time_s=fields[0], qpos=fields[1], qvel=fields[2], ctrl=fields[3],
                        node_index=fields[4], planned_origin=fields[5], planned_heading=fields[6],
                        local_origin=fields[7], local_heading=fields[8], reference_heading=fields[9])
    provenance = {"experiment_id": "frame_residual_learning_001", "treatment": label,
                  "seed": None, "case_id": case["id"], "protocol_sha": sha(ROOT / SOURCE / "protocol.json"),
                  "source_commit": source_record["provenance"]["code_commit"],
                  "source_evidence_commit": "86d1883db84a53de57eacfab061234f2a118c94c",
                  "producer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "producer_code_sha": sha(Path(__file__)), "policy_sha": sha(ROOT / POLICY),
                  "checkpoint_sha": None, "policy_identity": "official pretrained motion.pt; residual OFF",
                  "source_result_path": RESULT, "source_result_line": line,
                  "source_result_locator": RESULT + f"#decoded-line={line}",
                  "source_trace_path": trace_path, "source_trace_locator": trace_path + "#decoded-lines=1-end",
                  "source_protocol_path": SOURCE + "/protocol.json",
                  "source_manifest_path": SOURCE + "/evidence_manifest.json",
                  "source_result_sha": sha(ROOT / RESULT), "source_trace_sha": sha(ROOT / trace_path),
                  "source_manifest_sha": sha(ROOT / SOURCE / "evidence_manifest.json"),
                  "pose_sha": sha(output / "poses.npz"), "parity_sha": sha(output / "parity.json"),
                  "visual_source": "derived_visualization_replay", "original_video_available": False,
                  "historical_pose_identity_claim": "Unavailable; original trace has no joint states. Exact archived record/command trace verified.",
                  "frame_fps": FPS, "physics_timestep_s": .002, "freeze_verification": freeze}
    write_json(output / "capture_manifest.json", {"provenance": provenance, "case": case,
               "alpha": alpha, "source_record": source_record, "source_result_line": line,
               "capture_frequency_hz": FPS, "captured_states": len(states), "parity": certificate})
    if not all(certificate[k] for k in ("capture_off_on_equal", "historical_record_exact", "historical_command_trace_exact")):
        raise RuntimeError("Replay integrity mismatch; negative artifacts retained, no publication")
    print(json.dumps({"alpha": alpha, "passed": True, "states": len(states), "source_result_line": line}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--alpha", type=float, choices=[0, .5], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture_arm(args.output, args.alpha)
