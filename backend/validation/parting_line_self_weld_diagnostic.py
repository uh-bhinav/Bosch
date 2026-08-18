"""
backend/validation/parting_line_self_weld_diagnostic.py
------------------------------------------------------
Workstream A1 (2026-08-14). READ-ONLY DIAGNOSTIC. Proves/disproves the
self-closure welding-defect hypothesis:

  `_weld_piece_endpoints` (prototype file) unions a single piece's own two
  endpoints using the EXACT SAME flat pairwise-distance test it uses for
  cross-piece stitching. An OPEN Track-B curve that merely folds close to
  itself (small chord, large path length, but chord still <= the stitch
  tolerance) is therefore indistinguishable, to that function, from a
  genuinely closed/near-degenerate curve -- both get unioned into a
  degree-2 self-loop.

Real instance already traced (Part3, +Y, C_balanced_low, cluster 571):
piece 285 is a Track-B face-backed segment on face 371 (BSpline/NURBS),
genuinely OPEN, path length ~1.09mm, endpoint chord ~0.9312mm
(chord/path ~0.85) -- yet production's welding marks it `is_self_loop=True`
purely because chord (0.9312mm) <= the stitch tolerance.

Nothing in `backend/geometry/parting_line_v2/*` or the shared
`_weld_piece_endpoints` function in the prototype file is modified by this
script. The corrected function (`weld_piece_endpoints_v2`) lives entirely
here and is only ever wired into a real pipeline run via a SCOPED monkeypatch
of `proto._weld_piece_endpoints`, restored immediately after each
measurement (see `_patched_welding`).
"""

from __future__ import annotations

import contextlib
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.validation.parting_line_odd_degree_trace as odd_trace
import backend.validation.parting_line_region_partition_prototype as proto
from backend.validation.parting_line_region_partition_prototype import _dist

REPORTS_DIR = proto.REPORTS_DIR


# ============================================================
# Part A -- the diagnostic two-stage welding function
# ============================================================

def _path_length(points) -> float:
    return sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def weld_piece_endpoints_v2(resolved_pieces, tolerance, *, self_close_ratio_threshold: float = 0.1):
    """
    Same union-find over piece endpoints as production `_weld_piece_endpoints`,
    EXCEPT a piece's own two endpoints (same-piece self-closure) are unioned
    only when there is independent RELATIVE-geometry evidence the piece is
    actually closed/near-degenerate -- not merely spatially close.

    Stage 1 (UNCHANGED from production): cross-piece welding. Any two
    DIFFERENT pieces' endpoints within `tolerance` are unioned exactly as
    production does -- this is the legitimate D-022/D-023 stitching
    behaviour (documented gaps up to 1.05mm) and is not touched.

    Stage 2 (NEW): a piece's own start/end are unioned only if BOTH:
      (a) chord <= tolerance (the existing spatial-closeness gate), AND
      (b) chord / path_length <= self_close_ratio_threshold -- the piece's
          own two ends are close RELATIVE TO HOW FAR THE PIECE ITSELF
          TRAVELS, not just close in absolute terms.

    This is a relative (scale-invariant) criterion, not a new magic
    absolute tolerance: a piece that travels 1mm and ends 0.9mm from its
    own start (ratio 0.9) is refused self-closure identically to one that
    travels 0.001mm and ends 0.0009mm away (same ratio) -- while a piece
    that travels all the way back around to within noise of its own start
    (ratio ~0) self-closes correctly regardless of absolute scale.
    """
    points: list[tuple] = []
    for pts, _backing, _g in resolved_pieces:
        points.append(pts[0])
        points.append(pts[-1])
    n = len(points)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Stage 1: cross-piece only -- identical distance test to production.
    for i in range(n):
        for j in range(i + 1, n):
            if i // 2 == j // 2:
                continue  # same piece -- deferred to Stage 2
            if _dist(points[i], points[j]) <= tolerance:
                union(i, j)

    # Stage 2: same-piece self-closure, gated on relative evidence only.
    for idx, (pts, _backing, _g) in enumerate(resolved_pieces):
        i, j = 2 * idx, 2 * idx + 1
        chord = _dist(pts[0], pts[-1])
        if chord > tolerance:
            continue
        path_length = _path_length(pts)
        ratio = (chord / path_length) if path_length > 0 else 0.0
        if ratio <= self_close_ratio_threshold:
            union(i, j)

    return {i: find(i) for i in range(n)}


