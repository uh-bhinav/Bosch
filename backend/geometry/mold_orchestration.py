"""
backend/geometry/mold_orchestration.py
---------------------------------------
Phase C14 -- winning-direction mold orchestration (the missing wiring layer
Phase C13 investigated and recommended, for Bosch criterion #5).

Single generic entry point (``resolve_winning_direction_mold``) implementing
the ONE chain established by C13, replacing three near-duplicate, slightly
different ad hoc chains previously inlined in ``backend/api/main.py``'s
``/core-cavity``, ``/export/mold-halves``, and ``/export/report`` endpoints
(their ``use_optimal_direction=true`` path only -- the manual/override path
is untouched, see below):

    optimize_mold_direction (caller-supplied, computed once)
        -> require optimal_found=True (never best_unverified_candidate)
        -> analyse_parting_line for best_direction, WITH the SAME real
           undercut evidence the optimizer's own internal feasibility gate
           already used (_cached_is_parting_line_feasible, Phase C10) --
           fixes the latent ``undercuts=UndercutInput.empty()`` gap in
           ``backend.api.main._resolve_v2_parting_line`` that C13 found.
           H0-H7's gate LOGIC is unchanged; only the input evidence is now
           consistent between the optimizer's search and this re-derivation.
        -> split_core_cavity_solids
        -> optimal_undercuts.features (winning direction's OWN real
           UndercutFeature list, already computed by the optimizer) --
           NEVER SideActionReferral. Referrals
           (DirectionOptimizationResult.side_action_referrals, C12) remain
           reporting-only: most belong to OTHER, non-winning directions or
           to non-selected candidate loops at the winning direction itself
           (see C13's real-run evidence on Part1/Part3), so they are never
           read by this module, let alone passed into side_core.py.
        -> exclude features whose faces are fully covered by validated
           delegations for the selected candidate (D-044) -- threaded from
           ``pl_result.selected.feasibility.validated_delegations``
        -> generate_side_core() per eligible feature (reusing
           side_core.py's existing select_side_core_features/
           generate_side_core/combine_side_cores_per_half APIs unchanged)

Direction-consistency invariant: exactly ONE pull direction
(``direction_result.best_direction``) is threaded unchanged through every
step. The two intermediate results that carry their own ``pull_direction``
field (``optimal_undercuts``, the re-derived parting-line result) are
asserted equal to it before use, so this chain can never silently mix
directions from different steps.

Phase C16 adds a SECOND entry point, ``resolve_manual_direction_mold``, for
an engineer-supplied pull direction (``use_optimal_direction=false`` in the
API layer). It normalizes/validates the direction, computes real undercut
evidence for it (the same final-direction convention the optimizer's own
last step uses -- boolean-refined, ``mutate=True``), and feeds the result
into the EXACT SAME ``_resolve_mold_for_direction`` core the automatic path
uses -- never a second, parallel chain. It never fabricates a
``DirectionOptimizationResult`` or ``optimal_found``: the returned
``WinningDirectionMoldResult.direction_result`` stays ``None``, since
"optimal_found" is a search/optimizer concept that has no meaning for a
direction a human explicitly chose (Phase C15).
"""
from __future__ import annotations

import math
import types
from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings
from backend.models.geometry_models import PartGeometry, Vec3, normalize3
from backend.geometry.direction_optimizer import DirectionOptimizationResult
from backend.geometry.parting_line_v2 import (
    CorePinFaceRef,
    DelegatedSecondaryAction,
    PullDirectionInput,
    UndercutInput,
)
from backend.geometry.parting_line_v2.engine import analyse_parting_line, PartingLineV2Result
from backend.geometry.core_cavity import CoreCavitySolidResult, split_core_cavity_solids
from backend.geometry.side_core import (
    CombinedHalfSideCoreResult,
    MultiSideCoreResult,
    combine_side_cores_per_half,
    generate_side_core,
    select_primary_side_core_feature,
    select_side_core_features,
)
from backend.geometry.undercut_detector import UndercutDetectionResult, UndercutFeature, detect_undercuts


