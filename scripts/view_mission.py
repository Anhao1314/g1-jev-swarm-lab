"""Interactive MuJoCo viewer for Phase 2.0 missions (observation only).

Plays one structured Mission IR document through the *real* Phase 2.0 pipeline
(static validator -> capability grounder -> task graph -> deterministic
executor) on one continuous simulation, while the interactive MuJoCo viewer is
synchronised with the physics and a small overlay shows the live mission state.

Nothing here changes the runtime: the viewer wraps the existing
``LiveMissionSession`` through its ``simulation_wrapper`` hook, adds real-time
pacing, viewer synchronisation and clean exit handling, and never feeds
metrics back into the runtime. Viewer runs are an observation tool - they are
not benchmark evidence (``--write-evidence`` opts in explicitly and labels the
run as ``viewer``).

``--speed`` only changes wall-clock pacing; the physics, the skills and the
grounded execution modes are untouched, so a viewer run produces exactly the
same trajectory as the headless runtime.

Examples::

    python scripts/view_mission.py --list
    python scripts/view_mission.py --mission h5-stand-walk4-turn45-walk4-stop
    python scripts/view_mission.py --mission h1-walk8 --speed 2.0
    python scripts/view_mission.py --mission h3-walk4-turn45-stop --plan-only
    python scripts/view_mission.py --mission h3-walk4-turn45-stop --no-viewer
    python scripts/view_mission.py --mission-file my_mission.yaml --exit-after-mission

Exit codes: 0 = mission succeeded (or report-only command), 1 = usage or
validation failure, 2 = capability rejected/unknown (zero simulation steps),
3 = mission failed, 130 = window closed or Ctrl+C before the mission finished.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path
from typing import Any, Mapping

import mujoco
import yaml

from g1swarm.characterization.kinematics import (
    forward_lateral,
    horizontal_offset,
    wrap_angle_deg,
    yaw_deg,
    yaw_rad,
)
from g1swarm.config import load_yaml
from g1swarm.evidence import EnvironmentInfo
from g1swarm.mission import (
    CapabilityGrounder,
    CorpusError,
    GroundedPlan,
    LiveMissionSession,
    Mission,
    MissionExecutor,
    MissionIRError,
    MissionValidator,
    NodeExecution,
    TaskGraph,
    ValidationReport,
    load_corpus,
    mission_document,
)
from g1swarm.paths import artifacts_dir, repo_root, resolve_repo_path

DEFAULT_PROTOCOL = "configs/experiments/oracle_mission_runtime_001.yaml"
DEFAULT_ROBOT = "configs/robot/g1_locomotion_12dof.yaml"

HUD_FONT = mujoco.mjtFontScale.mjFONTSCALE_150
GRID = mujoco.mjtGridPos

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REJECTED = 2
EXIT_FAILED = 3
EXIT_INTERRUPTED = 130


# ----------------------------------------------------------------------
# Corpus / document loading
# ----------------------------------------------------------------------
def load_document(path: Path) -> dict[str, Any]:
    # YAML is a superset of JSON, so one loader covers both mission file types.
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise MissionIRError(f"{path} must contain a mapping")
    return dict(document)


def corpus_entries(corpus: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Valid and negative corpus entries, tagged with the section they came from."""

    entries: list[dict[str, Any]] = []
    for section in ("missions", "negatives"):
        for raw in corpus.get(section, []) or []:
            entry = dict(raw)
            entry["_section"] = section
            entries.append(entry)
    return entries


def find_entry(entries: list[dict[str, Any]], mission_id: str) -> dict[str, Any]:
    for entry in entries:
        if entry.get("mission_id") == mission_id:
            return entry
    raise MissionIRError(f"mission {mission_id!r} is not in the corpus (use --list)")


# ----------------------------------------------------------------------
# Reporting helpers
# ----------------------------------------------------------------------
def parameters_text(parameters: Mapping[str, float]) -> str:
    if not parameters:
        return "-"
    return " ".join(f"{key}={value:g}" for key, value in sorted(parameters.items()))


