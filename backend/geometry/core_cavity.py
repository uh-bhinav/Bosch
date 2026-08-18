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
from typing import TYPE_CHECKING, Optional
import logging
import time

from backend.config import settings
from backend.models.geometry_models import PartGeometry, Vec3, dot3, normalize3

if TYPE_CHECKING:
    from backend.geometry.parting_line_v2.regions import RegionClassification

logger = logging.getLogger(__name__)

try:
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Splitter
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.Interface import Interface_Static
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID
    from OCC.Core.TopoDS import topods
    from OCC.Core.TopTools import TopTools_ListOfShape
    from OCC.Core.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt
    _OCC_SPLIT_AVAILABLE = True
except Exception as _occ_import_exc:
    # Do NOT swallow this silently. A bare `except: _AVAILABLE = False` here
    # previously hid a genuine import-path bug (`OCC.Core.Interface_Static`
    # does not exist — the real module is `OCC.Core.Interface`) for the
    # entire time solid split / STEP export were "implemented": every call
    # silently reported the generic, environment-sounding
    # "pythonOCC Boolean APIs not available in this environment" instead of
    # the actual `ModuleNotFoundError`, so the failure read as a missing
    # dependency rather than a one-line bug. Log loudly so this class of
    # defect can never hide again.
    logger.error(
        "Core/cavity Boolean solid-split imports failed — solid split and "
        "STEP export will report 'not_attempted' for every request: %s",
        _occ_import_exc,
    )
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
    # C1 (2026-08-17): populated only when this result was built from an
    # authoritative parting_line_v2 RegionClassification (see
    # `_classify_core_cavity_from_region`) -- faces whose sampled normals
    # straddle the parting plane despite carrying a single cavity/core/
    # parting label here. Always empty for the pre-C1 single-normal path,
    # which has no multi-sample evidence to detect this from.
    inconsistent_face_ids: list[int] = field(default_factory=list)
    #: "single_normal" (pre-C1 per-face n.d test, unchanged default) or
    #: "parting_line_v2" (authoritative RegionClassification supplied).
    classification_source: str = "single_normal"

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
            "inconsistent_face_ids": self.inconsistent_face_ids,
            "classification_source": self.classification_source,
        }


def classify_core_cavity(
    part: PartGeometry,
    pull_direction: Optional[Vec3] = None,
    threshold: Optional[float] = None,
    mutate: bool = True,
    region_classification: Optional["RegionClassification"] = None,
) -> CoreCavityResult:
    """
    Classify every face as cavity, core, or parting relative to the pull direction.

    Uses part.optimal_pull_direction if pull_direction is not supplied.
    Uses config.yaml: dfm.core_cavity.threshold if threshold is not supplied.
    If mutate=True, writes face.cavity_or_core field on each FaceData object.

    ``region_classification`` (C1, 2026-08-17): optional, parting_line_v2's
    ``RegionClassification`` (``analyse_parting_line(...).regions`` — non-
    ``None`` exactly when a candidate was selected, i.e. the direction is
    v2-feasible). When supplied, it becomes the AUTHORITATIVE source for
    every face's cavity/core/parting label -- see
    ``_classify_core_cavity_from_region`` -- eliminating the previously
    documented disagreement between this module's own single-UV-centroid-
    normal test and parting_line_v2's graph-connectivity-based
    classification (audit RC-8). ``threshold`` is ignored in that path (v2
    already decided per-face labels from its own multi-sample test).
    When ``region_classification`` is ``None`` (the default), behavior is
    BYTE-IDENTICAL to before this parameter existed.
    """
    if region_classification is not None:
        return _classify_core_cavity_from_region(part, pull_direction, region_classification, mutate)

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


