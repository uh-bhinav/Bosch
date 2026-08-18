/**
 * F3: read-only Expert-mode display of the Guided analysis result (F3 spec:
 * "Expert tool panels may display available results, but do not implement
 * their independent execution workflows yet"). Shown for the two tools the
 * single `/core-cavity` orchestration call actually covers -- Parting Line,
 * Core/Cavity -- reading straight from the shared `analysisResult`/
 * `analysisError`, never re-fetching or re-deriving anything of its own. If
 * no analysis has run yet, or a different part is now loaded than the one
 * the result was computed for, this shows a plain "run analysis" nudge
 * instead of stale data.
 *
 * F7 adds tool-specific sections BELOW the shared verdict block (never
 * touching the verdict block's own markup/testids, since existing tests key
 * off them) so Parting Line and Core/Cavity render genuinely different
 * content, not just a different heading (F7 §9): Core/Cavity gets a
 * cavity/core/parting/skipped legend + the solid-split volumes when
 * available; Parting Line gets the curve's own point counts/quality plus a
 * legend for the raw/refined curve colors actually drawn in the viewport
 * (`viewport/useOverlaySync.ts`), and its own "run alone" action.
 */

import { describeAnalysisOutcome } from '../../../analysis/describeAnalysisOutcome';
import { runPartingLineOnly } from '../../../analysis/runIndividualAnalyses';
import { useAnalysisStore } from '../../../store/analysisStore';
import { Legend } from './Legend';
import styles from './AnalysisSummaryPanel.module.css';
import sharedStyles from './sharedPanel.module.css';

const CORE_CAVITY_LEGEND = [
  { color: 'var(--vis-cavity)', label: 'Cavity (upper mold half)', key: 'cavity' as const },
  { color: 'var(--vis-core)', label: 'Core (lower mold half)', key: 'core' as const },
  { color: 'var(--vis-parting)', label: 'Parting zone', key: 'parting' as const },
  { color: 'var(--vis-cc-skipped)', label: 'Skipped / unknown', key: 'skipped' as const },
];

function CoreCavityExtras() {
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const faceCounts = (analysisResult?.core_cavity as { face_counts?: Record<string, number> } | undefined)
    ?.face_counts;
  const solidSplit = analysisResult?.solid_split as
    | {
        solid_split_status?: string;
        split_tool_kind?: string;
        cavity_solid_volume_mm3?: number;
        core_solid_volume_mm3?: number;
      }
    | undefined;

  return (
    <>
      <section className={sharedStyles.section}>
        <h4 className={sharedStyles.sectionTitle}>Legend</h4>
        <Legend
          items={CORE_CAVITY_LEGEND.map((entry) => ({
            color: entry.color,
            label: entry.label,
            count: faceCounts?.[entry.key] ?? 0,
          }))}
        />
      </section>

      {solidSplit && (
        <section className={sharedStyles.section}>
          <h4 className={sharedStyles.sectionTitle}>Boolean Solid Split</h4>
          <dl className={sharedStyles.grid}>
            <div>
              <dt>Status</dt>
              <dd>{solidSplit.solid_split_status ?? '—'}</dd>
            </div>
            <div>
              <dt>Split tool</dt>
              <dd>{solidSplit.split_tool_kind ?? '—'}</dd>
            </div>
            {solidSplit.cavity_solid_volume_mm3 !== undefined && (
              <div>
                <dt>Cavity volume</dt>
                <dd>{solidSplit.cavity_solid_volume_mm3.toFixed(0)} mm³</dd>
              </div>
            )}
            {solidSplit.core_solid_volume_mm3 !== undefined && (
              <div>
                <dt>Core volume</dt>
                <dd>{solidSplit.core_solid_volume_mm3.toFixed(0)} mm³</dd>
              </div>
            )}
          </dl>
          {solidSplit.split_tool_kind === 'planar_approximation' && (
            <p className={sharedStyles.hint}>
              The Boolean split uses a labeled planar approximation, not the exact 3-D parting surface shown in the
              Parting Line tool.
            </p>
          )}
        </section>
      )}
    </>
  );
}

function PartingLineExtras() {
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const partingLineResult = useAnalysisStore((s) => s.partingLineResult);
  const partingLineStage = useAnalysisStore((s) => s.partingLineStage);
  const partingLineError = useAnalysisStore((s) => s.partingLineError);
  const paths = partingLineResult?.parting_line_paths;

  return (
    <>
      <section className={sharedStyles.section}>
        <h4 className={sharedStyles.sectionTitle}>Parting-Line Curve</h4>

        {!paths && partingLineStage !== 'running' && (
          <p className={sharedStyles.hint} data-testid="parting-line-curve-empty">
            Curve not fetched yet for this direction.
          </p>
        )}
        {partingLineStage === 'running' && <p className={sharedStyles.hint}>Fetching parting-line curve…</p>}
        {partingLineStage === 'error' && partingLineError && (
          <p className={sharedStyles.error}>{partingLineError}</p>
        )}

        <button
          type="button"
          className={sharedStyles.runButton}
          disabled={!pullDirection || partingLineStage === 'running'}
          onClick={() => void runPartingLineOnly()}
          title={pullDirection ? undefined : 'Pull direction required — run Pull Direction first.'}
        >
          {pullDirection ? 'Refresh Parting-Line Curve' : 'Pull direction required — run Pull Direction first'}
        </button>

        {paths && (
          <dl className={sharedStyles.grid}>
            <div>
              <dt>Raw points</dt>
              <dd>{paths.raw.point_count}</dd>
            </div>
            <div>
              <dt>Refined points</dt>
              <dd>{paths.refined.point_count}</dd>
            </div>
            <div>
              <dt>Smoothing passes</dt>
              <dd>{paths.refined.smoothing_iterations ?? 0}</dd>
            </div>
            <div>
              <dt>Curve quality</dt>
              <dd>{paths.refined.quality ?? 'unknown'}</dd>
            </div>
          </dl>
        )}
      </section>

      {paths && (
        <section className={sharedStyles.section}>
          <h4 className={sharedStyles.sectionTitle}>Legend</h4>
          <Legend
            items={[
              { color: paths.legend.raw.hex, label: paths.legend.raw.label },
              { color: paths.legend.refined.hex, label: paths.legend.refined.label },
            ]}
          />
        </section>
      )}
    </>
  );
}

export function AnalysisSummaryPanel() {
  const activeTool = useAnalysisStore((s) => s.activeTool);
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

      {activeTool === 'core-cavity' && <CoreCavityExtras />}
      {activeTool === 'parting-line' && <PartingLineExtras />}
    </div>
  );
}