def print_corpus(entries: list[dict[str, Any]], corpus_id: str) -> None:
    print(f"corpus {corpus_id}: {len(entries)} mission(s)")
    for entry in entries:
        section = entry.get("_section", "missions")
        marker = "" if section == "missions" else " [negative]"
        print(
            f"  {entry['mission_id']:<46} {str(entry.get('horizon', '-')):<3}"
            f" {len(entry['steps'])} step(s){marker}  {entry.get('purpose', '')}"
        )


def print_validation(mission: Mission, report: ValidationReport) -> None:
    status = "VALID" if report.valid else "INVALID"
    print(f"Validation: {status} ({len(report.issues)} issue(s))")
    for issue in report.issues:
        location = f" [{issue.step_id}]" if issue.step_id else ""
        print(f"  - {issue.code}{location}: {issue.message}")


def print_grounding(plan: GroundedPlan) -> None:
    print(f"Grounding: {plan.status}")
    for result in plan.results:
        mode = result.execution_mode or "-"
        risk = result.risk or "-"
        source = result.source_phase or "-"
        print(
            f"  {result.step_id:<4} {result.skill:<13} {mode:<16} risk={risk:<7}"
            f" {source:<19} {'OK' if result.supported else result.status}"
        )
        if not result.supported:
            print(f"       reason: {result.reason}")


def print_task_graph(graph: TaskGraph) -> None:
    order = " -> ".join(node.node_id for node in graph.nodes)
    print(f"Task graph ({len(graph.nodes)} node(s)): {order}")


def print_node_line(index: int, total: int, node, execution: NodeExecution) -> None:
    metrics = execution.metrics
    end_state = execution.end_state or {}
    position = end_state.get("base_position")
    orientation = end_state.get("base_orientation")
    position_text = (
        f"({float(position[0]):+.2f}, {float(position[1]):+.2f}, {float(position[2]):.2f})"
        if position is not None and len(position) >= 3
        else "n/a"
    )
    heading_text = (
        f"{yaw_deg(orientation):+.2f} deg" if orientation is not None else "n/a"
    )
    print(
        f"[{index}/{total}] done  {node.skill.value:<13}"
        f" {parameters_text(node.parameters):<20} mode={node.execution_mode:<16}"
        f" {execution.status:<8} t={metrics.get('simulation_time_s', 0.0):5.2f}s"
        f" steps={metrics.get('simulation_steps', 0):5d}"
        f" fwd={metrics.get('forward_displacement_m', 0.0):+.2f}m"
        f" lat={metrics.get('lateral_drift_m', 0.0):+.2f}m"
        f" head={metrics.get('heading_error_deg', 0.0):+6.2f}deg"
    )
    print(
        f"       base={position_text} heading={heading_text}"
        f" heading_error={metrics.get('heading_error_deg', 0.0):+6.2f} deg"
    )
    if execution.reason:
        print(f"       reason: {execution.reason}")


def print_mission_result(result) -> None:
    print()
    print(f"Mission {result.mission_id}: {result.state}")
    print(
        f"  success={result.mission_success}  completed={result.completed_nodes} node(s)"
        f"  failed_node={result.failed_node}  failure={result.failure_type}"
    )
    if result.failure_reason:
        print(f"  reason: {result.failure_reason}")
    print(
        f"  simulated={result.total_simulation_time_s:.2f}s"
        f"  wall={result.total_wall_time_s:.2f}s"
        f"  steps={result.simulation_steps_executed}"
        f"  path={result.path_length_m:.2f}m"
        f"  transitions={result.transition_count}"
        f"  memory_resets={result.controller_memory_resets}"
    )
    for payload in result.nodes:
        metrics = payload["metrics"]
        print(
            f"  {payload['node_id']:<4} {payload['skill']:<13} {metrics['skill_status']:<8}"
            f" physical={str(metrics['physical_success']):<5}"
            f" task={str(metrics['task_success']):<5}"
            f" path={metrics.get('path_length_m', 0.0):6.2f}m"
            f" fail={metrics.get('failure_type')}"
        )


