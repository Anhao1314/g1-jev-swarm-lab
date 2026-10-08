"""Simulation adapter error types."""


class G1SimulationError(RuntimeError):
    """Base class for simulation adapter failures."""


class ModelLoadError(G1SimulationError):
    """The MuJoCo model could not be loaded."""


class InvalidControlError(G1SimulationError):
    """Control input is malformed, non-finite or has the wrong shape."""


class SimulationStateError(G1SimulationError):
    """The simulator produced a non-finite or otherwise invalid state."""
