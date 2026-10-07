"""Exploratory post-hoc bounded-language authorization control.

This control was added AFTER observing unusable live LLM gate responses. It
does not belong to their original acquisition-bound treatment or freeze, and
its observed performance cannot be presented as fresh or blind evidence.

The guarantee is intentionally narrow: the ENTIRE source, after the existing
frozen normalization, must belong to the existing controlled-language grammar;
the grammar-derived Mission must be statically legal; and its full historical
canonical semantics (including step IDs and dependencies, excluding mission
identity) must exactly match B's unchanged candidate. No substring parsing,
source clipping, pattern detection, repairs, alternate compiler prompt or
provider call is used. ``apply_gate`` adds the original Structural Guard.

Assumptions and limits:
- User intent must be expressible in the bounded grammar and must agree with
  its frozen sequential interpretation of connectors and punctuation.
- Frozen normalization applies NFKC, maps documented punctuation to commas,
  deletes whitespace and connector-adjacent commas, and removes one trailing
  comma. This control additionally abstains if any parsed numeric token was
  assembled from noncontiguous characters in NFKC source. Remaining inherited
  normalization conventions are not proof that all original natural-language
  distinctions are harmless.
- A full token witness proves parser consumption of normalized source, not
  uniqueness under unrestricted Chinese. Edits, repetitions, references,
  conditional/temporal clauses and unrecognized suffixes are rejected when
  outside the grammar rather than guessed.
- Exact IDs/dependencies can reject a semantically equivalent candidate with
  noncanonical identifiers or a different dependency representation.
- Coverage is deliberately lost outside this bounded language. This control
  provides no new inference about fresh held-out natural-language performance.

No Runtime, Grounder, skills, historical thresholds or frozen files are changed.
"""

from __future__ import annotations

import hashlib
import time
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from lark import Token

from .language.compiler import LanguageCompiler
from .language.errors import CompilerStatus
from .language.normalization import _PUNCTUATION_MAP, normalize_text
from .mission.ir import Mission
from .mission.validator import MissionValidator
from .simplex.canonical import comparison_payload
from .source_authority import AuthorizationResult, AuthorizationStatus

