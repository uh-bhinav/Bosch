/**
 * Shared machinery between the Guided automatic run (F3, `runGuidedAnalysis.ts`)
 * and the Manual run (F4, `runManualAnalysis.ts`) -- both call the SAME
 * `/core-cavity` endpoint contract and must apply their result to the shared
 * store identically (pull direction, viewport overlay, pipeline status).
 * Factored out here rather than duplicated so "exactly one analysis request
 * in flight at a time" is a single, shared guarantee -- a manual run cannot
 * race a guided run (or another manual run) and stomp `analysisResult` out
 * of order; the shared analysis state stays the single authoritative
 * current result no matter which path produced it (F0 §2).
 */

import * as THREE from 'three';
import { ApiError } from '../api/client';
import { getDraft, getPartingLine, getSideCoreDetail, getUndercuts, type ManualAnalysisAuthorization } from '../api/endpoints';
import type { CoreCavityAnalysisResponse } from '../api/types';
import type { PullDirectionSource, Vec3 } from '../domain/types';
import { adaptDisplayMesh } from '../geometry/meshAdapter';
import { useAnalysisStore } from '../store/analysisStore';
import { getViewportEngine } from '../viewport/engineSingleton';

/**
 * `/core-cavity`'s `pull_direction_source` ("optimal_mold_direction" |
 * "manual_query_direction", `backend/api/main.py`) uses a different string
 * convention than `parting_line_v2`'s `PullDirectionInput.source`
 * ("optimizer" | "manual") that the frontend's `PullDirectionSource` type
 * already mirrors (see `src/domain/types.ts`) -- a genuine, pre-existing
 * naming inconsistency between two backend modules, not something this
 * phase changes. This is a mechanical adapter between the two spellings,
 * the same kind of adaptation `meshAdapter.ts` already does for mesh
 * payloads -- not a reinterpretation of what either module means.
 */
export const PULL_DIRECTION_SOURCE_MAP: Record<string, PullDirectionSource> = {
  optimal_mold_direction: 'optimizer',
  manual_query_direction: 'manual',
};

export function describeAnalysisFailure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong running the analysis.';
}

export function applyCoreCavityOverlay(response: CoreCavityAnalysisResponse): void {
  const meshPayload = response.display_mesh;
  if (!meshPayload) return;

  const adapted = adaptDisplayMesh(meshPayload);
  if (!adapted) return;

  const engine = getViewportEngine();
  engine.setMesh(adapted);

  const rgb = meshPayload.core_cavity_rgb as [number, number, number][] | undefined;
  if (rgb && rgb.length === adapted.faceIds.length) {
    const colors = new Map<number, THREE.Color>();
    adapted.faceIds.forEach((faceId, i) => {
      if (colors.has(faceId)) return;
      const [r, g, b] = rgb[i];
      colors.set(faceId, new THREE.Color(r, g, b));
    });
    engine.setOverlayColors(colors);
  }

  useAnalysisStore.getState().setOverlay('core-cavity');
}

/** Module-level guard: any second run (guided OR manual) while one is already in flight returns the SAME promise, never fires a second request. */
let inFlight: Promise<void> | null = null;

/**
 * F7: the follow-up sweep run AFTER the primary `/core-cavity` call resolves
 * a pull direction -- draft, undercuts, and the parting-line curve, all
 * fetched at that SAME direction (never re-running the optimizer), plus a
 * conditional side-core check. This is what makes "Run Full Analysis"
 * actually cover the complete workflow (F0 §4.1) instead of only the
 * core/cavity split: none of these three pieces of information exist
 * anywhere in `/core-cavity`'s own response, so a dedicated call per piece
 * is the only way to surface them, not a redundant one. Every step is
 * independently try/caught -- one follow-up failing (e.g. a slow Boolean
 * pass) never blocks or hides the others, and never touches
 * `analysisError`/`pipelineStatus`, which already reflect the primary
 * (already-succeeded) result.
 */