def _classify_core_cavity_from_region(
    part: PartGeometry,
    pull_direction: Optional[Vec3],
    region: "RegionClassification",
    mutate: bool,
) -> CoreCavityResult:
    """
    Build a ``CoreCavityResult`` from parting_line_v2's ``RegionClassification``
    (C1, 2026-08-17).

    Mapping from v2's four-way per-face ``label`` (``"cavity"``/``"core"``/
    ``"split"``/``"ambiguous"``, see ``FaceClassification``'s docstring) onto
    this module's three-way cavity/core/parting scheme:

    - ``"cavity"`` -> cavity (v2 already confirmed this face is cleanly on
      the cavity side via H3 graph connectivity, not a single normal).
    - ``"core"`` -> core, symmetrically.
    - ``"split"`` / ``"ambiguous"`` -> parting. Both mean "not cleanly
      assigned to one side" -- a split face genuinely belongs to BOTH
      regions (the loop runs through it) and an ambiguous face's own
      sampled normals are too close to zero to confirm a side locally.
      Forcing either onto one side would silently reintroduce exactly the
      v1 defect (RC-8) this path exists to remove, so both land in the
      same honest "parting" bucket v1 already had for "near-perpendicular,
      no confident side."

    A face's FULL area is attributed to whichever of the three buckets it
    lands in (never split fractionally here) -- this module's existing
    cavity/core/parting scheme has no fractional-attribution concept, and
    inventing one is out of scope for this phase (see
    ``FaceClassification.cavity_area_mm2``/``core_area_mm2`` if fractional
    split-face area is ever needed directly from v2's own richer data).
    """
    t0 = time.time()
    warnings: list[str] = list(region.warnings)

    if pull_direction is None:
        pull_direction = part.optimal_pull_direction
    if pull_direction is None:
        pull_direction = (0.0, 0.0, 1.0)
        warnings.append(
            "No optimal pull direction set; defaulting to +Z for core/cavity classification."
        )

    faces_by_id = {f.face_id: f for f in part.faces}
    label_by_id: dict[int, str] = {}
    cavity_ids: list[int] = []
    core_ids: list[int] = []
    parting_ids: list[int] = []
    cavity_area = core_area = parting_area = 0.0

    for fc in region.faces:
        face = faces_by_id.get(fc.face_id)
        face_area = face.area if face is not None else (fc.cavity_area_mm2 + fc.core_area_mm2)
        if fc.label == "cavity":
            cavity_ids.append(fc.face_id)
            cavity_area += face_area
            label_by_id[fc.face_id] = "cavity"
        elif fc.label == "core":
            core_ids.append(fc.face_id)
            core_area += face_area
            label_by_id[fc.face_id] = "core"
        else:  # "split" or "ambiguous"
            parting_ids.append(fc.face_id)
            parting_area += face_area
            label_by_id[fc.face_id] = "parting"

    skipped_ids = [f.face_id for f in part.faces if f.face_id not in label_by_id]
    total_area = cavity_area + core_area + parting_area

    if mutate:
        for face in part.faces:
            classification = label_by_id.get(face.face_id)
            if classification is not None:
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
        threshold_used=0.0,
        analysis_time_s=time.time() - t0,
        warnings=warnings,
        inconsistent_face_ids=list(region.inconsistent_face_ids),
        classification_source="parting_line_v2",
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
    - ``split_tool_kind``: honesty label for what shape actually bisected the
      tooling. As of Stage 2b this is always ``"planar_approximation"`` on
      success — a flat plane through the parting loop's centroid, NOT the
      reported 3-D parting surface (see ``build_planar_split_tool``). Never
      claim the export follows the exact candidate parting line without
      checking this field first.
    """

    solid_split_status: str  # "split_ok" | "blocked_by_parting_line" | "failed" | "not_attempted"
    split_solid_count: int = 0
    cavity_solid_volume_mm3: float = 0.0
    core_solid_volume_mm3: float = 0.0
    blank_volume_mm3: float = 0.0
    failure_reason: str | None = None
    split_tool_kind: str = "none"  # "none" | "planar_approximation"
    # C5 (2026-08-17): count/volume of Splitter fragments discarded as
    # negligible under the existing min_solid_volume_fraction invariant
    # (see _partition_meaningful_solids). Always 0 / 0.0 for an ordinary
    # 2-solid split -- never silently hidden when nonzero.
    discarded_sliver_count: int = 0
    discarded_sliver_volume_mm3: float = 0.0
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
            "split_tool_kind": self.split_tool_kind,
            "discarded_sliver_count": self.discarded_sliver_count,
            "discarded_sliver_volume_mm3": round(self.discarded_sliver_volume_mm3, 4),
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


def _partition_meaningful_solids(
    solids: list[object],
    tooling_volume: float,
    min_solid_volume_fraction: float,
) -> tuple[list[object], list[object]]:
    """
    C5 (2026-08-17, Phase C1-C5 investigation): split a raw list of OCC
    solids from ``BRepAlgoAPI_Splitter`` into "meaningful" (volume >=
    ``min_solid_volume_fraction`` of ``tooling_volume``) and "negligible"
    (below it) groups.

    Uses the EXISTING configured ``min_solid_volume_fraction`` (the same
    threshold ``_validate_split_volumes`` already uses to reject a
    degenerate solid) -- no new absolute-mm3 constant. A solid at EXACTLY
    the threshold counts as meaningful (``>=``, matching
    ``_validate_split_volumes``'s own "< min_volume" strict-rejection
    convention for the identical threshold).

    Phase C2/C3/C4 root-caused a real case (Part1's true, exact parting
    height coincides with a real flat face) where ``BRepAlgoAPI_Splitter``
    correctly reports success but yields one small genuine sliver fragment
    alongside the two real mold halves -- not a different topology, not
    numerical noise. This function is the pure, independently-testable
    partition step that lets ``split_core_cavity_solids`` tell that case
    apart from a genuinely ambiguous multi-way split (see C4's investigation
    report for the full evidence).

    Pure function: plain OCC shapes in, two plain lists out.
    """
    min_volume = tooling_volume * min_solid_volume_fraction
    meaningful: list[object] = []
    negligible: list[object] = []
    for solid in solids:
        volume = _solid_volume(solid)
        if volume >= min_volume:
            meaningful.append(solid)
        else:
            negligible.append(solid)
    return meaningful, negligible


def _check_meaningful_solids_disjoint(
    solid_a: object,
    solid_b: object,
    volume_tolerance: float,
) -> tuple[bool, str | None]:
    """
    C5 additional safety invariant (Phase C4 investigation, item 7): volume
    conservation alone cannot rule out a compensating-error overlap (two
    solids overlapping by some volume while each also missing material
    elsewhere, such that the volume SUM still happens to conserve). This
    measures the actual pairwise intersection directly via
    ``BRepAlgoAPI_Common`` -- already used elsewhere in this codebase
    (``undercut_detector.py``'s swept-Boolean interference check) -- rather
    than inferring disjointness from volume sums.

    C7 (2026-08-17): ``volume_tolerance`` is the caller's already-computed
    Boolean-volume noise-floor tolerance -- ``max(bbox_diagonal**3 *
    direction_search.boolean_volume_tolerance_factor,
    direction_search.boolean_min_volume_tolerance_mm3)``, the EXACT same
    scale-relative/absolute-floor pattern ``undercut_detector.py`` already
    uses to distinguish a genuine small Boolean-computed volume from OCC
    floating-point noise. C6's audit found ``min_solid_volume_fraction``
    (used here through C5) was never semantically defined in this
    repository for "acceptable overlap" -- only for "is a single solid big
    enough to be real" -- and a dangerous-case analysis showed it could
    silently accept a materially significant overlap (e.g. 900 mm³ on a
    100,000 mm³ tooling volume). This function no longer computes the
    tolerance itself; it only compares against what the caller supplies,
    keeping this helper decoupled from ``direction_search`` config.

    Fails CLOSED: if ``BRepAlgoAPI_Common`` cannot be built, reports
    errors, or its resulting volume cannot be measured, this returns
    ``(False, reason)`` -- NEVER treated as "0 intersection".
    """
    try:
        common = BRepAlgoAPI_Common()
        common.SetArguments(_shape_list([solid_a]))
        common.SetTools(_shape_list([solid_b]))
        common.Build()
    except Exception as exc:
        return False, f"Intersection check (BRepAlgoAPI_Common) raised: {exc}"

    if not common.IsDone() or common.HasErrors():
        return False, "Intersection check (BRepAlgoAPI_Common) did not complete successfully."

    try:
        props = GProp_GProps()
        brepgprop_VolumeProperties(common.Shape(), props)
        intersection_volume = float(props.Mass())
    except Exception as exc:
        return False, f"Intersection volume could not be measured: {exc}"

    # Strict comparison preserved unchanged from C5: acceptance is
    # `intersection_volume < volume_tolerance` (the `>=` branch below
    # fails); only the value being compared against changed in C7.
    if intersection_volume >= volume_tolerance:
        return False, (
            f"Meaningful solids are not sufficiently disjoint: intersection "
            f"volume {intersection_volume:.6f} mm³ >= the Boolean-volume "
            f"noise-floor tolerance ({volume_tolerance:.6f} mm³)."
        )
    return True, None


def _validate_split_volumes(
    cavity_volume: float,
    core_volume: float,
    tooling_volume: float,
    *,
    min_volume_fraction: float,
    conservation_tolerance: float,
) -> str | None:
    """
    Stage 2 (2026-07-28): a split that returns 2 solids is not the same as a
    split that returns 2 USABLE solids. `BRepAlgoAPI_Splitter` can report
    success while the parting sheet only partially bisects the tooling — the
    result is one near-full-blank solid plus a degenerate sliver (near-zero
    or even negative "volume"), not a genuine cavity/core pair. Measured on
    Part1 before this check existed: solid volumes 35950.05 and −0.164
    against a tooling volume of 34509.89 — nominally "2 solids", actually a
    broken split.

    Pure function (plain floats in, a failure-reason string or None out) so
    the check can be unit-tested without constructing real OCC solids.

    Returns a human-readable failure reason, or `None` if the volumes are
    plausible.
    """
    min_volume = tooling_volume * min_volume_fraction
    if cavity_volume < min_volume or core_volume < min_volume:
        return (
            f"Split produced 2 solids but one is degenerate: cavity="
            f"{cavity_volume:.3f} mm³, core={core_volume:.3f} mm³ against a "
            f"tooling volume of {tooling_volume:.3f} mm³ (each solid must be "
            f">= {min_volume_fraction * 100:.1f}% of tooling volume). "
            "The parting sheet likely does not fully bisect the mold blank — "
            "see roadmap Stage 2 §2.3."
        )

    volume_error = (
        abs((cavity_volume + core_volume) - tooling_volume) / tooling_volume
        if tooling_volume > 0
        else 1.0
    )
    if volume_error > conservation_tolerance:
        return (
            f"Split volumes don't conserve: cavity ({cavity_volume:.3f}) + core "
            f"({core_volume:.3f}) = {cavity_volume + core_volume:.3f} mm³ vs. "
            f"tooling volume {tooling_volume:.3f} mm³ "
            f"({volume_error * 100:.2f}% error, tolerance "
            f"{conservation_tolerance * 100:.1f}%)."
        )

    return None


def _shape_list(shapes: list[object]) -> object:
    """
    Wrap a Python list of OCC shapes into a `TopTools_ListOfShape`.

    `BRepAlgoAPI_BuilderAlgo.SetArguments`/`SetTools` in this pythonOCC
    binding do NOT accept a plain Python list — they raise
    `TypeError: ... argument 2 of type 'TopTools_ListOfShape const &'`. This
    was silently masked for the entire time solid split was "implemented":
    the surrounding `except Exception` in the retry loop caught it and
    reported the generic "failed after all fuzzy-tolerance retries" instead
    of the real `TypeError`.
    """
    shape_list = TopTools_ListOfShape()
    for shape in shapes:
        shape_list.Append(shape)
    return shape_list


def build_planar_split_tool(
    centroid: Vec3,
    pull_direction: Vec3,
    half_size_mm: float,
) -> object:
    """
    Build a single, always-topologically-valid planar face — perpendicular
    to the pull direction, centred on ``centroid``, extending ``half_size_mm``
    in every in-plane direction — for use as the Boolean splitter tool
    (Milestone 1.10).

    Why this exists, not the real parting surface (Stage 2, S2.3)
    ----------------------------------------------------------------
    The reported/displayed 3-D parting surface (`parting_line.
    _build_parting_surface`'s `BRepFill_Filling` patch) is confirmed
    topologically invalid via `BRepCheck_Analyzer` on both real demo parts —
    independent of any attempt to extend it to the blank's bounds.
    `ShapeFix_Shape`, `ShapeFix_Face`, and `BRepBuilderAPI_Sewing` were all
    tried directly against it and none produced a valid shape (see
    CHANGELOG.md 2026-07-28 "Stage 2b"). `BRepAlgoAPI_Splitter` cannot
    reliably consume an invalid tool shape. A flat plane sidesteps the
    problem entirely — it is trivially valid at any size — at the cost of
    being a genuine geometric approximation for non-planar parting lines
    (measured pull-axis span: Part1 16.16 mm / 30.78 mm part, Part3
    7.14 mm / 68.12 mm — a real but bounded simplification, not negligible).
    Verified end-to-end on real OCC: produces `split_ok` with 2 solids on
    both Part1 and Part3, where the real filling patch (extended or not)
    could not.

    This is purely the Boolean-split tool. It is NOT the reported parting
    line — `PartingSurfaceResult.occ_shape` is unaffected and stays the real
    3-D candidate curve/surface for display and reporting.
    """
    normal = normalize3(pull_direction)
    reference = (1.0, 0.0, 0.0) if abs(dot3((1.0, 0.0, 0.0), normal)) <= 0.9 else (0.0, 1.0, 0.0)
    proj = dot3(reference, normal)
    x_axis_raw = (
        reference[0] - proj * normal[0],
        reference[1] - proj * normal[1],
        reference[2] - proj * normal[2],
    )
    x_axis = normalize3(x_axis_raw)

    origin = gp_Pnt(*[float(v) for v in centroid])
    normal_dir = gp_Dir(*[float(v) for v in normal])
    x_dir = gp_Dir(*[float(v) for v in x_axis])
    plane = gp_Pln(gp_Ax3(origin, normal_dir, x_dir))
    return BRepBuilderAPI_MakeFace(
        plane, -half_size_mm, half_size_mm, -half_size_mm, half_size_mm
    ).Face()


def split_core_cavity_solids(
    part: PartGeometry,
    parting_sheet: object,
    pull_direction: Optional[Vec3] = None,
    *,
    loop_points: Optional[list[Vec3]] = None,
    blank_margin_factor: Optional[float] = None,
    split_fuzzy_factor: Optional[float] = None,
) -> CoreCavitySolidResult:
    """
    Perform the Boolean mold-half split (Milestone 1.10).

    Algorithm:
      1. Build an oversized mold blank with `BRepPrimAPI_MakeBox`.
      2. `BRepAlgoAPI_Cut(blank, part.occ_shape)` → tooling volume.
      3. Build a planar split tool (`build_planar_split_tool`) through the
         parting loop's centroid, perpendicular to the pull direction, then
         `BRepAlgoAPI_Splitter(tooling, split_tool)` → split into halves.
      4. Classify each resulting solid as cavity or core by the sign of
         dot(centre_of_mass − loop_centroid, pull_direction).

    ``parting_sheet`` is kept as a required argument purely as the "was a
    parting surface generated at all" precondition (``None`` → blocked) — it
    is NOT used as the Boolean tool itself. Stage 2 (S2.3) found the real
    3-D parting surface topologically invalid on both real demo parts (see
    `build_planar_split_tool`'s docstring), so the actual splitting tool is
    always a flat plane built from ``loop_points``. Pass the parting-line
    result's ``wire_points`` here.

    Failure modes (all return structured results, never raise):
      - Parting sheet unavailable, or no loop points to build a splitting
        tool from: `solid_split_status="blocked_by_parting_line"`.
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

    if not loop_points or len(loop_points) < 3:
        return CoreCavitySolidResult(
            solid_split_status="blocked_by_parting_line",
            failure_reason=(
                "Parting-line loop points were not provided; cannot build the "
                "planar Boolean splitting tool (see build_planar_split_tool)."
            ),
        )

    if pull_direction is None:
        pull_direction = part.optimal_pull_direction or (0.0, 0.0, 1.0)

    cfg = settings.dfm.core_cavity
    margin = blank_margin_factor if blank_margin_factor is not None else cfg.blank_margin_factor
    fuzzy = split_fuzzy_factor if split_fuzzy_factor is not None else cfg.split_fuzzy_factor

    loop_centroid = (
        sum(p[0] for p in loop_points) / len(loop_points),
        sum(p[1] for p in loop_points) / len(loop_points),
        sum(p[2] for p in loop_points) / len(loop_points),
    )

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
            cut.SetArguments(_shape_list([blank]))
            cut.SetTools(_shape_list([part.occ_shape]))
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
    tooling_volume = _solid_volume(tooling)

    # 3. Build the planar split tool and run BRepAlgoAPI_Splitter(tooling,
    #    split_tool) → two mold halves. See build_planar_split_tool's
    #    docstring for why a flat plane is used instead of parting_sheet.
    try:
        split_tool = build_planar_split_tool(
            loop_centroid, pull_direction, diag * cfg.split_plane_half_size_factor
        )
        splitter = BRepAlgoAPI_Splitter()
        splitter.SetArguments(_shape_list([tooling]))
        splitter.SetTools(_shape_list([split_tool]))
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

    # 4b. C5 (2026-08-17): partition into meaningful vs negligible fragments
    # using the EXISTING min_solid_volume_fraction invariant (Phase C1-C5
    # investigation -- see _partition_meaningful_solids' docstring). An
    # ordinary 2-solid split is UNCHANGED by this: both solids are, by
    # construction, either both meaningful (falls through exactly as
    # before) or the result already fails the meaningful-count check below
    # exactly as the old `len(solids) != 2` check did -- there is no new
    # acceptance path for a genuine 2-solid split.
    meaningful, negligible = _partition_meaningful_solids(
        solids, tooling_volume, cfg.min_solid_volume_fraction,
    )
    if len(meaningful) != 2:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            split_solid_count=len(solids),
            blank_volume_mm3=blank_volume,
            failure_reason=(
                f"Split yielded {len(solids)} solid(s), of which "
                f"{len(meaningful)} are meaningful (>= "
                f"{cfg.min_solid_volume_fraction * 100:.1f}% of tooling volume) "
                "instead of exactly 2. The parting sheet may not fully cut the "
                "tooling blank."
            ),
        )
    discarded_sliver_count = len(negligible)
    discarded_sliver_volume_mm3 = sum(_solid_volume(s) for s in negligible)
    solids = meaningful

    # 5. Classify each solid as cavity or core, using the SAME loop centroid
    # the split tool was built from (previously this recomputed a centroid
    # from parting_sheet's VolumeProperties — a face/shell has no volume, so
    # that call was silently degenerate and fell back to the blank midpoint,
    # a semantically wrong "parting centroid" for a 2-D surface).
    classified: dict[str, object] = {}
    for solid in solids:
        cg = _solid_center_of_mass(solid)
        if cg is None:
            continue
        rel = (
            cg[0] - loop_centroid[0],
            cg[1] - loop_centroid[1],
            cg[2] - loop_centroid[2],
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
    cavity_volume = _solid_volume(cavity)
    core_volume = _solid_volume(core)

    volume_failure = _validate_split_volumes(
        cavity_volume,
        core_volume,
        tooling_volume,
        min_volume_fraction=cfg.min_solid_volume_fraction,
        conservation_tolerance=cfg.volume_conservation_tolerance,
    )
    if volume_failure is not None:
        return CoreCavitySolidResult(
            solid_split_status="failed",
            split_solid_count=2,
            cavity_solid_volume_mm3=cavity_volume,
            core_solid_volume_mm3=core_volume,
            blank_volume_mm3=blank_volume,
            failure_reason=volume_failure,
        )

    # C5 (2026-08-17): additional safety invariant (Phase C4, item 7), only
    # exercised when a sliver was actually discarded above -- for an
    # ordinary 2-solid split (discarded_sliver_count == 0) this check is
    # skipped entirely, so that case's result stays byte-identical to
    # before this phase. Reuses _check_meaningful_solids_disjoint, which
    # fails CLOSED (never treats a measurement failure as "0 intersection").
    #
    # C7 (2026-08-17): the tolerance compared against is the EXISTING
    # direction_search Boolean-volume noise-floor pattern (already used by
    # undercut_detector.py for the identical question -- see C6's audit),
    # not cfg.min_solid_volume_fraction (which C6 found was never
    # semantically defined for "acceptable overlap" -- only for "is a
    # single solid big enough to be real"). Computed here, at the call
    # site, so _check_meaningful_solids_disjoint itself stays decoupled
    # from direction_search config.
    if discarded_sliver_count > 0:
        direction_search_cfg = settings.dfm.direction_search
        intersection_tolerance = max(
            part.bounding_box.diagonal ** 3 * direction_search_cfg.boolean_volume_tolerance_factor,
            direction_search_cfg.boolean_min_volume_tolerance_mm3,
        )
        disjoint_ok, disjoint_failure = _check_meaningful_solids_disjoint(
            cavity, core, intersection_tolerance,
        )
        if not disjoint_ok:
            return CoreCavitySolidResult(
                solid_split_status="failed",
                split_solid_count=2,
                cavity_solid_volume_mm3=cavity_volume,
                core_solid_volume_mm3=core_volume,
                blank_volume_mm3=blank_volume,
                failure_reason=disjoint_failure,
            )

    return CoreCavitySolidResult(
        solid_split_status="split_ok",
        split_solid_count=2,
        cavity_solid_volume_mm3=cavity_volume,
        core_solid_volume_mm3=core_volume,
        blank_volume_mm3=blank_volume,
        split_tool_kind="planar_approximation",
        cavity_solid=cavity,
        core_solid=core,
        discarded_sliver_count=discarded_sliver_count,
        discarded_sliver_volume_mm3=discarded_sliver_volume_mm3,
    )


# ---------------------------------------------------------------------------
# Milestone 1.11 — STEP export
# ---------------------------------------------------------------------------

def export_mold_halves(
    solid_result: CoreCavitySolidResult,
    output_dir: str | None = None,
    filename_prefix: str = "mold_halves",
    *,
    solid_overrides: dict[str, object] | None = None,
    extra_solids: list[tuple[object, str]] | None = None,
) -> dict:
    """
    Export cavity and core mold-half solids as a multi-body AP214 STEP file (Milestone 1.11).

    Writes to ``output_dir`` (default: ``settings.dfm.core_cavity.export_dir``).
    The output directory is created if it does not exist.
    Writes NEVER go to ``data/parts/`` (CLAUDE.md invariant #2).

    ``solid_overrides`` / ``extra_solids`` (Stage 4, 2026-07-28): this
    function stays the single AP214 writer for every mold-half export,
    including when a Stage 4 side core has been generated — rather than
    core_cavity.py importing the Stage 4 result type (which would create a
    circular import, since side_core.py already imports from here), the
    caller passes plain OCC shapes:
      - ``solid_overrides``: e.g. ``{"cavity": reduced_cavity_shape}`` —
        write this shape under the ``"cavity"``/``"core"`` label instead of
        ``solid_result``'s own, because Stage 4 replaces whichever half
        contained the side core with its post-Cut reduced volume.
      - ``extra_solids``: additional ``(shape, label)`` bodies appended to
        the same STEP file — e.g. ``[(side_core_solid, "side_core_0")]``.

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

        overrides = solid_overrides or {}
        bodies: list[tuple[object, str]] = [
            (overrides.get("cavity", solid_result.cavity_solid), "cavity"),
            (overrides.get("core", solid_result.core_solid), "core"),
        ]
        bodies.extend(extra_solids or [])

        writer = STEPControl_Writer()
        Interface_Static.SetCVal("write.step.schema", "AP214")

        for solid, label in bodies:
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
        result: dict[str, object] = {
            "status": "exported",
            "output_path": str(output_file),
            "file_size_bytes": file_size,
            "schema": "AP214",
            "solid_count": len(bodies),
        }
        # F6: only set when the file landed in the DEFAULT export directory
        # (`GET /export/download/{filename}` only ever serves from there) --
        # a caller-supplied `output_dir` produces a file the download
        # endpoint cannot see, so `download_filename` must not be offered
        # for one. Lets a caller (the frontend) retrieve the bytes without
        # parsing `output_path` (a server-side absolute filesystem path,
        # not portable/parseable across OS path-separator conventions).
        if export_path == Path(cfg.export_dir).resolve():
            result["download_filename"] = output_file.name
        return result

    except Exception as exc:
        return {
            "status": "failed",
            "failure_reason": f"Export failed: {exc}",
        }