TREATMENT_BOUNDED_EXPLORATORY = "guarded_direct_llm_bounded_source_authority_exploratory_v1"
NORMALIZATION_ASSUMPTION = (
    "Frozen NFKC, punctuation-to-comma mapping, whitespace removal, "
    "connector-adjacent comma removal and one trailing-comma removal preserve "
    "the intended bounded controlled-language interpretation."
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalization_alignment(source: str) -> tuple[str, list[tuple[str, int]]]:
    """Retain NFKC-source positions through frozen normalization operations.

    This supplies a loss witness only; its text is checked against the frozen
    normalizer, and it is never an alternate input to the compiler. Numeric
    tokens must each map to one contiguous NFKC span. There are no source-case
    pattern lists or semantic rewrite rules.
    """
    nfkc_source = unicodedata.normalize("NFKC", source)
    aligned = [(_PUNCTUATION_MAP.get(char, char), index)
               for index, char in enumerate(nfkc_source) if not char.isspace()]

    def delete_matches(pattern: str, comma_offset: int) -> None:
        cursor = 0
        while True:
            location = "".join(char for char, _ in aligned).find(pattern, cursor)
            if location < 0:
                return
            del aligned[location + comma_offset]
            # Match Python str.replace's nonoverlapping treatment of the
            # pre-replacement text; do not repeatedly delete new same matches.
            cursor = location + len(pattern) - 1

    # These are the existing normalizer's documented connector operations,
    # in its existing order. Alignment equality is checked by the caller.
    for connector in ("然后", "再", "接着", "之后", "最后"):
        delete_matches(f",{connector}", 0)
        delete_matches(f"{connector},", len(connector))
    if aligned and aligned[-1][0] == ",":
        aligned.pop()
    return nfkc_source, aligned


class BoundedSourceAuthorizationVerifier:
    """Full frozen controlled-language parse, then complete exact comparison."""

    treatment = TREATMENT_BOUNDED_EXPLORATORY
    source_aware = True

    def __init__(self) -> None:
        self.compiler = LanguageCompiler()
        language_dir = Path(__file__).with_name("language")
        self.frozen_file_hashes = {
            name: hashlib.sha256((language_dir / name).read_bytes()).hexdigest()
            for name in ("compiler.py", "grammar.lark", "normalization.py", "transformer.py", "units.py")
        }

    def authorize(self, source: str, candidate_ir: Mission | Mapping[str, Any]) -> AuthorizationResult:
        started = time.perf_counter()
        evidence: dict[str, Any] = {
            "treatment": self.treatment,
            "exploratory_post_hoc": True,
            "provider_calls": 0,
            "attempts": 0,
            "usage": None,
            "raw_response": None,
            "automatic_repair": False,
            "source_aware": True,
            "normalization_assumption": NORMALIZATION_ASSUMPTION,
            "frozen_language_raw_byte_hashes": dict(self.frozen_file_hashes),
        }

        def finish(status: AuthorizationStatus, reason: str) -> AuthorizationResult:
            evidence["latency_s"] = time.perf_counter() - started
            return AuthorizationResult(status, reason, evidence)

        if not isinstance(source, str):
            return finish(AuthorizationStatus.UNKNOWN, "INVALID_SOURCE_INPUT")
        normalized = normalize_text(source)
        evidence["source_witness"] = {
            "text": source,
            "sha256": _digest(source),
            "characters": len(source),
        }
        evidence["normalized_source_witness"] = {
            "text": normalized,
            "sha256": _digest(normalized),
            "characters": len(normalized),
            "changed": normalized != source,
            "procedure": "g1swarm.language.normalization.normalize_text (unchanged frozen implementation)",
        }
        try:
            compiled = self.compiler.compile(source)
        except Exception as exc:
            evidence["compiler_failure_type"] = type(exc).__name__
            return finish(AuthorizationStatus.UNKNOWN, "BOUNDED_COMPILER_FAILURE")
        evidence["bounded_compiler"] = {
            "status": compiled.status.value,
            "error_code": compiled.error_code.value if compiled.error_code else None,
            "error_message": compiled.error_message,
            "diagnostics": dict(compiled.diagnostics),
        }
        if compiled.status is CompilerStatus.AMBIGUOUS:
            return finish(AuthorizationStatus.AMBIGUOUS, "BOUNDED_SOURCE_AMBIGUOUS")
        if not compiled.success:
            return finish(AuthorizationStatus.UNKNOWN, "OUTSIDE_BOUNDED_LANGUAGE")
        if compiled.normalized_text != normalized:
            return finish(AuthorizationStatus.UNKNOWN, "NORMALIZATION_DISAGREEMENT")

        # The frozen compiler parses a complete mission using LALR/EOF. Repeat
        # that same full parse only to expose terminal-consumption evidence;
        # require no gaps, ignored fragments, clipping or changed token text.
        try:
            tree = self.compiler._parser.parse(normalized)
            tokens = list(tree.scan_values(lambda item: isinstance(item, Token)))
            witness = [{"type": token.type, "text": str(token),
                        "start": token.start_pos, "end": token.end_pos} for token in tokens]
            evidence["parse_witness"] = {
                "start": tree.meta.start_pos,
                "end": tree.meta.end_pos,
                "tokens": witness,
                "mode": "full mission parse, LALR/contextual lexer, EOF required",
            }
            cursor = 0
            for item in witness:
                if item["start"] != cursor or item["end"] <= cursor:
                    return finish(AuthorizationStatus.UNKNOWN, "PARSER_COVERAGE_FAILURE")
                if normalized[item["start"]:item["end"]] != item["text"]:
                    return finish(AuthorizationStatus.UNKNOWN, "PARSER_COVERAGE_FAILURE")
                cursor = item["end"]
            if (tree.meta.start_pos != 0 or tree.meta.end_pos != len(normalized)
                    or cursor != len(normalized)
                    or "".join(item["text"] for item in witness) != normalized):
                return finish(AuthorizationStatus.UNKNOWN, "PARSER_COVERAGE_FAILURE")
            evidence["parse_witness"]["full_consumption"] = True
            nfkc_source, aligned = _normalization_alignment(source)
            if "".join(char for char, _ in aligned) != normalized:
                return finish(AuthorizationStatus.UNKNOWN, "NORMALIZATION_ALIGNMENT_FAILURE")
            quantity_witness = []
            for item in witness:
                if item["type"] != "NUMBER":
                    continue
                number_positions = aligned[item["start"]:item["end"]]
                nfkc_start = number_positions[0][1]
                nfkc_end = number_positions[-1][1] + 1
                span = nfkc_source[nfkc_start:nfkc_end]
                contiguous = span == item["text"]
                quantity_witness.append({
                    "normalized_start": item["start"], "normalized_end": item["end"],
                    "numeric_text": item["text"], "nfkc_start": nfkc_start,
                    "nfkc_end": nfkc_end, "nfkc_source_span": span,
                    "contiguous": contiguous,
                })
            evidence["quantity_normalization_witness"] = quantity_witness
            if any(not item["contiguous"] for item in quantity_witness):
                return finish(AuthorizationStatus.UNKNOWN, "NORMALIZATION_QUANTITY_LOSS_RISK")
        except Exception as exc:
            evidence["parser_failure_type"] = type(exc).__name__
            return finish(AuthorizationStatus.UNKNOWN, "PARSER_COVERAGE_FAILURE")

        try:
            source_plan = compiled.mission
            source_validation = MissionValidator().validate(source_plan)
            evidence["authorized_plan_validation"] = source_validation.to_dict()
            if not source_validation.valid:
                return finish(AuthorizationStatus.UNKNOWN, "INVALID_AUTHORIZED_PLAN")
            document = candidate_ir.to_dict() if isinstance(candidate_ir, Mission) else candidate_ir
            candidate = Mission.from_dict(document)
            if any(step.execution_mode_override is not None for step in candidate.steps):
                return finish(AuthorizationStatus.UNKNOWN, "FORBIDDEN_CANDIDATE_FIELD")
            validation = MissionValidator().validate(candidate)
            evidence["candidate_validation"] = validation.to_dict()
            if not validation.valid:
                return finish(AuthorizationStatus.UNKNOWN, "INVALID_CANDIDATE_IR")
            source_semantics = comparison_payload(source_plan, allow_text_numbers=False)
            candidate_semantics = comparison_payload(candidate, allow_text_numbers=False)
            evidence["authorized_plan"] = source_semantics
            evidence["plan_matches_candidate"] = source_semantics == candidate_semantics
            if source_semantics != candidate_semantics:
                return finish(AuthorizationStatus.UNKNOWN, "AUTHORIZED_PLAN_DISAGREEMENT")
        except Exception as exc:
            evidence["candidate_failure_type"] = type(exc).__name__
            return finish(AuthorizationStatus.UNKNOWN, "INVALID_CANDIDATE_IR")
        return finish(AuthorizationStatus.AUTHORIZED_UNIQUE, "UNIQUE_BOUNDED_SOURCE_AUTHORITY")


__all__ = [
    "BoundedSourceAuthorizationVerifier",
    "NORMALIZATION_ASSUMPTION",
    "TREATMENT_BOUNDED_EXPLORATORY",
]
