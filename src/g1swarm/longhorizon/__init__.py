"""Phase 2.3 long-horizon language benchmark package.

The package is intentionally split into:

- :mod:`g1swarm.longhorizon.corpus` — canonical Mission IR generation,
  deterministic language realizations and the separate safety-control set;
- :mod:`g1swarm.longhorizon.benchmark` — scoring records, horizon summaries,
  transition analysis and failure attribution;
- :mod:`g1swarm.longhorizon.runner` — Stage A/B orchestration against the
  frozen selected compiler (``guarded_direct_llm_v1``) and the frozen
  Phase 2.0 runtime.
"""

from . import benchmark, corpus, runner  # noqa: F401

__all__ = ["benchmark", "corpus", "runner"]
