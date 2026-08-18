/**
 * F7 §8: individual per-tool analysis actions -- demonstrating/debugging one
 * capability at a time, distinct from "Run Full Analysis" (the primary demo
 * path, `runGuidedAnalysis.ts`). Each function calls exactly the one
 * endpoint its tool needs and writes only that tool's own store slice --
 * never touches `analysisResult`/`pipelineStatus`, the primary result's own
 * fields, so running "Draft only" can never overwrite or invalidate an
 * already-computed Full Analysis result.
 *
 * Draft/Undercuts use the current `pullDirection` if one has been resolved,
 * falling back to the backend's own +Z default otherwise (both endpoints
 * already default to +Z server-side, so this mirrors that rather than
 * inventing a client-side default). Parting Line genuinely NEEDS a resolved
 * direction to mean anything as an "individual" action -- its panel gates
 * the button on `pullDirection` being set instead of guessing +Z.
 */

import { getDraft, getPartingLine, getUndercuts } from '../api/endpoints';
import type { Vec3 } from '../domain/types';
import { useAnalysisStore } from '../store/analysisStore';
import { describeAnalysisFailure } from './analysisShared';

const DEFAULT_DIRECTION: Vec3 = [0, 0, 1];

export async function runDraftOnly(): Promise<void> {
  const state = useAnalysisStore.getState();
  const filename = state.currentPart;
  if (!filename) return;
  const direction = state.pullDirection ?? DEFAULT_DIRECTION;

  useAnalysisStore.getState().setDraftStage('running');
  useAnalysisStore.getState().setDraftError(null);
  try {
    const draft = await getDraft(filename, direction);
    useAnalysisStore.getState().setDraftResult(draft);
    useAnalysisStore.getState().setDraftStage('done');
  } catch (error) {
    useAnalysisStore.getState().setDraftError(describeAnalysisFailure(error));
    useAnalysisStore.getState().setDraftStage('error');
  }
}

export async function runUndercutsOnly(): Promise<void> {
  const state = useAnalysisStore.getState();
  const filename = state.currentPart;
  if (!filename) return;
  const direction = state.pullDirection ?? DEFAULT_DIRECTION;

  useAnalysisStore.getState().setUndercutsStage('running');
  useAnalysisStore.getState().setUndercutsError(null);
  try {
    const undercuts = await getUndercuts(filename, direction);
    useAnalysisStore.getState().setUndercutsResult(undercuts);
    useAnalysisStore.getState().setUndercutsStage('done');
  } catch (error) {
    useAnalysisStore.getState().setUndercutsError(describeAnalysisFailure(error));
    useAnalysisStore.getState().setUndercutsStage('error');
  }
}

/** Requires `pullDirection` to already be resolved (Pull Direction tool) -- the panel is responsible for the "run Pull Direction first" gating message, this function just no-ops if called without one. */
export async function runPartingLineOnly(): Promise<void> {
  const state = useAnalysisStore.getState();
  const filename = state.currentPart;
  if (!filename || !state.pullDirection) return;

  useAnalysisStore.getState().setPartingLineStage('running');
  useAnalysisStore.getState().setPartingLineError(null);
  try {
    const partingLine = await getPartingLine(filename, state.pullDirection);
    useAnalysisStore.getState().setPartingLineResult(partingLine);
    useAnalysisStore.getState().setPartingLineStage('done');
  } catch (error) {
    useAnalysisStore.getState().setPartingLineError(describeAnalysisFailure(error));
    useAnalysisStore.getState().setPartingLineStage('error');
  }
}