def expectation_text(entry: Mapping[str, Any] | None, plan: GroundedPlan) -> str | None:
    if entry is None:
        return None
    expected = entry.get("expected") or {}
    checks: list[str] = []
    if "grounding" in expected:
        checks.append(f"grounding {plan.status} (expected {expected['grounding']})")
    if "default_mode" in expected:
        modes = {
            result.execution_mode
            for result in plan.results
            if result.skill == "walk_forward" and result.execution_mode
        }
        observed = ",".join(sorted(mode for mode in modes if mode)) or "-"
        checks.append(f"walk mode {observed} (expected {expected['default_mode']})")
    return "; ".join(checks)


# ----------------------------------------------------------------------
# Viewer session
# ----------------------------------------------------------------------
class ViewerClosed(KeyboardInterrupt):
    """Raised when the MuJoCo window goes away.

    Deriving from ``KeyboardInterrupt`` (a ``BaseException``) is deliberate:
    the deterministic executor classifies ``Exception`` as INTERNAL_ERROR, and
    a closed window is not a mission failure.
    """


class ViewerProxy:
    """Wraps the node monitor with viewer sync, pacing and exit checks."""

    def __init__(self, monitor, session: "ViewerMissionSession") -> None:
        self._monitor = monitor
        self._session = session
        self._steps_since_sync = 0

    def step(self, control=None):
        viewer = self._session.viewer
        if viewer is None or not viewer.is_running():
            raise ViewerClosed("viewer window closed")
        started = time.perf_counter()
        state = self._monitor.step(control)
        self._session.node_steps = int(self._monitor.steps)
        self._steps_since_sync += 1
        if self._steps_since_sync >= self._session.sync_every:
            self._steps_since_sync = 0
            viewer.sync()
            self._session.update_hud(state)
        elapsed = time.perf_counter() - started
        remaining = float(self._monitor.timestep) / self._session.speed - elapsed
        if remaining > 0.0:
            time.sleep(remaining)
        return state

    def __getattr__(self, name: str):
        return getattr(self._monitor, name)


