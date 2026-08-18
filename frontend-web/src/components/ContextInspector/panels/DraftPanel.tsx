/**
 * F7: the Draft tool's real panel -- draft-angle classification counts,
 * area percentages, severity, and per-classification face selection, read
 * straight from `store.draftResult` (`GET /parts/{filename}/draft`, fetched
 * automatically as part of Full/Manual Analysis's follow-up sweep, or on
 * demand via "Run Draft Analysis"). Viewport highlighting is handled
 * centrally by `viewport/useOverlaySync.ts` whenever this tool is active --
 * this component only renders numbers, the legend, and selection buttons.
 *
 * F13 §4: a separate "Inspect another direction" control lets the engineer
 * look at draft classification for ANY direction (e.g. the engineering-
 * authorized candidate, or a direction under consideration) without
 * mutating `pullDirection`/`manualPullDirection` or the resolved
 * `draftResult` snapshot -- it writes only `draftInspect*` store fields via
 * `runDraftInspect`, and the viewport (`useOverlaySync.ts`) prefers that
 * inspection result over the resolved one only while it is active.
 */

import { useState } from 'react';
import { runDraftInspect, runDraftOnly } from '../../../analysis/runIndividualAnalyses';
import type { Vec3 } from '../../../domain/types';
import { useAnalysisStore } from '../../../store/analysisStore';
import { Legend } from './Legend';
import styles from './sharedPanel.module.css';

const DRAFT_LEGEND = [
  { key: 'good', color: 'var(--vis-draft-good)', label: 'Good draft (≥ threshold)' },
  { key: 'marginal', color: 'var(--vis-draft-marginal)', label: 'Marginal draft' },
  { key: 'bad', color: 'var(--vis-draft-bad)', label: 'Bad / insufficient draft' },
  { key: 'skipped', color: 'var(--vis-draft-skipped)', label: 'Skipped (not analysed)' },
] as const;

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

function DraftResultBlock({
  draft,
  onSelectFaces,
}: {
  draft: NonNullable<ReturnType<typeof useAnalysisStore.getState>['draftResult']>['draft'];
  onSelectFaces: (ids: number[]) => void;
}) {
  return (
    <>
      <div className={styles.resultCard}>
        <div className={styles.resultRow}>
          <span>Direction used</span>
          <span className={styles.mono}>{formatVec3(draft.pull_direction)}</span>
        </div>
        <div className={styles.resultRow}>
          <span>Severity</span>
          <span className={styles.mono}>{draft.severity}</span>
        </div>
        <div className={styles.resultRow}>
          <span>Manufacturable</span>
          <span className={styles.mono}>{draft.is_manufacturable ? 'Yes' : 'No'}</span>
        </div>
        <div className={styles.resultRow}>
          <span>Bad-area %</span>
          <span className={styles.mono}>{draft.percentages.bad_pct.toFixed(1)}%</span>
        </div>
      </div>

      <dl className={styles.grid}>
        <div>
          <dt>Good faces</dt>
          <dd>{draft.face_counts.good}</dd>
        </div>
        <div>
          <dt>Marginal faces</dt>
          <dd>{draft.face_counts.marginal}</dd>
        </div>
        <div>
          <dt>Bad faces</dt>
          <dd>{draft.face_counts.bad}</dd>
        </div>
        <div>
          <dt>Skipped faces</dt>
          <dd>{draft.face_counts.skipped}</dd>
        </div>
      </dl>

      <div className={styles.section}>
        <Legend
          items={DRAFT_LEGEND.map((entry) => ({
            color: entry.color,
            label: entry.label,
            count: draft.face_counts[entry.key],
          }))}
        />
        <div className={styles.section}>
          {DRAFT_LEGEND.map((entry) => {
            const ids = draft.face_ids?.[entry.key] ?? [];
            if (ids.length === 0) return null;
            return (
              <button
                key={entry.key}
                type="button"
                className={styles.faceListButton}
                onClick={() => onSelectFaces(ids)}
                title={`Select the ${ids.length} ${entry.label.toLowerCase()} face(s) in the viewport`}
              >
                Select {ids.length} {entry.key} face{ids.length === 1 ? '' : 's'}
              </button>
            );
          })}
        </div>
      </div>

      {draft.suggestions.length > 0 && (
        <div className={styles.section}>
          <h4 className={styles.sectionTitle}>Suggestions</h4>
          {draft.suggestions.slice(0, 5).map((suggestion, i) => (
            <p key={i} className={styles.note}>
              • {suggestion.action_text}
            </p>
          ))}
        </div>
      )}
    </>
  );
}

