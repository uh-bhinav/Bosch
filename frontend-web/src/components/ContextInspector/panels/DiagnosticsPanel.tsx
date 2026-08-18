/**
 * The Diagnostics workspace (F5) -- explains the system's conclusions to
 * an engineer, using F0's three-tier hierarchy (Tier 1 conclusion / Tier 2
 * evidence / Tier 3 raw). Reads ONLY the already-fetched shared analysis
 * state (`analysisResult`/`recommendedResult`/`currentPartSummary`/
 * `pullDirection`, all populated by F1-F4) through the pure
 * `deriveDiagnostics` function -- makes zero API calls of its own, never
 * reruns analysis, and never holds a second copy of the result.
 */

import { useMemo } from 'react';
import { deriveDiagnostics } from '../../../diagnostics/deriveDiagnostics';
import { useAnalysisStore } from '../../../store/analysisStore';
import { DiagnosticGroupCard } from './DiagnosticGroupCard';
import styles from './DiagnosticsPanel.module.css';

export function DiagnosticsPanel() {
  const currentPartSummary = useAnalysisStore((s) => s.currentPartSummary);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const recommendedResult = useAnalysisStore((s) => s.recommendedResult);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const pullDirectionSource = useAnalysisStore((s) => s.pullDirectionSource);
  const lastRunDurationMs = useAnalysisStore((s) => s.lastRunDurationMs);

  const model = useMemo(
    () =>
      deriveDiagnostics({
        currentPartSummary,
        analysisResult,
        recommendedResult,
        pullDirection,
        pullDirectionSource,
        lastRunDurationMs,
      }),
    [currentPartSummary, analysisResult, recommendedResult, pullDirection, pullDirectionSource, lastRunDurationMs],
  );

  if (!model.hasPart) {
    return (
      <p className={styles.hint} data-testid="diagnostics-empty">
        Load a part to see diagnostics.
      </p>
    );
  }

  return (
    <div className={styles.panel} data-testid="diagnostics-panel">
      <p className={styles.note}>
        Explains the current analysis result -- not a metric dump. Each section starts collapsed;
        click a title for the conclusion, "Details" for supporting evidence, "Advanced" for raw
        engineering data.
      </p>
      {model.groups.map((group) => (
        <DiagnosticGroupCard key={group.id} group={group} />
      ))}
    </div>
  );
}
