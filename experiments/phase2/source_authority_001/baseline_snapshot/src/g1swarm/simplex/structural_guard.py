"""Trusted structural monitor in front of the Phase 2.2b simplex router.

The guard is the only layer that runs *before* any model call.  It is fully
deterministic, side-effect free and deliberately high precision: it rejects
only surface-structural defects that the frozen normalizer, a helpful
language model, or a grader could silently "repair" into a valid command.
Every semantic decision -- unknown skills, missing parameters, vague
quantities, invalid units, unsupported capabilities -- is left to the frozen
Phase 2.1 grammar and the canonicalizer.

Frozen rule set (regression and hardening-corpus derived):

- empty, punctuation-only, connector-only or sequence-marker-only input;
- a connector token immediately repeated (``前进4米然后然后停止``);
- two different connectors immediately adjacent, except the legitimate
  compound ``然后再`` (``前进4米然后接着停止``);
- a connector immediately followed by punctuation, i.e. a dangling
  connector (``站立2秒，然后，停止``, ``前进4米。然后。停止``);
- two or more comma-class separators with no clause between
  (``前进4米，，，，，``);
- a repeated sequence marker (``先先前进4米``);
- a leading connector other than the adverbial ``再`` (``然后前进4米``);
- a dangling trailing connector (``前进4米然后``).

The two Phase 2.2 controlled-regression holes (``cl-h-016`` and ``cl-h-017``)
are rejected here without any model call.  The invariant that motivates the
guard is pinned in ``tests/test_simplex_structural_guard.py``: whenever the
hardening corpora label a sample ``MALFORMED`` but the frozen grammar would
accept it (silent fast-path repair), the guard must reject it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

GUARD_VERSION = "2.2b.2"

#: Connector vocabulary of the frozen Phase 2.1 grammar. ``先`` is the sequence
#: start marker and is intentionally not a connector here.
CONNECTORS = ("然后", "接着", "之后", "最后", "再")

#: Comma-class separators.  A run of these means an empty clause.  Period-like
#: punctuation is excluded because noisy ellipses such as ``站立2秒。。。`` are
#: valid source language.
SEPARATORS = "，,;；、：:→"

CONNECTOR_TRAILING_PUNCTUATION = SEPARATORS + "。.…!?"
_TRAILING_TRIM = CONNECTOR_TRAILING_PUNCTUATION + "！？"

#: The only legitimate adjacent connector pair in the corpora: ``然后再``.
ALLOWED_ADJACENT_PAIR = ("然后", "再")
_CONNECTOR_PATTERN = "|".join(CONNECTORS)
_SEPARATOR_CLASS = re.escape(SEPARATORS)
_TRIM_CLASS = re.escape(_TRAILING_TRIM)
_STRIP_CLASS = re.escape(SEPARATORS + "。.…!?！？")

_REPEATED_SEPARATOR_RE = re.compile(f"[{_SEPARATOR_CLASS}]\\s*[{_SEPARATOR_CLASS}]")
_CONNECTOR_RE = re.compile(_CONNECTOR_PATTERN)
_CONNECTOR_SEPARATOR_RE = re.compile(
    f"({_CONNECTOR_PATTERN})[{_SEPARATOR_CLASS}{re.escape('。.…!?！？')}\\s]*"
    f"[{_SEPARATOR_CLASS}{re.escape('。.')}]"
)
_TRAILING_TRIM_RE = re.compile(f"[{_TRIM_CLASS}\\s]+$")
_CONTENT_TRIM_RE = re.compile(f"[{_STRIP_CLASS}\\s]+")
_LEADING_CONNECTOR_RE = re.compile(f"^[{_STRIP_CLASS}\\s]*(然后|接着|之后|最后)")


class GuardStatus(str, Enum):
    """Verdict vocabulary consumed by :class:`~g1swarm.simplex.router.SimplexRouter`."""

    PASS = "PASS"
    MALFORMED = "MALFORMED"


class GuardReason(str, Enum):
    """Stable, evidence-friendly rejection reasons."""

    INVALID_INPUT = "INVALID_INPUT"
    EMPTY_INPUT = "EMPTY_INPUT"
    REPEATED_CONNECTOR = "REPEATED_CONNECTOR"
    DUPLICATE_CONNECTOR = "DUPLICATE_CONNECTOR"
    EMPTY_CLAUSE = "EMPTY_CLAUSE"
    REPEATED_SEPARATOR = "REPEATED_SEPARATOR"
    LEADING_CONNECTOR = "LEADING_CONNECTOR"
    TRAILING_CONNECTOR = "TRAILING_CONNECTOR"
    CONNECTOR_ONLY = "CONNECTOR_ONLY"
    PUNCTUATION_ONLY = "PUNCTUATION_ONLY"


@dataclass(frozen=True)
class GuardResult:
    """Typed verdict: ``status`` plus a stable ``reason_code`` when rejecting."""

    status: GuardStatus
    reason_code: GuardReason | None = None
    message: str = ""

    @property
    def passed(self) -> bool:
        return self.status is GuardStatus.PASS

    @property
    def malformed(self) -> bool:
        return self.status is GuardStatus.MALFORMED

    def to_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code.value if self.reason_code is not None else None,
            "message": self.message,
        }


def _reject(reason: GuardReason, message: str) -> GuardResult:
    return GuardResult(status=GuardStatus.MALFORMED, reason_code=reason, message=message)


def _adjacent_pairs(compressed: str) -> list[tuple[str, str]]:
    """Connector pairs that touch after separators/whitespace are removed."""

    matches = list(_CONNECTOR_RE.finditer(compressed))
    return [
        (first.group(), second.group())
        for first, second in zip(matches, matches[1:])
        if first.end() == second.start()
    ]


class StructuralGuard:
    """Deterministic pre-model monitor; see module docstring for the rule set."""

    name = "structural_guard"
    version = GUARD_VERSION

    def check(self, text: str) -> GuardResult:
        if not isinstance(text, str):
            return _reject(GuardReason.INVALID_INPUT, "language input must be a string")

        normalized = unicodedata.normalize("NFKC", text)
        if not normalized.strip():
            return _reject(GuardReason.EMPTY_INPUT, "language input is empty")

        compressed = _CONTENT_TRIM_RE.sub("", normalized)
        pairs = _adjacent_pairs(compressed)

        if any(first == second for first, second in pairs):
            return _reject(
                GuardReason.REPEATED_CONNECTOR,
                "a connector is immediately repeated",
            )

        if _CONNECTOR_SEPARATOR_RE.search(normalized):
            return _reject(
                GuardReason.EMPTY_CLAUSE,
                "a connector is immediately followed by punctuation",
            )

        if any(pair != ALLOWED_ADJACENT_PAIR for pair in pairs):
            return _reject(
                GuardReason.DUPLICATE_CONNECTOR,
                "two connectors are adjacent without a command between them",
            )

        if _REPEATED_SEPARATOR_RE.search(normalized):
            return _reject(
                GuardReason.REPEATED_SEPARATOR,
                "two separators occur with no clause between them",
            )

        if re.search("先[\\s" + _SEPARATOR_CLASS + "]*先", normalized):
            return _reject(
                GuardReason.DUPLICATE_CONNECTOR,
                "the sequence marker is repeated",
            )

        has_connector = _CONNECTOR_RE.search(compressed) is not None
        residual = _CONNECTOR_RE.sub("", compressed).replace("先", "")
        if not residual:
            if "先" in compressed:
                return _reject(
                    GuardReason.CONNECTOR_ONLY,
                    "input contains a sequence marker but no command",
                )
            if has_connector:
                return _reject(
                    GuardReason.CONNECTOR_ONLY,
                    "input contains connectors but no command",
                )
            return _reject(
                GuardReason.PUNCTUATION_ONLY,
                "input contains no command content",
            )

        if _LEADING_CONNECTOR_RE.search(normalized):
            return _reject(
                GuardReason.LEADING_CONNECTOR,
                "input starts with a dangling connector",
            )

        if _TRAILING_TRIM_RE.sub("", normalized).endswith(CONNECTORS):
            return _reject(
                GuardReason.TRAILING_CONNECTOR,
                "a connector trails with no command after it",
            )

        return GuardResult(status=GuardStatus.PASS)


_DEFAULT_GUARD = StructuralGuard()


def check_structure(text: str) -> GuardResult:
    """Module-level convenience wrapper around the stateless default guard."""

    return _DEFAULT_GUARD.check(text)


__all__ = [
    "ALLOWED_ADJACENT_PAIR",
    "CONNECTORS",
    "CONNECTOR_TRAILING_PUNCTUATION",
    "GUARD_VERSION",
    "SEPARATORS",
    "GuardReason",
    "GuardResult",
    "GuardStatus",
    "StructuralGuard",
    "check_structure",
]