export function DraftPanel() {
  const mode = useAnalysisStore((s) => s.mode);
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const draftResult = useAnalysisStore((s) => s.draftResult);
  const draftStage = useAnalysisStore((s) => s.draftStage);
  const draftError = useAnalysisStore((s) => s.draftError);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const setSelectedFaceIds = useAnalysisStore((s) => s.setSelectedFaceIds);

  const draftInspectDirection = useAnalysisStore((s) => s.draftInspectDirection);
  const draftInspectResult = useAnalysisStore((s) => s.draftInspectResult);
  const draftInspectStage = useAnalysisStore((s) => s.draftInspectStage);
  const draftInspectError = useAnalysisStore((s) => s.draftInspectError);
  const setDraftInspectDirection = useAnalysisStore((s) => s.setDraftInspectDirection);
  const setDraftInspectResult = useAnalysisStore((s) => s.setDraftInspectResult);
  const setDraftInspectStage = useAnalysisStore((s) => s.setDraftInspectStage);
  const setDraftInspectError = useAnalysisStore((s) => s.setDraftInspectError);

  const [vectorText, setVectorText] = useState<[string, string, string]>(['0', '0', '1']);

  const isRunning = draftStage === 'running' || pipelineStatus === 'running';
  const draft = draftResult?.draft;
  const inspecting = draftInspectDirection !== null;
  const isInspecting = draftInspectStage === 'running';

  const commitVector = (next: [string, string, string]) => setVectorText(next);
  const parsedVector = toTuple3(vectorText);
  const canInspect = currentPart !== null && !isInspecting && parsedVector.every(Number.isFinite);

  const startInspecting = (direction: Vec3) => {
    setVectorText(direction.map(String) as [string, string, string]);
    setDraftInspectDirection(direction);
    void runDraftInspect(direction);
  };

  const stopInspecting = () => {
    setDraftInspectDirection(null);
    setDraftInspectResult(null);
    setDraftInspectStage('idle');
    setDraftInspectError(null);
  };

  return (
    <div className={styles.panel} data-testid="draft-panel">
      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Draft Analysis</h4>

        {!currentPart && <p className={styles.hint}>Load a part first.</p>}

        {currentPart && !draft && draftStage !== 'running' && (
          <p className={styles.hint} data-testid="draft-empty">
            No draft analysis yet.{' '}
            {pullDirection
              ? 'Run "Run Full Analysis", or run draft alone at the current pull direction below.'
              : 'Run "Run Full Analysis" first, or run draft alone at the backend default (+Z) below.'}
          </p>
        )}

        {draftStage === 'running' && <p className={styles.hint} data-testid="draft-running">Running draft analysis…</p>}

        {draftError && draftStage === 'error' && (
          <p className={styles.error} data-testid="draft-error">
            {draftError}
          </p>
        )}

        {currentPart && mode === 'expert' && (
          <button
            type="button"
            className={styles.runButton}
            disabled={isRunning}
            onClick={() => void runDraftOnly()}
            title={
              pullDirection
                ? `Run draft analysis only, at the current pull direction (${pullDirection.map((v) => v.toFixed(2)).join(', ')})`
                : 'Run draft analysis only, at the backend default direction (0, 0, 1)'
            }
          >
            Run Draft Analysis
          </button>
        )}
        {currentPart && mode === 'guided' && !draft && (
          <p className={styles.hint}>Switch to Expert mode to run Draft Analysis individually.</p>
        )}
      </section>

      {currentPart && (
        <section className={styles.section} data-testid="draft-inspect-section">
          <h4 className={styles.sectionTitle}>Inspect Another Direction</h4>
          <p className={styles.hint}>
            Preview draft classification at any direction without changing the resolved pull direction used by the
            rest of the analysis. This is a visual inspection only -- it never reruns Pull Direction, Parting Line,
            Core/Cavity, or any other tool.
          </p>

          <label className={styles.inspectToggleRow}>
            <input
              type="checkbox"
              checked={inspecting}
              onChange={(e) => {
                if (e.target.checked) {
                  startInspecting(pullDirection ?? [0, 0, 1]);
                } else {
                  stopInspecting();
                }
              }}
            />
            Inspect another direction
          </label>

          {inspecting && (
            <>
              <div className={styles.vectorRow}>
                {(['X', 'Y', 'Z'] as const).map((axis, i) => (
                  <label key={axis} className={styles.vectorField}>
                    <span>{axis}</span>
                    <input
                      type="text"
                      inputMode="decimal"
                      aria-label={`Inspect draft direction ${axis} component`}
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
                    onClick={() => startInspecting(preset.value)}
                  >
                    {preset.label}
                  </button>
                ))}
                {pullDirection && (
                  <button type="button" className={styles.presetButton} onClick={() => startInspecting(pullDirection)}>
                    Resolved direction
                  </button>
                )}
              </div>

              <button
                type="button"
                className={styles.runButton}
                disabled={!canInspect}
                onClick={() => startInspecting(parsedVector)}
              >
                Preview This Direction
              </button>

              {isInspecting && <p className={styles.hint} data-testid="draft-inspect-running">Fetching draft classification…</p>}
              {draftInspectError && draftInspectStage === 'error' && (
                <p className={styles.error} data-testid="draft-inspect-error">
                  {draftInspectError}
                </p>
              )}
            </>
          )}
        </section>
      )}

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>
          {inspecting ? 'Currently Visualized: Inspection Direction' : 'Currently Visualized: Resolved Direction'}
        </h4>
        <div className={styles.resultRow}>
          <span>Resolved analysis direction</span>
          <span className={styles.mono}>{pullDirection ? formatVec3(pullDirection) : '—'}</span>
        </div>
        <div className={styles.resultRow}>
          <span>Currently visualized draft direction</span>
          <span className={styles.mono}>
            {inspecting && draftInspectDirection
              ? formatVec3(draftInspectDirection)
              : draft
                ? formatVec3(draft.pull_direction)
                : '—'}
          </span>
        </div>
      </section>

      {inspecting && draftInspectResult?.draft && (
        <section className={styles.section} data-testid="draft-inspect-result">
          <h4 className={styles.sectionTitle}>Inspection Result</h4>
          <DraftResultBlock draft={draftInspectResult.draft} onSelectFaces={setSelectedFaceIds} />
        </section>
      )}

      {!inspecting && draft && (
        <section className={styles.section} data-testid="draft-result-card">
          <h4 className={styles.sectionTitle}>Result</h4>
          <DraftResultBlock draft={draft} onSelectFaces={setSelectedFaceIds} />
        </section>
      )}
    </div>
  );
}
