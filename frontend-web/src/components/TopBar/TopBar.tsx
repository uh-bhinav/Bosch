/**
 * Top bar: product identity, current part, mode toggle, pipeline status,
 * export entry point. F1 renders these as real, wired-to-store controls
 * where the store already has a value (part name, mode) and inert
 * placeholders where it doesn't yet (export -- no analysis exists to
 * export in F1).
 *
 * F3 adds the Guided "Run full analysis" primary action here (F0 §4.1:
 * "one button runs the full pipeline") -- visible whenever a part is
 * loaded, not gated to Guided mode specifically, since both modes read the
 * SAME shared analysis result (F0 §2: "mode is a lens on the state, not a
 * separate state tree").
 */

import { runGuidedAnalysis } from '../../analysis/runGuidedAnalysis';
import { stageLabelForElapsed, useElapsedSeconds } from '../../analysis/useElapsedSeconds';
import { useAnalysisStore } from '../../store/analysisStore';
import styles from './TopBar.module.css';

const PIPELINE_LABEL: Record<string, string> = {
  idle: 'Idle',
  running: 'Running',
  complete: 'Complete',
  blocked: 'Blocked',
};

export function TopBar() {
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const mode = useAnalysisStore((s) => s.mode);
  const setMode = useAnalysisStore((s) => s.setMode);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const backendConnectivity = useAnalysisStore((s) => s.backendConnectivity);
  const isRunning = pipelineStatus === 'running';
  const elapsedSeconds = useElapsedSeconds(isRunning);

  return (
    <header className={styles.topBar}>
      <div className={styles.identity}>
        <span className={styles.mark}>MW</span>
        <span className={styles.productName}>Mold Workstation</span>
      </div>

      <div className={styles.partSlot}>
        {currentPart ? (
          <span className={styles.partName} data-testid="topbar-part-name">{currentPart}</span>
        ) : (
          <span className={styles.partNamePlaceholder}>No part loaded</span>
        )}
      </div>

      <div className={styles.spacer} />

      <div className={styles.modeToggle} role="group" aria-label="Workstation mode">
        <button
          type="button"
          className={mode === 'guided' ? styles.modeButtonActive : styles.modeButton}
          onClick={() => setMode('guided')}
        >
          Guided
        </button>
        <button
          type="button"
          className={mode === 'expert' ? styles.modeButtonActive : styles.modeButton}
          onClick={() => setMode('expert')}
        >
          Expert
        </button>
      </div>

      {isRunning ? (
        <span className={styles.runProgress} data-testid="run-analysis-progress">
          {stageLabelForElapsed(elapsedSeconds)} ({elapsedSeconds}s)
        </span>
      ) : (
        <button
          type="button"
          className={styles.runButton}
          disabled={!currentPart}
          title={currentPart ? 'Run direction search, parting line, and core/cavity split' : 'Load a part first'}
          onClick={() => void runGuidedAnalysis()}
        >
          Run Full Analysis
        </button>
      )}

      <div className={styles.pipelineStatus} data-status={pipelineStatus}>
        <span className={styles.statusDot} />
        {PIPELINE_LABEL[pipelineStatus]}
      </div>

      <button type="button" className={styles.exportButton} disabled title="Nothing to export yet">
        Export
      </button>

      <span
        className={styles.connectivityDot}
        data-connectivity={backendConnectivity}
        title={`Backend: ${backendConnectivity}`}
      />
    </header>
  );
}