def filter_features_excluding_delegated(
    features: list[UndercutFeature],
    delegated_face_ids: frozenset[int],
) -> list[UndercutFeature]:
    """
    C14: exclude any undercut feature whose face_ids are FULLY covered by
    ``delegated_face_ids`` -- i.e. a feature already entirely claimed by a
    validated ``DelegatedSecondaryAction`` for this direction (D-044) is
    assumed handled by that separate mechanism, and must not also get
    additional side-core steel generated for it. A feature only PARTIALLY
    covered is kept -- it still has undelegated surface that may need a
    side action.

    Pure, no OCC -- independently testable against a real UndercutFeature
    list without needing a split_ok core/cavity split or optimal_found=True
    anywhere in the picture.
    """
    if not delegated_face_ids:
        return list(features)
    kept = []
    for f in features:
        face_ids = frozenset(f.face_ids)
        if face_ids and face_ids <= delegated_face_ids:
            continue
        kept.append(f)
    return kept


@dataclass
class WinningDirectionMoldResult:
    """
    Result of ``resolve_winning_direction_mold``. Every path returns a
    structured result -- this function never raises for an ordinary
    "not ready yet" state (matches ``CoreCavitySolidResult``/
    ``SideCoreResult``'s existing convention).
    """

    #: "generated" | "blocked_optimal_not_found" | "blocked_by_parting_line"
    #: | "blocked_by_core_cavity_split" | "no_feature" | "invalid_direction"
    #: (the last one, Phase C16, only ever comes from
    #: resolve_manual_direction_mold -- the automatic path's
    #: optimize_mold_direction() never produces a malformed candidate).
    status: str
    failure_reason: Optional[str] = None
    #: C16: set directly by BOTH entry points (not derived from
    #: direction_result), so a manual-direction result can report its own
    #: direction even though direction_result stays None.
    pull_direction: Optional[Vec3] = None
    direction_result: Optional[DirectionOptimizationResult] = None
    pl_result: Optional[PartingLineV2Result] = None
    split_result: Optional[CoreCavitySolidResult] = None
    delegated_face_ids: frozenset = field(default_factory=frozenset)
    excluded_feature_ids: tuple = ()
    multi_side_core_result: Optional[MultiSideCoreResult] = None
    combined_side_cores: dict[str, CombinedHalfSideCoreResult] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "failure_reason": self.failure_reason,
            "pull_direction": (
                list(self.pull_direction) if self.pull_direction is not None else None
            ),
            # C15/C16: optimal_found stays a pure optimizer/search concept --
            # None whenever direction_result is None (every
            # resolve_manual_direction_mold result), never fabricated.
            "optimal_found": (
                self.direction_result.optimal_found if self.direction_result else None
            ),
            "parting_line_v2_outcome": self.pl_result.outcome if self.pl_result else None,
            "solid_split": self.split_result.to_dict() if self.split_result else None,
            "delegated_face_ids": sorted(self.delegated_face_ids),
            "excluded_feature_ids": list(self.excluded_feature_ids),
            "side_cores": (
                self.multi_side_core_result.to_dict() if self.multi_side_core_result else None
            ),
            "side_core_combined": {
                half: r.to_dict() for half, r in self.combined_side_cores.items()
            },
        }


#: Same scale as parting_line_v2.contracts._UNIT_TOLERANCE. Direction
#: values that traveled through independent floating-point code paths
#: (e.g. this module's own normalize3() vs. OCC's internal gp_Dir
#: normalization inside detect_undercuts()) can differ by ~1 ULP even
#: when mathematically identical -- confirmed empirically (C16): a real
#: manual (1,1,0) request produced undercuts.pull_direction ending
#: ...476 against a locally normalized ...475. Exact tuple equality
#: would false-positive-block a perfectly valid direction on this noise.
_DIRECTION_TOLERANCE = 1e-9


def _directions_match(a: Vec3, b: Vec3, tolerance: float = _DIRECTION_TOLERANCE) -> bool:
    return all(abs(a[i] - b[i]) <= tolerance for i in range(3))


