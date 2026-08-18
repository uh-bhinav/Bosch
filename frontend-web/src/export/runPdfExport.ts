/**
 * The PDF report export orchestration service (F6).
 *
 * Calls `POST /parts/{filename}/export/report`, which -- like STEP export
 * -- is a self-contained pipeline the backend runs from scratch on every
 * call (`backend/api/main.py`'s `export_pdf_report`, unchanged this
 * phase). ALWAYS sent with `use_optimal_direction=false` and the
 * frontend's own already-resolved `pullDirection`, for the same reason
 * `runStepExport.ts` does: never repeat the optimizer's expensive
 * candidate search purely to generate a report about a direction already
 * found. A real, disclosed consequence: because of this, the PDF's own
 * "Pull Direction Optimization" section (which only renders when the
 * backend itself ran `optimize_mold_direction`) never appears in a report
 * this service generates -- `ExportPanel.tsx` shows that section as
 * permanently unavailable, not a togglable checkbox that silently does
 * nothing.
 *
 * On success, triggers a real browser download (`downloadBlob.ts`) -- the
 * response is the actual PDF bytes (`application/pdf`,
 * `Content-Disposition: attachment`), not a server-side path, so unlike
 * `/export/mold-halves` there is no separate download-endpoint gap here.
 */

import { exportPdfReport } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAnalysisStore } from '../store/analysisStore';
import { downloadBlob } from './downloadBlob';

let inFlight: Promise<void> | null = null;

export function runPdfExport(): Promise<void> {
  if (inFlight) return inFlight;

  const store = useAnalysisStore.getState();
  const filename = store.currentPart;
  const direction = store.pullDirection;
  if (!filename || !direction) return Promise.resolve();

  store.setPdfExportError(null);
  store.setPdfExportStage('preparing');
  store.setPdfExportStartedAt(Date.now());

  const run = (async () => {
    useAnalysisStore.getState().setPdfExportStage('generating');
    try {
      const state = useAnalysisStore.getState();
      const blob = await exportPdfReport(
        filename,
        direction,
        { corePinFaceRefs: state.corePinFaceRefs, delegations: state.delegations },
        state.pdfSections,
      );
      const prefix = filename.replace(/\.stp$/i, '').replace(/\.step$/i, '');
      downloadBlob(blob, `${prefix}_dfm_report.pdf`);
      useAnalysisStore.getState().setPdfExportStage('complete');
    } catch (error) {
      const state = useAnalysisStore.getState();
      state.setPdfExportStage('failed');
      state.setPdfExportError(error instanceof ApiError ? error.message : 'Something went wrong generating the PDF report.');
    } finally {
      inFlight = null;
    }
  })();

  inFlight = run;
  return run;
}

/** Test-only: clears the in-flight guard so each test starts from a clean slate. */
export function __resetPdfExportForTests(): void {
  inFlight = null;
}
