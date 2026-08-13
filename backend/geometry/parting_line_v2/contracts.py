"""
backend/geometry/parting_line_v2/contracts.py
---------------------------------------------
Boundary contracts for the v2 parting-line engine.

Two boundaries, both deliberate:

**Upstream** (``PullDirectionInput``, ``UndercutInput``) — pull direction and
undercut detection are owned by teammates. This module consumes their results
through explicit adapters, so a change to their internals touches only the
adapter. Both inputs are **validated on entry and raise on invalid data**;
there is no silent fallback to ``+Z``. See ``docs/DECISIONS_AND_ALGORITHMS.md``
D-003.

**Downstream** (``PartingSurfaceProvider``, ``SplitTool``) — the swappable
surface boundary. The planar approximation currently used for the Boolean split
must never contaminate candidate generation or ranking, so:

    Candidate generation and ranking NEVER import or call a
    PartingSurfaceProvider.

That is plan §10.2 rule 1, and it is enforced by
``tests/test_parting_line_v2_contracts.py`` rather than by convention.

References: ``docs/PARTING_LINE_ALGORITHM_PLAN.md`` §10.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from backend.models.geometry_models import PartGeometry, Vec3

__all__ = [
    "PullDirectionInput",
    "UndercutFeatureRef",
    "UndercutInput",
    "SplitTool",
    "PartingSurfaceProvider",
    "ContractViolation",
]


class ContractViolation(ValueError):
    """
    Raised when an input contract is violated.

    Deliberately an exception rather than a structured result. The rest of the
    pipeline returns typed results for GEOMETRY failures, which are expected
    and recoverable; a malformed contract is a PROGRAMMING error and must be
    loud. v1's habit of warning-and-defaulting (``core_cavity.py:137-139``
    silently falls back to +Z) is the failure mode this prevents.
    """


# ---------------------------------------------------------------------------
# Upstream contract — pull direction
# ---------------------------------------------------------------------------

_UNIT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PullDirectionInput:
    """
    The mold opening direction, as consumed by v2.

    Stored normalized. ``‖d‖ = 1 ± 1e-9`` is checked on construction; a zero,
    non-finite, or degenerate vector raises rather than being repaired,
    because there is no defensible "nearest unit vector" to a zero vector.
    """

    direction: Vec3
    #: Where this direction came from. Recorded, never inferred.
    #:
    #: ``"manual"`` means a human/test explicitly specified it — the ONLY
    #: category admissible as independent evidence that this algorithm is
    #: correct, while the upstream optimizer is under repair. ``"optimizer"``
    #: results are integration evidence, not correctness evidence: a run at an
    #: optimizer-derived direction confounds "is our silhouette right?" with
    #: "is that direction right?", and those are different questions owned by
    #: different people.
    source: Literal["optimizer", "user_override", "fixture", "manual"]
    #: Optional upstream confidence. Carried through for provenance ONLY —
    #: v2 never computes, relabels, or reports it as its own (plan §12.7).
    upstream_confidence: float | None = None

    def __post_init__(self) -> None:
        if len(self.direction) != 3:
            raise ContractViolation(
                f"Pull direction must have 3 components, got {len(self.direction)}."
            )
        if not all(math.isfinite(c) for c in self.direction):
            raise ContractViolation(
                f"Pull direction has non-finite components: {self.direction}."
            )
        magnitude = math.sqrt(sum(c * c for c in self.direction))
        if magnitude < _UNIT_TOLERANCE:
            raise ContractViolation(
                "Pull direction is a zero vector; there is no meaningful mold "
                "opening direction to analyse against."
            )
        if abs(magnitude - 1.0) > _UNIT_TOLERANCE:
            object.__setattr__(
                self,
                "direction",
                (
                    self.direction[0] / magnitude,
                    self.direction[1] / magnitude,
                    self.direction[2] / magnitude,
                ),
            )

    @property
    def is_correctness_evidence(self) -> bool:
        """
        True only for directions a human or fixture specified explicitly.

        An ``"optimizer"`` direction cannot serve as correctness evidence for
        THIS module while the upstream optimizer is under repair — a good
        result would not distinguish "our algorithm works" from "that
        direction happens to suit it", and a bad one would not distinguish
        "our algorithm is broken" from "that direction is wrong".
        """
        return self.source in ("fixture", "user_override", "manual")

    @classmethod
    def from_optimizer_result(cls, result: object) -> "PullDirectionInput":
        """
        Adapt ``direction_optimizer.DirectionOptimizationResult``.

        ⚠ Provided for INTEGRATION use only. The parting-line engine never
        calls this itself — the optimizer is an external, teammate-owned
        module, and this package must not import it.

        Duck-typed on ``best_direction`` so a teammate's refactor of that
        module's internals does not break this package — only this adapter
        would need updating if the field itself is renamed.
        """
        direction = getattr(result, "best_direction", None)
        if direction is None:
            raise ContractViolation(
                f"{type(result).__name__} has no 'best_direction'; cannot adapt it "
                "to PullDirectionInput."
            )
        return cls(
            direction=tuple(float(c) for c in direction),  # type: ignore[arg-type]
            source="optimizer",
            upstream_confidence=None,
        )

    def to_dict(self) -> dict:
        return {
            "direction": [round(c, 9) for c in self.direction],
            "source": self.source,
            "upstream_confidence": self.upstream_confidence,
        }


# ---------------------------------------------------------------------------
# Upstream contract — undercuts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UndercutFeatureRef:
    """
    A reference to one upstream undercut feature.

    Deliberately a thin projection of ``undercut_detector.UndercutFeature`` —
    v2 needs only what H5 and T2 use. Copying the whole upstream type would
    couple this package to every future field added there.
    """

    feature_id: int
    face_ids: frozenset[int]
    severity: str                       # "critical" | "minor" | ... (upstream vocabulary)
    release_direction: Vec3 | None = None
    location: Vec3 | None = None
    depth_proxy_mm: float = 0.0

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "face_ids": sorted(self.face_ids),
            "severity": self.severity,
            "release_direction": (
                [round(c, 6) for c in self.release_direction]
                if self.release_direction is not None else None
            ),
            "location": (
                [round(c, 6) for c in self.location]
                if self.location is not None else None
            ),
            "depth_proxy_mm": round(self.depth_proxy_mm, 4),
        }


@dataclass(frozen=True)
class UndercutInput:
    """
    Undercut context, as consumed by v2.

    ``validate_against`` checks that every referenced face id actually exists
    on the part. An id that does not is a real integration bug (a stale result
    paired with a different part, or a face-id remapping) and must not be
    silently dropped — ``face_id`` stability is a documented invariant
    (``.claude/rules/geometry-engine.md``), so a violation means one of the
    two sides is wrong.
    """

    undercut_face_ids: frozenset[int] = frozenset()
    features: tuple[UndercutFeatureRef, ...] = ()

    @classmethod
    def empty(cls) -> "UndercutInput":
        """No undercut context supplied — a legitimate state, not an error."""
        return cls()

    @classmethod
    def from_detection_result(cls, result: object) -> "UndercutInput":
        """
        Adapt ``undercut_detector.UndercutDetectionResult``.

        Duck-typed on ``undercut_face_ids`` and ``features`` (the two fields
        v2 needs), so upstream can grow without breaking this package.
        """
        if result is None:
            return cls.empty()

        raw_ids = getattr(result, "undercut_face_ids", None)
        if raw_ids is None:
            raise ContractViolation(
                f"{type(result).__name__} has no 'undercut_face_ids'; cannot adapt "
                "it to UndercutInput. Pass UndercutInput.empty() if there is "
                "genuinely no undercut context."
            )

        refs: list[UndercutFeatureRef] = []
        for feature in getattr(result, "features", ()) or ():
            face_ids = getattr(feature, "face_ids", ()) or ()
            refs.append(UndercutFeatureRef(
                feature_id=int(getattr(feature, "feature_id", -1)),
                face_ids=frozenset(int(f) for f in face_ids),
                severity=str(getattr(feature, "severity", "unknown")),
                release_direction=_opt_vec3(getattr(feature, "release_direction", None)),
                location=_opt_vec3(getattr(feature, "location", None)),
                depth_proxy_mm=float(getattr(feature, "depth_proxy_mm", 0.0)),
            ))

        return cls(
            undercut_face_ids=frozenset(int(f) for f in raw_ids),
            features=tuple(sorted(refs, key=lambda r: r.feature_id)),
        )

    def validate_against(self, part: PartGeometry) -> None:
        """Raise if any referenced face id is not present on ``part``."""
        known = {face.face_id for face in part.faces}
        unknown = sorted(self.undercut_face_ids - known)
        if unknown:
            raise ContractViolation(
                f"Undercut context references {len(unknown)} face id(s) not present "
                f"on this part (first few: {unknown[:5]}). face_id is stable per "
                "STEP file, so this means the undercut result belongs to a "
                "different part."
            )
        for ref in self.features:
            feature_unknown = sorted(ref.face_ids - known)
            if feature_unknown:
                raise ContractViolation(
                    f"Undercut feature {ref.feature_id} references face id(s) not "
                    f"present on this part: {feature_unknown[:5]}."
                )

    def features_touching(self, face_ids: frozenset[int]) -> tuple[UndercutFeatureRef, ...]:
        """Features sharing at least one face with ``face_ids`` (used by H5)."""
        return tuple(f for f in self.features if f.face_ids & face_ids)

    def to_dict(self) -> dict:
        return {
            "undercut_face_ids": sorted(self.undercut_face_ids),
            "feature_count": len(self.features),
            "features": [f.to_dict() for f in self.features],
        }


def _opt_vec3(value: object) -> Vec3 | None:
    if value is None:
        return None
    try:
        components = [float(c) for c in value]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return None
    if len(components) != 3:
        return None
    return (components[0], components[1], components[2])


# ---------------------------------------------------------------------------
# Downstream contract — the swappable parting-surface boundary
# ---------------------------------------------------------------------------

SplitToolKind = Literal[
    "planar_approximation",   # today: a flat plane through the loop centroid
    "ruled_extension",
    "face_extension",         # Method D — extend neighbouring faces and sew
    "brep_filled",
]


@dataclass
class SplitTool:
    """
    The geometry that actually bisects the mold blank.

    NOT frozen and NOT JSON-safe: ``occ_shape`` is a live ``TopoDS_Shape``.
    Use ``to_dict()`` for any API or report output.

    ``max_deviation_from_loop_mm`` is the honest quantification of the current
    approximation. For the planar provider it equals the loop's **pull-axis
    span** — 16.16 mm on Part1, 7.14 mm on Part3 (plan §8.2). v1 computes and
    reports this number nowhere, which is precisely why "the split follows the
    parting line" was easy to believe.

    ``is_topologically_valid`` is MEASURED with ``BRepCheck_Analyzer`` on every
    build. v1 shipped and displayed a topologically invalid ``BRepFill_Filling``
    patch for the whole life of the feature because nothing in-module ever
    checked (audit RC-6).
    """

    occ_shape: object
    kind: SplitToolKind
    max_deviation_from_loop_mm: float
    is_topologically_valid: bool
    failure_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_exact(self) -> bool:
        """True only for a tool that genuinely follows the loop."""
        return self.max_deviation_from_loop_mm == 0.0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "max_deviation_from_loop_mm": round(self.max_deviation_from_loop_mm, 4),
            "is_topologically_valid": self.is_topologically_valid,
            "is_exact": self.is_exact,
            "failure_reason": self.failure_reason,
            "notes": list(self.notes),
        }


@runtime_checkable
class PartingSurfaceProvider(Protocol):
    """
    Builds the Boolean splitting tool from a selected parting loop.

    ⚠ **Candidate generation (plan §3-§6) and ranking (§8) must never import,
    call, or reference an implementation of this Protocol.** The selected
    parting line is a real geometric result about the part, independent of how
    the mold is currently split. Enforced by
    ``tests/test_parting_line_v2_contracts.py``.

    A future ``FaceExtensionProvider`` drops in here with zero changes to
    generation, filtering, ranking, or core/cavity classification.
    """

    def build(
        self,
        loop_points: tuple[Vec3, ...],
        part: PartGeometry,
        pull_direction: Vec3,
    ) -> SplitTool:
        ...