def resolve_authoritative_parting_line(
    part: PartGeometry,
    direction: Vec3,
    undercuts: UndercutDetectionResult,
    *,
    core_pin_face_refs: tuple[CorePinFaceRef, ...],
    delegations: tuple[DelegatedSecondaryAction, ...],
    source_label: str,
) -> PartingLineV2Result:
    """
    C18A: the ONE real-undercut-aware ``analyse_parting_line`` derivation --
    extracted out of ``_resolve_mold_for_direction`` so a caller that only
    needs face-classification regions (``backend.api.main``'s ``/core-cavity``
    and ``/export/report``, for their unconditional Level 1 display) can get
    the SAME authoritative result the mold orchestration itself uses,
    instead of a second, separate, ``undercuts=UndercutInput.empty()`` call
    (the stale ``_resolve_v2_parting_line`` gap C13/C17 identified).

    Fixes the latent ``undercuts=UndercutInput.empty()`` gap -- H0-H7's gate
    LOGIC is unchanged; only the input evidence is now real. Callers that
    already computed this result should pass it into
    ``resolve_winning_direction_mold``/``resolve_manual_direction_mold`` via
    ``precomputed_pl_result`` rather than letting those functions re-derive
    it a second time.
    """
    undercuts_input = UndercutInput.from_detection_result(undercuts)
    return analyse_parting_line(
        part,
        PullDirectionInput(direction, source_label),
        undercuts=undercuts_input,
        cfg=settings.dfm.parting_line_v2,
        core_pin_face_refs=core_pin_face_refs,
        delegations=delegations,
    )


