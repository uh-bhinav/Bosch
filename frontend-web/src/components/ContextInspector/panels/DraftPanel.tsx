/**
 * F7: the Draft tool's real panel -- draft-angle classification counts,
 * area percentages, severity, and per-classification face selection, read
 * straight from `store.draftResult` (`GET /parts/{filename}/draft`, fetched
 * automatically as part of Full/Manual Analysis's follow-up sweep, or on
 * demand via "Run Draft Analysis"). Viewport highlighting is handled
 * centrally by `viewport/useOverlaySync.ts` whenever this tool is active --
 * this component only renders numbers, the legend, and selection buttons.
 */

import { runDraftOnly } from '../../../analysis/runIndividualAnalyses';
import { useAnalysisStore } from '../../../store/analysisStore';
import { Legend } from './Legend';
import styles from './sharedPanel.module.css';

const DRAFT_LEGEND = [
  { key: 'good', color: 'var(--vis-draft-good)', label: 'Good draft (≥ threshold)' },
  { key: 'marginal', color: 'var(--vis-draft-marginal)', label: 'Marginal draft' },
  { key: 'bad', color: 'var(--vis-draft-bad)', label: 'Bad / insufficient draft' },
  { key: 'skipped', color: 'var(--vis-draft-skipped)', label: 'Skipped (not analysed)' },
] as const;

export function DraftPanel() {
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const draftResult = useAnalysisStore((s) => s.draftResult);
  const draftStage = useAnalysisStore((s) => s.draftStage);
  const draftError = useAnalysisStore((s) => s.draftError);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const setSelectedFaceIds = useAnalysisStore((s) => s.setSelectedFaceIds);

  const isRunning = draftStage === 'running' || pipelineStatus === 'running';
  const draft = draftResult?.draft;

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

        {currentPart && (
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
      </section>

      {draft && (
        <>
          <section className={styles.section}>
            <h4 className={styles.sectionTitle}>Result</h4>
            <div className={styles.resultCard} data-testid="draft-result-card">
              <div className={styles.resultRow}>
                <span>Direction used</span>
                <span className={styles.mono}>({draft.pull_direction.map((v) => v.toFixed(3)).join(', ')})</span>
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
          </section>

          <section className={styles.section}>
            <h4 className={styles.sectionTitle}>Legend</h4>
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
                    onClick={() => setSelectedFaceIds(ids)}
                    title={`Select the ${ids.length} ${entry.label.toLowerCase()} face(s) in the viewport`}
                  >
                    Select {ids.length} {entry.key} face{ids.length === 1 ? '' : 's'}
                  </button>
                );
              })}
            </div>
          </section>

          {draft.suggestions.length > 0 && (
            <section className={styles.section}>
              <h4 className={styles.sectionTitle}>Suggestions</h4>
              {draft.suggestions.slice(0, 5).map((suggestion, i) => (
                <p key={i} className={styles.note}>
                  • {suggestion.action_text}
                </p>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}