@contextlib.contextmanager
def _patched_welding(ratio_threshold: float):
    """Scoped monkeypatch: production module's `_weld_piece_endpoints` name is
    swapped for the diagnostic v2 function for the duration of the `with`
    block only, then restored unconditionally. No file on disk is touched."""
    original = proto._weld_piece_endpoints

    def patched(resolved_pieces, tolerance):
        return weld_piece_endpoints_v2(resolved_pieces, tolerance, self_close_ratio_threshold=ratio_threshold)

    proto._weld_piece_endpoints = patched
    odd_trace.proto._weld_piece_endpoints = patched
    try:
        yield
    finally:
        proto._weld_piece_endpoints = original
        odd_trace.proto._weld_piece_endpoints = original


# ============================================================
# Part B -- synthetic fixtures (pure Python, no OCC needed: welding only
# touches the already-sampled 3-D points, never the backing).
# ============================================================

def _arc_points(radius: float, angle_start_deg: float, angle_end_deg: float, n: int = 9, z: float = 0.0):
    pts = []
    for k in range(n):
        t = angle_start_deg + (angle_end_deg - angle_start_deg) * k / (n - 1)
        rad = math.radians(t)
        pts.append((radius * math.cos(rad), radius * math.sin(rad), z))
    return tuple(pts)


def fixture_open_hook(radius: float = 0.5, covered_deg: float = 110.0, n: int = 9):
    """A. Open curve folding close to itself -- a circular arc covering only
    `covered_deg` of the full circle (genuinely open, substantial path
    length) whose two ends are geometrically close because the arc curls
    back toward its own start. radius=0.5, covered_deg=110 reproduces the
    real Part3 piece-285 regime almost exactly: chord/path ~0.85."""
    pts = _arc_points(radius, 0.0, covered_deg, n=n)
    return [(pts, None, ())]


def fixture_closed_loop(radius: float = 0.5, n: int = 9):
    """B. Genuinely closed curve: full 360deg circle, chord ~0 by construction."""
    pts = _arc_points(radius, 0.0, 360.0, n=n)
    return [(pts, None, ())]


def fixture_near_degenerate_tiny_scale(radius: float = 2e-4, n: int = 9):
    """B2. Same closed-loop topology as fixture_closed_loop but at Part3's
    real near-degenerate absolute scale (~1e-4mm, matching piece 227's
    ~1.5e-4mm sub-arc length) -- proves the ratio criterion is
    SCALE-INVARIANT, unlike a fixed absolute tolerance."""
    pts = _arc_points(radius, 0.0, 360.0, n=n)
    return [(pts, None, ())]


def fixture_cross_piece_gap(gap_mm: float = 0.5):
    """C. Two DIFFERENT pieces whose facing endpoints are separated by a
    realistic Part3-scale gap (D-022 documents 0.043-1.05mm). Must remain
    welded together under the new logic exactly as under production's --
    Stage 1 is untouched by this diagnostic."""
    piece_p = ((0.0, 0.0, 0.0), (1.0, 0.2, 0.0), (2.0, 0.0, 0.0))
    piece_q = ((2.0 + gap_mm, 0.0, 0.0), (3.0, 0.3, 0.0), (4.0, 0.0, 0.0))
    return [(piece_p, None, ()), (piece_q, None, ())]


def _is_self_looped(clusters: dict, idx: int) -> bool:
    return clusters[2 * idx] == clusters[2 * idx + 1]


