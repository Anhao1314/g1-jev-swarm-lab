"""Phase 1.2 failure-boundary search, task envelopes and risk mapping."""

from .capability import (
    SCHEMA_VERSION as CAPABILITY_SCHEMA_VERSION,
    build_capability_boundary_map,
    build_risk_map,
    validate_capability_boundary_map,
    validate_risk_map,
)
from .envelope import (
    NOMINAL_WALK_ENVELOPE,
    STRICT_WALK_ENVELOPE,
    EnvelopeEvaluation,
    EnvelopeLimits,
    WalkEnvelope,
    evaluate_walk_task,
    failure_type_from_violations,
    physical_success,
)
from .risk import (
    RISK_RULES_VERSION,
    RiskEvidence,
    RiskLevel,
    risk_label,
    risk_label_for_observation,
)
from .search import BoundarySearch, Observation, SearchResult, classify_zone

__all__ = [
    "CAPABILITY_SCHEMA_VERSION",
    "NOMINAL_WALK_ENVELOPE",
    "RISK_RULES_VERSION",
    "STRICT_WALK_ENVELOPE",
    "BoundarySearch",
    "EnvelopeEvaluation",
    "EnvelopeLimits",
    "Observation",
    "RiskEvidence",
    "RiskLevel",
    "SearchResult",
    "WalkEnvelope",
    "build_capability_boundary_map",
    "build_risk_map",
    "classify_zone",
    "evaluate_walk_task",
    "failure_type_from_violations",
    "physical_success",
    "risk_label",
    "risk_label_for_observation",
    "validate_capability_boundary_map",
    "validate_risk_map",
]
