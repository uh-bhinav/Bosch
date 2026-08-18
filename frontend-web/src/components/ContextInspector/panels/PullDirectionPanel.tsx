/**
 * The Pull Direction workstation tool (F4).
 *
 * Two sources, one shared result:
 * - Recommended: the optimizer's winning direction, read straight from
 *   `recommendedResult` (set only by the Guided "Run Full Analysis" run,
 *   `runGuidedAnalysis.ts` -- this panel never re-runs or re-derives it).
 * - Manual: X/Y/Z vector input, axis presets, and "use selected face
 *   normal" (a convenience pre-fill from the viewport's already-loaded
 *   mesh geometry, `ViewportEngine.getFaceNormal`) feed a RAW, unnormalized
 *   direction straight to `runManualAnalysis.ts` -- this panel performs no
 *   normalization or zero-vector rejection of its own; backend C16
 *   (`resolve_manual_direction_mold`/`prepare_manual_direction`) is the one
 *   authority, and `invalid_direction` is just another orchestration status
 *   this panel displays via `describeAnalysisOutcome`, not a client-side
 *   error.
 *
 * `analysisResult`/`pullDirection`/`pullDirectionSource` stay the single
 * "current active result," exactly as F3 established -- a manual run
 * replaces them the same way a guided run does. `recommendedResult` is a
 * separate, untouched snapshot so the two stay comparable.
 */

import { useState } from 'react';
import { describeAnalysisOutcome } from '../../../analysis/describeAnalysisOutcome';
import { runManualAnalysis } from '../../../analysis/runManualAnalysis';
import type { Vec3 } from '../../../domain/types';
import { useAnalysisStore } from '../../../store/analysisStore';
import { getViewportEngine } from '../../../viewport/engineSingleton';
import { AuthorizationEditor } from './AuthorizationEditor';
import { Legend } from './Legend';
import styles from './PullDirectionPanel.module.css';

const AXIS_PRESETS: { label: string; value: Vec3 }[] = [
  { label: '+X', value: [1, 0, 0] },
  { label: '−X', value: [-1, 0, 0] },
  { label: '+Y', value: [0, 1, 0] },
  { label: '−Y', value: [0, -1, 0] },
  { label: '+Z', value: [0, 0, 1] },
  { label: '−Z', value: [0, 0, -1] },
];

function formatVec3(v: Vec3, digits = 3): string {
  return `(${v.map((c) => c.toFixed(digits)).join(', ')})`;
}

function toTuple3(text: [string, string, string]): Vec3 {
  return [Number(text[0]), Number(text[1]), Number(text[2])];
}