class ViewerMissionSession(LiveMissionSession):
    """``LiveMissionSession`` plus viewer synchronisation and a live HUD."""

    def __init__(
        self,
        *,
        robot_config: Mapping[str, Any],
        protocol: Mapping[str, Any],
        seed: int = 0,
        with_viewer: bool = True,
        speed: float = 1.0,
        sync_every: int = 8,
        node_pause_s: float = 1.0,
        track_camera: bool = True,
    ) -> None:
        self.speed = max(0.05, float(speed))
        self.sync_every = max(1, int(sync_every))
        self.node_pause_s = max(0.0, float(node_pause_s))
        self.track_camera = bool(track_camera)
        self.with_viewer = bool(with_viewer)
        self.viewer = None
        self.mission_id = ""
        self.mission_state = "RUNNING"
        self.node_index = 0
        self.node_total = 0
        self.node_steps = 0
        self.current_node = None
        self.current_risk = "-"
        self.node_start_state = None
        super().__init__(
            robot_config=robot_config,
            protocol=protocol,
            seed=seed,
            simulation_wrapper=self._wrap_simulation,
        )
        if self.with_viewer:
            self.viewer = self.simulation.open_viewer()
            if self.viewer is not None and self.track_camera:
                self._track_base_body()

    # -- viewer plumbing ------------------------------------------------
    def _wrap_simulation(self, monitor):
        if self.viewer is None:
            return monitor
        return ViewerProxy(monitor, self)

    def _track_base_body(self) -> None:
        """Keep the camera on the robot; a 4-10 m walk leaves a free camera behind."""

        viewer = self.viewer
        if viewer is None:
            return
        model = viewer.m  # mujoco.viewer.Handle exposes the model as `.m`
        if model is None:
            return
        body_name = str(self.robot_config.get("model", {}).get("base_body_name", "pelvis"))
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
        if body_id < 0:
            return
        viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
        viewer.cam.trackbodyid = int(body_id)
        viewer.cam.distance = 3.0
        viewer.cam.elevation = -20.0


    def update_hud(self, state) -> None:
        viewer = self.viewer
        if viewer is None or not viewer.is_running():
            return
        node = self.current_node
        if node is None:
            header = f"mission {self.mission_id}"
            detail = "pre-flight"
        else:
            header = (
                f"mission {self.mission_id}   node {self.node_index}/{self.node_total}"
                f"   {node.skill.value} {parameters_text(node.parameters)}"
            )
            detail = f"mode {node.execution_mode}   risk {self.current_risk}"
        forward = lateral = heading = 0.0
        if self.node_start_state is not None:
            offset = horizontal_offset(self.node_start_state, state)
            forward, lateral = forward_lateral(
                offset, yaw_rad(self.node_start_state.base_orientation)
            )
            heading = wrap_angle_deg(
                yaw_deg(state.base_orientation) - yaw_deg(self.node_start_state.base_orientation)
            )
        viewer.set_texts(
            [
                (HUD_FONT, GRID.mjGRID_TOPLEFT, header, detail),
                (
                    HUD_FONT,
                    GRID.mjGRID_TOPRIGHT,
                    f"sim {state.simulation_time:7.2f} s",
                    f"mission {self.mission_state}",
                ),
                (
                    HUD_FONT,
                    GRID.mjGRID_BOTTOMLEFT,
                    f"node fwd {forward:+.2f} m   lat {lateral:+.2f} m",
                    f"heading err {heading:+.1f} deg",
                ),
                (
                    HUD_FONT,
                    GRID.mjGRID_BOTTOMRIGHT,
                    f"speed {self.speed:g}x   steps {self.total_steps + self.node_steps}",
                    "close window to stop",
                ),
            ]
        )

    def _pause(self, seconds: float, state=None) -> None:
        if self.viewer is None or seconds <= 0.0:
            return
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            if not self.viewer.is_running():
                raise ViewerClosed("viewer window closed")
            self.viewer.sync()
            self.update_hud(state if state is not None else self.current_state)
            time.sleep(min(0.05, max(0.0, deadline - time.perf_counter())))

    # -- mission hooks --------------------------------------------------
    def run_node(self, node, execution_mode: str) -> NodeExecution:
        self.node_index += 1
        self.node_steps = 0
        self.current_node = node
        self.current_risk = getattr(node, "risk", "-") or "-"
        self.node_start_state = self.current_state
        self.update_hud(self.current_state)
        print(
            f"[{self.node_index}/{self.node_total}] start {node.skill.value}"
            f" {parameters_text(node.parameters)}  mode={execution_mode}  risk={self.current_risk}"
        )
        execution = super().run_node(node, execution_mode)
        self.node_steps = 0
        print_node_line(self.node_index, self.node_total, node, execution)
        if execution.status == "SUCCESS" and execution.physical_success:
            if self.node_index >= self.node_total:
                self.mission_state = "SUCCESS"
        else:
            self.mission_state = "FAILED"
        self.update_hud(self.current_state)
        self._pause(self.node_pause_s, self.current_state)
        return execution

    # -- lifecycle ------------------------------------------------------
    def close(self) -> None:
        """Executor hook: keep the final frame visible in viewer mode."""

        if self.viewer is not None:
            return
        super().close()

    def shutdown(self, *, hold_seconds: float | None) -> None:
        """Hold the final frame, then release the simulation and the window."""

        if self.viewer is not None:
            deadline = None if hold_seconds is None else time.perf_counter() + max(
                0.0, float(hold_seconds)
            )
            try:
                while self.viewer is not None and self.viewer.is_running():
                    if deadline is not None and time.perf_counter() >= deadline:
                        break
                    self.viewer.sync()
                    self.update_hud(self.current_state)
                    time.sleep(0.05)
            except KeyboardInterrupt:  # pragma: no cover - interactive path
                pass
        super().close()
        self.viewer = None


