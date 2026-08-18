/**
 * The Report / Export workstation tool (F6) -- STEP mold-half export and
 * the PDF Report Builder.
 *
 * Both reuse the CURRENT shared analysis result's `pullDirection` -- never
 * an independent fetch that recomputes the expensive optimizer search
 * (`runStepExport.ts`/`runPdfExport.ts`'s own docstrings explain exactly
 * why and what's unavoidably still re-run). STEP export is gated on the
 * on-screen result already showing a successful solid split
 * (`orchestration.status === 'generated'`) -- `export_mold_halves()`
 * itself hard-requires `solid_split_status === 'split_ok'`, so enabling
 * the button any earlier would just relay a guaranteed failure.
 *
 * The PDF Report Builder's section checkboxes reflect the REAL backend
 * contract (investigated directly against `backend/report/pdf_export.py`
 * and `backend/api/main.py`'s `/export/report`), not an idealized one:
 * - Executive Summary: a real, independent toggle (F6 backend addition,
 *   `include_executive_summary`).
 * - Part/Geometry, Parting Line, Undercuts: ALWAYS included by the
 *   backend, no flag exists to omit them -- shown checked and disabled,
 *   not fabricated as user-selectable.
 * - Pull Direction: NEVER appears in a report this frontend generates,
 *   because doing so would require `use_optimal_direction=true` (re-
 *   running the optimizer) -- shown unavailable, not a dead checkbox.
 * - Core / Cavity (solid split): a real toggle (`include_solid_split`),
 *   defaulted from whether the current result already shows a successful
 *   split.
 * - Side Cores: a real toggle (`include_side_core`) -- but checking it
 *   makes the backend run ADDITIONAL real side-core generation as part of
 *   report generation (independent of whatever the on-screen result did),
 *   so it defaults OFF with an explicit "adds computation time" note.
 * - Diagnostics / Metrics: no backend section exists for this at all --
 *   shown unavailable, never silently dropped without explanation.
 */

import { useEffect } from 'react';
import { stepDownloadUrl } from '../../../api/endpoints';
import { useElapsedSeconds } from '../../../analysis/useElapsedSeconds';
import { runPdfExport } from '../../../export/runPdfExport';
import { runStepExport } from '../../../export/runStepExport';
import { useAnalysisStore } from '../../../store/analysisStore';
import styles from './ExportPanel.module.css';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function StageReadout({
  stage,
  elapsedSeconds,
  label,
}: {
  stage: 'ready' | 'preparing' | 'generating' | 'complete' | 'failed';
  elapsedSeconds: number;
  label: string;
}) {
  if (stage === 'preparing') return <p className={styles.stageText}>Preparing {label}…</p>;
  if (stage === 'generating') {
    return (
      <p className={styles.stageText} data-testid="export-generating">
        Generating {label}… ({elapsedSeconds}s) — this can take tens to hundreds of seconds.
      </p>
    );
  }
  return null;
}

