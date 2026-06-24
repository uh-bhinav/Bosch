"""
backend/geometry/core_cavity.py
--------------------------------
Level 1 core/cavity face classification.

For each face in the loaded part, classify it as:
  "cavity" → face normal broadly aligned with pull direction (n·d > threshold)
  "core"   → face normal opposed to pull direction (n·d < -threshold)
  "parting" → face normal near-perpendicular to pull direction (|n·d| ≤ threshold)

This is the geometric classification only (Level 1).
Full Boolean split into two separate solid bodies is Level 2.

The threshold value is taken from config.yaml: dfm.parting_line.silhouette_dot_tolerance
or defaults to 0.05 (≈2.9° from perpendicular).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time

from backend.models.geometry_models import PartGeometry, Vec3, dot3


@dataclass(frozen=True)
class CoreCavityResult:
    pull_direction: Vec3
    cavity_face_ids: list[int]
    core_face_ids: list[int]
    parting_face_ids: list[int]
    skipped_face_ids: list[int]
    cavity_area_mm2: float
    core_area_mm2: float
    parting_area_mm2: float
    total_area_mm2: float
    threshold_used: float
    analysis_time_s: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def cavity_pct(self) -> float:
        return 100.0 * self.cavity_area_mm2 / self.total_area_mm2 if self.total_area_mm2 > 0 else 0.0

    @property
    def core_pct(self) -> float:
        return 100.0 * self.core_area_mm2 / self.total_area_mm2 if self.total_area_mm2 > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "pull_direction": list(self.pull_direction),
            "face_counts": {
                "cavity": len(self.cavity_face_ids),
                "core": len(self.core_face_ids),
                "parting": len(self.parting_face_ids),
                "skipped": len(self.skipped_face_ids),
            },
            "face_ids": {
                "cavity": self.cavity_face_ids,
                "core": self.core_face_ids,
                "parting": self.parting_face_ids,
            },
            "area_mm2": {
                "cavity": round(self.cavity_area_mm2, 3),
                "core": round(self.core_area_mm2, 3),
                "parting": round(self.parting_area_mm2, 3),
                "total": round(self.total_area_mm2, 3),
            },
            "percentages": {
                "cavity_pct": round(self.cavity_pct, 2),
                "core_pct": round(self.core_pct, 2),
            },
            "threshold_used": round(self.threshold_used, 6),
            "analysis_time_s": round(self.analysis_time_s, 4),
            "warnings": self.warnings,
        }


def classify_core_cavity(
    part: PartGeometry,
    pull_direction: Optional[Vec3] = None,
    threshold: float = 0.05,
    mutate: bool = True,
) -> CoreCavityResult:
    """
    Classify every face as cavity, core, or parting relative to the pull direction.

    Uses part.optimal_pull_direction if pull_direction is not supplied.
    If mutate=True, writes face.cavity_or_core field on each FaceData object.
    """
    t0 = time.time()
    warnings: list[str] = []

    if pull_direction is None:
        pull_direction = part.optimal_pull_direction
    if pull_direction is None:
        pull_direction = (0.0, 0.0, 1.0)
        warnings.append("No optimal pull direction set; defaulting to +Z for core/cavity classification.")

    cavity_ids, core_ids, parting_ids, skipped_ids = [], [], [], []
    cavity_area = core_area = parting_area = total_area = 0.0

    for face in part.faces:
        if not face.normal_valid:
            skipped_ids.append(face.face_id)
            continue

        sdot = dot3(face.normal, pull_direction)
        total_area += face.area

        if sdot > threshold:
            cavity_ids.append(face.face_id)
            cavity_area += face.area
            classification = "cavity"
        elif sdot < -threshold:
            core_ids.append(face.face_id)
            core_area += face.area
            classification = "core"
        else:
            parting_ids.append(face.face_id)
            parting_area += face.area
            classification = "parting"

        if mutate:
            face.cavity_or_core = classification

    return CoreCavityResult(
        pull_direction=pull_direction,
        cavity_face_ids=cavity_ids,
        core_face_ids=core_ids,
        parting_face_ids=parting_ids,
        skipped_face_ids=skipped_ids,
        cavity_area_mm2=cavity_area,
        core_area_mm2=core_area,
        parting_area_mm2=parting_area,
        total_area_mm2=total_area,
        threshold_used=threshold,
        analysis_time_s=time.time() - t0,
        warnings=warnings,
    )