# ----------------------------------------------------------------------
# Wiring
# ----------------------------------------------------------------------
def build_grounder(protocol: Mapping[str, Any]) -> CapabilityGrounder:
    grounding = protocol["grounding"]
    evidence = grounding["evidence"]
    capability_map = evidence.get("capability_map")
    return CapabilityGrounder(
        risk_map_path=resolve_repo_path(evidence["risk_map"]),
        boundary_comparison_path=resolve_repo_path(evidence["boundary_comparison"]),
        capability_map_path=resolve_repo_path(capability_map) if capability_map else None,
        mode_preference=grounding.get(
            "mode_preference", ("heading_lateral", "heading_only", "open_loop")
        ),
        historical_limits=grounding.get("historical", {}),
    )


def ensure_repo_output(path: Path) -> Path:
    """Reject viewer evidence redirection outside the repository workspace."""

    root = repo_root().resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise MissionIRError(f"evidence path escapes repository: {resolved}")
    return resolved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive MuJoCo viewer for Phase 2.0 missions (observation only).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL, help="frozen experiment protocol")
    parser.add_argument("--mission", default=None, help="mission_id to play from the corpus")
    parser.add_argument("--no-viewer", action="store_true", help="run headless at full speed")
    parser.add_argument("--free-camera", action="store_true", help="no base tracking")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--robot", default=None, help="robot config (default: from protocol)")
    parser.add_argument("--corpus", default=None, help="corpus (default: from protocol)")
    parser.add_argument("--mission-file", default=None, help="single Mission IR YAML/JSON file")
    parser.add_argument("--list", action="store_true", help="list corpus missions")
    parser.add_argument("--plan-only", action="store_true", help="print plan and exit")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed vs real time")
    parser.add_argument("--sync-every", type=int, default=8, help="sync every N steps")
    parser.add_argument("--node-pause", type=float, default=1.0, help="frozen pause per node")
    parser.add_argument("--hold-open-seconds", type=float, default=None, help="hold last frame")
    parser.add_argument("--exit-after-mission", action="store_true", help="close viewer at end")
    parser.add_argument("--write-evidence", action="store_true", help="write viewer bundle")
    parser.add_argument("--evidence-root", default=None, help="evidence root")
    return parser.parse_args(argv)