def run_fixture_tests(tolerance: float = 1.0, ratio_thresholds=(0.05, 0.1, 0.2, 0.3)):
    print("=== Workstream A1 fixture tests ===", flush=True)
    ok = True

    # --- Fixture A: open hook -- production SHOULD incorrectly self-weld it
    #     (proves the defect exists); v2 must NOT self-weld it at any
    #     reasonable ratio threshold (proves the fix + its robustness). ---
    hook = fixture_open_hook()
    pts = hook[0][0]
    chord = _dist(pts[0], pts[-1])
    path = _path_length(pts)
    ratio = chord / path
    assert chord <= tolerance, "fixture A must be spatially close enough to trigger the defect"
    old_clusters = proto._weld_piece_endpoints(hook, tolerance)
    old_self_looped = _is_self_looped(old_clusters, 0)
    defect_reproduced = old_self_looped
    print(f"Fixture A (open hook): chord={chord:.6f}mm path={path:.6f}mm ratio={ratio:.4f} "
          f"tolerance={tolerance}mm", flush=True)
    print(f"  PRODUCTION _weld_piece_endpoints: self_loop={old_self_looped} "
          f"{'(DEFECT REPRODUCED -- incorrectly self-welds an open curve)' if old_self_looped else '(no defect on this fixture)'}",
          flush=True)
    for thr in ratio_thresholds:
        new_clusters = weld_piece_endpoints_v2(hook, tolerance, self_close_ratio_threshold=thr)
        new_self_looped = _is_self_looped(new_clusters, 0)
        verdict = "CORRECT (no self-weld)" if not new_self_looped else "WRONG"
        print(f"  v2 (ratio_threshold={thr}): self_loop={new_self_looped} {verdict}", flush=True)
        if new_self_looped:
            ok = False

    # --- Fixture B: closed loop -- MUST self-weld under v2 at every threshold. ---
    closed = fixture_closed_loop()
    pts_b = closed[0][0]
    chord_b = _dist(pts_b[0], pts_b[-1])
    path_b = _path_length(pts_b)
    print(f"Fixture B (closed loop): chord={chord_b:.3e}mm path={path_b:.6f}mm ratio={chord_b / path_b:.3e}",
          flush=True)
    for thr in ratio_thresholds:
        new_clusters = weld_piece_endpoints_v2(closed, tolerance, self_close_ratio_threshold=thr)
        new_self_looped = _is_self_looped(new_clusters, 0)
        verdict = "CORRECT (self-welds)" if new_self_looped else "WRONG"
        print(f"  v2 (ratio_threshold={thr}): self_loop={new_self_looped} {verdict}", flush=True)
        if not new_self_looped:
            ok = False

    # --- Fixture B2: same topology, real near-degenerate absolute scale. ---
    tiny = fixture_near_degenerate_tiny_scale()
    pts_t = tiny[0][0]
    chord_t = _dist(pts_t[0], pts_t[-1])
    path_t = _path_length(pts_t)
    tiny_tolerance = 1e-3
    print(f"Fixture B2 (tiny-scale closed loop, matches piece-227 order of magnitude): "
          f"chord={chord_t:.3e}mm path={path_t:.3e}mm", flush=True)
    for thr in ratio_thresholds:
        new_clusters = weld_piece_endpoints_v2(tiny, tiny_tolerance, self_close_ratio_threshold=thr)
        new_self_looped = _is_self_looped(new_clusters, 0)
        verdict = "CORRECT (self-welds)" if new_self_looped else "WRONG"
        print(f"  v2 (ratio_threshold={thr}, tol={tiny_tolerance}): self_loop={new_self_looped} {verdict}",
              flush=True)
        if not new_self_looped:
            ok = False

    # --- Fixture C: cross-piece welding must be BYTE-IDENTICAL to production. ---
    for gap in (0.043, 0.5, 1.05):
        cross = fixture_cross_piece_gap(gap_mm=gap)
        cross_tolerance = 1.2
        old_clusters = proto._weld_piece_endpoints(cross, cross_tolerance)
        new_clusters = weld_piece_endpoints_v2(cross, cross_tolerance, self_close_ratio_threshold=0.1)
        old_cross_welded = old_clusters[1] == old_clusters[2]
        new_cross_welded = new_clusters[1] == new_clusters[2]
        match = old_cross_welded == new_cross_welded
        print(f"Fixture C (cross-piece gap={gap}mm): OLD_welded={old_cross_welded} "
              f"NEW_welded={new_cross_welded} {'MATCH' if match else 'MISMATCH'}", flush=True)
        if not match or not new_cross_welded:
            ok = False

    print(f"\nFixture suite: {'ALL PASS' if ok else 'FAILURE'} (defect_reproduced_on_fixture_A={defect_reproduced})",
          flush=True)
    return ok, defect_reproduced