export function ExportPanel() {
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);

  const stepStage = useAnalysisStore((s) => s.stepExportStage);
  const stepError = useAnalysisStore((s) => s.stepExportError);
  const stepResult = useAnalysisStore((s) => s.stepExportResult);
  const stepElapsed = useElapsedSeconds(stepStage === 'generating' || stepStage === 'preparing');

  const pdfStage = useAnalysisStore((s) => s.pdfExportStage);
  const pdfError = useAnalysisStore((s) => s.pdfExportError);
  const pdfElapsed = useElapsedSeconds(pdfStage === 'generating' || pdfStage === 'preparing');

  const pdfSections = useAnalysisStore((s) => s.pdfSections);
  const setPdfSections = useAnalysisStore((s) => s.setPdfSections);

  const hasSuccessfulSplit = analysisResult?.orchestration?.status === 'generated';

  // Default the "Core / Cavity (solid split)" checkbox from whether the
  // CURRENT on-screen result already has one -- a reasonable starting
  // point the engineer can still override, re-synced whenever the
  // underlying result changes (a fresh Guided/Manual run).
  useEffect(() => {
    setPdfSections({ ...useAnalysisStore.getState().pdfSections, solidSplit: hasSuccessfulSplit });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisResult]);

  const stepDisabled = !currentPart || !pullDirection || !hasSuccessfulSplit || stepStage === 'generating' || stepStage === 'preparing';
  const pdfDisabled = !currentPart || !pullDirection || pdfStage === 'generating' || pdfStage === 'preparing';

  return (
    <div className={styles.panel} data-testid="export-panel">
      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>STEP Mold-Half Export</h4>
        {!hasSuccessfulSplit && (
          <p className={styles.hint} data-testid="step-export-gate-hint">
            {analysisResult
              ? 'Requires a successful core/cavity solid split for the current result. Run an analysis that reaches "Feasible — mold split generated" first.'
              : 'Run an analysis first.'}
          </p>
        )}

        <button
          type="button"
          className={styles.actionButton}
          disabled={stepDisabled}
          onClick={() => void runStepExport()}
        >
          Export STEP
        </button>

        <StageReadout stage={stepStage} elapsedSeconds={stepElapsed} label="STEP export" />

        {stepStage === 'failed' && stepError && (
          <p className={styles.error} data-testid="step-export-error">
            {stepError}
          </p>
        )}

        {stepStage === 'complete' && stepResult && (
          <div className={styles.resultCard} data-testid="step-export-result">
            <p className={styles.resultLine}>
              ✓ {stepResult.solidCount} solid(s), {formatBytes(stepResult.fileSizeBytes)}, AP214.
            </p>
            <a
              className={styles.downloadLink}
              href={stepDownloadUrl(stepResult.downloadFilename)}
              download={stepResult.downloadFilename}
              data-testid="step-download-link"
            >
              Download STEP file
            </a>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>PDF Report Builder</h4>
        <p className={styles.hint}>
          An engineering communication document -- verdicts, tables, warnings -- not a raw data
          dump. Choose which available sections to include.
        </p>

        <div className={styles.sectionList} data-testid="pdf-section-list">
          <label className={styles.sectionRow}>
            <input
              type="checkbox"
              checked={pdfSections.executiveSummary}
              onChange={(e) => setPdfSections({ ...pdfSections, executiveSummary: e.target.checked })}
            />
            <span>Executive Summary</span>
          </label>

          <label className={styles.sectionRow} title="Always included -- the backend has no flag to omit it.">
            <input type="checkbox" checked disabled />
            <span>Part / Geometry <em className={styles.fixedNote}>(always included)</em></span>
          </label>

          <label
            className={styles.sectionRow}
            title="Not available: generating a report never re-runs the optimizer search (it would repeat expensive computation this workspace deliberately avoids), and the backend only renders this section for a report generated from an optimizer run."
          >
            <input type="checkbox" disabled />
            <span>Pull Direction <em className={styles.fixedNote}>(not available)</em></span>
          </label>

          <label className={styles.sectionRow} title="Always included -- the backend has no flag to omit it.">
            <input type="checkbox" checked disabled />
            <span>Parting Line <em className={styles.fixedNote}>(always included)</em></span>
          </label>

          <label className={styles.sectionRow} title="Face classification is always included; the Boolean solid split below is optional.">
            <input type="checkbox" checked disabled />
            <span>Core / Cavity classification <em className={styles.fixedNote}>(always included)</em></span>
          </label>

          <label className={styles.sectionRow}>
            <input
              type="checkbox"
              checked={pdfSections.solidSplit}
              onChange={(e) => setPdfSections({ ...pdfSections, solidSplit: e.target.checked })}
            />
            <span>Core / Cavity Boolean solid split</span>
          </label>

          <label className={styles.sectionRow} title="Always included -- the backend has no flag to omit it.">
            <input type="checkbox" checked disabled />
            <span>Undercuts <em className={styles.fixedNote}>(always included)</em></span>
          </label>

          <label className={styles.sectionRow} title="Generates additional side-core analysis as part of report generation -- real, independent computation, adds time.">
            <input
              type="checkbox"
              checked={pdfSections.sideCores}
              onChange={(e) => setPdfSections({ ...pdfSections, sideCores: e.target.checked })}
            />
            <span>Side Cores <em className={styles.fixedNote}>(adds computation time)</em></span>
          </label>

          <label
            className={styles.sectionRow}
            title="Not available: the PDF backend has no dedicated diagnostics section (kept as a real engineering document, not a dashboard dump). See the in-app Diagnostics workspace instead."
          >
            <input type="checkbox" disabled />
            <span>Diagnostics / Metrics <em className={styles.fixedNote}>(not available)</em></span>
          </label>
        </div>

        <button
          type="button"
          className={styles.actionButton}
          disabled={pdfDisabled}
          onClick={() => void runPdfExport()}
        >
          Generate &amp; Download PDF
        </button>

        <StageReadout stage={pdfStage} elapsedSeconds={pdfElapsed} label="PDF report" />

        {pdfStage === 'failed' && pdfError && (
          <p className={styles.error} data-testid="pdf-export-error">
            {pdfError}
          </p>
        )}
        {pdfStage === 'complete' && (
          <p className={styles.resultLine} data-testid="pdf-export-complete">
            ✓ Report downloaded.
          </p>
        )}
      </section>
    </div>
  );
}