def select_mission(
    args: argparse.Namespace, protocol: Mapping[str, Any], corpus_path: Path
) -> tuple[Mission, dict[str, Any] | None]:
    if args.mission_file:
        path = resolve_repo_path(args.mission_file)
        document = load_document(path)
        return Mission.from_dict(document), None
    if not args.mission:
        raise MissionIRError("pass --mission <mission_id>, --mission-file <path>, or --list")
    corpus = load_corpus(corpus_path)
    entry = find_entry(corpus_entries(corpus), args.mission)
    schema_version = str(corpus.get("schema_version", protocol["mission_schema_version"]))
    return Mission.from_dict(mission_document(entry, schema_version)), entry


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    protocol_path = resolve_repo_path(args.protocol)
    protocol = load_yaml(protocol_path)
    protocol["protocol_path"] = str(protocol_path)
    protocol["_protocol_sha256"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    corpus_path = resolve_repo_path(args.corpus or protocol["mission_corpus"])

    if args.list:
        if args.mission or args.mission_file:
            print("--list ignores --mission/--mission-file")
        try:
            corpus = load_corpus(corpus_path)
        except CorpusError as exc:
            print(f"corpus error: {exc}")
            return EXIT_USAGE
        print_corpus(corpus_entries(corpus), str(corpus.get("corpus_id", corpus_path.name)))
        return EXIT_OK

    try:
        mission, entry = select_mission(args, protocol, corpus_path)
    except (MissionIRError, CorpusError) as exc:
        print(f"mission error: {exc}")
        return EXIT_USAGE

    print(f"Protocol: {protocol_path}")
    print(
        f"Mission:  {mission.mission_id} (schema {mission.schema_version},"
        f" {mission.horizon} step(s))"
    )
    if entry is not None and entry.get("purpose"):
        print(f"Purpose:  {entry['purpose']}")
    print()

    validator = MissionValidator()
    report = validator.validate(mission)
    print_validation(mission, report)
    if not report.valid:
        return EXIT_USAGE

    grounder = build_grounder(protocol)
    plan = grounder.ground_mission(mission)
    print()
    print_grounding(plan)
    if not plan.grounded:
        print()
        print(f"Mission rejected before execution ({plan.status}); zero simulation steps executed.")
        return EXIT_REJECTED
    graph = TaskGraph.from_mission(mission, plan)
    print()
    print_task_graph(graph)
    expected = expectation_text(entry, plan)
    if expected:
        print(f"Corpus expectation: {expected}")
    if args.plan_only:
        return EXIT_OK

    robot = load_yaml(args.robot or protocol.get("robot_config", DEFAULT_ROBOT))
    sessions: dict[str, ViewerMissionSession] = {}

    def session_factory(seed: int) -> ViewerMissionSession:
        session = ViewerMissionSession(
            robot_config=robot,
            protocol=protocol,
            seed=seed,
            with_viewer=not args.no_viewer,
            speed=args.speed,
            sync_every=args.sync_every,
            node_pause_s=args.node_pause,
            track_camera=not args.free_camera,
        )
        session.mission_id = mission.mission_id
        session.node_total = len(mission.steps)
        sessions["session"] = session
        return session

    evidence_root = None
    if args.write_evidence or args.evidence_root:
        evidence_root = (
            Path(args.evidence_root) if args.evidence_root else artifacts_dir() / "missions"
        )
        evidence_root = ensure_repo_output(resolve_repo_path(evidence_root))
    provenance: dict[str, Any] = {
        "tool": "scripts/view_mission.py",
        "mode": "headless" if args.no_viewer else "viewer",
        "note": "viewer runs are observation only and not benchmark evidence",
    }
    if evidence_root:
        provenance["git_commit"] = EnvironmentInfo.collect().git_commit
    executor = MissionExecutor(
        validator=validator,
        grounder=grounder,
        session_factory=session_factory,
        protocol=protocol,
        recorder_root=str(evidence_root) if evidence_root else None,
        seed=args.seed,
        provenance=provenance,
    )

    print()
    if args.no_viewer:
        print("Running headless (no viewer).")
    else:
        print("Opening MuJoCo viewer. Close the window or press Ctrl+C to stop.")
    print()

    try:
        result = executor.run(
            mission,
            phase="viewer" if not args.no_viewer else "headless",
            write_evidence=bool(evidence_root),
        )
    except ViewerClosed:
        session = sessions.get("session")
        if session is not None:
            session.shutdown(hold_seconds=0.0)
        print("\nViewer closed before the mission finished - stopping.")
        return EXIT_INTERRUPTED
    except KeyboardInterrupt:
        session = sessions.get("session")
        if session is not None:
            session.shutdown(hold_seconds=0.0)
        print("\nInterrupted - stopping.")
        return EXIT_INTERRUPTED
    except BaseException:
        session = sessions.get("session")
        if session is not None:
            session.shutdown(hold_seconds=0.0)
        raise

    print_mission_result(result)
    if evidence_root:
        print(f"Evidence (viewer-labelled): {evidence_root / result.mission_id}")

    session = sessions.get("session")
    if session is not None:
        if session.viewer is not None:
            print()
            if args.exit_after_mission:
                print("Closing the viewer.")
            else:
                print("Mission complete. Close the MuJoCo window (or press Esc) to exit.")
        session.shutdown(
            hold_seconds=0.0
            if (args.exit_after_mission or session.viewer is None)
            else args.hold_open_seconds
        )
    return EXIT_OK if result.mission_success else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
