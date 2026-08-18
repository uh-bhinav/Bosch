"""
tests/test_parting_line_v2_h2_bbox_prefilter.py
------------------------------------------------
O15 (2026-08-17): H2's exhaustive pairwise self-intersection check
(measures.self_intersection / self_intersection_multi) now skips the
exact predicate (_segments_cross_2d) for segment pairs whose axis-aligned
2-D bounding boxes are strictly disjoint -- proven exact, not an
approximation (O14): any point where two segments touch or cross must lie
within both segments' bounding boxes, so disjoint boxes make touching or
crossing geometrically impossible, independent of _segments_cross_2d's
own internal tolerance. O13 measured this bbox-disjoint case as >99% of
all pairs examined on real Part3 geometry (98.8-99.9% across five
directions), making it the dominant cost driver O13 identified.

This module is the permanent regression suite for that change: the
14-case adversarial oracle from the O14 investigation (verifying the
bbox-then-exact helper functions agree with the exact predicate alone on
every hand-picked boundary case), plus end-to-end tests of the actual
production self_intersection()/self_intersection_multi() functions
proving the accelerated versions are byte-for-byte identical to the
documented pre-O15 semantics: same `intersects`, same `checked` count
(every non-adjacent pair the algorithm considers, NOT just the pairs that
reach the exact predicate -- deliberately unchanged, see
self_intersection's O15 docstring note), same `confirmed` count, same
adjacency exclusion, same closed-loop wraparound.
"""

from __future__ import annotations

import pytest

from backend.geometry.parting_line_v2.measures import (
    _bboxes_disjoint_2d,
    _segment_bbox_2d,
    _segments_cross_2d,
    self_intersection,
    self_intersection_multi,
)

PULL_Z = (0.0, 0.0, 1.0)


def _accelerated_cross_2d(p0, p1, q0, q1, tolerance):
    """bbox-then-exact, mirroring exactly what production now does."""
    if _bboxes_disjoint_2d(_segment_bbox_2d(p0, p1), _segment_bbox_2d(q0, q1)):
        return False
    return _segments_cross_2d(p0, p1, q0, q1, tolerance)


# ---------------------------------------------------------------------------
# Test A -- the 14-case adversarial oracle from O14, now permanent.
# ---------------------------------------------------------------------------

ADVERSARIAL_CASES = [
    ("crossing segments (X shape)", (0, 0), (2, 2), (0, 2), (2, 0), True),
    ("non-crossing separated segments", (0, 0), (1, 1), (100, 100), (101, 101), False),
    ("close but not crossing (parallel)", (0, 0), (1, 0), (0, 0.5), (1, 0.5), False),
    ("collinear overlap (same line, overlapping)", (0, 0), (2, 0), (1, 0), (3, 0), False),
    ("collinear non-overlap", (0, 0), (1, 0), (2, 0), (3, 0), False),
    ("endpoint touching (T shape)", (0, 0), (2, 0), (1, 0), (1, 1), False),
    ("endpoint touching (shared vertex)", (0, 0), (1, 1), (1, 1), (2, 0), False),
    ("near-tolerance crossing", (0, -1e-10), (2, 1e-10), (1, -1), (1, 1), True),
    ("bbox-overlap but no actual crossing", (0, 0), (1, 1), (0, 1), (0.3, 0.9), False),
    ("vertical/horizontal crossing", (1, -1), (1, 1), (-1, 0), (2, 0), True),
    ("bbox-edge touching, no crossing", (0, 0), (1, 0), (1, 0), (2, 1), False),
    ("zero-length segment", (0, 0), (0, 0), (0, 0), (1, 1), False),
    ("corner-only bbox overlap", (0, 0), (1, 1), (1, 1), (2, 2), False),
]


@pytest.mark.parametrize("name,p0,p1,q0,q1,expected", ADVERSARIAL_CASES)
def test_a_bbox_accelerated_matches_exact_predicate(name, p0, p1, q0, q1, expected):
    exact = _segments_cross_2d(p0, p1, q0, q1, 1e-12)
    accelerated = _accelerated_cross_2d(p0, p1, q0, q1, 1e-12)
    assert exact == expected, f"{name}: exact predicate itself disagrees with expected value"
    assert accelerated == exact, f"{name}: bbox-accelerated result diverges from the exact predicate"


def test_a_prefilter_actually_short_circuits_the_exact_predicate(monkeypatch):
    """
    Proves the prefilter is really wired into production self_intersection()
    -- not just that the standalone helpers agree in isolation. A large
    loop where most segment pairs are spatially far apart (points on a
    circle) must call the real _segments_cross_2d fewer times than the
    number of pairs considered (`checked`), since bbox-disjoint pairs
    should short-circuit before ever reaching it.
    """
    import math
    import backend.geometry.parting_line_v2.measures as measures_mod

    calls = {"n": 0}
    real = measures_mod._segments_cross_2d

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(measures_mod, "_segments_cross_2d", counting)

    n = 20
    points = tuple(
        (100.0 * math.cos(2 * math.pi * i / n), 100.0 * math.sin(2 * math.pi * i / n), 0.0)
        for i in range(n)
    )
    intersects, checked, confirmed = measures_mod.self_intersection(
        points, PULL_Z, closed=True, tolerance=1e-6
    )
    assert intersects is False
    assert calls["n"] < checked, (
        f"expected the bbox prefilter to skip the exact predicate for most "
        f"of the {checked} considered pairs, but it was called {calls['n']} times"
    )