def _resolve_mold_for_direction(
    part: PartGeometry,
    direction: Vec3,
    undercuts: UndercutDetectionResult,
    *,
    core_pin_face_refs: tuple[CorePinFaceRef, ...],
    delegations: tuple[DelegatedSecondaryAction, ...],
    severities: tuple[str, ...],
    max_features: Optional[int],
    generate_side_cores: bool,
    primary_only: bool,
    direction_result: Optional[DirectionOptimizationResult],
    precomputed_pl_result: Optional[PartingLineV2Result] = None,
) -> WinningDirectionMoldResult:
    """
    C16: the ONE chain -- extracted from C14's ``resolve_winning_direction_
    mold`` so both the automatic (optimizer) and manual (engineer-supplied)
    entry points run through EXACTLY this code, never two parallel
    versions. Parameterized on a concrete ``(direction, undercuts)`` pair
    instead of a ``DirectionOptimizationResult``, so it has no dependency
    on ``optimal_found``/the optimizer search at all.

    ``direction_result`` is threaded through ONLY so the automatic
    wrapper's result stays backward compatible (``WinningDirectionMoldResult
    .direction_result`` populated); the manual wrapper always passes
    ``None`` here, per C15's explicit requirement that ``optimal_found``
    stay a pure optimizer/search concept, never fabricated for an
    engineer-chosen direction.

    ``precomputed_pl_result`` (C18A): when the caller already derived the
    authoritative parting-line result via ``resolve_authoritative_parting_
    line`` (e.g. for face-classification display before deciding whether a
    solid split was even requested), pass it here to skip re-running
    ``analyse_parting_line`` a second time for the same direction/undercuts.
    The direction-consistency invariant is still checked against whatever
    is passed in -- never trusted blindly.
    """
    source_label = "manual" if direction_result is None else "optimizer"

    # Direction-consistency invariant, part 1: the undercut evidence this
    # chain is about to reuse must itself already be for `direction`. For
    # the automatic path this always holds by construction
    # (DirectionOptimizationResult.optimal_undercuts is computed for
    # best_direction inside optimize_mold_direction); for the manual path
    # it always holds because resolve_manual_direction_mold computes
    # `undercuts` from the SAME normalized `direction` it passes in here.
    # Asserted rather than assumed either way, so a future refactor can
    # never silently break it without this function noticing.
    if not _directions_match(tuple(undercuts.pull_direction), tuple(direction)):
        return WinningDirectionMoldResult(
            status="blocked_by_parting_line",
            failure_reason=(
                "Direction-consistency invariant violated: undercut evidence "
                f"was computed for {tuple(undercuts.pull_direction)}, "
                f"not the direction being resolved {tuple(direction)}."
            ),
            pull_direction=direction, direction_result=direction_result,
        )

    # C13/C14: fix the latent undercuts=UndercutInput.empty() gap -- re-
    # derive the parting-line result with the SAME real undercut evidence
    # the automatic path's internal feasibility gate already used
    # (_cached_is_parting_line_feasible, Phase C10) / the manual path's own
    # freshly-computed evidence, instead of
    # backend.api.main._resolve_v2_parting_line's undercuts=
    # UndercutInput.empty(). H0-H7's gate logic is unchanged -- only the
    # input evidence is now consistent with whatever computed `direction`.
    # C18A: skip the derivation entirely when the caller already did it.
    if precomputed_pl_result is not None:
        pl_result = precomputed_pl_result
    else:
        pl_result = resolve_authoritative_parting_line(
            part, direction, undercuts,
            core_pin_face_refs=core_pin_face_refs, delegations=delegations,
            source_label=source_label,
        )

    # Direction-consistency invariant, part 2. PartingLineV2Result.
    # pull_direction is a PullDirectionInput (label + direction), not a
    # bare Vec3 -- compare its .direction field. Checked even when
    # pl_result was precomputed -- never trust a caller-supplied value
    # blindly.
    if not _directions_match(tuple(pl_result.pull_direction.direction), tuple(direction)):
        return WinningDirectionMoldResult(
            status="blocked_by_parting_line",
            failure_reason=(
                "Direction-consistency invariant violated: the re-derived "
                f"parting-line result is for {tuple(pl_result.pull_direction.direction)}, "
                f"not the direction being resolved {tuple(direction)}."
            ),
            pull_direction=direction, direction_result=direction_result, pl_result=pl_result,
        )

    if pl_result.selected is None:
        # D-062/C11/C12: pl_result.outcome already distinguishes a genuine
        # dead end ("no_feasible_candidate") from "requires_side_action"
        # (H5 routed every candidate to referral rather than rejecting
        # outright) -- surfaced here via parting_line_v2_outcome in
        # to_dict(), never collapsed into one generic message. This is the
        # SAME existing PartingLineV2Result.outcome vocabulary C9/C11
        # established; no new status is invented for the referral case.
        return WinningDirectionMoldResult(
            status="blocked_by_parting_line",
            failure_reason=(
                f"analyse_parting_line found no selected candidate for this "
                f"direction (outcome={pl_result.outcome!r})."
            ),
            pull_direction=direction, direction_result=direction_result, pl_result=pl_result,
        )

    split_result = split_core_cavity_solids(
        part, pl_result.selected, direction,
        loop_points=list(pl_result.selected.points),
    )
    if split_result.solid_split_status != "split_ok":
        return WinningDirectionMoldResult(
            status="blocked_by_core_cavity_split",
            failure_reason=(
                f"Core/cavity solid split status is "
                f"'{split_result.solid_split_status}'."
            ),
            pull_direction=direction, direction_result=direction_result, pl_result=pl_result,
            split_result=split_result,
        )

    if not generate_side_cores:
        return WinningDirectionMoldResult(
            status="generated",
            pull_direction=direction, direction_result=direction_result, pl_result=pl_result,
            split_result=split_result,
        )

    # D-044: validated delegations for the SELECTED candidate at THIS
    # direction, threaded into side-core feature selection so a face
    # already claimed by a validated secondary mechanism never also gets
    # side-core steel generated for it.
    validated_delegations = (
        pl_result.selected.feasibility.validated_delegations
        if pl_result.selected.feasibility is not None else ()
    )
    delegated_face_ids = frozenset(
        fid for d in validated_delegations for fid in d.face_ids
    )
    all_features = list(undercuts.features)
    eligible_features = filter_features_excluding_delegated(all_features, delegated_face_ids)
    eligible_ids = {f.feature_id for f in eligible_features}
    excluded_feature_ids = tuple(
        f.feature_id for f in all_features if f.feature_id not in eligible_ids
    )

    # select_side_core_features/select_primary_side_core_feature only read
    # `.features` off their argument -- a plain SimpleNamespace satisfies
    # that duck-typed contract without needing a new UndercutResult-shaped
    # type or touching side_core.py.
    filtered_undercuts = types.SimpleNamespace(features=eligible_features)
    if primary_only:
        primary_feature = select_primary_side_core_feature(filtered_undercuts)
        selected_features = [primary_feature] if primary_feature is not None else []
    else:
        selected_features = select_side_core_features(
            filtered_undercuts, severities=severities, max_features=max_features,
        )
    if not selected_features:
        return WinningDirectionMoldResult(
            status="no_feature",
            failure_reason=(
                "No qualifying, non-delegated undercut feature at this "
                "direction."
            ),
            pull_direction=direction, direction_result=direction_result, pl_result=pl_result,
            split_result=split_result, delegated_face_ids=delegated_face_ids,
            excluded_feature_ids=excluded_feature_ids,
        )

    # Mirrors generate_side_cores_for_features's own body exactly (never
    # calling that function directly here, since it would re-derive an
    # UNFILTERED feature list from undercut_result.features itself --
    # delegation exclusion must happen BEFORE selection, never after).
    # Per-feature/per-half failures stay granular ("failed" entries inside
    # MultiSideCoreResult/CombinedHalfSideCoreResult) and never downgrade
    # this function's own overall "generated" status -- unchanged from C14.
    results = [generate_side_core(part, feature, split_result) for feature in selected_features]
    multi_result = MultiSideCoreResult(results=results)
    combined = combine_side_cores_per_half(split_result, multi_result)

    return WinningDirectionMoldResult(
        status="generated",
        pull_direction=direction, direction_result=direction_result, pl_result=pl_result,
        split_result=split_result, delegated_face_ids=delegated_face_ids,
        excluded_feature_ids=excluded_feature_ids,
        multi_side_core_result=multi_result, combined_side_cores=combined,
    )


