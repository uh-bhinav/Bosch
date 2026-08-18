/**
 * F3: read-only Expert-mode display of the Guided analysis result (F3 spec:
 * "Expert tool panels may display available results, but do not implement
 * their independent execution workflows yet"). Shown for the three tools
 * the single `/core-cavity` orchestration call actually covers -- Pull
 * Direction, Parting Line, Core/Cavity -- reading straight from the shared
 * `analysisResult`/`analysisError`, never re-fetching or re-deriving
 * anything of its own. If no analysis has run yet, or a different part is
 * now loaded than the one the result was computed for, this shows a plain
 * "run analysis" nudge instead of stale data.
 */

import { describeAnalysisOutcome } from '../../../analysis/describeAnalysisOutcome';
import { useAnalysisStore } from '../../../store/analysisStore';
import styles from './AnalysisSummaryPanel.module.css';

export function AnalysisSummaryPanel() {
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const analysisError = useAnalysisStore((s) => s.analysisError);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);

  const verdict = describeAnalysisOutcome(analysisResult);

  if (pipelineStatus === 'running') {
    return <p className={styles.note} data-testid="analysis-summary-running">Analysis is running…</p>;
  }

  if (analysisError) {
    return (
      <p className={styles.error} data-testid="analysis-summary-error">
        {analysisError}
      </p>
    );
  }

  if (!analysisResult || !verdict) {
    return (
      <p className={styles.note} data-testid="analysis-summary-empty">
        No analysis has run yet. Use "Run Full Analysis" in the top bar.
      </p>
    );
  }

  const faceCounts = (analysisResult.core_cavity as { face_counts?: Record<string, number> } | undefined)
    ?.face_counts;

  return (
    <div className={styles.panel} data-testid="analysis-summary-panel">
      <div className={styles.verdictRow} data-tone={verdict.tone}>
        <span className={styles.verdictDot} />
        <span>{verdict.label}</span>
      </div>
      {verdict.detail && <p className={styles.detail}>{verdict.detail}</p>}
      {faceCounts && (
        <dl className={styles.grid}>
          <div>
            <dt>Cavity faces</dt>
            <dd>{faceCounts.cavity ?? 0}</dd>
          </div>
          <div>
            <dt>Core faces</dt>
            <dd>{faceCounts.core ?? 0}</dd>
          </div>
          <div>
            <dt>Parting faces</dt>
            <dd>{faceCounts.parting ?? 0}</dd>
          </div>
          <div>
            <dt>Skipped</dt>
            <dd>{faceCounts.skipped ?? 0}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
