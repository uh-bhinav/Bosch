"""
backend/geometry/parting_line_v2/timing.py
------------------------------------------
Per-stage runtime instrumentation (plan §12.5).

**No Bosch runtime SLA has been provided, and none is invented here.** This
module measures; it never enforces a ceiling. The optimization policy is:

  1. Correctness and geometric validity first, always.
  2. Never optimize a stage the corpus profile did not identify as a bottleneck.
  3. Record before/after in ``CHANGELOG.md`` when a bottleneck IS addressed.
  4. A runtime regression is acceptable if it buys correctness — **provided it
     is measured and stated.** An unmeasured regression is not.

Timings are a **result field**, not log output, so a corpus run can aggregate
p50/p95 per stage without parsing text. See
``docs/DECISIONS_AND_ALGORITHMS.md`` D-004.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Literal

__all__ = ["StageName", "STAGE_ORDER", "StageTimings", "StageTimer", "percentile"]


StageName = Literal[
    "load",         # STEP parse / cache hit
    "track_a",      # silhouette at sharp edges (plan §3)
    "track_b",      # face-interior silhouette curves (plan §4)
    "weld",         # vertex welding into the graph (plan §5.2)
    "reduce",       # 2-core + degree-2 contraction (plan §5.4)
    "enumerate",    # loop enumeration (plan §6)
    "filter",       # hard gates H0-H7 (plan §7)
    "rank",         # lexicographic ranking (plan §8)
    "core_cavity",  # region classification (plan §9)
    "surface",      # split-tool construction (plan §10.2)
]

#: Canonical reporting order. Matches the pipeline diagram in plan §12.5.
STAGE_ORDER: tuple[StageName, ...] = (
    "load", "track_a", "track_b", "weld", "reduce",
    "enumerate", "filter", "rank", "core_cavity", "surface",
)


@dataclass
class StageTimings:
    """
    Accumulated per-stage elapsed time for one pipeline run.

    A stage may be entered more than once (e.g. ``track_b`` per face); elapsed
    times accumulate and ``call_counts`` records how many times. Stages that
    never ran are absent rather than zero — "did not run" and "ran instantly"
    are different facts, and conflating them is how a skipped stage hides.
    """

    elapsed_ms: dict[str, float] = field(default_factory=dict)
    call_counts: dict[str, int] = field(default_factory=dict)

    def record(self, stage: StageName, ms: float) -> None:
        self.elapsed_ms[stage] = self.elapsed_ms.get(stage, 0.0) + ms
        self.call_counts[stage] = self.call_counts.get(stage, 0) + 1

    @property
    def total_ms(self) -> float:
        return sum(self.elapsed_ms.values())

    def ran(self, stage: StageName) -> bool:
        return stage in self.elapsed_ms

    def to_dict(self) -> dict:
        return {
            "stages": [
                {
                    "stage": stage,
                    "elapsed_ms": round(self.elapsed_ms[stage], 3),
                    "calls": self.call_counts.get(stage, 0),
                }
                for stage in STAGE_ORDER
                if stage in self.elapsed_ms
            ],
            "total_ms": round(self.total_ms, 3),
            "stages_not_run": [s for s in STAGE_ORDER if s not in self.elapsed_ms],
        }


class StageTimer:
    """
    Context-manager timer writing into a ``StageTimings``.

    Usage::

        timings = StageTimings()
        timer = StageTimer(timings)
        with timer("track_a"):
            ...

    Uses ``perf_counter`` (monotonic, highest available resolution). Records
    even when the body raises, so a timing is never lost to a failure — a
    stage that blew up slowly is exactly the one worth seeing.
    """

    __slots__ = ("_timings",)

    def __init__(self, timings: StageTimings | None = None) -> None:
        self._timings = timings if timings is not None else StageTimings()

    @property
    def timings(self) -> StageTimings:
        return self._timings

    @contextmanager
    def __call__(self, stage: StageName) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self._timings.record(stage, (time.perf_counter() - start) * 1000.0)


def percentile(values: list[float], q: float) -> float:
    """
    Linear-interpolated percentile, ``q`` in [0, 1].

    Written out rather than pulling in numpy: this runs in the corpus harness
    where numpy is available, but also in tests that deliberately avoid heavy
    optional imports. Returns 0.0 for an empty input.

    p50 and p95 are what the corpus report publishes — **not the mean.** The
    mean hides the pathological parts, and those are the ones that decide
    whether a stage needs work.
    """
    if not values:
        return 0.0
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"percentile q must be in [0, 1], got {q}.")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