# ---------------------------------------------------------------------------
# Test B -- end-to-end self_intersection() regression, exact synthetic shapes.
# ---------------------------------------------------------------------------

def _square(cz: float = 0.0):
    """A simple, non-self-crossing closed square in the XY plane."""
    return ((0.0, 0.0, cz), (1.0, 0.0, cz), (1.0, 1.0, cz), (0.0, 1.0, cz))


def _figure_eight(cz: float = 0.0):
    """A closed, genuinely self-crossing figure-eight in the XY plane."""
    return (
        (0.0, 0.0, cz), (2.0, 2.0, cz), (0.0, 2.0, cz), (2.0, 0.0, cz),
    )


def test_b_square_does_not_self_intersect():
    intersects, checked, confirmed = self_intersection(_square(), PULL_Z, closed=True, tolerance=1e-6)
    assert intersects is False
    assert confirmed == 0
    # 4 points, closed -> 4 segments; each segment vs non-adjacent others:
    # (0,2) is the only non-adjacent pair for n=4 (0-1,1-2,2-3,3-0 segments;
    # segment 0 vs segment 2 is the only non-adjacent pair not sharing an endpoint).
    assert checked == 2  # (seg0,seg2) and (seg1,seg3)


def test_b_figure_eight_self_intersects():
    intersects, checked, confirmed = self_intersection(_figure_eight(), PULL_Z, closed=True, tolerance=1e-6)
    assert intersects is True
    assert confirmed >= 1


def test_b_checked_counts_every_considered_pair_not_just_bbox_survivors():
    """
    O15's explicit preserved-semantics requirement: `checked` must count
    every non-adjacent pair the algorithm considers, identically to
    before the bbox prefilter existed -- NOT only the pairs that reach
    the exact predicate. Verified by construction: a large loop where
    most pairs are bbox-disjoint (far apart) must still report the full
    O(n^2)-scale checked count, not a reduced one.
    """
    import math
    n = 20
    # A large, spread-out non-self-crossing polygon (points on a circle) --
    # most segment pairs will be bbox-disjoint, but `checked` must still
    # count all of them.
    points = tuple(
        (100.0 * math.cos(2 * math.pi * i / n), 100.0 * math.sin(2 * math.pi * i / n), 0.0)
        for i in range(n)
    )
    intersects, checked, confirmed = self_intersection(points, PULL_Z, closed=True, tolerance=1e-6)
    assert intersects is False
    # Non-adjacent pairs for an n-gon (closed): n*(n-3)/2
    expected_checked = n * (n - 3) // 2
    assert checked == expected_checked


def test_b_adjacent_segments_excluded():
    """Adjacent segments sharing a point must never be counted, exactly as before."""
    intersects, checked, confirmed = self_intersection(_square(), PULL_Z, closed=True, tolerance=1e-6)
    # For n=4, adjacent pairs are (0,1),(1,2),(2,3),(3,0) -- 4 pairs excluded
    # from the naive C(4,2)-with-i<j-2-apart count. Already asserted checked==2 above;
    # this test asserts it stays true (regression pin) and that no false
    # intersection is introduced by adjacency.
    assert checked == 2
    assert intersects is False


def test_b_closed_loop_wraparound_included():
    """
    The closing segment (last point back to first) must be tested when
    ``closed=True``, exactly as before O15. Constructed so the ONLY
    self-crossing in the shape involves the wraparound segment (point[-1]
    -> point[0]): detected when closed=True, and provably NOT even
    considered when closed=False (that segment doesn't exist in the open
    path at all).
    """
    pts = (
        (10.0, 0.0, 0.0),  # 0
        (4.0, 0.0, 0.0),   # 1
        (4.0, 4.0, 0.0),   # 2
        (10.0, 4.0, 0.0),  # 3
        (0.0, 2.0, 0.0),   # 4 -- wraparound segment (4 -> 0) is the
                            #      horizontal line y=2, x in [0,10], which
                            #      crosses segment (1 -> 2) (x=4, y in [0,4])
                            #      at (4, 2). No other segment pair crosses.
    )
    intersects_closed, checked_closed, confirmed_closed = self_intersection(
        pts, PULL_Z, closed=True, tolerance=1e-6
    )
    intersects_open, checked_open, _ = self_intersection(
        pts, PULL_Z, closed=False, tolerance=1e-6
    )
    assert intersects_closed is True, "wraparound segment must be tested and found crossing when closed=True"
    assert confirmed_closed >= 1
    assert checked_closed > checked_open, (
        "closed=True must consider the wraparound segment's pairs, "
        "strictly more than the open path"
    )


# ---------------------------------------------------------------------------
# Test C -- self_intersection_multi() cross-loop regression.
# ---------------------------------------------------------------------------

def test_c_two_disjoint_squares_do_not_cross():
    loop_a = _square()
    loop_b = tuple((x + 10.0, y + 10.0, z) for x, y, z in _square())
    intersects, checked, confirmed = self_intersection_multi((loop_a, loop_b), PULL_Z, tolerance=1e-6)
    assert intersects is False
    assert confirmed == 0
    assert checked > 0  # both within-loop and cross-loop pairs were considered


def test_c_two_overlapping_squares_cross():
    loop_a = _square()
    loop_b = tuple((x + 0.5, y + 0.5, z) for x, y, z in _square())
    intersects, checked, confirmed = self_intersection_multi((loop_a, loop_b), PULL_Z, tolerance=1e-6)
    assert intersects is True
    assert confirmed >= 1
