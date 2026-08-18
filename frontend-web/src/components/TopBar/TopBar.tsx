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
import { readViewportBackground, useTheme } from '../../theme/useTheme';
import { getViewportEngine } from '../../viewport/engineSingleton';
import { useEffect, useRef, useState } from 'react';
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
  const { theme, toggleTheme } = useTheme();

  // F13 §2: a real click-toggled popover -- the previous `title` attribute
  // relied on the browser's native hover tooltip, which is slow, easy to
  // miss, and unreliable across browsers/devices; a click target is always
  // discoverable and works the same way on desktop and touch.
  const [showModeInfo, setShowModeInfo] = useState(false);
  const modeInfoRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!showModeInfo) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (modeInfoRef.current && !modeInfoRef.current.contains(event.target as Node)) {
        setShowModeInfo(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [showModeInfo]);

  // The three.js scene background is a real THREE.Color, not CSS -- it must
  // be re-read and re-applied explicitly whenever the theme flips (mount
  // included, so a page load that restores 'light' from localStorage still
  // paints the correct viewport ground, not the dark default baked into
  // ViewportEngine's constructor).
  useEffect(() => {
    getViewportEngine().setBackgroundColor(readViewportBackground());
  }, [theme]);

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

      <div className={styles.modeGroup} ref={modeInfoRef}>
        <div className={styles.modeToggle} role="group" aria-label="Workstation mode">
          <button
            type="button"
            className={mode === 'guided' ? styles.modeButtonActive : styles.modeButton}
            onClick={() => setMode('guided')}
          >
            Guided (Recommended)
          </button>
          <button
            type="button"
            className={mode === 'expert' ? styles.modeButtonActive : styles.modeButton}
            onClick={() => setMode('expert')}
          >
            Expert
          </button>
        </div>
        <button
          type="button"
          className={styles.modeInfo}
          onClick={() => setShowModeInfo((v) => !v)}
          aria-expanded={showModeInfo}
          aria-label="What do Guided and Expert mean?"
        >
          ⓘ
        </button>
        {showModeInfo && (
          <div className={styles.modeInfoPopover} role="dialog" data-testid="mode-info-popover">
            <p>
              <strong>Guided (Recommended)</strong> — the normal DfM workflow. Follow the recommended analysis
              sequence from import → draft → pull direction → undercuts → parting line → core/cavity → side
              actions.
            </p>
            <p>
              <strong>Expert</strong> — advanced engineering workflow. Provides individual analysis controls,
              manual direction testing, authorization configuration, and lower-level diagnostic information.
            </p>
            <p className={styles.modeInfoFootnote}>
              Both modes read and write the SAME analysis state. Switching between them never reruns analysis,
              resets results, or changes what was analyzed.
            </p>
          </div>
        )}
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
          title={
            currentPart
              ? 'Run direction search, core/cavity split, draft, undercuts, parting-line curve, and a side-core check'
              : 'Load a part first'
          }
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

      <button
        type="button"
        className={styles.themeToggle}
        onClick={toggleTheme}
        title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
        aria-label="Toggle theme"
      >
        {theme === 'dark' ? '☾' : '☀'}
      </button>

      <span
        className={styles.connectivityDot}
        data-connectivity={backendConnectivity}
        title={`Backend: ${backendConnectivity}`}
      />
    </header>
  );
}