# ============================================================
# Part C -- full-pipeline regression: OLD vs NEW welding, real parts.
# ============================================================

def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


GOLDEN_PART1_PLUS_Z = {
    "cavity_face_count": 42, "core_face_count": 269,
    "cavity_area_mm2": 362.338, "core_area_mm2": 1203.814,
    "h3_region_count": 2.0, "h4_orientation_violation_fraction": 0.0,
    "h7_coverage": 0.9991608536203086,
    "is_single_continuous_loop": True, "h1_closure_error_mm": 0.0,
}


def _fingerprint(r: dict) -> dict:
    fr = r["feasibility"]
    areas = r.get("region_areas") or {}
    return {
        "cavity_face_count": r["cavity_face_count"], "core_face_count": r["core_face_count"],
        "cavity_area_mm2": areas.get("cavity_area_mm2"), "core_area_mm2": areas.get("core_area_mm2"),
        "h3_region_count": fr["measurements"].get("h3_region_count"),
        "h4_orientation_violation_fraction": fr["measurements"].get("h4_orientation_violation_fraction"),
        "h7_coverage": fr["measurements"].get("h7_coverage"),
        "is_single_continuous_loop": r["is_single_continuous_loop"],
        "h1_closure_error_mm": fr["measurements"].get("h1_closure_error_mm"),
        "outcome": fr["outcome"], "failed_gate": fr["failed_gate"],
    }


def _obj_result(result: dict, obj_name: str):
    return next((r for r in result["results"] if r.get("objective") == obj_name), None)


def run_part1_regression(part1, cfg, undercuts, *, ratio_threshold: float = 0.1):
    print("\n########## WORKSTREAM A1 -- Part1 +Z/+X regression, OLD vs NEW welding ##########", flush=True)
    all_match = True
    golden_match = None
    for direction, label in [(unit((0, 0, 1)), "+Z"), (unit((1, 0, 0)), "+X")]:
        old_result = proto.run_experiment_nway_subedge(part1, direction, "Part1", label, cfg, undercuts)
        with _patched_welding(ratio_threshold):
            new_result = proto.run_experiment_nway_subedge(part1, direction, "Part1", label, cfg, undercuts)
        for obj_name in proto.OBJECTIVES:
            old_r = _obj_result(old_result, obj_name)
            new_r = _obj_result(new_result, obj_name)
            if (old_r is None or new_r is None or "error" in old_r or "error" in new_r
                    or old_r.get("degenerate_cut") or new_r.get("degenerate_cut")):
                print(f"  Part1 {label} / {obj_name}: OLD_or_NEW unusable "
                      f"(old={'error:' + old_r['error'] if old_r and 'error' in old_r else 'degenerate' if old_r and old_r.get('degenerate_cut') else 'missing' if not old_r else 'ok'}, "
                      f"new={'error:' + new_r['error'] if new_r and 'error' in new_r else 'degenerate' if new_r and new_r.get('degenerate_cut') else 'missing' if not new_r else 'ok'})",
                      flush=True)
                continue
            old_fp = _fingerprint(old_r)
            new_fp = _fingerprint(new_r)
            match = old_fp == new_fp
            all_match = all_match and match
            print(f"  Part1 {label} / {obj_name}: {'IDENTICAL' if match else 'DIFFERS'}", flush=True)
            if not match:
                for k in old_fp:
                    if old_fp[k] != new_fp[k]:
                        print(f"      {k}: old={old_fp[k]!r} new={new_fp[k]!r}", flush=True)
            if label == "+Z" and obj_name == "C_balanced_low":
                golden_check = {k: new_fp[k] for k in GOLDEN_PART1_PLUS_Z}
                golden_match = golden_check == GOLDEN_PART1_PLUS_Z
                print(f"      vs GOLDEN fingerprint: {'MATCH' if golden_match else 'MISMATCH'}", flush=True)
                if not golden_match:
                    for k in GOLDEN_PART1_PLUS_Z:
                        if golden_check[k] != GOLDEN_PART1_PLUS_Z[k]:
                            print(f"        {k}: golden={GOLDEN_PART1_PLUS_Z[k]!r} new={golden_check[k]!r}", flush=True)
    print(f"\nPart1 regression: {'ALL IDENTICAL (old vs new)' if all_match else 'SOME DIFFERENCES'}, "
          f"golden +Z/C_balanced_low fingerprint {'MATCHES' if golden_match else 'DOES NOT MATCH'}", flush=True)
    return all_match, golden_match


