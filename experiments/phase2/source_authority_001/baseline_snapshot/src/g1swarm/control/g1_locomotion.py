"""Official Unitree G1 locomotion controller (native MuJoCo port).

Ported from ``unitree_rl_gym`` at commit
``276801e46c5d433564f24658bac64f254b7d2d4b``:

* ``deploy/deploy_mujoco/deploy_mujoco.py`` - control and observation pipeline
* ``deploy/pre_train/g1/motion.pt`` - official pretrained TorchScript policy

Scope: 12 leg DOF, 47 observations, 50 Hz policy (``control_decimation`` = 10
at 500 Hz physics). The port keeps the official ordering and scales; it only
drops the interactive viewer and the wall-clock sleep so that headless,
reproducible runs are possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..paths import resolve_repo_path


class ControllerUnavailableError(RuntimeError):
    """The locomotion policy cannot be used in this environment."""


@dataclass(frozen=True)
class G1LocomotionConfig:
    policy_path: str | Path
    default_angles: tuple[float, ...]
    kp: tuple[float, ...]
    kd: tuple[float, ...]
    ang_vel_scale: float = 0.25
    dof_pos_scale: float = 1.0
    dof_vel_scale: float = 0.05
    action_scale: float = 0.25
    cmd_scale: tuple[float, float, float] = (2.0, 2.0, 0.25)
    control_decimation: int = 10
    phase_period_s: float = 0.8
    source_repository: str = ""
    source_commit: str = ""

    def resolved_policy_path(self) -> Path:
        return resolve_repo_path(self.policy_path)

    def validate(self) -> None:
        size = len(self.default_angles)
        if size == 0:
            raise ValueError("default_angles must not be empty")
        if len(self.kp) != size or len(self.kd) != size:
            raise ValueError("kp/kd must match default_angles length")
        if len(self.cmd_scale) != 3:
            raise ValueError("cmd_scale must contain (vx, vy, yaw)")
        if self.control_decimation < 1:
            raise ValueError("control_decimation must be >= 1")


class G1LocomotionController:
    """Drives the official 12-DOF G1 policy with the official PD gains."""

    def __init__(self, config: G1LocomotionConfig, *, device: str = "cpu") -> None:
        config.validate()
        self.config = config
        self.device = device
        self._policy_path = config.resolved_policy_path()
        if not self._policy_path.is_file():
            raise ControllerUnavailableError(f"policy file not found: {self._policy_path}")
        try:
            import torch
        except ImportError as exc:
            raise ControllerUnavailableError(
                "torch is required for the learned locomotion controller; install the "
                "cu130 wheel with: pip install torch --index-url "
                "https://download.pytorch.org/whl/cu130"
            ) from exc
        self._torch = torch
        self._policy = torch.jit.load(str(self._policy_path), map_location=device)
        self._policy.eval()
        self._default_angles = np.asarray(config.default_angles, dtype=np.float64)
        self._kp = np.asarray(config.kp, dtype=np.float64)
        self._kd = np.asarray(config.kd, dtype=np.float64)
        self._cmd_scale = np.asarray(config.cmd_scale, dtype=np.float64)
        self._num_actions = len(config.default_angles)
        self._action = np.zeros(self._num_actions, dtype=np.float64)
        self._target = self._default_angles.copy()
        self._counter = 0
        self.reset()

    # -- availability ---------------------------------------------------
    @staticmethod
    def available(config: G1LocomotionConfig) -> bool:
        if not config.resolved_policy_path().is_file():
            return False
        try:
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    # -- lifecycle ------------------------------------------------------
    def reset(self) -> None:
        # The official policy is recurrent (LSTM); Unitree ships an explicit
        # ``reset_memory`` TorchScript method used at task/episode boundaries.
        reset_memory = getattr(self._policy, "reset_memory", None)
        if callable(reset_memory):
            reset_memory()
        self._action = np.zeros(self._num_actions, dtype=np.float64)
        self._target = self._default_angles.copy()
        self._counter = 0

    @property
    def num_actions(self) -> int:
        return self._num_actions

    @property
    def default_angles(self) -> tuple[float, ...]:
        return tuple(float(value) for value in self._default_angles)

    def target_angles(self) -> np.ndarray:
        return self._target.copy()

    # -- control --------------------------------------------------------
    def compute_torques(
        self,
        *,
        joint_positions: np.ndarray,
        joint_velocities: np.ndarray,
        quaternion: np.ndarray,
        angular_velocity: np.ndarray,
        command: np.ndarray,
        dt: float,
    ) -> np.ndarray:
        """Return joint torques for the current physics step.

        Ordering matches the official deployment loop: PD torques are computed
        from the current target, the physics step happens outside this method,
        and the policy refresh (every ``control_decimation`` calls) updates the
        target for the following step.
        """

        command = np.asarray(command, dtype=np.float64)
        if command.shape != (3,):
            raise ValueError(f"command must have shape (3,), got {command.shape}")
        joint_positions = np.asarray(joint_positions, dtype=np.float64)
        joint_velocities = np.asarray(joint_velocities, dtype=np.float64)
        if joint_positions.shape != (self._num_actions,) or joint_velocities.shape != (
            self._num_actions,
        ):
            raise ValueError("joint state does not match the 12-DOF policy layout")

        torques = (self._target - joint_positions) * self._kp - joint_velocities * self._kd

        self._counter += 1
        if self._counter % self.config.control_decimation == 0:
            observation = self._build_observation(
                joint_positions, joint_velocities, quaternion, angular_velocity, command, dt
            )
            with self._torch.no_grad():
                tensor = self._torch.from_numpy(observation).unsqueeze(0).to(self.device)
                action = self._policy(tensor).detach().cpu().numpy().reshape(-1)
            if action.shape != (self._num_actions,):
                raise ControllerUnavailableError(
                    f"policy returned {action.shape}, expected ({self._num_actions},)"
                )
            self._action = action
            self._target = action * self.config.action_scale + self._default_angles
        return torques

    # -- internals ------------------------------------------------------
    def _build_observation(
        self,
        joint_positions: np.ndarray,
        joint_velocities: np.ndarray,
        quaternion: np.ndarray,
        angular_velocity: np.ndarray,
        command: np.ndarray,
        dt: float,
    ) -> np.ndarray:
        observation = np.zeros(47, dtype=np.float32)
        observation[0:3] = np.asarray(angular_velocity, dtype=np.float64) * self.config.ang_vel_scale
        observation[3:6] = self.get_gravity_orientation(np.asarray(quaternion, dtype=np.float64))
        observation[6:9] = command * self._cmd_scale
        observation[9:21] = (joint_positions - self._default_angles) * self.config.dof_pos_scale
        observation[21:33] = joint_velocities * self.config.dof_vel_scale
        observation[33:45] = self._action
        phase_time = self._counter * dt
        phase = (phase_time % self.config.phase_period_s) / self.config.phase_period_s
        observation[45] = np.sin(2.0 * np.pi * phase)
        observation[46] = np.cos(2.0 * np.pi * phase)
        return observation

    @staticmethod
    def get_gravity_orientation(quaternion: np.ndarray) -> np.ndarray:
        """Official gravity projection used by the Unitree deployment script."""

        qw, qx, qy, qz = (float(value) for value in quaternion)
        return np.array(
            [
                2.0 * (-qz * qx + qw * qy),
                -2.0 * (qz * qy + qw * qx),
                1.0 - 2.0 * (qw * qw + qz * qz),
            ],
            dtype=np.float64,
        )