def resolve_winning_direction_mold(
    part: PartGeometry,
    direction_result: DirectionOptimizationResult,
    *,
    core_pin_face_refs: tuple[CorePinFaceRef, ...] = (),
    delegations: tuple[DelegatedSecondaryAction, ...] = (),
    severities: tuple[str, ...] = ("critical",),
    max_features: Optional[int] = None,
    generate_side_cores: bool = True,
    primary_only: bool = False,
    precomputed_pl_result: Optional[PartingLineV2Result] = None,
) -> WinningDirectionMoldResult:
    """
    C14: the automatic-direction entry point -- see module docstring.
    Thin wrapper (C16) around ``_resolve_mold_for_direction``: unchanged
    signature and behavior, backward compatible with every existing call
    site and test.

    ``primary_only`` (default False) selects between side_core.py's two
    pre-existing, UNCHANGED selection entry points, applied to the
    delegation-filtered feature list: False uses
    ``select_side_core_features`` (``severities``/``max_features``, the
    S4.3 multi-feature generalization); True uses
    ``select_primary_side_core_feature`` (the original Stage 4
    single-highest-confidence-critical-feature-with-severity-fallback
    entry point, ``severities``/``max_features`` ignored). Either way the
    result is reported through the same ``multi_side_core_result``/
    ``combined_side_cores`` fields (0 or 1 entries for ``primary_only``),
    so callers do not need to branch on which mode produced it.

    ``direction_result`` MUST already be the result of calling
    ``optimize_mold_direction(part, core_pin_face_refs=core_pin_face_refs,
    delegations=delegations)`` with these SAME authorization arguments --
    this function does not call the optimizer itself (every existing API
    call site already computes ``direction_result`` once, to resolve
    ``pull_direction``; re-running the search here would silently double
    its cost). ``core_pin_face_refs``/``delegations`` are threaded straight
    through to ``analyse_parting_line``, exactly as
    ``backend.api.main._resolve_v2_parting_line`` already did -- this
    function performs no discovery or inference of its own.

    ``precomputed_pl_result`` (C18A): pass the result of an earlier
    ``resolve_authoritative_parting_line`` call (e.g. one already used for
    face-classification display) to skip re-deriving it here.
    """
    # Critical requirement: never proceed past this point when
    # optimal_found is False, and never treat best_unverified_candidate as
    # a tooling direction. When optimal_found is False, best_direction IS
    # the unverified candidate (DirectionOptimizationResult's own
    # docstring) -- refusing here means nothing below ever reads
    # best_unverified_candidate at all.
    if not direction_result.optimal_found:
        return WinningDirectionMoldResult(
            status="blocked_optimal_not_found",
            failure_reason=(
                "optimize_mold_direction found no verified, parting-line-"
                "feasible optimum (optimal_found=False); refusing to "
                "generate a core/cavity split or side core for "
                f"best_unverified_candidate ({direction_result.best_label})."
            ),
            pull_direction=direction_result.best_direction,
            direction_result=direction_result,
        )

    return _resolve_mold_for_direction(
        part, direction_result.best_direction, direction_result.optimal_undercuts,
        core_pin_face_refs=core_pin_face_refs, delegations=delegations,
        severities=severities, max_features=max_features,
        generate_side_cores=generate_side_cores, primary_only=primary_only,
        direction_result=direction_result, precomputed_pl_result=precomputed_pl_result,
    )