def _odd_degree_stats(part, direction_tuple, label, cfg, ratio_threshold=None):
    """Odd-vertex count/classification + component stats for ONE direction at
    C_balanced_low, under either production (ratio_threshold=None) or v2
    welding (patched)."""
    ctx = _patched_welding(ratio_threshold) if ratio_threshold is not None else contextlib.nullcontext()
    with ctx:
        odd = odd_trace.run_direction(part, direction_tuple, cfg, None, label)
    tally: dict[str, int] = {}
    for v in odd:
        cls = odd_trace.classify(v)
        tally[cls] = tally.get(cls, 0) + 1
    return odd, tally


def run_part3_comparison(part3, cfg, undercuts, *, ratio_threshold: float = 0.1):
    print("\n########## WORKSTREAM A1 -- Part3, OLD vs NEW welding ##########", flush=True)
    az15 = unit((math.cos(math.radians(15)), math.sin(math.radians(15)), 0.0))
    directions = [
        (az15, "az15"), (unit((0, 1, 1)), "(0,1,1)"),
        (unit((1, 0, 0)), "+X"), (unit((-1, 0, 0)), "-X"), (unit((0, 1, 0)), "+Y"),
    ]

    print("\n--- Odd-degree vertex counts (C_balanced_low), OLD vs NEW ---", flush=True)
    for direction, label in directions:
        old_odd, old_tally = _odd_degree_stats(part3, direction, label, cfg, ratio_threshold=None)
        new_odd, new_tally = _odd_degree_stats(part3, direction, label, cfg, ratio_threshold=ratio_threshold)
        print(f"  {label}: OLD odd_count={len(old_odd)} tally={old_tally}", flush=True)
        print(f"  {label}: NEW odd_count={len(new_odd)} tally={new_tally}", flush=True)

    # Specifically re-check the previously-identified real instance:
    # +Y @ C_balanced_low, piece 285 (cluster 571).
    print("\n--- Direct re-check: is piece 285 (+Y, C_balanced_low) still self-welded? ---", flush=True)
    direction_y = unit((0, 1, 0))
    bbox_diag = proto._bbox_diagonal(part3)
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.parting_line_v2.types import EdgeBacking as _EdgeBacking

    direction = PullDirectionInput(direction_y, "manual").direction
    track_a = detect_edge_silhouettes(part3, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments if s.kind == "silhouette" and isinstance(s.backing, _EdgeBacking)
    )
    track_b = detect_face_silhouettes(part3, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag,
                                       start_segment_id=len(track_a.segments))
    unary_w, smooth_w, discount = proto.OBJECTIVES["C_balanced_low"]
    cut = proto.build_min_cut_partition_nway_subedge(
        part3, direction, track_b.segments, silhouette_edge_ids,
        unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount,
    )
    resolved = [proto._resolve_piece_geometry(part3, p) for p in cut["cut_pieces"]]
    weld_cell = max(cfg.stitch_snap_tolerance_rel * bbox_diag, 1e-6)
    piece_285 = resolved[285] if len(resolved) > 285 else None
    if piece_285 is not None:
        pts, backing, _g = piece_285
        chord = _dist(pts[0], pts[-1])
        path = _path_length(pts)
        print(f"  piece 285: kind={cut['cut_pieces'][285].get('kind')} chord={chord:.4f}mm path={path:.4f}mm "
              f"ratio={chord / path:.4f} weld_cell={weld_cell:.4f}mm", flush=True)
        old_clusters = proto._weld_piece_endpoints(resolved, weld_cell)
        new_clusters = weld_piece_endpoints_v2(resolved, weld_cell, self_close_ratio_threshold=ratio_threshold)
        print(f"  OLD: self_loop={_is_self_looped(old_clusters, 285)}", flush=True)
        print(f"  NEW: self_loop={_is_self_looped(new_clusters, 285)}", flush=True)
    else:
        print(f"  piece index 285 not present in this run ({len(resolved)} pieces total) -- "
              f"cut-piece indexing may have shifted since the original trace; reporting count only.", flush=True)

    print("\n--- Full gate outcomes (all 5 objectives), OLD vs NEW ---", flush=True)
    for direction_tuple, label in directions:
        old_result = proto.run_experiment_nway_subedge(part3, direction_tuple, "Part3", label, cfg, undercuts)
        with _patched_welding(ratio_threshold):
            new_result = proto.run_experiment_nway_subedge(part3, direction_tuple, "Part3", label, cfg, undercuts)
        for obj_name in proto.OBJECTIVES:
            old_r = _obj_result(old_result, obj_name)
            new_r = _obj_result(new_result, obj_name)

            def _line(tag, r):
                if r is None:
                    return f"    {tag} {obj_name:22s} MISSING"
                if "error" in r:
                    return f"    {tag} {obj_name:22s} ERROR: {r['error']}"
                if r.get("degenerate_cut"):
                    return f"    {tag} {obj_name:22s} degenerate cut"
                fr = r["feasibility"]
                areas = r.get("region_areas") or {}
                return (f"    {tag} {obj_name:22s} outcome={fr['outcome']:10s} failed_gate={str(fr['failed_gate']):5s} "
                        f"loops={r['loop_count']} cavity={r['cavity_face_count']} core={r['core_face_count']} "
                        f"cavity_mm2={areas.get('cavity_area_mm2')} core_mm2={areas.get('core_area_mm2')} "
                        f"h1={fr['measurements'].get('h1_closure_error_mm')} h3={fr['measurements'].get('h3_region_count')} "
                        f"h4={fr['measurements'].get('h4_orientation_violation_fraction')} "
                        f"h7={fr['measurements'].get('h7_coverage')}")

            print(f"  {label}:", flush=True)
            print(_line("OLD", old_r), flush=True)
            print(_line("NEW", new_r), flush=True)


