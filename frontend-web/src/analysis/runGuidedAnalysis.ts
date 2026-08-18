/**
 * The Guided "Run full analysis" orchestration service (F3, F0 §4.1 "one
 * primary action... walks direction search -> parting line -> core/cavity
 * -> undercuts -> side cores"). F3 implements the direction/parting-line/
 * core-cavity portion via the ONE authoritative backend call that already
 * covers it (`/core-cavity?use_optimal_direction=true&solid_split=true`,
 * `backend/geometry/mold_orchestration.py`'s C14-C18A orchestration) --
 * side-core generation is out of scope (F3 spec: "do not implement...
 * automatic side-action routing").
 *
 * F4 factored the run/apply-result machinery this and `runManualAnalysis.ts`
 * both need into `analysisShared.ts` -- this file now only supplies the
 * automatic path's specific API call and marks its result as the
 * "recommended" result (F4: preserved separately from whatever the engineer
 * runs manually afterward, so the two stay comparable).
 *
 * Deliberately NOT inside the Zustand store (kept pure data, per F1) and
 * NOT inside a component (components must not call the API layer or the
 * viewport engine directly).
 */

import { runFullAnalysis } from '../api/endpoints';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetAnalysisRunLockForTests, executeAnalysisRun } from './analysisShared';

export function runGuidedAnalysis(): Promise<void> {
  const filename = useAnalysisStore.getState().currentPart;
  if (!filename) return Promise.resolve();

  return executeAnalysisRun(() => runFullAnalysis(filename), { isRecommended: true, filename });
}

/** Test-only: clears the shared in-flight guard so each test starts from a clean slate. */
export function __resetGuidedAnalysisForTests(): void {
  __resetAnalysisRunLockForTests();
}