def prepare_manual_direction(
    part: PartGeometry,
    pull_direction: Vec3,
) -> tuple[Optional[Vec3], Optional[UndercutDetectionResult], Optional[WinningDirectionMoldResult]]:
    """
    C18A: validate/normalize a manual pull direction and compute its real
    undercut evidence -- factored out of ``resolve_manual_direction_mold``
    so a caller that ALSO needs face-classification display (``backend.
    api.main``'s ``/core-cavity``/``/export/report``) can do this ONCE and
    reuse both the normalized direction and the undercut evidence for both
    purposes, instead of ``detect_undercuts`` running twice per request.

    Validates and normalizes ``pull_direction`` (rejects non-finite or
    zero/near-zero vectors) via the existing ``normalize3`` helper -- the
    SAME normalization every other direction in this codebase already goes
    through. Computes real undercut evidence with ``detect_undercuts(...,
    mutate=True, boolean_refine=True)`` -- the SAME final-direction
    convention ``optimize_mold_direction``'s own last step uses for its
    winning direction (CLAUDE.md's mutate-flag contract: ``mutate=True`` is
    for "the final chosen direction", which an engineer's explicit choice
    is exactly as much as a search's winner).

    Returns ``(normalized_direction, undercuts, None)`` on success, or
    ``(None, None, WinningDirectionMoldResult(status="invalid_direction",
    ...))`` on validation failure -- the caller can return that result
    object directly.
    """
    if len(pull_direction) != 3 or not all(math.isfinite(c) for c in pull_direction):
        return None, None, WinningDirectionMoldResult(
            status="invalid_direction",
            failure_reason=(
                f"Pull direction has non-finite or malformed components: "
                f"{pull_direction}."
            ),
        )
    try:
        normalized = normalize3(tuple(pull_direction))
    except ValueError as exc:
        return None, None, WinningDirectionMoldResult(
            status="invalid_direction",
            failure_reason=str(exc),
        )

    undercuts = detect_undercuts(part, normalized, mutate=True, boolean_refine=True)
    return normalized, undercuts, None


def resolve_manual_direction_mold(
    part: PartGeometry,
    pull_direction: Vec3,
    *,
    core_pin_face_refs: tuple[CorePinFaceRef, ...] = (),
    delegations: tuple[DelegatedSecondaryAction, ...] = (),
    severities: tuple[str, ...] = ("critical",),
    max_features: Optional[int] = None,
    generate_side_cores: bool = True,
    primary_only: bool = False,
    precomputed_undercuts: Optional[UndercutDetectionResult] = None,
    precomputed_pl_result: Optional[PartingLineV2Result] = None,
) -> WinningDirectionMoldResult:
    """
    C15/C16: the manual/engineer-supplied-direction entry point.

    Validates/normalizes ``pull_direction`` and computes its real undercut
    evidence via ``prepare_manual_direction`` (rejects non-finite or
    zero/near-zero vectors with ``status="invalid_direction"``), then feeds
    the result into the EXACT SAME ``_resolve_mold_for_direction`` core
    ``resolve_winning_direction_mold`` uses -- there is no second, parallel
    chain. Never calls ``optimize_mold_direction`` and never fabricates a
    ``DirectionOptimizationResult``: the returned result's
    ``direction_result`` stays ``None``, so ``to_dict()["optimal_found"]``
    is always ``None`` here -- "optimal_found" is a search/optimizer
    concept (Phase C15) that does not apply to a direction a human
    explicitly chose.

    ``precomputed_undercuts``/``precomputed_pl_result`` (C18A): when the
    caller already ran ``prepare_manual_direction``/``resolve_
    authoritative_parting_line`` itself (e.g. for face-classification
    display before deciding whether a solid split was even requested),
    pass both here to skip re-running validation/``detect_undercuts``/
    ``analyse_parting_line`` a second time. ``pull_direction`` MUST already
    be the normalized direction ``prepare_manual_direction`` returned in
    that case -- this function does not re-validate it.
    """
    if precomputed_undercuts is not None:
        normalized, undercuts = pull_direction, precomputed_undercuts
    else:
        normalized, undercuts, invalid = prepare_manual_direction(part, pull_direction)
        if invalid is not None:
            return invalid

    return _resolve_mold_for_direction(
        part, normalized, undercuts,
        core_pin_face_refs=core_pin_face_refs, delegations=delegations,
        severities=severities, max_features=max_features,
        generate_side_cores=generate_side_cores, primary_only=primary_only,
        direction_result=None, precomputed_pl_result=precomputed_pl_result,
    )
