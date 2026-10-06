"""Minimal MuJoCo adapter for the Unitree G1.

The adapter owns the MuJoCo model/data pair and exposes a compact surface:
``reset``, ``step`` and ``get_robot_state``. Raw simulator buffers stay private
so that mission, decision and skill layers depend on the stable ``RobotState``
protocol instead of ``mjModel``/``mjData`` internals.

Viewer rendering is strictly optional and never required by a skill or test:
the default mode is headless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..paths import resolve_repo_path
from ..state.robot_state import RobotState
from .errors import InvalidControlError, ModelLoadError, SimulationStateError


@dataclass(frozen=True)
class G1ModelConfig:
    """Configuration for one MuJoCo G1 model file."""

    name: str
    xml_path: str | Path
    timestep: float = 0.002
    fall_height_m: float = 0.45
    fall_tilt_deg: float = 65.0
    standing_min_height_m: float = 0.55
    standing_max_tilt_deg: float = 30.0
    base_body_name: str = "pelvis"

    def resolved_xml_path(self) -> Path:
        return resolve_repo_path(self.xml_path)


class G1Simulation:
    """Headless-by-default MuJoCo adapter for the Unitree G1."""

    def __init__(self, config: G1ModelConfig, *, seed: int = 0) -> None:
        import mujoco

        self._mujoco = mujoco
        self.config = config
        self._xml_path = config.resolved_xml_path()
        if not self._xml_path.is_file():
            raise ModelLoadError(f"model file not found: {self._xml_path}")
        try:
            self._model = mujoco.MjModel.from_xml_path(str(self._xml_path))
        except Exception as exc:
            raise ModelLoadError(
                f"failed to load MuJoCo model from {self._xml_path}: {exc}"
            ) from exc
        self._model.opt.timestep = float(config.timestep)
        self._data = mujoco.MjData(self._model)
        self._base_body_id = self._resolve_body_id(config.base_body_name)
        self._active_skill: str | None = None
        self._viewer = None
        self._closed = False
        self._seed = int(seed)
        self.reset(seed=seed)

    # -- introspection -------------------------------------------------
    @property
    def timestep(self) -> float:
        return float(self._model.opt.timestep)

    @property
    def num_actuators(self) -> int:
        return int(self._model.nu)

    @property
    def num_qpos(self) -> int:
        return int(self._model.nq)

    @property
    def num_qvel(self) -> int:
        return int(self._model.nv)

    @property
    def simulation_time(self) -> float:
        return float(self._data.time)

    @property
    def model_name(self) -> str:
        raw = self._model.names
        return raw[: raw.find(b"\x00")].decode() if raw else ""

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def active_skill(self) -> str | None:
        return self._active_skill

    def set_active_skill(self, name: str | None) -> None:
        self._active_skill = name

    def actuator_names(self) -> tuple[str, ...]:
        mujoco = self._mujoco
        return tuple(
            mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_ACTUATOR, index)
            or f"actuator_{index}"
            for index in range(self._model.nu)
        )

    def model_summary(self) -> dict:
        return {
            "name": self.config.name,
            "xml_path": str(self._xml_path),
            "num_qpos": self.num_qpos,
            "num_qvel": self.num_qvel,
            "num_actuators": self.num_actuators,
            "timestep": self.timestep,
            "actuator_names": list(self.actuator_names()),
        }

    # -- lifecycle -----------------------------------------------------
    def reset(self, *, seed: int | None = None, keyframe: str | None = None) -> RobotState:
        if self._closed:
            raise SimulationStateError("simulation is closed")
        if seed is not None:
            self._seed = int(seed)
        mujoco = self._mujoco
        if keyframe is None:
            mujoco.mj_resetData(self._model, self._data)
        else:
            key_id = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_KEY, keyframe)
            if key_id < 0:
                raise SimulationStateError(f"unknown keyframe: {keyframe}")
            mujoco.mj_resetDataKeyframe(self._model, self._data, key_id)
        self._active_skill = None
        mujoco.mj_forward(self._model, self._data)
        return self.get_robot_state()

    def step(self, control: np.ndarray | None = None) -> RobotState:
        if self._closed:
            raise SimulationStateError("simulation is closed")
        if control is not None:
            control = np.asarray(control, dtype=np.float64)
            if control.shape != (self.num_actuators,):
                raise InvalidControlError(
                    f"control must have shape ({self.num_actuators},), got {control.shape}"
                )
            if not np.all(np.isfinite(control)):
                raise InvalidControlError("control contains non-finite values")
            self._data.ctrl[:] = control
        self._mujoco.mj_step(self._model, self._data)
        if not np.all(np.isfinite(self._data.qpos)) or not np.all(np.isfinite(self._data.qvel)):
            raise SimulationStateError(f"non-finite simulation state at t={self.simulation_time:.4f}")
        return self.get_robot_state()

    def get_robot_state(self) -> RobotState:
        if self._closed:
            raise SimulationStateError("simulation is closed")
        data = self._data
        position = tuple(float(value) for value in data.qpos[0:3])
        orientation = tuple(float(value) for value in data.qpos[3:7])
        linear_velocity = tuple(float(value) for value in data.qvel[0:3])
        angular_velocity = tuple(float(value) for value in data.qvel[3:6])
        height = position[2]
        tilt_deg = self._tilt_deg()
        fallen = height < self.config.fall_height_m or tilt_deg > self.config.fall_tilt_deg
        standing = (
            not fallen
            and height >= self.config.standing_min_height_m
            and tilt_deg <= self.config.standing_max_tilt_deg
        )
        return RobotState(
            simulation_time=self.simulation_time,
            base_position=position,
            base_orientation=orientation,
            linear_velocity=linear_velocity,
            angular_velocity=angular_velocity,
            standing=standing,
            fallen=fallen,
            active_skill=self._active_skill,
        )

    # -- low-level surface (control layer only) ------------------------
    def contact_count(self) -> int:
        """Number of active contacts in the last computed state."""

        # MuJoCo <= 3.1 exposed ``ncontact``; 3.15 uses ``ncon``.
        return int(getattr(self._data, "ncon", getattr(self._data, "ncontact", 0)))

    def mujoco_warning(self) -> tuple[int, str]:
        """Latest MuJoCo warning as ``(count, text)``; ``(0, "")`` when none."""

        try:
            result = self._mujoco.mj_getWarning(self._model, self._data)
        except Exception:  # pragma: no cover - API differences between versions
            return 0, ""
        if isinstance(result, tuple):
            count = int(result[0]) if result else 0
            text = result[1] if len(result) > 1 else ""
        else:  # pragma: no cover - older bindings return text only
            count, text = 1, result
        if isinstance(text, bytes):
            text = text.decode(errors="replace")
        return count, str(text)

    # -- low-level surface (control layer only) ------------------------
    def joint_positions(self) -> np.ndarray:
        return np.array(self._data.qpos[7:], dtype=np.float64, copy=True)

    def joint_velocities(self) -> np.ndarray:
        return np.array(self._data.qvel[6:], dtype=np.float64, copy=True)

    def base_quaternion(self) -> np.ndarray:
        return np.array(self._data.qpos[3:7], dtype=np.float64, copy=True)

    def base_angular_velocity(self) -> np.ndarray:
        return np.array(self._data.qvel[3:6], dtype=np.float64, copy=True)

    # -- optional viewer ----------------------------------------------
    def open_viewer(self) -> None:
        """Open the interactive MuJoCo viewer (desktop sessions only)."""

        if self._viewer is not None:
            return
        import mujoco.viewer

        self._viewer = mujoco.viewer.launch_passive(self._model, self._data)

    def sync_viewer(self) -> None:
        if self._viewer is not None:
            self._viewer.sync()

    def close(self) -> None:
        if self._viewer is not None:
            self._viewer.close()
            self._viewer = None
        self._closed = True

    # -- helpers -------------------------------------------------------
    def _resolve_body_id(self, name: str) -> int:
        body_id = self._mujoco.mj_name2id(self._model, self._mujoco.mjtObj.mjOBJ_BODY, name)
        if body_id < 0:
            raise ModelLoadError(f"base body {name!r} not found in {self._xml_path.name}")
        return int(body_id)

    def _tilt_deg(self) -> float:
        quat = self._data.qpos[3:7]
        w, x, y, z = (float(value) for value in quat)
        # Base body z axis projected on the world up vector. Normalize the
        # quaternion defensively so integrator drift cannot produce acos(>1).
        norm = math.sqrt(w * w + x * x + y * y + z * z)
        if norm == 0.0:
            return 0.0
        w, x, y, z = w / norm, x / norm, y / norm, z / norm
        up_z = 1.0 - 2.0 * (x * x + y * y)
        return math.degrees(math.acos(max(-1.0, min(1.0, up_z))))
