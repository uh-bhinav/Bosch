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
import { createPortal } from 'react-dom';
import styles from './TopBar.module.css';

const PIPELINE_LABEL: Record<string, string> = {
  idle: 'Idle',
  running: 'Running',
  complete: 'Complete',
  blocked: 'Blocked',
  'needs-side-action': 'Needs side action (solution found)',
  'split-failed': 'Faces classified — solid split failed',
};

export function TopBar() {
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const mode = useAnalysisStore((s) => s.mode);
  const setMode = useAnalysisStore((s) => s.setMode);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const sideCoreStatus = useAnalysisStore((s) => s.sideCoreStatus);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const partingLineResult = useAnalysisStore((s) => s.partingLineResult);
  const backendConnectivity = useAnalysisStore((s) => s.backendConnectivity);
  const isRunning = pipelineStatus === 'running';
  const elapsedSeconds = useElapsedSeconds(isRunning);
  const { theme, toggleTheme } = useTheme();

  // `pipelineStatus === 'blocked'` reflects only the primary /core-cavity
  // call's own optimal-direction search (its own `orchestration.status`) --
  // it says nothing about whatever the CURRENT, possibly-authorized rerun
  // actually resolved to. "Blocked" must never just stick at whatever the
  // very first automatic run produced: this is re-derived live from the
  // most current data every render.
  //
  // `currentOutcome` prefers `partingLineResult.outcome` (the latest v2
  // parting-line verdict for the resolved direction -- updated by EITHER a
  // full rerun's follow-up sweep OR an Expert-mode "Parting Line only"
  // authorized rerun, so it reflects an authorization change even before
  // any side-core follow-up has resolved) and falls back to the primary
  // call's own `orchestration.parting_line_v2_outcome` when no parting-line
  // fetch has completed yet. `'referred_to_side_action'` is this app's own
  // established authoritative signal for "needs a side action" (see
  // `SideCoresPanel.tsx`) -- distinct from `sideCoreStatus` (whether a side
  // CORE SOLID was successfully generated for that referral), which lags
  // behind and can independently be 'checking'/'unavailable'/'available'.
  // Either signal is enough to show yellow instead of a stale red.
  const currentOutcome = partingLineResult?.outcome ?? analysisResult?.orchestration?.parting_line_v2_outcome ?? null;
  const needsSideAction =
    currentOutcome === 'referred_to_side_action' ||
    sideCoreStatus === 'available' ||
    sideCoreStatus === 'checking' ||
    sideCoreStatus === 'unavailable';
  // `orchestration.status === 'blocked_by_core_cavity_split'` is a
  // DIFFERENT partial-success case from side-action: the direction search
  // AND the parting-line face classification both genuinely succeeded (the
  // Core/Cavity tab's face counts and "AUTHORITATIVE ANALYSIS" badge are
  // real), only the LATER, separate step -- cutting the tooling blank into
  // exactly 2 Boolean solids with the planar-approximation split tool --
  // failed for this part's geometry (a real, disclosed limitation, not a
  // bug: see CLAUDE.md's honesty rule on `split_tool_kind`). Flat red
  // "Blocked" implies nothing worked, which isn't true here either.
  const splitFailed = analysisResult?.orchestration?.status === 'blocked_by_core_cavity_split';
  const displayStatus: 'idle' | 'running' | 'complete' | 'blocked' | 'needs-side-action' | 'split-failed' =
    pipelineStatus === 'blocked'
      ? needsSideAction
        ? 'needs-side-action'
        : splitFailed
          ? 'split-failed'
          : 'blocked'
      : pipelineStatus;

  // F13 §2: a real click-toggled popover -- the previous `title` attribute
  // relied on the browser's native hover tooltip, which is slow, easy to
  // miss, and unreliable across browsers/devices; a click target is always
  // discoverable and works the same way on desktop and touch.
  //
  // Rendered through a portal into `document.body` rather than inline: the
  // top bar has `overflow-x: auto; overflow-y: hidden` (so the control
  // cluster can scroll horizontally at narrow widths instead of clipping
  // off-screen), and that `overflow-y: hidden` was ALSO clipping this
  // popover -- it renders below the bar's own height, so it was invisible
  // every time despite the click handler firing correctly. A portal escapes
  // that ancestor clipping entirely; position is computed from the trigger
  // button's own screen rect so it still lands directly under it.
  const [showModeInfo, setShowModeInfo] = useState(false);
  const [modeInfoPos, setModeInfoPos] = useState<{ top: number; right: number } | null>(null);
  const modeInfoRef = useRef<HTMLDivElement | null>(null);
  const modeInfoButtonRef = useRef<HTMLButtonElement | null>(null);
  const modeInfoPopoverRef = useRef<HTMLDivElement | null>(null);

  const toggleModeInfo = () => {
    setShowModeInfo((current) => {
      const next = !current;
      if (next && modeInfoButtonRef.current) {
        const rect = modeInfoButtonRef.current.getBoundingClientRect();
        setModeInfoPos({ top: rect.bottom + 8, right: window.innerWidth - rect.right });
      }
      return next;
    });
  };

  useEffect(() => {
    if (!showModeInfo) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (modeInfoRef.current?.contains(target)) return;
      if (modeInfoPopoverRef.current?.contains(target)) return;
      setShowModeInfo(false);
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
          ref={modeInfoButtonRef}
          className={styles.modeInfo}
          onClick={toggleModeInfo}
          aria-expanded={showModeInfo}
          aria-label="What do Guided and Expert mean?"
        >
          ⓘ
        </button>
        {showModeInfo &&
          modeInfoPos &&
          createPortal(
            <div
              ref={modeInfoPopoverRef}
              className={styles.modeInfoPopover}
              style={{ position: 'fixed', top: modeInfoPos.top, right: modeInfoPos.right }}
              role="dialog"
              data-testid="mode-info-popover"
            >
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
            </div>,
            document.body,
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

      <div className={styles.pipelineStatus} data-status={displayStatus} title={
        displayStatus === 'needs-side-action'
          ? sideCoreStatus === 'available'
            ? 'The automatic optimal-direction search did not converge on a plain split, but a side-core solid WAS generated for this direction -- a real manufacturing solution exists, see Side Cores.'
            : 'This direction was referred to a side action rather than a plain split -- see Parting Line / Side Cores for the current authorization/generation status.'
          : displayStatus === 'split-failed'
            ? (analysisResult?.solid_split as { failure_reason?: string } | null)?.failure_reason ??
              "Direction search and face classification both succeeded, but the Boolean solid split (cutting the tooling blank into exactly 2 solids) failed for this part's geometry -- see Core/Cavity for detail."
            : undefined
      }>
        <span className={styles.statusDot} />
        {PIPELINE_LABEL[displayStatus]}
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
