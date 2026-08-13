"""
backend/agent/schemas.py
-------------------------
Structured DfM recommendation schema (Stage 5, roadmap §4.5).

`evidence_source` and `analysis_warnings` are the schema's honesty
enforcement: a finding derived from proxy heuristics is structurally
distinguishable from a Boolean-confirmed one, and engine warnings are
surfaced as a first-class field rather than dropped when the agent
summarizes tool output into a finding.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"  # part cannot be molded as designed
    HIGH = "high"  # needs expensive tooling (side action, lifter)
    MEDIUM = "medium"  # quality/cosmetic risk
    LOW = "low"  # minor optimization


class EvidenceSource(str, Enum):
    BOOLEAN_CONFIRMED = "boolean_confirmed"
    PROXY_HEURISTIC = "proxy_heuristic"
    USER_SUPPLIED = "user_supplied"


class DfMFinding(BaseModel):
    finding_id: str
    category: Literal[
        "draft", "undercut", "parting_line", "core_cavity", "pull_direction",
    ]
    severity: Severity
    title: str  # "12 faces below minimum draft"
    description: str  # engineer-readable explanation
    affected_face_ids: list[int] = Field(default_factory=list)
    measured_values: dict[str, float] = Field(default_factory=dict)
    evidence_source: EvidenceSource
    confidence: float = Field(ge=0.0, le=1.0)
    recommendation: str  # the concrete design change
    estimated_tooling_impact: Optional[str] = None  # "requires side-action slide"


class DfMReport(BaseModel):
    part_name: str
    pull_direction: tuple[float, float, float]
    pull_direction_source: Literal["optimal", "user_specified", "default_z"]
    overall_manufacturability: Literal["good", "acceptable", "problematic", "not_manufacturable"]
    findings: list[DfMFinding] = Field(default_factory=list)
    summary: str
    analysis_warnings: list[str] = Field(default_factory=list)  # engine warnings, surfaced not swallowed
    tools_called: list[str] = Field(default_factory=list)  # audit trail
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
