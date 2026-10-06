"""Phase 1.2b: distance-boundary refinement and skill segmentation study."""

from .mission import (
    DEFAULT_SEGMENT_M,
    MissionFrame,
    PathLengthProxy,
    build_segment_schedule,
    build_state_aware_schedule,
    drift_per_meter,
    heading_error_per_meter,
)
from .runner import (
    EXPERIMENT_ID,
    MEMORY_CONTINUOUS,
    TREATMENTS,
    SegmentationRunner,
    build_distance_boundary,
    build_execution_strategy_map,
    build_risk_map_v1_2b,
    build_segmentation_comparison,
    validate_comparison,
    validate_distance_boundary,
    validate_execution_strategy,
    validate_risk_map_v1_2b,
)

__all__ = [
    "DEFAULT_SEGMENT_M",
    "EXPERIMENT_ID",
    "MEMORY_CONTINUOUS",
    "TREATMENTS",
    "MissionFrame",
    "PathLengthProxy",
    "SegmentationRunner",
    "build_distance_boundary",
    "build_execution_strategy_map",
    "build_risk_map_v1_2b",
    "build_segment_schedule",
    "build_segmentation_comparison",
    "build_state_aware_schedule",
    "drift_per_meter",
    "heading_error_per_meter",
    "validate_comparison",
    "validate_distance_boundary",
    "validate_execution_strategy",
    "validate_risk_map_v1_2b",
]
