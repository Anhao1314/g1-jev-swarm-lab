"""Typed result returned by the controlled-language compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..mission.ir import Mission
from .errors import CompilerStatus, LanguageErrorCode


@dataclass(frozen=True)
class CompilerResult:
    status: CompilerStatus
    mission: Mission | None = None
    normalized_text: str = ""
    error_code: LanguageErrorCode | None = None
    error_message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status is CompilerStatus.SUCCESS and self.mission is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "mission": self.mission.to_dict() if self.mission is not None else None,
            "normalized_text": self.normalized_text,
            "error_code": self.error_code.value if self.error_code is not None else None,
            "error_message": self.error_message,
            "diagnostics": dict(self.diagnostics),
        }
