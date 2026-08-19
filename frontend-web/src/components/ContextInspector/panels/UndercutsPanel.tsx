/**
 * F7: the Undercuts tool's real panel -- feature counts, severity, and the
 * full backend-supplied visual legend (`display_mesh.undercut_visual_
 * summary`, 10 categories -- backend/api/main.py's `UNDERCUT_FACE_VISUAL_
 * STYLES`), read straight from `store.undercutsResult`. Viewport
 * highlighting is centralized in `viewport/useOverlaySync.ts`. The
 * "needs a side action" count is a simple client-side tally over each
 * feature's own `recommended_mold_action` field -- no fabricated per-feature
 * data, only a sum of real backend values (the same approach the Streamlit
 * reference UI uses, since the backend has no single "N features need a
 * side core" field of its own).
 */

import { runUndercutsOnly } from '../../../analysis/runIndividualAnalyses';
import { undercutCategoryOverlayColorHex } from '../../../geometry/overlayColors';
import { useAnalysisStore } from '../../../store/analysisStore';
import { Legend } from './Legend';
import styles from './sharedPanel.module.css';

const VIEWPORT_UNCOLORED = 'rgb(124, 135, 148)';

export function UndercutsPanel() {
  const mode = useAnalysisStore((s) => s.mode);
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const undercutsResult = useAnalysisStore((s) => s.undercutsResult);
  const undercutsStage = useAnalysisStore((s) => s.undercutsStage);
  const undercutsError = useAnalysisStore((s) => s.undercutsError);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const setSelectedFaceIds = useAnalysisStore((s) => s.setSelectedFaceIds);

  const isRunning = undercutsStage === 'running' || pipelineStatus === 'running';
  const undercuts = undercutsResult?.undercuts;
  const summary = undercutsResult?.display_mesh?.undercut_visual_summary;

  const sideActionFeatures = undercuts?.features.filter((f) => f.recommended_mold_action === 'side-action') ?? [];

  return (
    <div className={styles.panel} data-testid="undercuts-panel">
      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Undercut Detection</h4>

        {!currentPart && <p className={styles.hint}>Load a part first.</p>}

        {currentPart && !undercuts && undercutsStage !== 'running' && (
          <p className={styles.hint} data-testid="undercuts-empty">
            No undercut analysis yet. Run "Run Full Analysis", or run undercut detection alone below.
          </p>
        )}

        {undercutsStage === 'running' && (
          <p className={styles.hint} data-testid="undercuts-running">
            Running undercut detection (Boolean refinement can take a while)…
          </p>
        )}

        {undercutsError && undercutsStage === 'error' && (
          <p className={styles.error} data-testid="undercuts-error">
            {undercutsError}
          </p>
        )}

        {currentPart && mode === 'expert' && (
          <button
            type="button"
            className={styles.runButton}
            disabled={isRunning}
            onClick={() => void runUndercutsOnly()}
            title={
              pullDirection
                ? `Run undercut detection only, at the current pull direction (${pullDirection.map((v) => v.toFixed(2)).join(', ')})`
                : 'Run undercut detection only, at the backend default direction (0, 0, 1)'
            }
          >
            Run Undercut Detection
          </button>
        )}
        {currentPart && mode === 'guided' && !undercuts && (
          <p className={styles.hint}>Switch to Expert mode to run undercut detection individually.</p>
        )}
      </section>

      {undercuts && (
        <>
          <section className={styles.section}>
            <h4 className={styles.sectionTitle}>Result</h4>
            <div className={styles.badge} data-tone={undercuts.has_critical_undercut ? 'bad' : undercuts.has_undercuts ? 'warn' : 'ok'}>
              {undercuts.has_critical_undercut
                ? 'Critical undercuts present'
                : undercuts.has_undercuts
                  ? 'Undercuts present'
                  : 'No undercuts at this direction'}
            </div>
            <dl className={styles.grid}>
              <div>
                <dt>Features</dt>
                <dd>{undercuts.feature_count}</dd>
              </div>
              <div>
                <dt>Major features</dt>
                <dd>{undercuts.major_undercut_features_count}</dd>
              </div>
              <div>
                <dt>Undercut area %</dt>
                <dd>{undercuts.percentages.undercut_area_pct.toFixed(1)}%</dd>
              </div>
              <div>
                <dt>Needs side action</dt>
                <dd>{sideActionFeatures.length}</dd>
              </div>
            </dl>
          </section>

          {summary && (
            <section className={styles.section}>
              <h4 className={styles.sectionTitle}>Legend</h4>
              <p className={styles.hint}>
                Three colors do real work on the model here -- everything else (parting/silhouette, accessible, and
                "zero-draft, no independent risk evidence") stays uncolored, shown only as a count below.
              </p>
              <ul className={styles.hint} style={{ margin: '0 0 8px', paddingLeft: 18 }}>
                <li>
                  <strong style={{ color: undercutCategoryOverlayColorHex('proxy_undercut') ?? undefined }}>
                    Bright red
                  </strong>{' '}
                  -- genuine undercut evidence: Boolean-confirmed at any severity, draft-proxy evidence, or
                  Boolean-inconclusive-with-risk-evidence.
                </li>
                <li>
                  <strong style={{ color: undercutCategoryOverlayColorHex('tangent_boundary_undercut') ?? undefined }}>
                    Faint red
                  </strong>{' '}
                  -- the tangent/zero-draft BOUNDARY face of that same physical feature (its normal sits almost
                  exactly perpendicular to the pull direction). Industrially, this is a parting-line ambiguity, not
                  independently confirmed trapped material -- it's reported because it's part of the same pocket, not
                  because it was itself proven to block the pull. Never painted as loudly as the feature's genuinely
                  backward-facing member.
                </li>
                <li>
                  <strong style={{ color: undercutCategoryOverlayColorHex('ray_verified_clear') ?? undefined }}>
                    Teal
                  </strong>{' '}
                  -- ray-verified clear: an independent geometric clearance check (adaptive ray casting, not a
                  Boolean operation) found no material blocking this face along its own natural mold-access
                  direction.
                </li>
              </ul>
              <Legend
                items={Object.entries(summary.legend)
                  .filter(([key]) => (summary.counts[key] ?? 0) > 0)
                  .sort((a, b) => b[1].priority - a[1].priority)
                  .map(([key, entry]) => ({
                    color: undercutCategoryOverlayColorHex(key) ?? VIEWPORT_UNCOLORED,
                    label: entry.label,
                    count: summary.counts[key] ?? 0,
                  }))}
              />
            </section>
          )}

          {undercuts.features.length > 0 && (
            <section className={styles.section}>
              <h4 className={styles.sectionTitle}>Features</h4>
              {undercuts.features.slice(0, 8).map((feature) => (
                <div key={feature.feature_id} className={styles.resultCard}>
                  <div className={styles.resultRow}>
                    <span>Feature {feature.feature_id}</span>
                    <span className={styles.mono}>{feature.severity}</span>
                  </div>
                  <div className={styles.resultRow}>
                    <span>Type</span>
                    <span className={styles.mono}>{feature.undercut_type}</span>
                  </div>
                  <div className={styles.resultRow}>
                    <span>Recommended action</span>
                    <span className={styles.mono}>{feature.recommended_mold_action}</span>
                  </div>
                  <button
                    type="button"
                    className={styles.faceListButton}
                    onClick={() => setSelectedFaceIds(feature.face_ids)}
                    title={`Select this feature's ${feature.face_ids.length} face(s) in the viewport`}
                  >
                    Select {feature.face_ids.length} face{feature.face_ids.length === 1 ? '' : 's'}
                  </button>
                </div>
              ))}
              {undercuts.features.length > 8 && (
                <p className={styles.hint}>+ {undercuts.features.length - 8} more feature(s) not shown.</p>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
