#!/usr/bin/env python
"""
scripts/generate_fixtures.py
----------------------------
Generate the synthetic fixture corpus for the v2 parting-line engine (plan P0).

Writes STEP files plus a ``manifest.json`` to ``data/fixtures/synthetic/``.

**``data/parts/`` is never touched** — CLAUDE.md invariant #2. These fixtures
live in their own directory precisely so the two real Bosch parts stay
read-only inputs.

Design principle (plan §12 P0): these are **not** "some CAD models". Each one
targets a specific algorithmic failure mode and has a checkable answer — either
an analytic closed form (§4.1) or a stated structural property. The corpus is
what lets P1 vs P2 vs P3 be compared on evidence rather than impression.

Run with the OCC-capable interpreter::

    .micromamba/root/envs/dfm_agent/bin/python scripts/generate_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cadquery as cq


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "synthetic"

#: Guard: this script must never be able to write into the read-only fixtures.
FORBIDDEN_DIR = Path(__file__).resolve().parent.parent / "data" / "parts"


@dataclass
class Fixture:
    """One synthetic fixture and everything the harness needs to judge it."""

    fixture_id: str
    name: str
    pull_direction: tuple[float, float, float]
    targets: str
    expected: str
    #: What P1 (Level 0, Track A only) should do. "pass" = find the correct
    #: loop; "fail_loudly" = there is no edge-based silhouette, so Level 0 must
    #: report no feasible candidate rather than invent a plausible wrong one.
    p1_expectation: str
    #: True when the silhouette has a closed-form answer (plan §4.1) that a
    #: test can check numerically rather than by eye.
    analytic: bool
    notes: str = ""
    filename: str = ""
    stats: dict = field(default_factory=dict)


def _cube() -> tuple[cq.Workplane, Fixture]:
    solid = cq.Workplane("XY").box(40, 40, 40)
    return solid, Fixture(
        fixture_id="F1",
        name="cube",
        pull_direction=(0, 0, 1),
        targets="planar sharp edges only; many-equal-optima; determinism",
        expected=(
            "Top face g=+1, bottom g=-1, four side faces g=0 (zero-draft band). "
            "Every horizontal ring around the sides is a valid parting line — an "
            "infinite family of equal optima. Track A ground truth."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "The engine must DETECT the degeneracy and break the tie "
            "deterministically, not present one ring as 'the' answer."
        ),
    )


def _cylinder_parallel() -> tuple[cq.Workplane, Fixture]:
    solid = cq.Workplane("XY").circle(15).extrude(40)
    return solid, Fixture(
        fixture_id="F2",
        name="cylinder_axis_parallel_to_pull",
        pull_direction=(0, 0, 1),
        targets="degenerate zero-draft band (plan §4.3, §5.3)",
        expected=(
            "d is parallel to the cylinder axis, so R=sqrt(a^2+b^2)=0 and "
            "g == 0 over the ENTIRE lateral face. There is no unique silhouette "
            "curve; every circumferential ring is equally valid."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "This is the case from the study notes' cylinder sketch. The "
            "circumferential 'parting line' drawn there is NOT a silhouette "
            "curve — it is a free choice on a zero-draft surface. The engine "
            "must report the band and its free parameter, not invent a curve."
        ),
    )


def _cylinder_perpendicular() -> tuple[cq.Workplane, Fixture]:
    # Axis along X, pull along +Z.
    solid = cq.Workplane("YZ").circle(15).extrude(60)
    return solid, Fixture(
        fixture_id="F3",
        name="cylinder_axis_perpendicular_to_pull",
        pull_direction=(0, 0, 1),
        targets=(
            "STAR: cylindrical face-interior silhouette. "
            "Track A provably fails, Track B provably passes."
        ),
        expected=(
            "n(u) = cos(u)*x + sin(u)*y is independent of v, so g(u) = R*cos(u-phi) "
            "with R=sqrt(a^2+b^2), phi=atan2(b,a). g=0 at u = phi +/- pi/2 — exactly "
            "TWO STRAIGHT RULINGS on the SIDES of the lateral surface, at "
            "y = +/-15, z = 0, running the full length in x. (Corrected "
            "2026-08-09: an earlier draft said z = +/-15, which is exactly "
            "wrong -- there the normal is (0,0,+/-1) so g = +/-1, the EXTREME. "
            "The zero is where the normal is (0,+/-1,0), i.e. the sides.) "
            "Both flat end caps have normal (+/-1,0,0) so g == 0 over their "
            "whole area: they are zero-draft bands, not curves."
        ),
        p1_expectation="fail_loudly",
        analytic=True,
        notes=(
            "THE A/B fixture for the whole architecture. The two rulings are "
            "interior isoparametric curves, not B-Rep edges, so an edge-only "
            "detector cannot see them. P1 must report 'no feasible candidate', "
            "NOT a plausible-looking wrong loop."
        ),
    )


def _sphere() -> tuple[cq.Workplane, Fixture]:
    solid = cq.Workplane("XY").sphere(20)
    return solid, Fixture(
        fixture_id="F4",
        name="sphere",
        pull_direction=(0, 0, 1),
        targets="Track B on a face with no usable edges at all",
        expected=(
            "n = (p-C)/r, so g = (p-C).d/r = 0 exactly on the GREAT CIRCLE "
            "perpendicular to d: the circle z=0, radius 20."
        ),
        p1_expectation="fail_loudly",
        analytic=True,
        notes=(
            "A sphere has essentially no topological edges beyond the "
            "parameterisation seam, so Track A has nothing to work with. The "
            "answer is entirely a face-interior curve."
        ),
    )


def _cone() -> tuple[cq.Workplane, Fixture]:
    solid = cq.Workplane("XY").add(cq.Solid.makeCone(20.0, 5.0, 40.0))
    return solid, Fixture(
        fixture_id="F5",
        name="cone",
        pull_direction=(0, 0, 1),
        targets="plan §4.1 cone closed form, including the no-solution case",
        expected=(
            "n(u) = cos(alpha)*(cos u * x + sin u * y) - sin(alpha)*axis, so "
            "g(u) = cos(alpha)*R*cos(u-phi) - sin(alpha)*c. With d parallel to the "
            "cone axis: a=b=0 so R=0, c=1, giving g = -sin(alpha) = const != 0 — "
            "NO interior silhouette. The silhouette is the base rim edge only."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "MEASURED at P1: passes, coverage 99.4%, selected loop = the base rim. "
            "Deliberately the DEGENERATE branch of the cone formula: "
            "|tan(alpha)*c/R| -> infinity > 1, so no ruling solution exists. "
            "Tests that Track B correctly finds NOTHING here rather than "
            "producing noise, and that Track A picks up the rim."
        ),
    )


def _filleted_box() -> tuple[cq.Workplane, Fixture]:
    solid = cq.Workplane("XY").box(40, 40, 20).edges(">Z").fillet(5)
    return solid, Fixture(
        fixture_id="F6",
        name="filleted_box",
        pull_direction=(0, 0, 1),
        targets="STAR: fillet faces — silhouette runs ACROSS a blend",
        expected=(
            "The top edges are replaced by constant-radius blends. A blend is "
            "locally cylindrical (straight runs) or toroidal (corners), so the "
            "g=0 curve lies in the blend's INTERIOR where the surface turns from "
            "up-facing to vertical — checkable against plan §4.1's cylinder and "
            "torus forms."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "EXPECTATION CORRECTED 2026-08-09 after P1 measured it. This was "
            "predicted to need Track B; it does NOT. The top fillets span "
            "g in [0, 1] -- from the vertical side wall to the horizontal top -- "
            "so g only TOUCHES zero at the fillet/side-wall edge and never "
            "crosses inside the face. Track A finds that edge, and the bottom rim "
            "is a genuinely valid parting line because the side walls are "
            "vertical. Measured: feasible, coverage 99.1%. The a-priori error was "
            "assuming 'has curved faces' implies 'needs Track B'; the real "
            "criterion is whether g CHANGES SIGN inside a face. See F17, added to "
            "cover the case this one does not."
        ),
    )


def _spline_lid() -> tuple[cq.Workplane, Fixture]:
    solid = (
        cq.Workplane("XY")
        .rect(40, 30)
        .workplane(offset=20)
        .ellipse(12, 8)
        .loft()
    )
    return solid, Fixture(
        fixture_id="F7",
        name="spline_lofted_lid",
        pull_direction=(0, 0, 1),
        targets="STAR: pure marching-squares path (plan §4.2)",
        expected=(
            "A lofted rect->ellipse side surface has NO closed form. Ground truth "
            "is a dense 1024^2 reference extraction with tight Newton tolerance, "
            "frozen once; the production adaptive-grid result must agree with it "
            "to within tau_sag."
        ),
        p1_expectation="pass",
        analytic=False,
        notes=(
            "EXPECTATION CORRECTED 2026-08-09 after P1 measured it. All five "
            "lofted side faces have g_centroid in [0.33, 0.44] -- strictly "
            "positive, a monotone inward slope -- so g never changes sign and the "
            "silhouette is exactly the bottom rim, which Track A finds. Measured: "
            "feasible, coverage 100.0%. It therefore does NOT exercise the "
            "marching-squares path it was built for; F17 does. Kept as a "
            "free-form-geometry robustness case."
        ),
    )


def _box_with_boss() -> tuple[cq.Workplane, Fixture]:
    solid = (
        cq.Workplane("XY").box(40, 40, 20)
        .faces(">Z").workplane().circle(6).extrude(10)
    )
    return solid, Fixture(
        fixture_id="F8",
        name="box_with_boss",
        pull_direction=(0, 0, 1),
        targets="local-feature rejection (the Bug-H failure mode)",
        expected=(
            "Two closed loops exist: the box's outer rim and the boss's base "
            "rim. The outer rim is the parting line. The boss rim is a LOCAL "
            "FEATURE and must lose on T1 coverage."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "v1 selected the tidiest loop rather than the largest until Bug H "
            "was fixed on 2026-07-27 (Part1 coverage 27.6% -> 94.8%). This "
            "fixture makes that regression impossible to reintroduce silently."
        ),
    )


def _box_with_hole() -> tuple[cq.Workplane, Fixture]:
    solid = (
        cq.Workplane("XY").box(40, 40, 20)
        .faces(">Z").workplane().hole(12)
    )
    return solid, Fixture(
        fixture_id="F9",
        name="box_with_through_hole",
        pull_direction=(0, 0, 1),
        targets="multiple GENUINE competing loops — both feasible, ranking decides",
        expected=(
            "Outer rim and hole rim are BOTH feasible closed separating loops. "
            "The outer rim wins on T1 coverage. The hole rim must be retained in "
            "the scorecard as a feasible runner-up, not silently dropped."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "Distinguishes 'rejected' from 'ranked lower' — a distinction v1's "
            "fused feasibility/score cannot express (audit RC-4)."
        ),
    )


def _t_junction_rib() -> tuple[cq.Workplane, Fixture]:
    base = cq.Workplane("XY").box(40, 40, 10)
    rib = (
        cq.Workplane("XY")
        .center(0, 10)
        .box(4, 20, 20, centered=(True, True, False))
        .translate((0, 0, 5))
    )
    return base.union(rib), Fixture(
        fixture_id="F10",
        name="t_junction_rib",
        pull_direction=(0, 0, 1),
        targets="STAR: branches — a real topological branch node",
        expected=(
            "The rib meets the outer wall, so the silhouette graph has a genuine "
            "T-junction: a branch node that SURVIVES 2-core reduction and "
            "degree-2 contraction (plan §5.4)."
        ),
        p1_expectation="pass",
        analytic=False,
        notes=(
            "Distinguishes a REAL topological branch from tolerance noise. Plan "
            "§5.4 requires reporting which of four causes produced each surviving "
            "branch node; only the real-branch case is an optimization question."
        ),
    )


def _alternating_pockets() -> tuple[cq.Workplane, Fixture]:
    solid = cq.Workplane("XY").box(60, 30, 30)
    # Cut pockets from alternating sides at alternating heights so the
    # silhouette breaks into disconnected pieces.
    for i, x in enumerate((-20, -7, 6, 19)):
        y_sign = 1 if i % 2 == 0 else -1
        z = 6 if i % 2 == 0 else 18
        cutter = (
            cq.Workplane("XY")
            .box(8, 14, 8)
            .translate((x, y_sign * 10, z - 15))
        )
        solid = solid.cut(cutter)
    return solid, Fixture(
        fixture_id="F11",
        name="alternating_draft_pockets",
        pull_direction=(0, 0, 1),
        targets="STAR: disconnected candidates — the Part3 failure mode, small",
        expected=(
            "Pockets cut from alternating sides at alternating heights fragment "
            "the silhouette into 3+ disconnected pieces."
        ),
        p1_expectation="pass",
        analytic=False,
        notes=(
            "Part3's real failure (22 components, 18.1% coverage) reproduced at a "
            "size a human can reason about. The P1 baseline records the component "
            "count; P2 must reduce it, and if it does not, the RC-1 hypothesis is "
            "wrong and we stop and re-diagnose."
        ),
    )


def _draft_free_rib() -> tuple[cq.Workplane, Fixture]:
    base = cq.Workplane("XY").box(40, 40, 8)
    rib = (
        cq.Workplane("XY")
        .box(4, 30, 24, centered=(True, True, False))
        .translate((0, 0, 4))
    )
    return base.union(rib), Fixture(
        fixture_id="F12",
        name="draft_free_rib",
        pull_direction=(0, 0, 1),
        targets="zero-draft band collapse (plan §5.3)",
        expected=(
            "The rib's side walls are exactly vertical: g == 0 over their whole "
            "area. The band must be collapsed to a single medial curve with its "
            "span reported, NOT emitted as two parallel boundary loops."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "The parting line's position WITHIN this band is a genuine free "
            "parameter. Report it as such; optimizing within it is Level 3, "
            "which is out of scope for this milestone."
        ),
    )


def _peanut() -> tuple[cq.Workplane, Fixture]:
    left = cq.Workplane("XY").center(-14, 0).circle(14).extrude(20)
    right = cq.Workplane("XY").center(14, 0).circle(14).extrude(20)
    waist = cq.Workplane("XY").box(28, 12, 20, centered=(True, True, False))
    return left.union(right).union(waist), Fixture(
        fixture_id="F13",
        name="peanut_two_lobed",
        pull_direction=(0, 0, 1),
        targets="STAR: non-convex outline — bbox coverage LIES here, §8.1 must not",
        expected=(
            "A strongly non-convex projected outline. v1's bbox-ratio coverage "
            "scores this the same as a rectangle of equal extent. The shoelace "
            "numerator plus a proper projected-outline denominator must not."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "Also quantifies the A_cauchy overestimate (plan §8.1) against a "
            "shape whose true projected area is computable in closed form: two "
            "circles of r=14 at x=+/-14 unioned with a 28x12 waist."
        ),
    )


def _mirror_symmetric() -> tuple[cq.Workplane, Fixture]:
    solid = cq.Workplane("XY").box(40, 40, 20)
    for x in (-12, 12):
        boss = (
            cq.Workplane("XY")
            .center(x, 0)
            .circle(5)
            .extrude(8)
            .translate((0, 0, 10))
        )
        solid = solid.union(boss)
    return solid, Fixture(
        fixture_id="F14",
        name="mirror_symmetric",
        pull_direction=(0, 0, 1),
        targets="determinism under EXACT ties (plan §8.3)",
        expected=(
            "Two identical bosses mirrored about x=0 produce two exactly "
            "equivalent local loops. Every ranking tier ties; T7's stable_id must "
            "break it, and must break it the SAME WAY on every run."
        ),
        p1_expectation="pass",
        analytic=True,
        notes=(
            "Regression test for §8.3: run twice, assert identical stable_id and "
            "identical point list. Catches set-iteration-order dependence, which "
            "is the usual source of non-determinism in graph code."
        ),
    )


def _barrel() -> tuple[cq.Workplane, Fixture]:
    """
    A barrel (bulged revolve), pulled along its own axis.

    Added 2026-08-09 after P1 measured that NO existing fixture actually
    exercised Track B's marching-squares path — see this fixture's ``notes``.
    """
    solid = (
        cq.Workplane("XY")
        .circle(10)
        .workplane(offset=20).circle(16)
        .workplane(offset=20).circle(10)
        .loft()
    )
    return solid, Fixture(
        fixture_id="F17",
        name="barrel_bulged_loft",
        pull_direction=(0, 0, 1),
        targets="STAR: free-form face whose g CROSSES zero in its INTERIOR",
        expected=(
            "A single BSpline side face lofted r=10 -> 16 -> 10. Its radius is "
            "maximal at mid-height, where the outward normal is exactly horizontal "
            "and g = 0: a silhouette CIRCLE strictly inside the face. Below it "
            "g < 0, above it g > 0 — a genuine SIGN CHANGE across the face, not a "
            "touch at its boundary. By the loft's symmetry the crossing lies at "
            "z = 20, radius ~16."
        ),
        p1_expectation="fail_loudly",
        analytic=False,
        notes=(
            "Added 2026-08-09 to fix a real gap found by P1 measurement: NO other "
            "fixture actually exercised Track B. F6's fillets span g in [0,1] and "
            "F7's loft faces are all g>0, so both only TOUCH zero at a face "
            "BOUNDARY, where Track A already finds an edge — the a-priori error "
            "was assuming 'has curved faces' implies 'needs Track B', when the "
            "real criterion is whether g CHANGES SIGN inside a face. "
            "This one cannot be answered by any edge test at all: no B-Rep edge "
            "lies anywhere near the correct curve. Ground truth is the symmetry "
            "argument plus a dense-grid reference, so it is a numerical "
            "convergence test, not an analytic one."
        ),
    )


BUILDERS = [
    _cube, _cylinder_parallel, _cylinder_perpendicular, _sphere, _cone,
    _filleted_box, _spline_lid, _box_with_boss, _box_with_hole,
    _t_junction_rib, _alternating_pockets, _draft_free_rib, _peanut,
    _mirror_symmetric, _barrel,
]


def main() -> int:
    resolved_out = OUTPUT_DIR.resolve()
    if resolved_out == FORBIDDEN_DIR.resolve() or FORBIDDEN_DIR.resolve() in resolved_out.parents:
        print("REFUSED: output directory is inside data/parts/ (CLAUDE.md invariant #2).")
        return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fixtures: list[Fixture] = []
    failures: list[str] = []

    for builder in BUILDERS:
        try:
            solid, meta = builder()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{builder.__name__}: build failed: {exc}")
            continue

        meta.filename = f"{meta.fixture_id}_{meta.name}.stp"
        path = OUTPUT_DIR / meta.filename
        try:
            shape = solid.val()
            bbox = shape.BoundingBox()
            meta.stats = {
                "volume_mm3": round(shape.Volume(), 4),
                "area_mm2": round(shape.Area(), 4),
                "face_count": len(shape.Faces()),
                "edge_count": len(shape.Edges()),
                "bbox_mm": [
                    round(bbox.xlen, 4), round(bbox.ylen, 4), round(bbox.zlen, 4),
                ],
                "bbox_diagonal_mm": round(
                    math.sqrt(bbox.xlen ** 2 + bbox.ylen ** 2 + bbox.zlen ** 2), 4
                ),
            }
            cq.exporters.export(solid, str(path), cq.exporters.ExportTypes.STEP)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{meta.fixture_id}: export failed: {exc}")
            continue

        if not path.exists() or path.stat().st_size == 0:
            failures.append(f"{meta.fixture_id}: wrote an empty file.")
            continue

        fixtures.append(meta)
        print(
            f"  {meta.fixture_id:<4} {meta.name:<38} "
            f"{meta.stats['face_count']:>3} faces  "
            f"{meta.stats['edge_count']:>3} edges  "
            f"{path.stat().st_size / 1024:>7.1f} KB"
        )

    manifest = {
        "generated_by": "scripts/generate_fixtures.py",
        "purpose": (
            "Synthetic fixture corpus for the v2 parting-line engine. Each "
            "fixture targets a specific algorithmic failure mode and has a "
            "checkable answer. See docs/PARTING_LINE_ALGORITHM_PLAN.md §12 P0."
        ),
        "real_parts_note": (
            "F15 (Part1.stp) and F16 (Part3.stp) live in data/parts/ and are NOT "
            "generated here. Part3 has NO ground truth — Bosch has not disclosed "
            "an expected solution — so it is scored on feasibility, "
            "fragmentation, and honesty, never on correctness."
        ),
        "fixture_count": len(fixtures),
        "fixtures": [asdict(f) for f in fixtures],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n{len(fixtures)}/{len(BUILDERS)} fixtures written to {OUTPUT_DIR}")
    print(f"manifest.json lists {len(fixtures)} fixture(s)")
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
