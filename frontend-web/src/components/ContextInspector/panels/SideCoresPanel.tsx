/**
 * F7: the Side Cores tool's real panel. Side cores are conditional (F7 §2):
 * this panel distinguishes "genuinely not required for this pull direction"
 * (a real, positive backend result) from "not yet known" and from "required
 * but the generation attempt itself failed" -- three different states, never
 * collapsed into one generic "not run" message. See
 * `analysis/analysisShared.ts`'s `runFollowUpAnalyses` for exactly which
 * orchestration field (`parting_line_v2_outcome`) decides which state this
 * lands in, and `store/analysisStore.ts`'s `SideCoreStatus` doc comment for
 * what each value means.
 */

import { useAnalysisStore } from '../../../store/analysisStore';
import styles from './sharedPanel.module.css';

function formatVolume(mm3: number | undefined): string {
  if (mm3 === undefined) return '—';
  return `${mm3.toLocaleString(undefined, { maximumFractionDigits: 1 })} mm³`;
}

export function SideCoresPanel() {
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const sideCoreStatus = useAnalysisStore((s) => s.sideCoreStatus);
  const sideCoreDetail = useAnalysisStore((s) => s.sideCoreDetail);
  const sideCoreError = useAnalysisStore((s) => s.sideCoreError);

  if (!currentPart) {
    return <p className={styles.hint}>Load a part first.</p>;
  }

  const sideCore = sideCoreDetail?.side_core as
    | {
        status?: string;
        feature_id?: number;
        containing_half?: string;
        side_core_volume_mm3?: number;
        reduced_half_volume_mm3?: number;
        conservation_error?: number;
        failure_reason?: string | null;
      }
    | undefined;

  return (
    <div className={styles.panel} data-testid="side-cores-panel">
      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Side-Action Requirement</h4>

        {sideCoreStatus === 'unknown' && (
          <p className={styles.hint} data-testid="side-cores-unknown">
            Run "Run Full Analysis" or a Manual Analysis to determine whether this pull direction needs a side
            core.
          </p>
        )}

        {sideCoreStatus === 'checking' && (
          <p className={styles.hint} data-testid="side-cores-checking">
            This pull direction was referred to a side action -- generating the side-core solid…
          </p>
        )}

        {sideCoreStatus === 'blocked' && (
          <p className={styles.hint} data-testid="side-cores-blocked">
            Side-core requirement could not be determined -- the parting-line/core-cavity analysis did not reach a
            feasible split for this pull direction (see the Core / Cavity tab for why).
          </p>
        )}

        {sideCoreStatus === 'not-required' && (
          <div className={styles.badge} data-tone="ok" data-testid="side-cores-not-required">
            No side cores required for this pull direction.
          </div>
        )}

        {(sideCoreStatus === 'available' || sideCoreStatus === 'unavailable') && (
          <div className={styles.badge} data-tone="warn" data-testid="side-cores-required">
            This pull direction was referred to a side action.
          </div>
        )}

        {sideCoreStatus === 'unavailable' && (
          <p className={styles.error} data-testid="side-cores-error">
            {sideCoreError ?? sideCore?.failure_reason ?? 'Side-core generation did not succeed for this feature.'}
          </p>
        )}
      </section>

      {sideCoreStatus === 'available' && sideCore && (
        <section className={styles.section}>
          <h4 className={styles.sectionTitle}>Generated Side Core</h4>
          <dl className={styles.grid}>
            <div>
              <dt>Feature</dt>
              <dd>{sideCore.feature_id ?? '—'}</dd>
            </div>
            <div>
              <dt>Containing half</dt>
              <dd>{sideCore.containing_half ?? '—'}</dd>
            </div>
            <div>
              <dt>Side-core volume</dt>
              <dd>{formatVolume(sideCore.side_core_volume_mm3)}</dd>
            </div>
            <div>
              <dt>Reduced half volume</dt>
              <dd>{formatVolume(sideCore.reduced_half_volume_mm3)}</dd>
            </div>
          </dl>
          <p className={styles.note}>
            Single-feature, single-direction sweep (verbatim release direction, planar-approximation tool) -- this
            does not decide the tooling mechanism (lifter vs. slide vs. collapsible core).
          </p>
        </section>
      )}

      {analysisResult?.orchestration?.delegated_face_ids && analysisResult.orchestration.delegated_face_ids.length > 0 && (
        <section className={styles.section}>
          <h4 className={styles.sectionTitle}>Delegated Faces</h4>
          <p className={styles.note}>
            {analysisResult.orchestration.delegated_face_ids.length} face(s) were delegated to a secondary action by
            the current authorization, from the Pull Direction tool.
          </p>
        </section>
      )}
    </div>
  );
}
