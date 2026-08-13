"""
backend/geometry/side_core.py
------------------------------
Stage 4 (Bosch criterion #5) — side-core / lifter solid generation.

Scope: Stage 4's original pass (2026-07-28) implemented the roadmap's
"suggested first increment" (docs/ARCHITECTURE_ROADMAP.md §4.4) — a single
side core for the single highest-confidence critical feature.
S4.3 (2026-07-29) generalizes this to multiple/grouped features. Explicit
scope decisions, one per open design question in §4.3:

1. **Per-feature, independently generated — not merged** (§4.3 Q1,
   generalized 2026-07-29). ``generate_side_cores_for_features()`` generates
   ONE side core per qualifying feature (default: every "critical"
   feature), each computed independently against the pristine cavity/core
   solids. Merging spatially-close features into a single shared side core
   is a materially harder problem (deciding "close enough", fusing
   overlapping sweep geometry) and remains deliberately out of scope — this
   pass delivers N independent side cores, not fewer, smarter ones.
   ``generate_primary_side_core`` (Stage 4's original single-feature entry
   point) is unchanged and still available.
   Two things about individual results are geometric facts, not bugs, and
   callers must not treat them as such:
   - A single feature's ``SideCoreResult.side_core_solid`` can itself be a
     multi-piece (disconnected) compound rather than one simply-connected
     solid. Confirmed on Part1's 11-face critical feature (feature 0,
     default `detect_undercuts()` settings): its side core is a 5-piece
     compound (251.0/75.4/82.4/3.6/4.5 mm3, summing to the reported 417.0
     mm3) — `BRepAlgoAPI_Common` between a swept plane and a spatially
     complex, non-convex 11-face region legitimately produces disjoint
     fragments. Volume conservation is unaffected (measured 0.0028% error);
     only the *solid count* changes.
   - Two or more features' individual `side_core_volume_mm3` values CAN
     overlap in physical space when the features are near each other.
     Confirmed on Part1: 4 pairs of adjacent features overlap by ~21.4mm3
     each, ~128mm3 total. Summing individual volumes (or exporting each as
     a separate STEP body alongside a combined-reduced half) double-counts
     that overlap — a real reload measured 34639.0mm3 total vs. the
     original 34508.5mm3 tooling volume (≈0.38% inflation, fully explained
     by this overlap, not a Boolean-tolerance defect). Use
     `combine_side_cores_per_half()`'s fused-then-cut-once body for any
     volume-conserving representation or STEP export; treat individual
     `SideCoreResult.side_core_volume_mm3` values as per-feature
     diagnostics only, never summable across features in the same half.
2. **release_direction used verbatim** (§4.3 Q2), never snapped to a machine
   axis. The undercut engine already computed this from real
   Boolean-confirmed geometry (``undercut_detector.py``); second-guessing it
   here would be unjustified without a concrete reason to distrust it.
3. **Not built on BRepFill_Filling** (§4.3 Q3, which speculated this as "most
   likely"). That machinery is confirmed topologically invalid on both real
   demo parts for the MAIN parting surface (Stage 2, S2.3) and there is no
   reason to expect it more reliable on a smaller, still-curved side
   feature. This reuses Stage 2b's proven fix instead: a flat planar
   Boolean-split tool (``core_cavity.build_planar_split_tool``), sized to
   the feature's own local footprint and swept along ``release_direction``.
4. **Lifter vs. slide vs. collapsible-core is NOT decided here** (§4.3 Q4).
   That is a tooling-mechanism decision, not a geometry one. This module
   answers only "what volume of steel must retract, and along which
   direction" — never claim it also selects the actuation mechanism.
5. **Containing-half selection and ordering** (§4.3 Q5): each feature's side
   core is subtracted from whichever main half (cavity or core) has the
   larger Boolean overlap with its own swept volume — measured against the
   SAME pristine ``cavity_solid``/``core_solid`` for every feature, never a
   half already reduced by an earlier feature's cut (which would make the
   result depend on generation order). When two or more features land in
   the same half, ``combine_side_cores_per_half()`` fuses their side-core
   solids together and performs exactly ONE combined cut against the
   pristine half, rather than cutting sequentially.
6. **Output format** (§4.3 Q6): every side core is exported as an additional
   solid in the SAME AP214 STEP file as cavity/core — see
   ``core_cavity.export_mold_halves``'s ``extra_solids``/``solid_overrides``
   parameters, which this module's caller (the API layer) is expected to use
   directly; this module does not write STEP files itself.

Two real sizing/tolerance bugs were found and fixed while prototyping the
original single-feature pass against real Part1/Part3 geometry
(2026-07-28), both load-bearing enough to document here rather than just in
CHANGELOG.md:

- **Footprint sizing must use each feature face's Bnd_Box corners, not face
  centroids or vertex-only sampling.** Face-centroid scatter is zero for a
  single-face feature (Part3 feature 0 is exactly one face), flooring the
  plane to a useless 2mm minimum regardless of the face's true size.
  Vertex-only sampling under-measures curved-edge faces: a circular arc's
  widest point relative to the feature centroid is generally NOT at either
  of its endpoint vertices. Measured on Part3 face 37: vertex sampling gave
  a 1.50mm radius while the face's real Bnd_Box spans 36mm — a ~24x
  undersizing that would have made the side core miss most of the real
  feature. Bnd_Box is built from the actual underlying curve/surface
  geometry, so it gets curved extrema right where point-sampling can't.
- **The fuzzy tolerance used to measure the side-core overlap
  (``BRepAlgoAPI_Common``) MUST be reused, unchanged, for the Cut that
  removes it (``BRepAlgoAPI_Cut``).** A mismatched pair (0.01 for the
  Common, a different hardcoded 0.1 for the Cut) measured a 37.72%
  volume-conservation error on Part1 even though BOTH Boolean ops
  individually reported success (``IsDone()`` / no errors) — this is a
  same-value invariant, not a "pick a safe default" tolerance. A consistent
  0.01 measured 0.00-0.02% error at every plane size tested, 1.0x-2.0x the
  feature's footprint.

A THIRD real bug was found while generalizing to multiple features
(2026-07-29), surfaced by a real face grouping neither original test
exercised: **footprint sizing must use a percentile of Bnd_Box corner
radii, not the max.** Re-running the original single-feature pass at
`detect_undercuts()`'s default `max_boolean_faces` (120, vs. the original
verification's 20) grouped 11 faces into Part1's critical feature instead
of 6 — including one face (225) sitting ~5.5mm from the tightly-clustered
other ten (which spread only ~0.6-2.3mm from each other). A max-based
footprint size is dragged out by that single outlier enough to make the
Boolean split numerically unstable: measured 36.59% volume-conservation
error at the max (half_size=16.6mm), 0.00% at the 75th percentile
(half_size=3.1mm) — with no regression on every previously-verified case
(percentile and max coincide when there is no lone outlier). See
`_feature_footprint_half_size`'s docstring and `dfm.side_core.
footprint_percentile` in `config.yaml`.

Validated on both real demo parts:
  - Part1 feature 0, 6-face grouping (2026-07-28, `max_boolean_faces=20`):
    side core 907.4 mm3 (post-percentile-fix; was 9219.8 mm3 under the
    original max-based sizing — both conserve volume to <0.01% error, the
    percentile version is simply a tighter, more locally-accurate plane).
  - Part1 feature 0, 11-face grouping (2026-07-29, default settings): side
    core 417.0 mm3, 0.0028% conservation error (was 36.59% before the
    percentile fix).
  - Part3 feature 0 (1 face, depth 40.01mm, release ~+X, pull -Z): side core
    46967.3 mm3 subtracted from the cavity half, 0.0000% conservation error
    (percentile and max coincide for a single face — no change).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
import logging

from backend.config import settings
from backend.models.geometry_models import PartGeometry, Vec3, normalize3
from backend.geometry.core_cavity import (
    CoreCavitySolidResult,
    build_planar_split_tool,
    _shape_list,
    _solid_volume,
)

if TYPE_CHECKING:
    from backend.geometry.undercut_detector import UndercutFeature, UndercutResult

logger = logging.getLogger(__name__)

try:
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.gp import gp_Trsf, gp_Vec
    _OCC_SIDE_CORE_AVAILABLE = True
except Exception as _occ_import_exc:
    # Same lesson as core_cavity.py's own import-guard: log loudly rather
    # than swallow, so an import-path bug can never again hide behind the
    # generic "not available in this environment" message.
    logger.error(
        "Side-core Boolean imports failed — side-core generation will report "
        "'not_attempted' for every request: %s", _occ_import_exc,
    )
    _OCC_SIDE_CORE_AVAILABLE = False


@dataclass
class SideCoreResult:
    """
    Result of Stage 4 side-core solid generation (Bosch criterion #5).

    See the module docstring for the explicit scope decisions this result
    reflects (single feature, verbatim release_direction, planar-
    approximation sweep tool, no lifter/slide/collapsible-core
    classification).
    """

    status: str  # "generated" | "blocked_by_core_cavity_split" | "no_feature" | "failed" | "not_attempted"
    feature_id: Optional[int] = None
    containing_half: Optional[str] = None  # "cavity" | "core" | None
    side_core_volume_mm3: float = 0.0
    reduced_half_volume_mm3: float = 0.0
    conservation_error: float = 1.0
    failure_reason: Optional[str] = None
    # OCC shapes — not serialized; consumed by export_mold_halves's
    # solid_overrides/extra_solids parameters.
    side_core_solid: object = None
    reduced_half_solid: object = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "feature_id": self.feature_id,
            "containing_half": self.containing_half,
            "side_core_volume_mm3": round(self.side_core_volume_mm3, 4),
            "reduced_half_volume_mm3": round(self.reduced_half_volume_mm3, 4),
            "conservation_error": round(self.conservation_error, 6),
            "failure_reason": self.failure_reason,
            "occ_available": _OCC_SIDE_CORE_AVAILABLE,
        }


def select_primary_side_core_feature(
    undercut_result: "UndercutResult",
) -> Optional["UndercutFeature"]:
    """
    Pick the single feature Stage 4's first increment targets: the
    highest-interference-volume CRITICAL, Boolean-confirmed feature, falling
    back to the highest-interference feature of any severity if there is no
    critical one. Matches roadmap §4.4's "single highest-confidence...
    critical side-action feature" — grouping/multi-feature generation is
    explicitly out of scope (§4.3 Q1).
    """
    features = [f for f in undercut_result.features if f.severity == "critical"]
    if not features:
        features = list(undercut_result.features)
    if not features:
        return None
    return max(features, key=lambda f: f.interference_volume_mm3)


def _project_perpendicular(point: Vec3, centroid: Vec3, unit_axis: Vec3) -> float:
    rel = tuple(point[i] - centroid[i] for i in range(3))
    along = sum(rel[i] * unit_axis[i] for i in range(3))
    perp = tuple(rel[i] - along * unit_axis[i] for i in range(3))
    return sum(c * c for c in perp) ** 0.5


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile on a plain list — no numpy dependency for one number."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


def _feature_footprint_half_size(
    faces: list,
    centroid: Vec3,
    unit_release: Vec3,
    margin_factor: float,
    min_half_size_mm: float,
    *,
    percentile: float = 0.75,
) -> float:
    """
    Lateral size for the planar sweep tool — how far the feature's own
    geometry extends perpendicular to its release direction. See the module
    docstring for the two sizing approaches this deliberately avoids
    (face-centroid scatter, vertex-only sampling) and why each measured
    wrong on real parts. Uses each feature face's Bnd_Box corners instead,
    which correctly captures curved-edge extrema.

    Sized from the `percentile`-th ranked corner radius, NOT the max
    (found and fixed 2026-07-29, S4.3): a single outlier face far from the
    feature's main cluster — a real case on Part1, where the undercut
    grouper attached a distant face (225, a different Z-plane, ~5.5mm from
    the other 10 faces vs. their ~0.6-2.3mm spread) to an otherwise tightly
    clustered 11-face critical feature — inflates a max-based half_size
    enough to make the Boolean split numerically unstable. Measured
    directly: max-based sizing (half_size=16.6mm) gave a 36.59% volume-
    conservation error on this exact feature; switching to the 75th
    percentile (half_size=3.1mm) gave 0.00% error, with no regression on
    the simpler single-cluster/single-face cases this project's tests were
    already covering (percentile and max coincide when there's no lone
    outlier). This is NOT about being "more lenient" — a smaller, tighter
    plane that actually hugs the real feature is a *more* faithful
    geometric approximation than a bigger one dragged out by one
    unrepresentative corner, and it is what made the Boolean operations
    well-behaved.
    """
    radii: list[float] = []
    for f in faces:
        bnd = Bnd_Box()
        brepbndlib_Add(f.occ_face, bnd)
        x1, y1, z1, x2, y2, z2 = bnd.Get()
        for x in (x1, x2):
            for y in (y1, y2):
                for z in (z1, z2):
                    radii.append(_project_perpendicular((x, y, z), centroid, unit_release))
    representative_radius = _percentile(radii, percentile) if radii else 1.0
    return max(representative_radius * margin_factor, min_half_size_mm)


def generate_side_core(
    part: PartGeometry,
    feature: "UndercutFeature",
    split_result: CoreCavitySolidResult,
    *,
    footprint_margin_factor: Optional[float] = None,
    min_half_size_mm: Optional[float] = None,
    fuzzy_tolerance: Optional[float] = None,
) -> SideCoreResult:
    """
    Generate one side-core solid for ``feature`` (Stage 4 first increment,
    roadmap §4.4).

    Algorithm:
      1. Resolve the feature's faces; compute their lateral footprint
         perpendicular to ``feature.release_direction``
         (``_feature_footprint_half_size``).
      2. Build a planar Boolean-split tool at that size, centred on the
         feature faces' centroid, oriented perpendicular to
         release_direction (reuses ``core_cavity.build_planar_split_tool`` —
         the same proven fix from Stage 2b).
      3. Sweep the plane along release_direction with
         ``BRepPrimAPI_MakePrism``.
      4. ``BRepAlgoAPI_Common`` the swept solid against BOTH ``cavity_solid``
         and ``core_solid`` directly (not a separately-rebuilt tooling
         instance — an earlier prototype iteration measured a false
         zero-overlap bug from exactly that mismatch). Whichever has the
         larger overlap volume is the containing half.
      5. ``BRepAlgoAPI_Cut(containing_solid, side_core)`` to get the reduced
         half, using the SAME fuzzy tolerance that succeeded in step 4 (see
         module docstring — this is a same-value invariant, not a
         "reasonable default").

    Never raises; returns a structured ``SideCoreResult`` on every path,
    matching ``split_core_cavity_solids``'s error-handling convention.
    """
    if not _OCC_SIDE_CORE_AVAILABLE:
        return SideCoreResult(
            status="not_attempted",
            failure_reason="pythonOCC Boolean APIs not available in this environment.",
        )

    if split_result.solid_split_status != "split_ok":
        return SideCoreResult(
            status="blocked_by_core_cavity_split",
            failure_reason=(
                f"Cannot generate a side core: core/cavity solid split status "
                f"is '{split_result.solid_split_status}'. Run solid_split=true "
                "on /core-cavity first."
            ),
        )
    if split_result.cavity_solid is None or split_result.core_solid is None:
        return SideCoreResult(
            status="blocked_by_core_cavity_split",
            failure_reason="Cavity/core solid shapes are None despite split_ok status.",
        )

    cfg = settings.dfm.side_core
    margin_factor = (
        footprint_margin_factor if footprint_margin_factor is not None
        else cfg.footprint_margin_factor
    )
    min_half_size = (
        min_half_size_mm if min_half_size_mm is not None else cfg.min_half_size_mm
    )
    default_fuzzy = fuzzy_tolerance if fuzzy_tolerance is not None else cfg.fuzzy_tolerance

    faces = [part.get_face(fid) for fid in feature.face_ids]
    faces = [f for f in faces if f is not None]
    if not faces:
        return SideCoreResult(
            status="failed",
            feature_id=feature.feature_id,
            failure_reason=(
                f"None of feature {feature.feature_id}'s face_ids resolved to real faces."
            ),
        )

    centroid = tuple(sum(f.centroid[i] for f in faces) / len(faces) for i in range(3))
    unit_release = normalize3(feature.release_direction)

    half_size = _feature_footprint_half_size(
        faces, centroid, unit_release, margin_factor, min_half_size,
        percentile=cfg.footprint_percentile,
    )

    try:
        plane = build_planar_split_tool(centroid, unit_release, half_size)
    except Exception as exc:
        return SideCoreResult(
            status="failed",
            feature_id=feature.feature_id,
            failure_reason=f"Planar sweep-tool construction failed: {exc}",
        )

    try:
        bnd = Bnd_Box()
        brepbndlib_Add(part.occ_shape, bnd)
        x1, y1, z1, x2, y2, z2 = bnd.Get()
        diag = ((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2) ** 0.5
        epsilon = diag * 0.001
        sweep_distance = diag * 2.0

        # Push the plane slightly backward (into the feature) before
        # sweeping forward, so the sweep starts inside the undercut pocket
        # rather than exactly on its boundary (mirrors the epsilon-offset
        # trick already proven in undercut_detector.py).
        offset = gp_Trsf()
        offset.SetTranslation(gp_Vec(
            -unit_release[0] * epsilon, -unit_release[1] * epsilon, -unit_release[2] * epsilon,
        ))
        moved_plane = BRepBuilderAPI_Transform(plane, offset, True).Shape()
        prism_vec = gp_Vec(
            unit_release[0] * sweep_distance,
            unit_release[1] * sweep_distance,
            unit_release[2] * sweep_distance,
        )
        swept = BRepPrimAPI_MakePrism(moved_plane, prism_vec, True, True).Shape()
    except Exception as exc:
        return SideCoreResult(
            status="failed",
            feature_id=feature.feature_id,
            failure_reason=f"Sweep construction failed: {exc}",
        )

    def _common(main_solid: object) -> tuple[object, float, Optional[float]]:
        for candidate_fuzzy in (default_fuzzy, 0.05, 0.1, 0.5):
            try:
                common = BRepAlgoAPI_Common()
                common.SetArguments(_shape_list([main_solid]))
                common.SetTools(_shape_list([swept]))
                common.SetFuzzyValue(candidate_fuzzy)
                common.Build()
            except Exception:
                continue
            if common.IsDone() and not common.HasErrors():
                shape = common.Shape()
                return shape, _solid_volume(shape), candidate_fuzzy
        return None, 0.0, None

    cavity_shape, cavity_overlap, cavity_fuzzy = _common(split_result.cavity_solid)
    core_shape, core_overlap, core_fuzzy = _common(split_result.core_solid)

    if cavity_overlap <= 0.0 and core_overlap <= 0.0:
        return SideCoreResult(
            status="failed",
            feature_id=feature.feature_id,
            failure_reason=(
                "Swept side-core volume does not overlap either mold half; "
                "no side-core geometry to subtract."
            ),
        )

    if cavity_overlap >= core_overlap:
        containing_half = "cavity"
        containing_solid = split_result.cavity_solid
        side_core_solid = cavity_shape
        side_core_volume = cavity_overlap
        chosen_fuzzy = cavity_fuzzy
        containing_volume_before = split_result.cavity_solid_volume_mm3
    else:
        containing_half = "core"
        containing_solid = split_result.core_solid
        side_core_solid = core_shape
        side_core_volume = core_overlap
        chosen_fuzzy = core_fuzzy
        containing_volume_before = split_result.core_solid_volume_mm3

    try:
        reduce_op = BRepAlgoAPI_Cut()
        reduce_op.SetArguments(_shape_list([containing_solid]))
        reduce_op.SetTools(_shape_list([side_core_solid]))
        reduce_op.SetFuzzyValue(chosen_fuzzy)  # MUST match the Common's fuzzy — see docstring.
        reduce_op.Build()
        if not reduce_op.IsDone() or reduce_op.HasErrors():
            raise RuntimeError("BRepAlgoAPI_Cut reported errors or did not complete.")
        reduced_half_solid = reduce_op.Shape()
    except Exception as exc:
        return SideCoreResult(
            status="failed",
            feature_id=feature.feature_id,
            containing_half=containing_half,
            side_core_volume_mm3=side_core_volume,
            failure_reason=f"Reducing the {containing_half} half by the side core failed: {exc}",
        )

    reduced_half_volume = _solid_volume(reduced_half_solid)
    conservation_error = (
        abs((side_core_volume + reduced_half_volume) - containing_volume_before)
        / containing_volume_before
        if containing_volume_before > 0
        else 1.0
    )

    if conservation_error > cfg.volume_conservation_tolerance:
        return SideCoreResult(
            status="failed",
            feature_id=feature.feature_id,
            containing_half=containing_half,
            side_core_volume_mm3=side_core_volume,
            reduced_half_volume_mm3=reduced_half_volume,
            conservation_error=conservation_error,
            failure_reason=(
                f"Side-core volumes don't conserve: side_core ({side_core_volume:.3f}) + "
                f"reduced_half ({reduced_half_volume:.3f}) = "
                f"{side_core_volume + reduced_half_volume:.3f} mm3 vs. original "
                f"{containing_half} volume {containing_volume_before:.3f} mm3 "
                f"({conservation_error * 100:.2f}% error, tolerance "
                f"{cfg.volume_conservation_tolerance * 100:.1f}%)."
            ),
        )

    return SideCoreResult(
        status="generated",
        feature_id=feature.feature_id,
        containing_half=containing_half,
        side_core_volume_mm3=side_core_volume,
        reduced_half_volume_mm3=reduced_half_volume,
        conservation_error=conservation_error,
        side_core_solid=side_core_solid,
        reduced_half_solid=reduced_half_solid,
    )


def generate_primary_side_core(
    part: PartGeometry,
    undercut_result: "UndercutResult",
    split_result: CoreCavitySolidResult,
) -> SideCoreResult:
    """
    Convenience entry point combining feature selection
    (``select_primary_side_core_feature``) with generation
    (``generate_side_core``) — the single call the API layer needs for the
    roadmap's first increment.
    """
    feature = select_primary_side_core_feature(undercut_result)
    if feature is None:
        return SideCoreResult(
            status="no_feature",
            failure_reason=(
                "No undercut features detected at this pull direction; "
                "nothing to generate a side core for."
            ),
        )
    return generate_side_core(part, feature, split_result)


# ---------------------------------------------------------------------------
# S4.3 (2026-07-29) — generalization to multiple/grouped features
# ---------------------------------------------------------------------------


@dataclass
class MultiSideCoreResult:
    """
    Result of generating side cores for every qualifying feature (S4.3),
    not just the single highest-confidence one.

    Each entry in `results` is independent -- one feature's `"failed"`
    status (e.g. a conservation-tolerance miss on an awkward face grouping)
    never blocks or invalidates the others.
    """

    results: list[SideCoreResult] = field(default_factory=list)

    @property
    def generated_results(self) -> list[SideCoreResult]:
        return [r for r in self.results if r.status == "generated"]

    def to_dict(self) -> dict:
        return {
            "feature_count": len(self.results),
            "generated_count": len(self.generated_results),
            "results": [r.to_dict() for r in self.results],
        }


def select_side_core_features(
    undercut_result: "UndercutResult",
    *,
    severities: tuple[str, ...] = ("critical",),
    max_features: Optional[int] = None,
) -> list["UndercutFeature"]:
    """
    Select every qualifying feature for side-core generation, ranked by
    interference volume (highest first) -- the multi-feature generalization
    of `select_primary_side_core_feature`, which only ever returned one.

    `severities` defaults to critical-only, matching the roadmap's original
    "highest-confidence critical" framing; pass a wider tuple (e.g.
    `("critical", "moderate")`) to include lower-severity features.
    `max_features` caps the count for cost/time control on parts with many
    proxy-retained low-confidence features (Part1 has 1 critical + 7 minor,
    for example) -- `None` means no cap.
    """
    features = [f for f in undercut_result.features if f.severity in severities]
    features.sort(key=lambda f: f.interference_volume_mm3, reverse=True)
    if max_features is not None:
        features = features[:max_features]
    return features


def generate_side_cores_for_features(
    part: PartGeometry,
    undercut_result: "UndercutResult",
    split_result: CoreCavitySolidResult,
    *,
    severities: tuple[str, ...] = ("critical",),
    max_features: Optional[int] = None,
) -> MultiSideCoreResult:
    """
    Generate one side core per qualifying feature (S4.3's generalization of
    `generate_primary_side_core`). See the module docstring's §4.3 Q1/Q5
    for the design decisions this implements: independent generation (not
    merged), and every feature measured against the SAME pristine
    `cavity_solid`/`core_solid` so results never depend on generation
    order. Use `combine_side_cores_per_half()` afterward to get the
    actual reduced mold-half solids when 2+ features share a half.
    """
    features = select_side_core_features(
        undercut_result, severities=severities, max_features=max_features,
    )
    results = [generate_side_core(part, feature, split_result) for feature in features]
    return MultiSideCoreResult(results=results)


@dataclass
class CombinedHalfSideCoreResult:
    """
    One mold half's combined result from `combine_side_cores_per_half` --
    every feature landing in that half fused into a single side-core body
    and cut from the half in one combined operation.

    `feature_ids` lists every feature folded in. `overlap_volume_mm3` is
    `sum(individual side-core volumes) - side_core_volume_mm3` (the fused
    body's volume) -- a real, expected, non-negative quantity whenever two
    or more features' local sweep footprints physically overlap (e.g.
    nearby symmetric ribs); it is NOT a bug or measurement error. See the
    module docstring's S4.3 combined-export note: exporting each feature's
    `side_core_solid` as a SEPARATE STEP body double-counts this overlap,
    which is why the STEP export uses this combined, already-deduplicated
    body instead.
    """

    half: str  # "cavity" | "core"
    status: str  # "generated" | "failed"
    feature_ids: list[int] = field(default_factory=list)
    side_core_volume_mm3: float = 0.0  # fused body's volume, not sum(individual)
    reduced_half_volume_mm3: float = 0.0
    overlap_volume_mm3: float = 0.0
    conservation_error: float = 1.0
    failure_reason: Optional[str] = None
    side_core_solid: object = None
    reduced_half_solid: object = None

    def to_dict(self) -> dict:
        return {
            "half": self.half,
            "status": self.status,
            "feature_ids": self.feature_ids,
            "side_core_volume_mm3": round(self.side_core_volume_mm3, 4),
            "reduced_half_volume_mm3": round(self.reduced_half_volume_mm3, 4),
            "overlap_volume_mm3": round(self.overlap_volume_mm3, 4),
            "conservation_error": round(self.conservation_error, 6),
            "failure_reason": self.failure_reason,
        }


def combine_side_cores_per_half(
    split_result: CoreCavitySolidResult,
    multi_result: MultiSideCoreResult,
    *,
    fuzzy_tolerance: Optional[float] = None,
) -> dict[str, CombinedHalfSideCoreResult]:
    """
    Combine every successfully-generated side core into, at most, one
    reduced solid per mold half (roadmap §4.3 Q5: "the side-core volume
    must be subtracted from whichever mold half contains it -- ordering
    matters").

    When only one feature landed in a half, its already-computed
    `reduced_half_solid` is reused directly (no redundant Boolean op).
    When two or more share a half, their `side_core_solid` shapes are
    fused together first, then cut from the PRISTINE half in one combined
    operation -- never by cutting each one sequentially from an
    already-reduced half, which would make the result depend on the order
    features happened to be processed in.

    This is also the ONLY volume-conserving representation when features
    are close enough that their local sweep footprints overlap (a real
    case on Part1: 4 pairs of adjacent features overlap by ~21.4mm3 each,
    ~128mm3 total -- found 2026-07-29 while diagnosing why exporting each
    feature's raw `side_core_solid` as a separate STEP body reloaded with
    more total volume than the original tooling). Summing individual
    `SideCoreResult.side_core_volume_mm3` values double-counts that
    overlap; this function's fused body does not.

    Returns `{"cavity": CombinedHalfSideCoreResult, "core": ...}` with
    entries only for halves that actually had at least one
    successfully-generated side core; a half with none is simply absent
    (the caller should fall back to `split_result.cavity_solid`/
    `core_solid` unchanged for any half not present here).
    """
    cfg = settings.dfm.side_core
    fuzzy = fuzzy_tolerance if fuzzy_tolerance is not None else cfg.fuzzy_tolerance

    by_half: dict[str, list[SideCoreResult]] = {"cavity": [], "core": []}
    for result in multi_result.generated_results:
        by_half[result.containing_half].append(result)

    reduced: dict[str, CombinedHalfSideCoreResult] = {}
    pristine_by_half = {"cavity": split_result.cavity_solid, "core": split_result.core_solid}
    pristine_volume_by_half = {
        "cavity": split_result.cavity_solid_volume_mm3,
        "core": split_result.core_solid_volume_mm3,
    }

    for half_name, half_results in by_half.items():
        if not half_results:
            continue

        feature_ids = [r.feature_id for r in half_results]
        pristine_volume = pristine_volume_by_half[half_name]

        if len(half_results) == 1:
            only = half_results[0]
            reduced[half_name] = CombinedHalfSideCoreResult(
                half=half_name,
                status="generated",
                feature_ids=feature_ids,
                side_core_volume_mm3=only.side_core_volume_mm3,
                reduced_half_volume_mm3=only.reduced_half_volume_mm3,
                overlap_volume_mm3=0.0,
                conservation_error=only.conservation_error,
                side_core_solid=only.side_core_solid,
                reduced_half_solid=only.reduced_half_solid,
            )
            continue

        sum_individual_volumes = sum(r.side_core_volume_mm3 for r in half_results)
        fused_side_core = half_results[0].side_core_solid
        fuse_ok = True
        for other_result in half_results[1:]:
            try:
                fuse = BRepAlgoAPI_Fuse()
                fuse.SetArguments(_shape_list([fused_side_core]))
                fuse.SetTools(_shape_list([other_result.side_core_solid]))
                fuse.SetFuzzyValue(fuzzy)
                fuse.Build()
                if fuse.IsDone() and not fuse.HasErrors():
                    fused_side_core = fuse.Shape()
                else:
                    fuse_ok = False
                    logger.warning(
                        "combine_side_cores_per_half: fusing feature %s's side core into "
                        "the %s half's combined solid failed; it will be under-represented "
                        "in the final cut.",
                        other_result.feature_id, half_name,
                    )
            except Exception:
                fuse_ok = False
                logger.exception(
                    "combine_side_cores_per_half: exception fusing feature %s's side core "
                    "for the %s half.",
                    other_result.feature_id, half_name,
                )

        if not fuse_ok:
            reduced[half_name] = CombinedHalfSideCoreResult(
                half=half_name,
                status="failed",
                feature_ids=feature_ids,
                failure_reason=(
                    f"One or more features failed to fuse into the {half_name} half's "
                    "combined side core; see logs for the specific feature_id."
                ),
            )
            continue

        fused_volume = _solid_volume(fused_side_core)
        overlap_volume = max(sum_individual_volumes - fused_volume, 0.0)

        try:
            cut = BRepAlgoAPI_Cut()
            cut.SetArguments(_shape_list([pristine_by_half[half_name]]))
            cut.SetTools(_shape_list([fused_side_core]))
            cut.SetFuzzyValue(fuzzy)
            cut.Build()
            if not cut.IsDone() or cut.HasErrors():
                raise RuntimeError("BRepAlgoAPI_Cut reported errors or did not complete.")
            reduced_half_solid = cut.Shape()
        except Exception as exc:
            reduced[half_name] = CombinedHalfSideCoreResult(
                half=half_name,
                status="failed",
                feature_ids=feature_ids,
                side_core_volume_mm3=fused_volume,
                overlap_volume_mm3=overlap_volume,
                failure_reason=(
                    f"Combined Cut for the {half_name} half failed: {exc}"
                ),
            )
            continue

        reduced_half_volume = _solid_volume(reduced_half_solid)
        conservation_error = (
            abs((fused_volume + reduced_half_volume) - pristine_volume) / pristine_volume
            if pristine_volume > 0
            else 1.0
        )

        reduced[half_name] = CombinedHalfSideCoreResult(
            half=half_name,
            status="generated",
            feature_ids=feature_ids,
            side_core_volume_mm3=fused_volume,
            reduced_half_volume_mm3=reduced_half_volume,
            overlap_volume_mm3=overlap_volume,
            conservation_error=conservation_error,
            side_core_solid=fused_side_core,
            reduced_half_solid=reduced_half_solid,
        )

    return reduced
