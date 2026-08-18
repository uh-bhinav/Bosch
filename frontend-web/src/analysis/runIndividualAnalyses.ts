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
 *
 * One narrow exception to "never touches pipelineStatus": `runPartingLineOnly`
 * is how an engineer re-resolves the parting line after editing authorization
 * (core-pin refs / delegations) in Expert mode -- it does NOT re-run the
 * primary `/core-cavity` call, so that call's own `orchestration.status`
 * (what set `pipelineStatus` originally) can go stale relative to the
 * authoritative v2 engine's own outcome for the SAME resolved direction. If
 * the primary run had left `pipelineStatus` at 'blocked' and this rerun comes
 * back with a real `selected` candidate, the top bar was showing a wrong
 * "Blocked" for a direction that just proved feasible -- promote it.
 */

import { getDraft, getPartingLineV2, getUndercuts } from '../api/endpoints';
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

/** Requires `pullDirection` to already be resolved (Pull Direction tool) -- the panel is responsible for the "run Pull Direction first" gating message, this function just no-ops if called without one. Uses the v2 engine (`getPartingLineV2`), with the current authoritative configuration (`corePinFaceRefs`/`delegations`), the same authority `/core-cavity` uses for the real split. */
export async function runPartingLineOnly(): Promise<void> {
  const state = useAnalysisStore.getState();
  const filename = state.currentPart;
  if (!filename || !state.pullDirection) return;

  useAnalysisStore.getState().setPartingLineStage('running');
  useAnalysisStore.getState().setPartingLineError(null);
  try {
    const partingLine = await getPartingLineV2(filename, state.pullDirection, {
      corePinFaceRefs: state.corePinFaceRefs,
      delegations: state.delegations,
    });
    useAnalysisStore.getState().setPartingLineResult(partingLine);
    useAnalysisStore.getState().setPartingLineStage('done');
    if (partingLine.selected && useAnalysisStore.getState().pipelineStatus === 'blocked') {
      useAnalysisStore.getState().setPipelineStatus('complete');
    }
  } catch (error) {
    useAnalysisStore.getState().setPartingLineError(describeAnalysisFailure(error));
    useAnalysisStore.getState().setPartingLineStage('error');
  }
}

/**
 * F13 §4: Draft direction INSPECTION -- a pure visual override for the
 * Draft tool, writing ONLY `draftInspectResult` (never `draftResult`, the
 * resolved-direction snapshot, and never `pullDirection`/
 * `manualPullDirection`). Calling this can never change analysis scope or
 * trigger a rerun of anything else -- it is exactly one `/draft` fetch at
 * whatever direction the engineer typed in to look at.
 */
export async function runDraftInspect(direction: Vec3): Promise<void> {
  const state = useAnalysisStore.getState();
  const filename = state.currentPart;
  if (!filename) return;

  useAnalysisStore.getState().setDraftInspectStage('running');
  useAnalysisStore.getState().setDraftInspectError(null);
  try {
    const draft = await getDraft(filename, direction);
    useAnalysisStore.getState().setDraftInspectResult(draft);
    useAnalysisStore.getState().setDraftInspectStage('done');
  } catch (error) {
    useAnalysisStore.getState().setDraftInspectError(describeAnalysisFailure(error));
    useAnalysisStore.getState().setDraftInspectStage('error');
  }
}
