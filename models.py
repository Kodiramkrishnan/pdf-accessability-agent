from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"


class AccessibilityIssue(BaseModel):
    """Single check result aligned with common PDF/UA checker categories."""

    code: str
    message: str
    severity: Severity = Severity.WARN
    page: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RemediationAction(BaseModel):
    """Structured step the agent (or human) can apply."""

    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class RemediationPlan(BaseModel):
    """LLM or rule engine output describing fixes to attempt."""

    summary: str = ""
    actions: list[RemediationAction] = Field(default_factory=list)


class PacPredictionIssue(BaseModel):
    """LLM-estimated PAC blocker candidate."""

    code: str
    message: str
    confidence: float = 0.0


class PacPrediction(BaseModel):
    """LLM prediction for PAC-zero likelihood."""

    predicted_zero_errors: bool = False
    confidence: float = 0.0
    blockers: list[PacPredictionIssue] = Field(default_factory=list)
    notes: str = ""
