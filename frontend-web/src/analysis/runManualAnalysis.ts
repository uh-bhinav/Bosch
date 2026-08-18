/**
 * The Manual Pull Direction orchestration service (F4).
 *
 * Calls the SAME `/core-cavity` endpoint contract F3's Guided run uses,
 * with `use_optimal_direction=false` -- never the old four-call legacy
 * override pipeline (`draft` + `undercuts` + legacy `parting-line` +
 * `core-cavity`) F0 §1.5 identified and flagged obsolete. The backend's
 * `resolve_manual_direction_mold`/`prepare_manual_direction` (C15/C16) is
 * the one authority for direction normalization and invalid-direction
 * detection -- this module sends the engineer's raw vector completely
 * unmodified and never pre-empts that check itself (no client-side
 * zero-vector or magnitude validation).
 *
 * Shares `executeAnalysisRun`'s in-flight guard with `runGuidedAnalysis`
 * (`analysisShared.ts`) -- a manual run cannot fire while a guided run (or
 * another manual run) is already in flight, and vice versa, so
 * `analysisResult` is always written by exactly one completed request at a
 * time. Marked `isRecommended: false`: a manual result never overwrites
 * `recommendedResult`, so the optimizer's recommendation stays available
 * for comparison for as long as the current part is loaded.
 */

import { runManualCoreCavity } from '../api/endpoints';
import type { CorePinFaceRefInput, DelegationInput } from '../api/types';
import type { Vec3 } from '../domain/types';
import { useAnalysisStore } from '../store/analysisStore';
import { executeAnalysisRun } from './analysisShared';

export function runManualAnalysis(
  direction: Vec3,
  corePinFaceRefs: CorePinFaceRefInput[] = [],
  delegations: DelegationInput[] = [],
): Promise<void> {
  const filename = useAnalysisStore.getState().currentPart;
  if (!filename) return Promise.resolve();

  return executeAnalysisRun(
    () => runManualCoreCavity(filename, direction, { corePinFaceRefs, delegations }),
    { isRecommended: false, filename, authorization: { corePinFaceRefs, delegations } },
  );
}
