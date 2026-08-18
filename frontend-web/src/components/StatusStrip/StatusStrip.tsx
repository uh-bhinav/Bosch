/**
 * Bottom status strip: collapsed to one compact line by default (F1 spec,
 * "BOTTOM STATUS STRIP"). Expanding it in F1 only reveals a slightly fuller
 * placeholder summary -- the real tiered diagnostics workspace (F0 §6) is
 * still out of scope (H0-H7 per-gate detail etc.); F3 adds the one-line
 * Guided analysis verdict (F0 §3.1: "a single status line... progressive
 * disclosure -- this is where H0-H7/OCC detail lives, never in the
 * inspector by default") using `describeAnalysisOutcome`, never inventing
 * its own interpretation of the orchestration result.
 */

import { useState } from 'react';
import { describeAnalysisOutcome } from '../../analysis/describeAnalysisOutcome';
import { TOOLS } from '../../domain/types';
import { useAnalysisStore } from '../../store/analysisStore';
import styles from './StatusStrip.module.css';

const PIPELINE_LABEL: Record<string, string> = {
  idle: 'Idle',
  running: 'Running',
  complete: 'Complete',
  blocked: 'Blocked',
};

export function StatusStrip() {
  const [expanded, setExpanded] = useState(false);
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const activeTool = useAnalysisStore((s) => s.activeTool);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const backendConnectivity = useAnalysisStore((s) => s.backendConnectivity);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const analysisError = useAnalysisStore((s) => s.analysisError);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const pullDirectionSource = useAnalysisStore((s) => s.pullDirectionSource);

  const tool = TOOLS.find((t) => t.id === activeTool);
  const verdict = describeAnalysisOutcome(analysisResult);

  return (
    <footer className={styles.strip} data-expanded={expanded}>
      <button
        type="button"
        className={styles.summaryRow}
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span className={styles.readyTag}>{PIPELINE_LABEL[pipelineStatus].toUpperCase()}</span>
        <span className={styles.summaryItem}>Part: {currentPart ?? '—'}</span>
        <span className={styles.summaryItem}>Tool: {tool?.label}</span>
        {verdict && (
          <span className={styles.verdictBadge} data-tone={verdict.tone} data-testid="analysis-verdict-badge">
            {verdict.label}
          </span>
        )}
        <span className={styles.summaryItem}>Backend: {backendConnectivity}</span>
        <span className={styles.chevron}>{expanded ? '▾' : '▴'}</span>
      </button>

      {expanded && (
        <div className={styles.details} data-testid="status-strip-details">
          <div className={styles.detailRow}>
            <span>Pipeline</span>
            <span>{PIPELINE_LABEL[pipelineStatus]}</span>
          </div>
          <div className={styles.detailRow}>
            <span>Active tool</span>
            <span>{tool?.label}</span>
          </div>
          <div className={styles.detailRow}>
            <span>Current part</span>
            <span>{currentPart ?? 'None'}</span>
          </div>
          <div className={styles.detailRow}>
            <span>Pull direction</span>
            <span>
              {pullDirection
                ? `(${pullDirection.map((v) => v.toFixed(3)).join(', ')}) — ${pullDirectionSource ?? 'unknown source'}`
                : 'Not resolved'}
            </span>
          </div>
          {verdict && (
            <div className={styles.detailRow} data-testid="analysis-verdict-detail">
              <span>Analysis result</span>
              <span data-tone={verdict.tone} className={styles.verdictText}>
                {verdict.label}
                {verdict.detail ? ` — ${verdict.detail}` : ''}
              </span>
            </div>
          )}
          {analysisError && (
            <div className={styles.detailRow} data-testid="analysis-error-detail">
              <span>Analysis error</span>
              <span className={styles.errorText}>{analysisError}</span>
            </div>
          )}
          <p className={styles.detailNote}>
            Full diagnostics workspace (geometry, pull-direction search, parting-line
            validation, core/cavity, undercuts, side cores, runtime, advanced) arrives with
            the Diagnostics tool in a later phase.
          </p>
        </div>
      )}
    </footer>
  );
}