export function PullDirectionPanel() {
  const mode = useAnalysisStore((s) => s.mode);
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const recommendedResult = useAnalysisStore((s) => s.recommendedResult);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const analysisError = useAnalysisStore((s) => s.analysisError);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const pullDirectionSource = useAnalysisStore((s) => s.pullDirectionSource);
  const manualPullDirection = useAnalysisStore((s) => s.manualPullDirection);
  const setManualPullDirection = useAnalysisStore((s) => s.setManualPullDirection);
  const corePinFaceRefs = useAnalysisStore((s) => s.corePinFaceRefs);
  const delegations = useAnalysisStore((s) => s.delegations);
  const selectedFaceIds = useAnalysisStore((s) => s.selectedFaceIds);

  const [vectorText, setVectorText] = useState<[string, string, string]>(
    manualPullDirection.map(String) as [string, string, string],
  );
  const [showAuthorization, setShowAuthorization] = useState(false);

  const isRunning = pipelineStatus === 'running';
  const recommendedVerdict = describeAnalysisOutcome(recommendedResult);
  const currentVerdict = describeAnalysisOutcome(analysisResult);

  // F7: both direction arrows (the already-resolved direction, and this
  // tool's own live manual-edit preview) are now driven centrally by
  // `viewport/useOverlaySync.ts` -- it reads this same `manualPullDirection`
  // store field, so no per-panel effect is needed here.

  const commitVector = (next: [string, string, string]) => {
    setVectorText(next);
    const parsed = toTuple3(next);
    if (parsed.every(Number.isFinite)) {
      setManualPullDirection(parsed);
    }
  };

  const applyPreset = (value: Vec3) => {
    setManualPullDirection(value);
    setVectorText(value.map(String) as [string, string, string]);
  };

  const useSelectedFaceNormal = () => {
    if (selectedFaceIds.length !== 1) return;
    const normal = getViewportEngine().getFaceNormal(selectedFaceIds[0]);
    if (normal) applyPreset(normal);
  };

  const parsedVector = toTuple3(vectorText);
  const canRunManual = currentPart !== null && !isRunning && parsedVector.every(Number.isFinite);

  return (
    <div className={styles.panel} data-testid="pull-direction-panel">
      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Recommended</h4>
        <p className={styles.hint}>
          The automatic optimizer's own search result -- it may pick a different axis than any specific direction
          you expect (e.g. not +Z), because it searches for a direction that is ALREADY feasible with no
          authorization needed. A direction that only becomes feasible WITH engineering authorization (see Parting
          Line / Engineering Authorization) is a separate, deliberately-chosen manual case below, not
          something the optimizer will find on its own.
        </p>
        {recommendedResult && recommendedVerdict ? (
          <div className={styles.resultCard} data-testid="recommended-result-card">
            <div className={styles.resultRow}>
              <span>Direction</span>
              <span className={styles.mono}>
                {recommendedResult.orchestration?.pull_direction
                  ? formatVec3(recommendedResult.orchestration.pull_direction)
                  : '—'}
              </span>
            </div>
            <div className={styles.resultRow}>
              <span>Result</span>
              <span data-tone={recommendedVerdict.tone} className={styles.verdict}>
                {recommendedVerdict.label}
              </span>
            </div>
          </div>
        ) : (
          <p className={styles.hint} data-testid="recommended-result-empty">
            Run "Run Full Analysis" in the top bar to see the optimizer's recommended direction.
          </p>
        )}
      </section>

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Manual (Expert)</h4>
        {mode === 'guided' && (
          <p className={styles.hint}>
            Guided mode resolves the pull direction automatically via "Run Full Analysis." These manual controls
            still work in Guided mode too -- switch to Expert for the focused manual/authoritative workflow.
          </p>
        )}
        <Legend
          items={[
            { color: 'var(--accent)', label: 'Resolved direction (current result, every tool)' },
            { color: 'var(--vis-pull-direction-manual-preview)', label: "This tool's live edit preview" },
          ]}
        />

        <div className={styles.vectorRow}>
          {(['X', 'Y', 'Z'] as const).map((axis, i) => (
            <label key={axis} className={styles.vectorField}>
              <span>{axis}</span>
              <input
                type="text"
                inputMode="decimal"
                aria-label={`Manual pull direction ${axis} component`}
                className={styles.vectorInput}
                value={vectorText[i]}
                onChange={(e) => {
                  const next = [...vectorText] as [string, string, string];
                  next[i] = e.target.value;
                  commitVector(next);
                }}
              />
            </label>
          ))}
        </div>

        <div className={styles.presetRow}>
          {AXIS_PRESETS.map((preset) => (
            <button
              key={preset.label}
              type="button"
              className={styles.presetButton}
              onClick={() => applyPreset(preset.value)}
            >
              {preset.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          className={styles.presetButton}
          disabled={selectedFaceIds.length !== 1}
          onClick={useSelectedFaceNormal}
          title={
            selectedFaceIds.length === 1
              ? `Use face ${selectedFaceIds[0]}'s normal as the pull direction`
              : 'Select exactly one face in the viewport first'
          }
        >
          Use selected face normal
        </button>

        <button
          type="button"
          className={styles.authorizationToggle}
          onClick={() => setShowAuthorization((v) => !v)}
          aria-expanded={showAuthorization}
        >
          Authorization{' '}
          {corePinFaceRefs.length + delegations.length > 0
            ? `(${corePinFaceRefs.length + delegations.length})`
            : ''}{' '}
          {showAuthorization ? '▾' : '▸'}
        </button>
        {showAuthorization && <AuthorizationEditor />}

        <button
          type="button"
          className={styles.runButton}
          disabled={!canRunManual}
          onClick={() => void runManualAnalysis(parsedVector, corePinFaceRefs, delegations)}
        >
          Run Manual Analysis
        </button>
      </section>

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Current result</h4>
        {analysisError && (
          <p className={styles.error} data-testid="pull-direction-error">
            {analysisError}
          </p>
        )}
        {!analysisError && currentVerdict && (
          <div className={styles.resultCard} data-testid="current-result-card">
            <div className={styles.resultRow}>
              <span>Direction</span>
              <span className={styles.mono}>{pullDirection ? formatVec3(pullDirection) : '—'}</span>
            </div>
            <div className={styles.resultRow}>
              <span>Source</span>
              <span className={styles.mono}>{pullDirectionSource ?? '—'}</span>
            </div>
            <div className={styles.resultRow}>
              <span>Result</span>
              <span data-tone={currentVerdict.tone} className={styles.verdict}>
                {currentVerdict.label}
              </span>
            </div>
            {currentVerdict.detail && <p className={styles.detail}>{currentVerdict.detail}</p>}
            {analysisResult?.orchestration && (
              <div className={styles.resultRow}>
                <span>Delegated / excluded faces</span>
                <span className={styles.mono}>
                  {analysisResult.orchestration.delegated_face_ids.length} /{' '}
                  {analysisResult.orchestration.excluded_feature_ids.length}
                </span>
              </div>
            )}
          </div>
        )}
        {!analysisError && !currentVerdict && (
          <p className={styles.hint} data-testid="current-result-empty">
            No analysis has run yet for this part.
          </p>
        )}
      </section>

      {recommendedResult && recommendedVerdict && pullDirectionSource === 'manual' && currentVerdict && (
        <section className={styles.section}>
          <h4 className={styles.sectionTitle}>Comparison</h4>
          <div className={styles.compareGrid} data-testid="comparison-table">
            <div />
            <div className={styles.compareHeader}>Recommended</div>
            <div className={styles.compareHeader}>Manual</div>

            <div className={styles.compareLabel}>Direction</div>
            <div className={styles.mono}>
              {recommendedResult.orchestration?.pull_direction
                ? formatVec3(recommendedResult.orchestration.pull_direction)
                : '—'}
            </div>
            <div className={styles.mono}>{pullDirection ? formatVec3(pullDirection) : '—'}</div>

            <div className={styles.compareLabel}>Result</div>
            <div data-tone={recommendedVerdict.tone} className={styles.verdict}>
              {recommendedVerdict.label}
            </div>
            <div data-tone={currentVerdict.tone} className={styles.verdict}>
              {currentVerdict.label}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
