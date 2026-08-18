"""
backend/geometry/undercut_isolation_worker.py
-----------------------------------------------
O22: fresh-process undercut-detection worker.

One invocation = one direction's Boolean-refined undercut detection, in a
brand-new OS process (spawned by `direction_optimizer._run_isolated_undercut_detection`),
then exit. This is the mechanism that removes the O17-O19-proven
process-lifetime OCC degradation from the parent's long-running search --
the parent never accumulates the OCC workload that triggers it.

Contract (stdin -> stdout, both JSON, one line each):
  stdin:  {"step_path": str, "direction": [x,y,z], "max_boolean_faces": int}
  stdout success: {"ok": true, "result": <undercut_result_to_plain(...) dict>}
  stdout failure: {"ok": false, "error": "<explicit reason>"}

Never mutates any parent state -- this process loads its own independent
`PartGeometry` copy and always calls `detect_undercuts(mutate=False, ...)`.
The parent applies mutation itself (via `_apply_undercut_result_to_part`)
using the reconstructed result, exactly mirroring the existing cache-hit
code path. Any exception here is caught and reported as an "ok": false
payload -- this script must never raise past its own top-level guard, since
a non-JSON stdout or a traceback on stderr is exactly the "malformed
payload" / "non-zero exit" failure mode the parent is required to treat as
`evaluation_failed`, never as a clean/geometric verdict.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# This script is spawned as a bare `python <this file>` subprocess (O22),
# so it has none of the parent's sys.path setup. backend/geometry/ ->
# parents[2] is the repo root, from which `import backend...` resolves the
# same way it does for every other entry point (uvicorn, pytest) in this
# project.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        step_path = request["step_path"]
        direction = tuple(request["direction"])
        max_boolean_faces = int(request["max_boolean_faces"])
    except Exception as exc:  # malformed request from the parent itself
        print(json.dumps({"ok": False, "error": f"malformed request: {exc}"}))
        return 1

    try:
        from backend.geometry.step_loader import load_step
        from backend.geometry.undercut_detector import (
            detect_undercuts,
            undercut_result_to_plain,
        )

        part = load_step(step_path)
        result = detect_undercuts(
            part,
            direction,
            mutate=False,
            boolean_refine=True,
            max_boolean_faces=max_boolean_faces,
        )
        payload = undercut_result_to_plain(result)
        print(json.dumps({"ok": True, "result": payload}))
        return 0
    except Exception as exc:  # STEP-load failure, OCC failure, anything else
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
