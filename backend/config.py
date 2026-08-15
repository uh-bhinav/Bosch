"""
backend/config.py
-----------------
Frozen configuration for the DfM Agent.

All thresholds and visualization constants used by geometry modules live here
so Bosch-specific tuning can happen without touching algorithm code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields as dataclass_fields, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DraftConditionSettings:
    """
    Named draft-condition thresholds (Roadmap Phase 1e).

    STEP AP203/AP214 carries no surface-finish/texture information — these
    conditions are never auto-detected from geometry. They exist so a
    caller (the frontend, once a face is user-marked as textured) can
    override the global threshold for specific faces via `analyze_draft`'s
    `face_conditions` parameter. "smooth" duplicates the global default so
    a caller can explicitly reset a face to it.
    """
    smooth_good_deg: float = 1.5
    smooth_marginal_deg: float = 0.5
    light_texture_good_deg: float = 3.0
    light_texture_marginal_deg: float = 2.0
    heavy_texture_good_deg: float = 5.0
    heavy_texture_marginal_deg: float = 3.5
    deep_rib_good_deg: float = 2.0
    deep_rib_marginal_deg: float = 1.0


@dataclass(frozen=True)
class DraftSettings:
    good_threshold_deg: float = 1.5
    marginal_threshold_deg: float = 0.5
    conditions: DraftConditionSettings = DraftConditionSettings()


@dataclass(frozen=True)
class DirectionSearchSettings:
    angular_step_deg: float = 15.0
    max_candidates: int = 54
    prefilter_skip_score_factor: float = 2.0
    prefilter_survivor_top_count: int = 8
    prefilter_min_boolean_candidates: int = 1
    prefilter_zero_score_margin: float = 1.0
    prefilter_low_undercut_area_pct: float = 5.0
    prefilter_low_bad_area_pct: float = 5.0
    prefilter_principal_axis_keep_count: int = 2
    prefilter_uncertainty_score_margin: float = 0.10
    boolean_refine_top_candidates: int = 5
    boolean_refine_max_faces: int = 80
    boolean_refine_score_margin: float = 0.25
    boolean_interference_weight: float = 4000.0
    boolean_offset_factor: float = 1e-5
    boolean_min_offset_mm: float = 1e-4
    boolean_max_offset_mm: float = 0.25
    boolean_retry_offset_multipliers: tuple[float, ...] = (1.0, 5.0, 25.0)
    boolean_sweep_distance_factor: float = 2.0
    boolean_min_sweep_distance_mm: float = 1.0
    boolean_fuzzy_factor: float = 0.1
    boolean_max_fuzzy_value_mm: float = 0.05
    boolean_volume_tolerance_factor: float = 1e-9
    boolean_min_volume_tolerance_mm3: float = 1e-6
    boolean_min_face_area_mm2: float = 1e-5
    boolean_min_face_area_factor: float = 1e-10
    boolean_feature_seed_faces_per_group: int = 1
    boolean_grouping_proximity_factor: float = 0.15
    boolean_grouping_min_proximity_mm: float = 0.25
    flash_risk_weight: float = 200.0
    flash_angle_threshold_deg: float = 5.0
    flash_thin_area_factor: float = 0.02
    fine_search_enabled: bool = True
    fine_search_top_k: int = 3
    fine_angular_step_deg: float = 5.0
    fine_search_cone_half_angle_deg: float = 15.0
    fine_search_max_candidates: int = 60
    # ── Milestone 3: hierarchical candidate generation ────────────────────
    # When True, evaluate ±X/Y/Z first, diagonals second, broader sphere
    # last — stopping early when Boolean validation confirms an acceptable
    # direction.  When False, flat 54-candidate behavior is preserved exactly.
    hierarchical_search_enabled: bool = True
    # Stage 2 diagonal directions (configurable — Bosch has not confirmed
    # which 45° orientations are practical; this list must be replaceable
    # via config without changing code).
    stage2_directions: tuple[tuple[float, float, float], ...] = (
        (1.0, 1.0, 0.0), (1.0, -1.0, 0.0), (-1.0, 1.0, 0.0), (-1.0, -1.0, 0.0),
        (1.0, 0.0, 1.0), (1.0, 0.0, -1.0), (-1.0, 0.0, 1.0), (-1.0, 0.0, -1.0),
        (0.0, 1.0, 1.0), (0.0, 1.0, -1.0), (0.0, -1.0, 1.0), (0.0, -1.0, -1.0),
    )
    # ── Suitability thresholds (PROVISIONAL engineering defaults) ─────────
    # These gate the hierarchical search between stages and are NOT Bosch
    # requirements.  Bosch has not provided numerical thresholds for
    # "suitable".  These values are clearly labeled provisional; they must
    # remain configurable and must not be treated as engineering laws.
    #
    # Cheap screen (stages 1 and 2): gates BEFORE Boolean refinement.
    # A direction passes when BOTH conditions hold.
    suitability_max_bad_draft_pct: float = 30.0    # PROVISIONAL
    suitability_max_accessibility_risk_pct: float = 15.0  # PROVISIONAL
    # Boolean confirmation screen: gates AFTER Boolean refinement.
    # Only Boolean-confirmed undercut area is used here — proxy faces
    # (failed/skipped Boolean) do not count.  A cheap-screen-pass that
    # fails this check is NOT accepted; the search falls through.
    suitability_max_confirmed_undercut_pct: float = 10.0  # PROVISIONAL
    # ── Milestone 4: scoring weights ──────────────────────────────────────
    # Default weights are chosen to preserve scoring magnitude and keep
    # backward compat with parts analysed under the pre-M4 formula.
    # Cheap stage (no Boolean data):
    scoring_bad_draft: float = 1000.0         # surface-orientation penalty
    scoring_marginal_draft: float = 100.0
    scoring_accessibility_risk: float = 1500.0  # heuristic risk (independent)
    scoring_bad_draft_count: float = 10.0
    scoring_marginal_draft_count: float = 2.0
    scoring_accessibility_risk_count: float = 25.0
    scoring_axis_preference: float = 0.25
    # Boolean-refined stage (replaces proxy with confirmed data):
    scoring_confirmed_undercut: float = 1500.0  # Boolean-confirmed area


@dataclass(frozen=True)
class CoreCavitySettings:
    threshold: float = 0.05
    cavity_color: tuple[float, float, float] = (0.2, 0.8, 0.3)
    core_color: tuple[float, float, float] = (0.2, 0.45, 0.9)
    # Milestone 1.10: Boolean solid split
    blank_margin_factor: float = 0.25
    solid_split_enabled: bool = True
    export_dir: str = "output/mold_halves"
    split_fuzzy_factor: float = 0.1
    # Stage 2 (2026-07-28): a split that returns 2 solids is not the same as
    # a split that returns 2 USABLE solids — BRepAlgoAPI_Splitter can report
    # success while handing back one near-full-blank solid plus a degenerate
    # sliver when the parting sheet doesn't fully bisect the tooling. Reject
    # the result rather than report `split_ok` on a broken split.
    min_solid_volume_fraction: float = 0.01  # each solid must be >= 1% of tooling volume
    # Stage 2b (2026-07-28): the real BRepFill_Filling parting surface is
    # confirmed topologically invalid on both real parts (BRepCheck_Analyzer,
    # unfixable by ShapeFix/Sewing — see CHANGELOG.md). The Boolean split now
    # uses a flat planar approximation (build_planar_split_tool) instead,
    # which trades some volume fidelity for reliably reaching split_ok.
    # Measured on real geometry: 4.04% (Part1) / 3.81% (Part3) conservation
    # error. 0.06 covers both with margin; tightening this further is tracked
    # as a bounded follow-up (TODO.md S2.5), not a correctness bug.
    volume_conservation_tolerance: float = 0.06  # cavity+core vs tooling, relative error
    # Stage 2b: half-width (as a multiple of the part's bounding-box
    # diagonal) of the planar Boolean-split tool built by
    # build_planar_split_tool. Must be large enough to fully span the mold
    # blank (itself blank_margin_factor beyond the part) on every side.
    split_plane_half_size_factor: float = 2.0


@dataclass(frozen=True)
class SideCoreSettings:
    # Stage 4 (2026-07-28) — Bosch criterion #5 first increment. See
    # config.yaml's side_core block and backend/geometry/side_core.py's
    # module docstring for the measured justification of each value.
    enabled: bool = True
    footprint_margin_factor: float = 1.5
    min_half_size_mm: float = 2.0
    fuzzy_tolerance: float = 0.01
    volume_conservation_tolerance: float = 0.05
    # S4.3 (2026-07-29): the footprint's lateral half-size is sized from
    # this percentile of feature-face Bnd_Box corner radii, NOT the max.
    # A max-based size is dragged out by a single outlier face far from an
    # otherwise tightly-clustered feature (measured real case: Part1's
    # 11-face critical feature at default undercut-detection settings) --
    # inflating the sweep plane enough to make the Boolean split
    # numerically unstable (36.59% conservation error measured at the max,
    # 0.00% at this percentile). 0.75 was the value verified against real
    # geometry; lower values under-size single-outlier-free features less
    # but risk cropping genuinely large single-cluster features.
    footprint_percentile: float = 0.75


@dataclass(frozen=True)
class UndercutSettings:
    convexity_tangent_tolerance: float = 0.01
    convexity_suppression_enabled: bool = True
    # Milestone 2: accessibility risk heuristic threshold.
    # A face is "core-side" when n·d < -threshold.  Used by
    # _compute_accessibility_risk() to flag faces that are geometrically on
    # the pull-opposing side AND have concave edge evidence of a pocket.
    # PROVISIONAL engineering default — not a Bosch-approved threshold.
    accessibility_risk_core_side_threshold: float = 0.01


@dataclass(frozen=True)
class TierEpsilonSettings:
    """
    Per-tier tie tolerances for v2's lexicographic ranking (plan §8).

    A difference within these bands counts as a TIE and falls through to the
    next tier, so near-equal candidates are never separated by numerical
    noise. Without them, a 1e-12 coverage difference would decide the winner
    and the result would look precise while being arbitrary.
    """
    coverage: float = 0.01
    undercut_proximity: float = 0.02
    pull_axis_span_mm: float = 0.10
    ambiguous_area_fraction: float = 0.01
    excess_turning: float = 0.02
    length_3d_mm: float = 0.50


@dataclass(frozen=True)
class PartingLineV2Settings:
    """
    Thresholds for the v2 parting-line engine (plan §13).

    Every value used by v2 lives here — v1's hardcoded search limits
    (``parting_line.py:3238-3239``: ``search_edge_limit = 22``,
    ``max_search_states = 75_000``) violated CLAUDE.md invariant #4 and made a
    silent fallback to a degraded strategy invisible in the result. Do not
    repeat that.

    Tolerances suffixed ``_rel`` are RELATIVE — multiplied by the part's
    bounding-box diagonal at runtime, then floored, then max'd with the
    kernel's own declared tolerance for the specific face/edge. v1's flat
    ``point_tolerance = 1e-4 mm`` is scale- and kernel-blind (audit RC-9).
    """

    # --- visibility band ---
    #: |g| <= this is the zero-draft / silhouette band. 0.02 ~ 1.15 deg.
    silhouette_epsilon: float = 0.02
    orientation_epsilon: float = 0.05          # H4 slack
    orientation_violation_max: float = 0.02    # H4 rho_max, area fraction

    # --- scale-aware tolerances (x bbox diagonal) ---
    weld_tolerance_rel: float = 1e-6           # floor 1e-7 mm; max'd with vertex tol
    closure_tolerance_rel: float = 1e-5        # H1
    sag_tolerance_rel: float = 1e-3            # grid + edge sampling resolution
    #: How far a Track-B face-interior curve's endpoint may be from the real
    #: bounding edge it terminates on before ``stitch.py`` gives up trying to
    #: snap/cut a junction there (search itself stays restricted to edges that
    #: genuinely bound that face -- ``part.face_to_edges[face_id]`` -- so
    #: raising this cannot pull in an unrelated edge/face).
    #:
    #: STATUS (2026-08-12, still open): was ``weld_tolerance_rel * 100`` (~6.8e-3
    #: mm on Part3). The controlled-direction connectivity diagnostic
    #: (``backend/validation/parting_line_connectivity_diagnostic.py``) measured
    #: real Track-A/Track-B junction gaps of 0.043-1.05 mm on Part3 at +-X/+-Y --
    #: 6x to 150x larger than that search radius -- so this was raised to cover
    #: the measured range. That change is a genuine, regression-clean structural
    #: improvement (the cut-detection loop is now scoped to
    #: ``edge.adjacent_face_ids`` too, not just the snap search), but it is
    #: **NOT YET DEMONSTRATED TO FIX ANYTHING**: re-measured on both Part1 and
    #: Part3, the number of segments pruned by 2-core reduction is IDENTICAL
    #: before and after this change, on every controlled direction tested. The
    #: snap does measurably move face-curve endpoints, but a residual gap
    #: (~0.01-0.02 mm on the traced example, still ~150-300x weld_tolerance_rel)
    #: remains unexplained. Do not read this value's existence as evidence the
    #: connectivity problem is understood or fixed -- see D-022 in
    #: ``docs/DECISIONS_AND_ALGORITHMS.md`` for the open investigation.
    stitch_snap_tolerance_rel: float = 2e-2    # floor 1e-6 mm

    # --- H0 ON-SURFACE INVARIANT (definitional; plan §7.0, H0) ---
    surface_tolerance_rel: float = 1e-6        # tau_surface, floor 1e-7 mm
    edge_tolerance_rel: float = 1e-6           # tau_edge,    floor 1e-7 mm
    #: tau_silhouette = silhouette_epsilon * this (10x tighter than the band)
    silhouette_error_factor: float = 0.1
    #: A smoothed curve is display-only unless it passes H0 in its own right
    #: (plan §9.5 rule 5). Defaults False so the v1 defect cannot recur by
    #: omission — unconstrained 3-D smoothing leaves the surface.
    allow_smoothed_as_geometry: bool = False

    # --- Track A (edge-local silhouette, plan §3) ---
    edge_samples_min: int = 5
    edge_samples_max: int = 33

    # --- Track B (face-interior silhouette, plan §4) ---
    uv_grid_min: int = 8
    uv_grid_max: int = 256
    newton_max_iterations: int = 8
    newton_tolerance: float = 1e-9

    # --- enumeration bounds (plan §6.1) ---
    #: P3a measures the mu distribution across the corpus BEFORE any search
    #: strategy is written. If mu = 1 dominates after reduction, Johnson and
    #: beam search are never built and these knobs stay unused.
    mu_max_for_johnson: int = 12
    #: "basis" | "johnson". DEFAULT "basis", decided by measurement.
    #:
    #: P3a's mu distribution (77.3% of 22 parts in 2 <= mu <= 12) justified
    #: BUILDING bounded Johnson under plan §6.1's gate, and it was built. P3b
    #: then measured what it bought: **zero outcome changes across the entire
    #: corpus**, at up to 22x the candidate count and 10x the runtime (F10:
    #: 9 -> 200 candidates, hitting the cap; 168 -> 1756 ms).
    #:
    #: The reason is structural, not incidental: 6 of the 8 failing parts have
    #: branch_node_count == 0, where every node has degree 2 and the connected
    #: components ARE the only simple cycles -- so Johnson and the basis are
    #: identical there by construction. Enumeration is provably not the binding
    #: constraint.
    #:
    #: The code is kept (it is correct, and complete where the basis is not)
    #: but is opt-in, per plan §11: "Did complexity actually buy us something?"
    #: Here, measurably, it did not. Flip to "johnson" if evidence changes.
    enumeration_strategy: str = "basis"
    max_candidates: int = 200
    beam_width: int = 3
    #: Γ is a DISJOINT UNION of closed curves and a genus-g part generally
    #: needs g+1 of them (D-007). P1 bounded this to pairs; P3 measurement
    #: showed pairs are insufficient — Part3's reduced graph is 3 disjoint
    #: cycles with ZERO branch nodes, so every single and every pair was
    #: rejected at H3 and only the triple remained. Subset enumeration is
    #: cheap because reduction works: 2^n - 1 with n in the low single digits.
    max_loop_union_size: int = 4
    enumeration_time_budget_s: float = 5.0

    # --- hard filter ---
    #: H7. PROVISIONAL -- a configuration decision, NOT an engineering truth
    #: and NOT a manufacturing law. Calibrated from corpus data in P3a. H3
    #: (topological separation) is the real validity test; if H3 and H7
    #: disagree, H3 is right. See plan §7.0.
    min_coverage_ratio: float = 0.50
    min_length_rel: float = 0.05               # H6, x bbox diagonal
    min_projected_area_rel: float = 1e-4       # H6, x bbox_diagonal^2

    # --- ranking ---
    tier_epsilon: TierEpsilonSettings = TierEpsilonSettings()

    # --- core/cavity + Cauchy quadrature ---
    #: M x M per-face sampling, used both for inconsistency detection and for
    #: the area-weighted |g| quadrature in the T1 coverage denominator.
    #: MEASURED convergence against the sphere's exact answer (pi*r^2), P2:
    #:   5x5 -4.89% | 7x7 -2.51% | 9x9 -1.52% | 11x11 -1.02% | 15x15 -0.55%
    #: 11 buys ~1% for 121 samples/face. The denominator is COMMON to every
    #: candidate of a part, so its error cannot affect ranking -- only the
    #: reported coverage value and the H7 threshold comparison.
    face_sample_grid: int = 11


@dataclass(frozen=True)
class PartingLineSettings:
    #: Which parting-line engine to use. v1 is the default and stays the
    #: default until v2 wins or ties on every corpus part (plan P6 cutover).
    #: v1 is frozen — bug fixes only, no features — so the flag stays a
    #: genuine A/B rather than drifting into two diverging codepaths.
    engine: str = "v1"  # "v1" | "v2"
    dot_tolerance: float = 0.01
    boundary_dot_tolerance: float = 0.15
    point_tolerance: float = 1e-4
    smoothing_iterations: int = 8
    display_resample_min_points: int = 96
    max_refined_display_points: int = 32_000
    refined_curve_color: tuple[float, float, float] = (0.0, 0.72, 1.0)
    raw_curve_color: tuple[float, float, float] = (1.0, 0.72, 0.0)
    # Milestone 1.7: component bridging via real B-Rep edges
    bridge_penalty_factor: float = 4.0
    boundary_bridge_factor: float = 0.6
    # Milestone 1.8: closure guarantee
    max_closure_error_mm: float = 0.05
    max_components_exact_cycle: int = 8
    # Bug H: the selected loop must plausibly wrap the part silhouette.
    # Below this fraction of the part's pull-normal projected extent, the
    # selected loop is almost certainly a local feature (hole rim, boss)
    # rather than the main parting line, and the result is flagged.
    min_silhouette_coverage_ratio: float = 0.35


@dataclass(frozen=True)
class PartingSurfaceSettings:
    """
    Parameters for parting surface generation (Milestone 1.9).

    planar_tolerance_mm
        Maximum deviation of loop points from PCA best-fit plane before the
        planar-extrusion strategy is abandoned in favour of BRepFill_Filling.
    extension_factor
        How far to extrude the surface past the part bounding box (multiplier
        of the bbox diagonal). Must be > 1.0 to fully contain the blank.
    filling_max_degree
        Maximum polynomial degree for BRepFill_Filling patches.
    filling_tolerance_mm
        Geometric tolerance for BRepFill_Filling.
    """
    planar_tolerance_mm: float = 0.25
    extension_factor: float = 1.5
    filling_max_degree: int = 3
    filling_tolerance_mm: float = 0.01
    planar_pull_alignment_min: float = 0.90
    filling_max_constraint_edges: int = 120


@dataclass(frozen=True)
class DisplaySettings:
    """
    Frontend rendering limits.

    max_triangle_count
        Hard ceiling on triangles in any display mesh. When the initial
        triangulation exceeds this, `build_display_mesh` re-triangulates with a
        proportionally coarser linear deflection. This prevents unbounded memory
        growth in the Streamlit session state, which stores up to 6 mesh copies
        simultaneously (one per analysis step). Set to 0 to disable.
    """
    max_triangle_count: int = 100_000


@dataclass(frozen=True)
class DFMSettings:
    draft: DraftSettings = DraftSettings()
    direction_search: DirectionSearchSettings = DirectionSearchSettings()
    parting_line: PartingLineSettings = PartingLineSettings()
    parting_line_v2: PartingLineV2Settings = PartingLineV2Settings()
    parting_surface: PartingSurfaceSettings = PartingSurfaceSettings()
    core_cavity: CoreCavitySettings = CoreCavitySettings()
    side_core: SideCoreSettings = SideCoreSettings()
    undercut: UndercutSettings = UndercutSettings()
    display: DisplaySettings = DisplaySettings()


@dataclass(frozen=True)
class AgentModelsSettings:
    gemini: str = "gemini-2.5-flash"
    anthropic: str = "claude-opus-5"
    openai: str = "gpt-4o-mini"
    grok: str = "grok-2-latest"


@dataclass(frozen=True)
class AgentSettings:
    # Stage 5 (2026-07-28): provider-agnostic agent layer, see config.yaml's
    # agent block for the full rationale. `model`/`temperature` alone
    # (pre-Stage-5) is superseded by `provider` + per-provider `models`.
    provider: str = "gemini"  # gemini | anthropic | openai | grok
    temperature: float = 0.1
    max_tool_iterations: int = 8
    max_face_ids_per_tool: int = 25
    models: AgentModelsSettings = AgentModelsSettings()


@dataclass(frozen=True)
class Settings:
    dfm: DFMSettings = DFMSettings()
    agent: AgentSettings = AgentSettings()


def _read_yaml(path: Path) -> dict[str, Any]:
    """
    Read a YAML config file if PyYAML is available.

    The project can still run with defaults when PyYAML is not installed; this
    keeps low-level geometry tests independent from optional app dependencies.
    """
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {}

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _replace_scalars(base_obj: Any, raw: Any) -> Any:
    """
    Override scalar (``bool``/``int``/``float``/``str``) dataclass fields from a
    raw YAML dict, coercing by the field's declared type.

    Used for settings blocks that are entirely scalars — notably
    ``PartingLineV2Settings``, whose ~25 keys would otherwise need ~25
    near-identical ``float(raw.get(...))`` lines. Unknown keys and
    non-coercible values are ignored, matching this module's existing
    "fall back to the default rather than crash" behaviour.

    Note: ``from __future__ import annotations`` makes ``field.type`` a STRING,
    so the comparisons below are against type names, not type objects.
    """
    if not isinstance(raw, dict):
        return base_obj

    coercers = {"bool": bool, "int": int, "float": float, "str": str}
    updates: dict[str, Any] = {}
    for f in dataclass_fields(base_obj):
        if f.name not in raw:
            continue
        coerce = coercers.get(str(f.type))
        if coerce is None:
            continue  # nested dataclass / tuple — handled explicitly by callers
        try:
            updates[f.name] = coerce(raw[f.name])
        except (TypeError, ValueError):
            continue
    return replace(base_obj, **updates) if updates else base_obj


def _tuple3(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    return (float(value[0]), float(value[1]), float(value[2]))


def _condition_pair(
    conditions_raw: dict[str, Any],
    name: str,
    default_good: float,
    default_marginal: float,
) -> tuple[float, float]:
    """Parse one `conditions.<name>: {good, marginal}` entry from config.yaml."""
    entry = conditions_raw.get(name, {})
    if not isinstance(entry, dict):
        return default_good, default_marginal
    return (
        float(entry.get("good", default_good)),
        float(entry.get("marginal", default_marginal)),
    )


def _float_tuple(value: Any, default: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return default
    parsed_values: list[float] = []
    for item in value:
        try:
            parsed = float(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0.0:
            parsed_values.append(parsed)
    parsed = tuple(parsed_values)
    return parsed or default


def _parse_stage2_directions(
    raw: Any,
    default: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], ...]:
    """
    Parse the ``stage2_directions`` list from config.yaml.

    Expects a YAML list of 3-element numeric lists, e.g.::

        stage2_directions:
          - [1, 1, 0]
          - [-1, 1, 0]

    Returns the default when the input is absent, malformed, or empty.
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        return default
    result: list[tuple[float, float, float]] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            try:
                result.append((float(item[0]), float(item[1]), float(item[2])))
            except (TypeError, ValueError):
                continue
    return tuple(result) if result else default


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    """
    Load frozen settings from config.yaml, falling back to production defaults.

    Precedence:
      1. Explicit ``config_path`` argument.
      2. ``DFM_CONFIG`` environment variable.
      3. Repository-level ``config.yaml``.
      4. Dataclass defaults.
    """
    default_path = Path(__file__).resolve().parent.parent / "config.yaml"
    path = Path(config_path or os.environ.get("DFM_CONFIG", default_path))
    raw = _read_yaml(path)

    base = Settings()
    dfm_raw = raw.get("dfm", {}) if isinstance(raw.get("dfm", {}), dict) else {}
    draft_raw = dfm_raw.get("draft", {}) if isinstance(dfm_raw.get("draft", {}), dict) else {}
    direction_raw = (
        dfm_raw.get("direction_search", {})
        if isinstance(dfm_raw.get("direction_search", {}), dict)
        else {}
    )
    core_raw = (
        dfm_raw.get("core_cavity", {})
        if isinstance(dfm_raw.get("core_cavity", {}), dict)
        else {}
    )
    side_core_raw = (
        dfm_raw.get("side_core", {})
        if isinstance(dfm_raw.get("side_core", {}), dict)
        else {}
    )
    parting_raw = (
        dfm_raw.get("parting_line", {})
        if isinstance(dfm_raw.get("parting_line", {}), dict)
        else {}
    )
    parting_v2_raw = (
        dfm_raw.get("parting_line_v2", {})
        if isinstance(dfm_raw.get("parting_line_v2", {}), dict)
        else {}
    )
    undercut_raw = (
        dfm_raw.get("undercut", {})
        if isinstance(dfm_raw.get("undercut", {}), dict)
        else {}
    )
    display_raw = (
        dfm_raw.get("display", {})
        if isinstance(dfm_raw.get("display", {}), dict)
        else {}
    )
    parting_surface_raw = (
        dfm_raw.get("parting_surface", {})
        if isinstance(dfm_raw.get("parting_surface", {}), dict)
        else {}
    )
    agent_raw = raw.get("agent", {}) if isinstance(raw.get("agent", {}), dict) else {}

    conditions_raw = (
        draft_raw.get("conditions", {})
        if isinstance(draft_raw.get("conditions", {}), dict)
        else {}
    )
    base_conditions = base.dfm.draft.conditions
    smooth_good, smooth_marginal = _condition_pair(
        conditions_raw, "smooth", base_conditions.smooth_good_deg, base_conditions.smooth_marginal_deg
    )
    light_texture_good, light_texture_marginal = _condition_pair(
        conditions_raw,
        "light_texture",
        base_conditions.light_texture_good_deg,
        base_conditions.light_texture_marginal_deg,
    )
    heavy_texture_good, heavy_texture_marginal = _condition_pair(
        conditions_raw,
        "heavy_texture",
        base_conditions.heavy_texture_good_deg,
        base_conditions.heavy_texture_marginal_deg,
    )
    deep_rib_good, deep_rib_marginal = _condition_pair(
        conditions_raw, "deep_rib", base_conditions.deep_rib_good_deg, base_conditions.deep_rib_marginal_deg
    )
    conditions = replace(
        base_conditions,
        smooth_good_deg=smooth_good,
        smooth_marginal_deg=smooth_marginal,
        light_texture_good_deg=light_texture_good,
        light_texture_marginal_deg=light_texture_marginal,
        heavy_texture_good_deg=heavy_texture_good,
        heavy_texture_marginal_deg=heavy_texture_marginal,
        deep_rib_good_deg=deep_rib_good,
        deep_rib_marginal_deg=deep_rib_marginal,
    )
    draft = replace(
        base.dfm.draft,
        good_threshold_deg=float(
            draft_raw.get("good_threshold_deg", base.dfm.draft.good_threshold_deg)
        ),
        marginal_threshold_deg=float(
            draft_raw.get("marginal_threshold_deg", base.dfm.draft.marginal_threshold_deg)
        ),
        conditions=conditions,
    )
    direction = replace(
        base.dfm.direction_search,
        angular_step_deg=float(
            direction_raw.get(
                "angular_step_deg", base.dfm.direction_search.angular_step_deg
            )
        ),
        max_candidates=int(
            direction_raw.get("max_candidates", base.dfm.direction_search.max_candidates)
        ),
        prefilter_skip_score_factor=float(
            direction_raw.get(
                "prefilter_skip_score_factor",
                base.dfm.direction_search.prefilter_skip_score_factor,
            )
        ),
        prefilter_survivor_top_count=int(
            direction_raw.get(
                "prefilter_survivor_top_count",
                base.dfm.direction_search.prefilter_survivor_top_count,
            )
        ),
        prefilter_min_boolean_candidates=int(
            direction_raw.get(
                "prefilter_min_boolean_candidates",
                base.dfm.direction_search.prefilter_min_boolean_candidates,
            )
        ),
        prefilter_zero_score_margin=float(
            direction_raw.get(
                "prefilter_zero_score_margin",
                base.dfm.direction_search.prefilter_zero_score_margin,
            )
        ),
        prefilter_low_undercut_area_pct=float(
            direction_raw.get(
                "prefilter_low_undercut_area_pct",
                base.dfm.direction_search.prefilter_low_undercut_area_pct,
            )
        ),
        prefilter_low_bad_area_pct=float(
            direction_raw.get(
                "prefilter_low_bad_area_pct",
                base.dfm.direction_search.prefilter_low_bad_area_pct,
            )
        ),
        prefilter_principal_axis_keep_count=int(
            direction_raw.get(
                "prefilter_principal_axis_keep_count",
                base.dfm.direction_search.prefilter_principal_axis_keep_count,
            )
        ),
        prefilter_uncertainty_score_margin=float(
            direction_raw.get(
                "prefilter_uncertainty_score_margin",
                base.dfm.direction_search.prefilter_uncertainty_score_margin,
            )
        ),
        boolean_refine_top_candidates=int(
            direction_raw.get(
                "boolean_refine_top_candidates",
                base.dfm.direction_search.boolean_refine_top_candidates,
            )
        ),
        boolean_refine_max_faces=int(
            direction_raw.get(
                "boolean_refine_max_faces",
                base.dfm.direction_search.boolean_refine_max_faces,
            )
        ),
        boolean_refine_score_margin=float(
            direction_raw.get(
                "boolean_refine_score_margin",
                base.dfm.direction_search.boolean_refine_score_margin,
            )
        ),
        boolean_interference_weight=float(
            direction_raw.get(
                "boolean_interference_weight",
                base.dfm.direction_search.boolean_interference_weight,
            )
        ),
        boolean_offset_factor=float(
            direction_raw.get(
                "boolean_offset_factor",
                base.dfm.direction_search.boolean_offset_factor,
            )
        ),
        boolean_min_offset_mm=float(
            direction_raw.get(
                "boolean_min_offset_mm",
                base.dfm.direction_search.boolean_min_offset_mm,
            )
        ),
        boolean_max_offset_mm=float(
            direction_raw.get(
                "boolean_max_offset_mm",
                base.dfm.direction_search.boolean_max_offset_mm,
            )
        ),
        boolean_retry_offset_multipliers=_float_tuple(
            direction_raw.get(
                "boolean_retry_offset_multipliers",
                base.dfm.direction_search.boolean_retry_offset_multipliers,
            ),
            base.dfm.direction_search.boolean_retry_offset_multipliers,
        ),
        boolean_sweep_distance_factor=float(
            direction_raw.get(
                "boolean_sweep_distance_factor",
                base.dfm.direction_search.boolean_sweep_distance_factor,
            )
        ),
        boolean_min_sweep_distance_mm=float(
            direction_raw.get(
                "boolean_min_sweep_distance_mm",
                base.dfm.direction_search.boolean_min_sweep_distance_mm,
            )
        ),
        boolean_fuzzy_factor=float(
            direction_raw.get(
                "boolean_fuzzy_factor",
                base.dfm.direction_search.boolean_fuzzy_factor,
            )
        ),
        boolean_max_fuzzy_value_mm=float(
            direction_raw.get(
                "boolean_max_fuzzy_value_mm",
                base.dfm.direction_search.boolean_max_fuzzy_value_mm,
            )
        ),
        boolean_volume_tolerance_factor=float(
            direction_raw.get(
                "boolean_volume_tolerance_factor",
                base.dfm.direction_search.boolean_volume_tolerance_factor,
            )
        ),
        boolean_min_volume_tolerance_mm3=float(
            direction_raw.get(
                "boolean_min_volume_tolerance_mm3",
                base.dfm.direction_search.boolean_min_volume_tolerance_mm3,
            )
        ),
        boolean_min_face_area_mm2=float(
            direction_raw.get(
                "boolean_min_face_area_mm2",
                base.dfm.direction_search.boolean_min_face_area_mm2,
            )
        ),
        boolean_min_face_area_factor=float(
            direction_raw.get(
                "boolean_min_face_area_factor",
                base.dfm.direction_search.boolean_min_face_area_factor,
            )
        ),
        boolean_feature_seed_faces_per_group=int(
            direction_raw.get(
                "boolean_feature_seed_faces_per_group",
                base.dfm.direction_search.boolean_feature_seed_faces_per_group,
            )
        ),
        boolean_grouping_proximity_factor=float(
            direction_raw.get(
                "boolean_grouping_proximity_factor",
                base.dfm.direction_search.boolean_grouping_proximity_factor,
            )
        ),
        boolean_grouping_min_proximity_mm=float(
            direction_raw.get(
                "boolean_grouping_min_proximity_mm",
                base.dfm.direction_search.boolean_grouping_min_proximity_mm,
            )
        ),
        flash_risk_weight=float(
            direction_raw.get(
                "flash_risk_weight", base.dfm.direction_search.flash_risk_weight
            )
        ),
        flash_angle_threshold_deg=float(
            direction_raw.get(
                "flash_angle_threshold_deg",
                base.dfm.direction_search.flash_angle_threshold_deg,
            )
        ),
        flash_thin_area_factor=float(
            direction_raw.get(
                "flash_thin_area_factor",
                base.dfm.direction_search.flash_thin_area_factor,
            )
        ),
        fine_search_enabled=bool(
            direction_raw.get(
                "fine_search_enabled", base.dfm.direction_search.fine_search_enabled
            )
        ),
        fine_search_top_k=int(
            direction_raw.get(
                "fine_search_top_k", base.dfm.direction_search.fine_search_top_k
            )
        ),
        fine_angular_step_deg=float(
            direction_raw.get(
                "fine_angular_step_deg",
                base.dfm.direction_search.fine_angular_step_deg,
            )
        ),
        fine_search_cone_half_angle_deg=float(
            direction_raw.get(
                "fine_search_cone_half_angle_deg",
                base.dfm.direction_search.fine_search_cone_half_angle_deg,
            )
        ),
        fine_search_max_candidates=int(
            direction_raw.get(
                "fine_search_max_candidates",
                base.dfm.direction_search.fine_search_max_candidates,
            )
        ),
        # Milestone 3: hierarchical search
        hierarchical_search_enabled=bool(
            direction_raw.get(
                "hierarchical_search_enabled",
                base.dfm.direction_search.hierarchical_search_enabled,
            )
        ),
        stage2_directions=_parse_stage2_directions(
            direction_raw.get("stage2_directions"),
            base.dfm.direction_search.stage2_directions,
        ),
        suitability_max_bad_draft_pct=float(
            direction_raw.get(
                "suitability_max_bad_draft_pct",
                base.dfm.direction_search.suitability_max_bad_draft_pct,
            )
        ),
        suitability_max_accessibility_risk_pct=float(
            direction_raw.get(
                "suitability_max_accessibility_risk_pct",
                base.dfm.direction_search.suitability_max_accessibility_risk_pct,
            )
        ),
        suitability_max_confirmed_undercut_pct=float(
            direction_raw.get(
                "suitability_max_confirmed_undercut_pct",
                base.dfm.direction_search.suitability_max_confirmed_undercut_pct,
            )
        ),
        # Milestone 4: scoring weights
        scoring_bad_draft=float(
            direction_raw.get(
                "scoring_bad_draft",
                base.dfm.direction_search.scoring_bad_draft,
            )
        ),
        scoring_marginal_draft=float(
            direction_raw.get(
                "scoring_marginal_draft",
                base.dfm.direction_search.scoring_marginal_draft,
            )
        ),
        scoring_accessibility_risk=float(
            direction_raw.get(
                "scoring_accessibility_risk",
                base.dfm.direction_search.scoring_accessibility_risk,
            )
        ),
        scoring_bad_draft_count=float(
            direction_raw.get(
                "scoring_bad_draft_count",
                base.dfm.direction_search.scoring_bad_draft_count,
            )
        ),
        scoring_marginal_draft_count=float(
            direction_raw.get(
                "scoring_marginal_draft_count",
                base.dfm.direction_search.scoring_marginal_draft_count,
            )
        ),
        scoring_accessibility_risk_count=float(
            direction_raw.get(
                "scoring_accessibility_risk_count",
                base.dfm.direction_search.scoring_accessibility_risk_count,
            )
        ),
        scoring_axis_preference=float(
            direction_raw.get(
                "scoring_axis_preference",
                base.dfm.direction_search.scoring_axis_preference,
            )
        ),
        scoring_confirmed_undercut=float(
            direction_raw.get(
                "scoring_confirmed_undercut",
                base.dfm.direction_search.scoring_confirmed_undercut,
            )
        ),
    )
    core_cavity = replace(
        base.dfm.core_cavity,
        threshold=float(
            core_raw.get("threshold", base.dfm.core_cavity.threshold)
        ),
        cavity_color=_tuple3(
            core_raw.get("cavity_color", base.dfm.core_cavity.cavity_color),
            base.dfm.core_cavity.cavity_color,
        ),
        core_color=_tuple3(
            core_raw.get("core_color", base.dfm.core_cavity.core_color),
            base.dfm.core_cavity.core_color,
        ),
        blank_margin_factor=float(
            core_raw.get("blank_margin_factor", base.dfm.core_cavity.blank_margin_factor)
        ),
        solid_split_enabled=bool(
            core_raw.get("solid_split_enabled", base.dfm.core_cavity.solid_split_enabled)
        ),
        export_dir=str(
            core_raw.get("export_dir", base.dfm.core_cavity.export_dir)
        ),
        split_fuzzy_factor=float(
            core_raw.get("split_fuzzy_factor", base.dfm.core_cavity.split_fuzzy_factor)
        ),
        min_solid_volume_fraction=float(
            core_raw.get(
                "min_solid_volume_fraction", base.dfm.core_cavity.min_solid_volume_fraction
            )
        ),
        volume_conservation_tolerance=float(
            core_raw.get(
                "volume_conservation_tolerance", base.dfm.core_cavity.volume_conservation_tolerance
            )
        ),
        split_plane_half_size_factor=float(
            core_raw.get(
                "split_plane_half_size_factor", base.dfm.core_cavity.split_plane_half_size_factor
            )
        ),
    )
    side_core = replace(
        base.dfm.side_core,
        enabled=bool(
            side_core_raw.get("enabled", base.dfm.side_core.enabled)
        ),
        footprint_margin_factor=float(
            side_core_raw.get(
                "footprint_margin_factor", base.dfm.side_core.footprint_margin_factor
            )
        ),
        min_half_size_mm=float(
            side_core_raw.get("min_half_size_mm", base.dfm.side_core.min_half_size_mm)
        ),
        fuzzy_tolerance=float(
            side_core_raw.get("fuzzy_tolerance", base.dfm.side_core.fuzzy_tolerance)
        ),
        volume_conservation_tolerance=float(
            side_core_raw.get(
                "volume_conservation_tolerance",
                base.dfm.side_core.volume_conservation_tolerance,
            )
        ),
        footprint_percentile=float(
            side_core_raw.get("footprint_percentile", base.dfm.side_core.footprint_percentile)
        ),
    )
    parting_line_v2 = _replace_scalars(base.dfm.parting_line_v2, parting_v2_raw)
    parting_line_v2 = replace(
        parting_line_v2,
        tier_epsilon=_replace_scalars(
            base.dfm.parting_line_v2.tier_epsilon,
            parting_v2_raw.get("tier_epsilon", {}),
        ),
    )
    parting_line = replace(
        base.dfm.parting_line,
        engine=str(parting_raw.get("engine", base.dfm.parting_line.engine)).strip().lower(),
        dot_tolerance=float(
            parting_raw.get("dot_tolerance", base.dfm.parting_line.dot_tolerance)
        ),
        boundary_dot_tolerance=float(
            parting_raw.get(
                "boundary_dot_tolerance",
                base.dfm.parting_line.boundary_dot_tolerance,
            )
        ),
        point_tolerance=float(
            parting_raw.get("point_tolerance", base.dfm.parting_line.point_tolerance)
        ),
        smoothing_iterations=int(
            parting_raw.get(
                "smoothing_iterations",
                base.dfm.parting_line.smoothing_iterations,
            )
        ),
        display_resample_min_points=int(
            parting_raw.get(
                "display_resample_min_points",
                base.dfm.parting_line.display_resample_min_points,
            )
        ),
        max_refined_display_points=int(
            parting_raw.get(
                "max_refined_display_points",
                base.dfm.parting_line.max_refined_display_points,
            )
        ),
        refined_curve_color=_tuple3(
            parting_raw.get(
                "refined_curve_color",
                base.dfm.parting_line.refined_curve_color,
            ),
            base.dfm.parting_line.refined_curve_color,
        ),
        raw_curve_color=_tuple3(
            parting_raw.get("raw_curve_color", base.dfm.parting_line.raw_curve_color),
            base.dfm.parting_line.raw_curve_color,
        ),
        bridge_penalty_factor=float(
            parting_raw.get("bridge_penalty_factor", base.dfm.parting_line.bridge_penalty_factor)
        ),
        boundary_bridge_factor=float(
            parting_raw.get("boundary_bridge_factor", base.dfm.parting_line.boundary_bridge_factor)
        ),
        max_closure_error_mm=float(
            parting_raw.get("max_closure_error_mm", base.dfm.parting_line.max_closure_error_mm)
        ),
        max_components_exact_cycle=int(
            parting_raw.get("max_components_exact_cycle", base.dfm.parting_line.max_components_exact_cycle)
        ),
        min_silhouette_coverage_ratio=float(
            parting_raw.get(
                "min_silhouette_coverage_ratio",
                base.dfm.parting_line.min_silhouette_coverage_ratio,
            )
        ),
    )
    undercut = replace(
        base.dfm.undercut,
        convexity_tangent_tolerance=float(
            undercut_raw.get(
                "convexity_tangent_tolerance",
                base.dfm.undercut.convexity_tangent_tolerance,
            )
        ),
        convexity_suppression_enabled=bool(
            undercut_raw.get(
                "convexity_suppression_enabled",
                base.dfm.undercut.convexity_suppression_enabled,
            )
        ),
        accessibility_risk_core_side_threshold=float(
            undercut_raw.get(
                "accessibility_risk_core_side_threshold",
                base.dfm.undercut.accessibility_risk_core_side_threshold,
            )
        ),
    )
    display = replace(
        base.dfm.display,
        max_triangle_count=int(
            display_raw.get("max_triangle_count", base.dfm.display.max_triangle_count)
        ),
    )
    parting_surface = replace(
        base.dfm.parting_surface,
        planar_tolerance_mm=float(
            parting_surface_raw.get("planar_tolerance_mm", base.dfm.parting_surface.planar_tolerance_mm)
        ),
        extension_factor=float(
            parting_surface_raw.get("extension_factor", base.dfm.parting_surface.extension_factor)
        ),
        filling_max_degree=int(
            parting_surface_raw.get("filling_max_degree", base.dfm.parting_surface.filling_max_degree)
        ),
        filling_tolerance_mm=float(
            parting_surface_raw.get("filling_tolerance_mm", base.dfm.parting_surface.filling_tolerance_mm)
        ),
        planar_pull_alignment_min=float(
            parting_surface_raw.get(
                "planar_pull_alignment_min",
                base.dfm.parting_surface.planar_pull_alignment_min,
            )
        ),
        filling_max_constraint_edges=int(
            parting_surface_raw.get(
                "filling_max_constraint_edges",
                base.dfm.parting_surface.filling_max_constraint_edges,
            )
        ),
    )
    dfm = replace(
        base.dfm,
        draft=draft,
        direction_search=direction,
        parting_line=parting_line,
        parting_line_v2=parting_line_v2,
        parting_surface=parting_surface,
        core_cavity=core_cavity,
        side_core=side_core,
        undercut=undercut,
        display=display,
    )
    models_raw = (
        agent_raw.get("models", {}) if isinstance(agent_raw.get("models", {}), dict) else {}
    )
    agent_models = replace(
        base.agent.models,
        gemini=str(models_raw.get("gemini", base.agent.models.gemini)),
        anthropic=str(models_raw.get("anthropic", base.agent.models.anthropic)),
        openai=str(models_raw.get("openai", base.agent.models.openai)),
        grok=str(models_raw.get("grok", base.agent.models.grok)),
    )
    agent = replace(
        base.agent,
        provider=str(agent_raw.get("provider", base.agent.provider)),
        temperature=float(agent_raw.get("temperature", base.agent.temperature)),
        max_tool_iterations=int(
            agent_raw.get("max_tool_iterations", base.agent.max_tool_iterations)
        ),
        max_face_ids_per_tool=int(
            agent_raw.get("max_face_ids_per_tool", base.agent.max_face_ids_per_tool)
        ),
        models=agent_models,
    )
    return replace(base, dfm=dfm, agent=agent)


settings = load_settings()