def main():
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.step_loader import load_step_cached

    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()

    ok, defect_reproduced = run_fixture_tests()
    if not ok:
        print("\nFIXTURE SUITE FAILED -- stopping before touching real parts.", flush=True)
        return
    if not defect_reproduced:
        print("\nDefect NOT reproduced on the synthetic fixture -- hypothesis may be falsified. "
              "Proceeding to real-part checks anyway for completeness, but treat results skeptically.", flush=True)

    print("\nLoading Part1.stp / Part3.stp ...", flush=True)
    part1 = load_step_cached("data/parts/Part1.stp")
    part3 = load_step_cached("data/parts/Part3.stp")

    all_match, golden_match = run_part1_regression(part1, cfg, undercuts)
    run_part3_comparison(part3, cfg, undercuts)

    print("\n\n========== A1 SUMMARY ==========", flush=True)
    print(f"Fixture suite: {'PASS' if ok else 'FAIL'}", flush=True)
    print(f"Defect reproduced on synthetic fixture A: {defect_reproduced}", flush=True)
    print(f"Part1 old-vs-new fingerprint identical across both directions/all objectives: {all_match}", flush=True)
    print(f"Part1 +Z/C_balanced_low golden fingerprint preserved: {golden_match}", flush=True)


if __name__ == "__main__":
    main()