async function runFollowUpAnalyses(
  filename: string,
  direction: Vec3,
  result: CoreCavityAnalysisResponse,
  authorization: ManualAnalysisAuthorization,
): Promise<void> {
  const store = useAnalysisStore;

  store.getState().setDraftStage('running');
  try {
    const draft = await getDraft(filename, direction);
    store.getState().setDraftResult(draft);
    store.getState().setDraftStage('done');
  } catch (error) {
    store.getState().setDraftError(describeAnalysisFailure(error));
    store.getState().setDraftStage('error');
  }

  store.getState().setUndercutsStage('running');
  try {
    const undercuts = await getUndercuts(filename, direction);
    store.getState().setUndercutsResult(undercuts);
    store.getState().setUndercutsStage('done');
  } catch (error) {
    store.getState().setUndercutsError(describeAnalysisFailure(error));
    store.getState().setUndercutsStage('error');
  }

  store.getState().setPartingLineStage('running');
  try {
    const partingLine = await getPartingLine(filename, direction);
    store.getState().setPartingLineResult(partingLine);
    store.getState().setPartingLineStage('done');
  } catch (error) {
    store.getState().setPartingLineError(describeAnalysisFailure(error));
    store.getState().setPartingLineStage('error');
  }

  // F7 §2: side cores are conditional -- the ONE signal that a direction
  // needs a side action is `parting_line_v2_outcome==='referred_to_side_
  // action'` (the same field `describeAnalysisOutcome.ts` already treats as
  // authoritative). A feasible split with no referral is a real, positive
  // "not required" result; anything else means the primary analysis itself
  // never resolved a feasible parting line, so requirement can't be
  // determined either way.
  const outcome = result.orchestration?.parting_line_v2_outcome;
  const primaryStatus = result.orchestration?.status;
  if (outcome === 'referred_to_side_action') {
    store.getState().setSideCoreStatus('checking');
    try {
      const detail = await getSideCoreDetail(filename, direction, authorization);
      store.getState().setSideCoreDetail(detail);
      store.getState().setSideCoreStatus(detail.side_core?.status === 'generated' ? 'available' : 'unavailable');
    } catch (error) {
      store.getState().setSideCoreError(describeAnalysisFailure(error));
      store.getState().setSideCoreStatus('unavailable');
    }
  } else if (primaryStatus === 'generated') {
    store.getState().setSideCoreStatus('not-required');
  } else {
    store.getState().setSideCoreStatus('blocked');
  }
}

export function executeAnalysisRun(
  fetchResult: () => Promise<CoreCavityAnalysisResponse>,
  options: { isRecommended: boolean; filename: string; authorization?: ManualAnalysisAuthorization },
): Promise<void> {
  if (inFlight) return inFlight;

  const store = useAnalysisStore.getState();
  store.setAnalysisResult(null);
  store.setAnalysisError(null);
  store.setPipelineStatus('running');
  store.setDraftResult(null);
  store.setDraftStage('idle');
  store.setDraftError(null);
  store.setUndercutsResult(null);
  store.setUndercutsStage('idle');
  store.setUndercutsError(null);
  store.setPartingLineResult(null);
  store.setPartingLineStage('idle');
  store.setPartingLineError(null);
  store.setSideCoreStatus('unknown');
  store.setSideCoreDetail(null);
  store.setSideCoreError(null);

  const startedAt = Date.now();
  const run = (async () => {
    try {
      const result = await fetchResult();
      const state = useAnalysisStore.getState();
      // F5: a real, frontend-measured request round-trip duration -- NEVER
      // a per-stage breakdown (the backend doesn't expose one on this
      // endpoint; Diagnostics must not manufacture one). Set before the
      // other fields purely for ordering clarity; harmless either way.
      state.setLastRunDurationMs(Date.now() - startedAt);
      state.setAnalysisResult(result);
      if (options.isRecommended) {
        state.setRecommendedResult(result);
      }

      const pullDirection = result.orchestration?.pull_direction;
      if (pullDirection) {
        const source = PULL_DIRECTION_SOURCE_MAP[result.pull_direction_source] ?? null;
        state.setPullDirection(pullDirection as Vec3, source);
      }

      applyCoreCavityOverlay(result);

      const succeeded = result.orchestration?.status === 'generated';
      state.setPipelineStatus(succeeded ? 'complete' : 'blocked');

      if (pullDirection) {
        await runFollowUpAnalyses(options.filename, pullDirection as Vec3, result, options.authorization ?? {});
      }
    } catch (error) {
      const state = useAnalysisStore.getState();
      state.setAnalysisError(describeAnalysisFailure(error));
      state.setPipelineStatus('blocked');
    } finally {
      inFlight = null;
    }
  })();

  inFlight = run;
  return run;
}

/** Test-only: clears the in-flight guard so each test starts from a clean slate. */
export function __resetAnalysisRunLockForTests(): void {
  inFlight = null;
}
