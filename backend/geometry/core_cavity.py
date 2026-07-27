"""
backend/geometry/core_cavity.py
--------------------------------
Level 1 core/cavity face classification and Level 2 Boolean solid split.

Face classification (Level 1):
  "cavity" → face normal broadly aligned with pull direction (n·d > threshold)
  "core"   → face normal opposed to pull direction (n·d < -threshold)
  "parting" → face normal near-perpendicular to pull direction (|n·d| ≤ threshold)

Boolean solid split (Milestone 1.10 / Level 2):
  blank → BRepAlgoAPI_Cut(blank, part) → tooling volume
         → BRepAlgoAPI_Splitter(tooling, parting_sheet) → cavity + core halves

Thresholds from config.yaml: dfm.core_cavity.*
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import logging
import time

from backend.config import settings
from backend.models.geometry_models import PartGeometry, Vec3, dot3

logger = logging.getLogger(__name__)

try:
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Splitter
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.Interface_Static import Interface_Static
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID
    from OCC.Core.TopoDS import topods
    from OCC.Core.gp import gp_Pnt
    _OCC_SPLIT_AVAILABLE = True
except (ImportError, Exception):
    _OCC_SPLIT_AVAILABLE = False


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
    threshold: Optional[float] = None,
    mutate: bool = True,
) -> CoreCavityResult:
    """
    Classify every face as cavity, core, or parting relative to the pull direction.

    Uses part.optimal_pull_direction if pull_direction is not supplied.
    Uses config.yaml: dfm.core_cavity.threshold if threshold is not supplied.
    If mutate=True, writes face.cavity_or_core field on each FaceData object.
    """
    t0 = time.time()
    warnings: list[str] = []

    if threshold is None:
        threshold = settings.dfm.core_cavity.threshold

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


# ---------------------------------------------------------------------------
# Milestone 1.10 — Boolean solid split
# ---------------------------------------------------------------------------

@dataclass
class CoreCavitySolidResult:
    """
    Result of the Boolean mold-half solid split (Milestone 1.10).

    Adds to the face-classification result:
    - ``solid_split_status``: outcome of the Boolean operations.
    - ``cavity_solid`` / ``core_solid``: raw OCC ``TopoDS_Shape`` objects for
      downstream export (Milestone 1.11). NOT serialized.
    - Volume metrics for sanity checking.
    """

    solid_split_status: str  # "split_ok" | "blocked_by_parting_line" | "failed" | "not_attempted"
    split_solid_count: int = 0
    cavity_solid_volume_mm3: float = 0.0
    core_solid_volume_mm3: float = 0.0
    blank_volume_mm3: float = 0.0
    failure_reason: str | None = None
    # OCC shapes — not serialized; consumed by Milestone 1.11 export.
    cavity_solid: object = None
    core_solid: object = None

    def to_dict(self) -> dict:
        return {
            "solid_split_status": self.solid_split_status,
            "split_solid_count": self.split_solid_count,
            "cavity_solid_volume_mm3": round(self.cavity_solid_volume_mm3, 4),
            "core_solid_volume_mm3": round(self.core_solid_volume_mm3, 4),
            "blank_volume_mm3": round(self.blank_volume_mm3, 4),
            "failure_reason": self.failure_reason,
            "occ_available": _OCC_SPLIT_AVAILABLE,
        }


def _solid_volume(shape: object) -> float:
    """Return the volume of an OCC solid in mm³. Returns 0.0 on failure."""
    try:
        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
        return float(props.Mass())
    except Exception:
        return 0.0


def _solid_center_of_mass(shape: object) -> tuple[float, float, float] | None:
    """Return the centre of mass of an OCC solid. Returns None on failure."""
    try:
        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
        cg = props.CentreOfMass()
        return (float(cg.X()), float(cg.Y()), float(cg.Z()))
    except Exception:
        return None


def split_core_cavity_solids(
    part: PartGeometry,
    parting_sheet: object,
    pull_direction: Optional[Vec3] = None,
    *,
    blank_margin_factor: Optional[float] = None,
    split_fuzzy_factor: Optional[float] = None,
) -> CoreCavitySolidResult:
    """
    Perform the Boolean mold-half split (Milestone 1.10).

    Algorithm:
      1. Build an oversized mold blank with `BRepPrimAPI_MakeBox`.
      2. `BRepAlgoAPI_Cut(blank, part.occ_shape)` → tooling volume.
      3. `BRepAlgoAPI_Splitter(tooling, parting_sheet)` → split into halves.
      4. Classify each resulting solid as cavity or core by the sign of
         dot(centre_of_mass − parting_centroid, pull_direction).

    Failure modes (all return structured results, never raise):
      - Parting sheet unavailable: `solid_split_status="blocked_by_parting_line"`.
      - BRepAlgoAPI_Cut failure: retry with fuzzy tolerance; on exhaustion return
        `status="failed"` with `failure_reason`.
      - Split yields ≠ 2 solids: report actual count in `split_solid_count`,
        `status="failed"` with `failure_reason`.

    Requires `_OCC_SPLIT_AVAILABLE` (pythonOCC in the conda environment).
    """
    if not _OCC_SPLIT_AVAILABLE:
        return CoreCavitySolidResult(
            solid_split_status="not_attempted",
            failure_reason="pythonOCC Boolean APIs not available in this environment.",
        )

    if parting_sheet is None:
        return CoreCavitySolidResult(
            solid_split_status="blocked_by_parting_line",
            failure_reason="Parting surface was not generated; cannot split mold blank.",
        )

    if pull_direction is None:
        pull_direction = part.optimal_pull_direction or (0.0, 0.0, 1.0)

    cfg = settings.dfm.core_cavity
    margin = blank_margin_factor if blank_margin_factor is not None else cfg.blank_margin_factor
    fuzzy = split_fuzzy_factor if split_fuzzy_factor is not None else cfg.split_fuzzy_factor

    # 1. Build oversized mold blank.
    try:
        bbox = part.bounding_box
        bnd = Bnd_Box()
        brepbndlib_Add(part.occ_shape, bnd)
        x1, y1, z1, x2, y2, z2 = bnd.Get()
        diag = ((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2) ** 0.5
        margin_mm = diag * margin
        blank = BRepPrimAPI_MakeBox(
            gp_Pnt(x1 - margin_mm, y1 - margin_mm, z1 - margin_mm),
            gp_Pnt(x2 + margin_mm, y2 + margin_mm, z2 + margin_mm),
        ).Shape()
        blank_volume = _solid_volume(blank)
    except Exception as exc:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            failure_reason=f"Mold blank construction failed: {exc}",
        )

    # 2. BRepAlgoAPI_Cut(blank, part) → tooling volume.
    tooling = None
    for attempt_factor in [1.0, 5.0, 25.0]:
        try:
            cut = BRepAlgoAPI_Cut()
            cut.SetArguments([blank])
            cut.SetTools([part.occ_shape])
            cut.SetFuzzyValue(fuzzy * attempt_factor)
            cut.Build()
            if cut.IsDone() and not cut.HasErrors():
                tooling = cut.Shape()
                break
            logger.warning(
                "BRepAlgoAPI_Cut attempt %s failed (fuzzy=%.4f); retrying.",
                attempt_factor, fuzzy * attempt_factor,
            )
        except Exception as exc:
            logger.warning("BRepAlgoAPI_Cut exception at factor %s: %s", attempt_factor, exc)

    if tooling is None:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            blank_volume_mm3=blank_volume,
            failure_reason="BRepAlgoAPI_Cut (blank − part) failed after all fuzzy-tolerance retries.",
        )

    # 3. BRepAlgoAPI_Splitter(tooling, parting_sheet) → two mold halves.
    try:
        splitter = BRepAlgoAPI_Splitter()
        splitter.SetArguments([tooling])
        splitter.SetTools([parting_sheet])
        splitter.SetFuzzyValue(fuzzy)
        splitter.Build()
        if splitter.HasErrors():
            raise RuntimeError("BRepAlgoAPI_Splitter reported errors.")
        split_shape = splitter.Shape()
    except Exception as exc:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            blank_volume_mm3=blank_volume,
            failure_reason=f"BRepAlgoAPI_Splitter failed: {exc}",
        )

    # 4. Enumerate resulting solids.
    solids: list[object] = []
    try:
        explorer = TopExp_Explorer(split_shape, TopAbs_SOLID)
        while explorer.More():
            solids.append(topods.Solid(explorer.Current()))
            explorer.Next()
    except Exception as exc:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            blank_volume_mm3=blank_volume,
            failure_reason=f"Solid enumeration after split failed: {exc}",
        )

    if len(solids) != 2:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            split_solid_count=len(solids),
            blank_volume_mm3=blank_volume,
            failure_reason=(
                f"Split yielded {len(solids)} solid(s) instead of 2. "
                "The parting sheet may not fully cut the tooling blank."
            ),
        )

    # 5. Classify each solid as cavity or core.
    # Compute parting centroid from the parting-surface boundary.
    try:
        ps_props = GProp_GProps()
        brepgprop_VolumeProperties(parting_sheet, ps_props)
        ps_cg = ps_props.CentreOfMass()
        parting_centroid = (float(ps_cg.X()), float(ps_cg.Y()), float(ps_cg.Z()))
    except Exception:
        # Fallback: use the midpoint of the blank
        parting_centroid = (
            (x1 + x2) / 2.0,
            (y1 + y2) / 2.0,
            (z1 + z2) / 2.0,
        )

    classified: dict[str, object] = {}
    for solid in solids:
        cg = _solid_center_of_mass(solid)
        if cg is None:
            continue
        rel = (
            cg[0] - parting_centroid[0],
            cg[1] - parting_centroid[1],
            cg[2] - parting_centroid[2],
        )
        sdot = dot3(rel, pull_direction)
        label = "cavity" if sdot > 0 else "core"
        classified[label] = solid

    if "cavity" not in classified or "core" not in classified:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            split_solid_count=len(solids),
            blank_volume_mm3=blank_volume,
            failure_reason=(
                "Both split solids have the same side-of-parting classification; "
                "centre-of-mass assignment ambiguous."
            ),
        )

    cavity = classified["cavity"]
    core = classified["core"]
    return CoreCavitySolidResult(
        solid_split_status="split_ok",
        split_solid_count=2,
        cavity_solid_volume_mm3=_solid_volume(cavity),
        core_solid_volume_mm3=_solid_volume(core),
        blank_volume_mm3=blank_volume,
        cavity_solid=cavity,
        core_solid=core,
    )


# ---------------------------------------------------------------------------
# Milestone 1.11 — STEP export
# ---------------------------------------------------------------------------

def export_mold_halves(
    solid_result: CoreCavitySolidResult,
    output_dir: str | None = None,
    filename_prefix: str = "mold_halves",
) -> dict:
    """
    Export cavity and core mold-half solids as a multi-body AP214 STEP file (Milestone 1.11).

    Writes to ``output_dir`` (default: ``settings.dfm.core_cavity.export_dir``).
    The output directory is created if it does not exist.
    Writes NEVER go to ``data/parts/`` (CLAUDE.md invariant #2).

    Returns a JSON-safe dict with ``status``, ``output_path``, and ``failure_reason``.
    """
    from pathlib import Path

    if not _OCC_SPLIT_AVAILABLE:
        return {
            "status": "not_attempted",
            "failure_reason": "pythonOCC STEP writer not available.",
        }

    if solid_result.solid_split_status != "split_ok":
        return {
            "status": "failed",
            "failure_reason": (
                f"Cannot export: solid split status is '{solid_result.solid_split_status}'. "
                "Run solid_split=true on /core-cavity first."
            ),
        }

    if solid_result.cavity_solid is None or solid_result.core_solid is None:
        return {
            "status": "failed",
            "failure_reason": "Solid shapes are None; export requires split_ok result.",
        }

    cfg = settings.dfm.core_cavity
    export_dir_str = output_dir or cfg.export_dir

    # Hard guard: never write to data/parts/ (invariant #2)
    export_path = Path(export_dir_str).resolve()
    data_parts = Path("data/parts").resolve()
    try:
        export_path.relative_to(data_parts)
        return {
            "status": "failed",
            "failure_reason": "Export to data/parts/ is forbidden (CLAUDE.md invariant #2).",
        }
    except ValueError:
        pass  # Not under data/parts/ — safe to write

    try:
        export_path.mkdir(parents=True, exist_ok=True)
        output_file = export_path / f"{filename_prefix}.stp"

        writer = STEPControl_Writer()
        Interface_Static.SetCVal("write.step.schema", "AP214")

        for solid, label in [
            (solid_result.cavity_solid, "cavity"),
            (solid_result.core_solid, "core"),
        ]:
            status = writer.Transfer(solid, STEPControl_AsIs)
            if status != IFSelect_RetDone:
                logger.warning("STEP Transfer for %s solid returned status %s.", label, status)

        write_status = writer.Write(str(output_file))
        if write_status != IFSelect_RetDone:
            return {
                "status": "failed",
                "failure_reason": f"STEPControl_Writer.Write returned {write_status}.",
                "attempted_path": str(output_file),
            }

        file_size = output_file.stat().st_size if output_file.exists() else 0
        return {
            "status": "exported",
            "output_path": str(output_file),
            "file_size_bytes": file_size,
            "schema": "AP214",
            "solid_count": 2,
        }

    except Exception as exc:
        return {
            "status": "failed",
            "failure_reason": f"Export failed: {exc}",
        }
