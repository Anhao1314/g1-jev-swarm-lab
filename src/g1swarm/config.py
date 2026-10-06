"""YAML configuration loading for G1 robot and experiment configs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .control import G1LocomotionConfig, G1LocomotionController
from .paths import resolve_repo_path
from .simulation import G1ModelConfig, G1Simulation


def load_yaml(path: str | Path) -> dict[str, Any]:
    resolved = resolve_repo_path(path)
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected a mapping in {resolved}")
    return data


def model_config(robot: dict[str, Any]) -> G1ModelConfig:
    model = robot["model"]
    simulation = robot.get("simulation", {})
    return G1ModelConfig(
        name=robot["name"],
        xml_path=model["xml_path"],
        timestep=float(simulation.get("timestep", 0.002)),
        fall_height_m=float(simulation.get("fall_height_m", 0.45)),
        fall_tilt_deg=float(simulation.get("fall_tilt_deg", 65.0)),
        standing_min_height_m=float(simulation.get("standing_min_height_m", 0.55)),
        standing_max_tilt_deg=float(simulation.get("standing_max_tilt_deg", 30.0)),
    )


def locomotion_config(robot: dict[str, Any]) -> G1LocomotionConfig | None:
    controller = robot.get("controller", {})
    if controller.get("kind") != "official_pretrained_policy":
        return None
    cmd_scale = tuple(float(value) for value in controller.get("cmd_scale", (2.0, 2.0, 0.25)))
    if len(cmd_scale) != 3:
        raise ValueError("controller.cmd_scale must contain three values")
    return G1LocomotionConfig(
        policy_path=controller["policy_path"],
        default_angles=tuple(float(value) for value in controller["default_angles"]),
        kp=tuple(float(value) for value in controller["kp"]),
        kd=tuple(float(value) for value in controller["kd"]),
        ang_vel_scale=float(controller.get("ang_vel_scale", 0.25)),
        dof_pos_scale=float(controller.get("dof_pos_scale", 1.0)),
        dof_vel_scale=float(controller.get("dof_vel_scale", 0.05)),
        action_scale=float(controller.get("action_scale", 0.25)),
        cmd_scale=(cmd_scale[0], cmd_scale[1], cmd_scale[2]),
        control_decimation=int(controller.get("control_decimation", 10)),
        phase_period_s=float(controller.get("phase_period_s", 0.8)),
        source_repository=str(controller.get("source_repository", "")),
        source_commit=str(controller.get("source_commit", "")),
    )


def build_simulation(robot: dict[str, Any], *, seed: int = 0) -> G1Simulation:
    return G1Simulation(model_config(robot), seed=seed)


def build_controller(robot: dict[str, Any]) -> G1LocomotionController | None:
    config = locomotion_config(robot)
    if config is None:
        return None
    return G1LocomotionController(config)


def model_source(robot: dict[str, Any]) -> tuple[str | None, str | None]:
    model = robot.get("model", {})
    return model.get("source_repository"), model.get("source_commit")


def controller_source(robot: dict[str, Any]) -> tuple[str | None, str | None]:
    controller = robot.get("controller", {})
    source = controller.get("source_repository") or controller.get("source_file")
    return source, controller.get("source_commit")
