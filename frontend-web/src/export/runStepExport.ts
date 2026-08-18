/**
 * The STEP mold-half export orchestration service (F6).
 *
 * Calls `POST /parts/{filename}/export/mold-halves` -- the SAME
 * authoritative pipeline C14/C16's orchestration module already
 * establishes, reused via the existing `resolve_winning_direction_mold`/
 * `resolve_manual_direction_mold` chain server-side. This service ALWAYS
 * sends `use_optimal_direction=false` with the frontend's own already-
 * resolved `pullDirection` (whichever of Guided/Manual produced the
 * current on-screen result) -- never re-running the optimizer's expensive
 * candidate search purely to export what was already found. See
 * `api/endpoints.ts`'s `exportMoldHalves` docstring for the one
 * unavoidable exception: undercut detection/parting-line/solid-split ARE
 * still re-run for that one direction, since the backend is stateless and
 * never caches OCC solids between requests -- there is no "just export
 * the solids already sitting in memory" path available on this endpoint.
 *
 * Deliberately NOT inside the Zustand store (kept pure data) and NOT
 * inside a component (components must not call the API layer directly) --
 * matches every other F3-F5 orchestration service's architecture.
 */

import { exportMoldHalves } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAnalysisStore } from '../store/analysisStore';

let inFlight: Promise<void> | null = null;

export function runStepExport(): Promise<void> {
  if (inFlight) return inFlight;

  const store = useAnalysisStore.getState();
  const filename = store.currentPart;
  const direction = store.pullDirection;
  if (!filename || !direction) return Promise.resolve();

  store.setStepExportError(null);
  store.setStepExportResult(null);
  store.setStepExportStage('preparing');
  store.setStepExportStartedAt(Date.now());

  const run = (async () => {
    // "Preparing" is real but brief (building the request) -- the request
    // itself is what can take tens/hundreds of seconds, so "generating"
    // is the stage that actually matters for the elapsed-time readout.
    useAnalysisStore.getState().setStepExportStage('generating');
    try {
      const response = await exportMoldHalves(filename, direction, {
        corePinFaceRefs: store.corePinFaceRefs,
        delegations: store.delegations,
      });
      const state = useAnalysisStore.getState();

      if (!response.export) {
        state.setStepExportStage('failed');
        state.setStepExportError(
          response.orchestration?.failure_reason ??
            'The parting line could not be resolved for this direction, so no solid split was attempted.',
        );
        return;
      }
      if (response.export.status !== 'exported' || !response.export.download_filename) {
        state.setStepExportStage('failed');
        state.setStepExportError(response.export.failure_reason ?? `Export status: ${response.export.status}.`);
        return;
      }

      state.setStepExportResult({
        downloadFilename: response.export.download_filename,
        fileSizeBytes: response.export.file_size_bytes ?? 0,
        solidCount: response.export.solid_count ?? 0,
      });
      state.setStepExportStage('complete');
    } catch (error) {
      const state = useAnalysisStore.getState();
      state.setStepExportStage('failed');
      state.setStepExportError(error instanceof ApiError ? error.message : 'Something went wrong exporting the STEP file.');
    } finally {
      inFlight = null;
    }
  })();

  inFlight = run;
  return run;
}

/** Test-only: clears the in-flight guard so each test starts from a clean slate. */
export function __resetStepExportForTests(): void {
  inFlight = null;
}
