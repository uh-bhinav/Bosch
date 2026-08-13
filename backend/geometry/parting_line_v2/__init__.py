"""
backend/geometry/parting_line_v2
--------------------------------
Clean-room parting-line engine (plan Levels 0-2).

Built alongside ``backend/geometry/parting_line.py`` (v1), not replacing it.
v1 stays the default engine and keeps working until v2 beats it on measured
metrics across the fixture corpus; the switch is
``dfm.parting_line.engine: "v1" | "v2"`` in ``config.yaml``.

Status: **P0 — contracts, fixtures, and harness only.** No algorithm code
lives here yet. The first algorithm (Track A, edge-local silhouette detection)
lands in P1.

Two import rules are enforced by ``tests/test_parting_line_v2_contracts.py``:

1. **Nothing in this package may import ``side_core``.** H5 emits a
   ``SideActionReferral``; it never routes (plan §12.8).
2. **Candidate generation and ranking may not import a
   ``PartingSurfaceProvider``.** The parting line is a real geometric result,
   independent of how the mold is currently split (plan §10.2 rule 1).

Design notes and the reasoning behind each decision are recorded in
``docs/DECISIONS_AND_ALGORITHMS.md``.
"""

from __future__ import annotations

from backend.geometry.parting_line_v2.contracts import (
    ContractViolation,
    PartingSurfaceProvider,
    PullDirectionInput,
    SplitTool,
    UndercutFeatureRef,
    UndercutInput,
)
from backend.geometry.parting_line_v2.timing import (
    STAGE_ORDER,
    StageName,
    StageTimer,
    StageTimings,
    percentile,
)
from backend.geometry.parting_line_v2.types import (
    HARD_GATES,
    CandidateScore,
    CurveSegment,
    EdgeBacking,
    EnumerationBounds,
    FaceBacking,
    FaceClassification,
    FeasibilityReport,
    GateId,
    OnSurfaceReport,
    PartingLoopCandidate,
    SegmentBacking,
    SegmentKind,
    SideActionReferral,
)

__all__ = [
    # contracts
    "ContractViolation",
    "PartingSurfaceProvider",
    "PullDirectionInput",
    "SplitTool",
    "UndercutFeatureRef",
    "UndercutInput",
    # timing
    "STAGE_ORDER",
    "StageName",
    "StageTimer",
    "StageTimings",
    "percentile",
    # types
    "HARD_GATES",
    "CandidateScore",
    "CurveSegment",
    "EdgeBacking",
    "EnumerationBounds",
    "FaceBacking",
    "FaceClassification",
    "FeasibilityReport",
    "GateId",
    "OnSurfaceReport",
    "PartingLoopCandidate",
    "SegmentBacking",
    "SegmentKind",
    "SideActionReferral",
]
