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

import { useState } from 'react';
import { describeAnalysisOutcome } from '../../../analysis/describeAnalysisOutcome';
import { runPartingLineOnly } from '../../../analysis/runIndividualAnalyses';
import { runManualAnalysis } from '../../../analysis/runManualAnalysis';
import { undercutCategoryOverlayColorHex } from '../../../geometry/overlayColors';
import { useAnalysisStore, type CoreCavityLayers } from '../../../store/analysisStore';
import { AuthorizationEditor } from './AuthorizationEditor';
import { Legend } from './Legend';
import styles from './AnalysisSummaryPanel.module.css';
import sharedStyles from './sharedPanel.module.css';

const CORE_CAVITY_LEGEND = [
  { color: 'var(--vis-cavity)', label: 'Cavity (upper mold half)', key: 'cavity' as const },
  { color: 'var(--vis-core)', label: 'Core (lower mold half)', key: 'core' as const },
  { color: 'var(--vis-parting)', label: 'Parting zone', key: 'parting' as const },
  { color: 'var(--vis-cc-skipped)', label: 'Skipped / unknown', key: 'skipped' as const },
];

const LAYER_TOGGLES: { key: keyof CoreCavityLayers; label: string; swatch?: string }[] = [
  { key: 'core', label: 'Core', swatch: 'var(--vis-core)' },
  { key: 'cavity', label: 'Cavity', swatch: 'var(--vis-cavity)' },
  { key: 'partingZone', label: 'Parting Zone', swatch: 'var(--vis-parting)' },
  { key: 'partingLine', label: 'Parting Line (curve)', swatch: 'var(--vis-parting-line-refined)' },
  { key: 'undercuts', label: 'Undercuts', swatch: '#ff2020' },
  { key: 'corePin', label: 'Core Pin', swatch: '#c026d3' },
  { key: 'sideAction', label: 'Side Actions', swatch: 'var(--vis-side-action)' },
  { key: 'pullDirection', label: 'Pull Direction' },
];

/**
 * F12 §5: independent viewport-layer toggles for the Core/Cavity tab only
 * (`store.coreCavityLayers`, consumed exclusively by `useOverlaySync.ts`
 * when `activeTool === 'core-cavity'`) -- switching tabs away and back
 * leaves these exactly as the engineer left them; they never apply to
 * Draft/Undercuts/Parting Line's own overlays (F12 §15).
 */
function LayerTogglePanel() {
  const coreCavityLayers = useAnalysisStore((s) => s.coreCavityLayers);
  const setCoreCavityLayer = useAnalysisStore((s) => s.setCoreCavityLayer);

  return (
    <section className={sharedStyles.section}>
      <h4 className={sharedStyles.sectionTitle}>Visualization Layers</h4>
      <div className={sharedStyles.layerToggleList}>
        {LAYER_TOGGLES.map((toggle) => (
          <label key={toggle.key} className={sharedStyles.layerToggleRow}>
            <input
              type="checkbox"
              checked={coreCavityLayers[toggle.key]}
              onChange={(e) => setCoreCavityLayer(toggle.key, e.target.checked)}
            />
            {toggle.swatch && <span className={sharedStyles.layerSwatch} style={{ background: toggle.swatch }} />}
            <span>{toggle.label}</span>
          </label>
        ))}
      </div>
      <p className={sharedStyles.hint}>
        Turning Parting Zone off falls those faces back to their real core/cavity side (from the authoritative
        region split), never leaving them uncolored.
      </p>
    </section>
  );
}

function CoreCavityExtras() {
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const coreCavity = analysisResult?.core_cavity as
    | { face_counts?: Record<string, number>; classification_source?: string }
    | undefined;
  const faceCounts = coreCavity?.face_counts;
  const solidSplit = analysisResult?.solid_split as
    | {
        solid_split_status?: string;
        split_tool_kind?: string;
        cavity_solid_volume_mm3?: number;
        core_solid_volume_mm3?: number;
      }
    | undefined;

  const isAuthoritativeAnalysis = coreCavity?.classification_source === 'parting_line_v2';

  return (
    <>
      {coreCavity?.classification_source && (
        <section className={sharedStyles.section}>
          <div className={sharedStyles.badge} data-tone={isAuthoritativeAnalysis ? 'ok' : 'warn'} data-testid="core-cavity-source-badge">
            {isAuthoritativeAnalysis ? 'AUTHORITATIVE ANALYSIS — CORE/CAVITY SPLIT' : 'PREVIEW / FALLBACK CLASSIFICATION'}
          </div>
          <p className={sharedStyles.note}>
            {isAuthoritativeAnalysis
              ? 'Sourced from the same graph-connectivity, straddle-aware parting-line result used everywhere else in this workspace.'
              : 'The parting-line analysis did not produce a feasible candidate for this direction, so this is a single-normal-test fallback classification -- NOT the authoritative mold split. See the Parting Line tool for the rejected-candidate detail and engineering authorization path.'}
          </p>
        </section>
      )}

      <LayerTogglePanel />

      <section className={sharedStyles.section}>
        <h4 className={sharedStyles.sectionTitle}>Legend</h4>
        <Legend
          items={[
            ...CORE_CAVITY_LEGEND.map((entry) => ({
              color: entry.color,
              label: entry.label,
              count: faceCounts?.[entry.key] ?? 0,
            })),
            { color: '#c026d3', label: 'Core Pin — Purple' },
            { color: 'var(--vis-side-action)', label: 'Side Action (delegated faces, colored per group)' },
            { color: undercutCategoryOverlayColorHex('proxy_undercut') ?? '#ff2020', label: 'Undercut (confirmed evidence)' },
            {
              color: undercutCategoryOverlayColorHex('tangent_boundary_undercut') ?? '#c96060',
              label: 'Undercut — tangent/zero-draft boundary face (same feature, not independently confirmed)',
            },
            {
              color: undercutCategoryOverlayColorHex('ray_verified_clear') ?? '#5fb894',
              label: 'Ray-verified clear (geometric clearance check, not Boolean proof)',
            },
          ]}
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

const OUTCOME_LABEL: Record<string, string> = {
  feasible: 'Feasible — candidate selected',
  referred_to_side_action: 'Referred to a side action',
  no_feasible_candidate: 'No feasible candidate',
};

const OUTCOME_TONE: Record<string, 'ok' | 'warn' | 'bad'> = {
  feasible: 'ok',
  referred_to_side_action: 'warn',
  no_feasible_candidate: 'bad',
};

/**
 * F13: the failed-direction -> engineering-authorization handoff (the most
 * important single UX gap this phase closes). Never says just "Blocked" --
 * always: what the automatic search found, why it was rejected (real
 * backend reason/gate/candidate), and then ONE of two honest paths:
 *
 * 1. The search's OWN candidate pool already carries a real,
 *    evidence-based signal that a specific direction (`engineering_
 *    candidate`, backend/api/main.py's `_engineering_candidate_summary`)
 *    is worth authorization review -- surfaced with its ACTUAL direction,
 *    never a hardcoded one. A "Try This Direction" button reruns the full
 *    pipeline at exactly that direction with whatever authorization is
 *    configured.
 * 2. No such signal exists -- said explicitly, never faked. The engineer
 *    can still manually configure authorization and retry the automatic
 *    direction itself (unchanged from before).
 */
function EngineeringAuthorizationRequired() {
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const partingLineResult = useAnalysisStore((s) => s.partingLineResult);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const pullDirectionSource = useAnalysisStore((s) => s.pullDirectionSource);
  const corePinFaceRefs = useAnalysisStore((s) => s.corePinFaceRefs);
  const delegations = useAnalysisStore((s) => s.delegations);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);
  const [showAuthorization, setShowAuthorization] = useState(true);

  const failureReason = analysisResult?.orchestration?.failure_reason;
  const referrals = partingLineResult?.referrals ?? [];
  const isRunning = pipelineStatus === 'running';
  const engineeringCandidate = analysisResult?.engineering_candidate;

  return (
    <section className={sharedStyles.section} data-testid="engineering-authorization-required">
      <div className={sharedStyles.badge} data-tone="bad">
        Automatic direction could not produce a verified parting line
      </div>
      <p className={sharedStyles.note}>
        {pullDirectionSource === 'optimizer' ? 'The automatic search' : 'This direction'} could not select a
        candidate without further authorization -- this is a real engineering finding, not a system failure.
      </p>

      <dl className={sharedStyles.grid}>
        <div>
          <dt>Best candidate considered</dt>
          <dd>{partingLineResult?.best_rejected_candidate_id !== null && partingLineResult?.best_rejected_candidate_id !== undefined ? `#${partingLineResult.best_rejected_candidate_id}` : '—'}</dd>
        </div>
        <div>
          <dt>Blocked at gate</dt>
          <dd>{partingLineResult?.best_rejected_failed_gate ?? '—'}</dd>
        </div>
      </dl>
      {partingLineResult?.best_rejected_reason && (
        <p className={sharedStyles.note}>Reason: {partingLineResult.best_rejected_reason}</p>
      )}
      {failureReason && <p className={sharedStyles.note}>Orchestration: {failureReason}</p>}

      {referrals.length > 0 && (
        <div className={sharedStyles.section}>
          <h4 className={sharedStyles.sectionTitle}>Affected geometry (referred features)</h4>
          {referrals.map((r, i) => (
            <p key={i} className={sharedStyles.note}>
              Feature(s) {r.feature_ids.join(', ')} -- {r.note} ({r.conflict_length_mm.toFixed(1)} mm conflict)
            </p>
          ))}
        </div>
      )}

      {engineeringCandidate ? (
        <div className={sharedStyles.resultCard} data-testid="engineering-candidate">
          <div className={sharedStyles.badge} data-tone="warn">
            Engineering authorization may resolve this design
          </div>
          <p className={sharedStyles.note}>
            The automatic search's own candidate pool identifies{' '}
            {engineeringCandidate.same_as_automatic_direction
              ? 'the SAME direction above'
              : `a DIFFERENT direction, ${engineeringCandidate.label}`}{' '}
            as worth engineering review: a confirmed feature was found with a plausible mechanism class, not proof
            it is feasible.
          </p>
          <div className={sharedStyles.resultRow}>
            <span>Candidate direction</span>
            <span className={sharedStyles.mono}>({engineeringCandidate.direction.map((v) => v.toFixed(3)).join(', ')})</span>
          </div>
          <div className={sharedStyles.resultRow}>
            <span>Signal</span>
            <span className={sharedStyles.mono}>{engineeringCandidate.feature_acceptability}</span>
          </div>
          <div className={sharedStyles.resultRow}>
            <span>Features worth review</span>
            <span className={sharedStyles.mono}>{engineeringCandidate.secondary_tooling_feature_count}</span>
          </div>
          <p className={sharedStyles.note}>{engineeringCandidate.reason}</p>
          <button
            type="button"
            className={sharedStyles.runButton}
            disabled={isRunning}
            onClick={() =>
              void runManualAnalysis(engineeringCandidate.direction, corePinFaceRefs, delegations)
            }
            title="Re-runs the full core/cavity pipeline at this candidate's own direction, with whatever authorization is currently configured below."
          >
            Try This Direction With Authorization
          </button>
        </div>
      ) : (
        <p className={sharedStyles.note} data-testid="no-engineering-candidate">
          The automatic search's own evidence does not identify a specific direction worth engineering
          authorization review for this part -- not every rejected direction has one. You can still manually
          configure authorization and retry the direction shown above.
        </p>
      )}

      <button
        type="button"
        className={sharedStyles.runButton}
        onClick={() => setShowAuthorization((v) => !v)}
        aria-expanded={showAuthorization}
      >
        {corePinFaceRefs.length + delegations.length > 0
          ? `Authorization configured (${corePinFaceRefs.length + delegations.length})`
          : 'Configure authorization'}{' '}
        {showAuthorization ? '▾' : '▸'}
      </button>
      {showAuthorization && <AuthorizationEditor />}

      <button
        type="button"
        className={sharedStyles.runButton}
        disabled={!pullDirection || isRunning}
        onClick={() => pullDirection && void runManualAnalysis(pullDirection, corePinFaceRefs, delegations)}
        title="Re-runs the full core/cavity pipeline at the same pull direction, now including this authorization."
      >
        Continue Analysis with This Authorization
      </button>
    </section>
  );
}

/**
 * F13 §1B: the before/after engineering story -- `recommendedResult` is the
 * ORIGINAL automatic Guided run's snapshot (F4: preserved separately, never
 * overwritten by a later manual/authorized rerun), so it stays available to
 * compare against whatever the CURRENT result is once authorization has
 * been supplied and re-run. Only rendered when the two actually disagree
 * (different direction or different outcome) -- otherwise there is no
 * "before/after" story to tell yet. Shows the full engineering picture on
 * both sides, not just a verdict badge: candidate/rejection detail on
 * BEFORE, split/authorization detail on AFTER.
 */
function BeforeAfterComparison() {
  const recommendedResult = useAnalysisStore((s) => s.recommendedResult);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const pullDirectionSource = useAnalysisStore((s) => s.pullDirectionSource);
  const corePinFaceRefs = useAnalysisStore((s) => s.corePinFaceRefs);
  const delegations = useAnalysisStore((s) => s.delegations);
  const sideCoreStatus = useAnalysisStore((s) => s.sideCoreStatus);
  const compareMode = useAnalysisStore((s) => s.compareMode);
  const setCompareMode = useAnalysisStore((s) => s.setCompareMode);

  const beforeVerdict = describeAnalysisOutcome(recommendedResult);
  const afterVerdict = describeAnalysisOutcome(analysisResult);
  const beforeDirection = recommendedResult?.orchestration?.pull_direction;
  const afterDirection = analysisResult?.orchestration?.pull_direction;

  if (!beforeVerdict || !afterVerdict || pullDirectionSource !== 'manual') return null;
  const sameOutcome =
    beforeVerdict.code === afterVerdict.code &&
    JSON.stringify(beforeDirection) === JSON.stringify(afterDirection);
  if (sameOutcome) return null;

  const fmt = (d: [number, number, number] | null | undefined) => (d ? `(${d.map((v) => v.toFixed(2)).join(', ')})` : '—');
  const beforeSplit = (recommendedResult?.solid_split as { solid_split_status?: string } | null)?.solid_split_status;
  const afterSplit = (analysisResult?.solid_split as { solid_split_status?: string } | null)?.solid_split_status;
  const authorizationCount = corePinFaceRefs.length + delegations.length;

  return (
    <section className={sharedStyles.section} data-testid="before-after-comparison">
      <h4 className={sharedStyles.sectionTitle}>Before / After Engineering Authorization</h4>
      <p className={sharedStyles.note}>
        What the algorithm determined automatically, and what changed once the engineer supplied the missing
        manufacturing knowledge.
      </p>
      <div className={sharedStyles.resultCard}>
        <div className={sharedStyles.resultRow}>
          <span>BEFORE — automatic direction {fmt(beforeDirection)}</span>
          <span data-tone={beforeVerdict.tone} className={sharedStyles.badge}>
            {beforeVerdict.label}
          </span>
        </div>
        {recommendedResult?.engineering_candidate && (
          <div className={sharedStyles.resultRow}>
            <span>Engineering signal found</span>
            <span className={sharedStyles.mono}>{recommendedResult.engineering_candidate.feature_acceptability}</span>
          </div>
        )}
        <div className={sharedStyles.resultRow}>
          <span>Core/cavity split</span>
          <span className={sharedStyles.mono}>{beforeSplit ?? 'not attempted'}</span>
        </div>
      </div>
      <div className={sharedStyles.resultCard}>
        <div className={sharedStyles.resultRow}>
          <span>AFTER — authorized direction {fmt(afterDirection)}</span>
          <span data-tone={afterVerdict.tone} className={sharedStyles.badge}>
            {afterVerdict.label}
          </span>
        </div>
        <div className={sharedStyles.resultRow}>
          <span>Authorization used</span>
          <span className={sharedStyles.mono}>
            {authorizationCount > 0 ? `${authorizationCount} entr${authorizationCount === 1 ? 'y' : 'ies'}` : 'None'}
          </span>
        </div>
        <div className={sharedStyles.resultRow}>
          <span>Core/cavity split</span>
          <span className={sharedStyles.mono}>{afterSplit ?? 'not attempted'}</span>
        </div>
        <div className={sharedStyles.resultRow}>
          <span>Side-action requirement</span>
          <span className={sharedStyles.mono}>{sideCoreStatus}</span>
        </div>
      </div>
      <label className={sharedStyles.inspectToggleRow}>
        <input type="checkbox" checked={compareMode} onChange={(e) => setCompareMode(e.target.checked)} />
        Compare side-by-side in viewport (AFTER left, BEFORE right)
      </label>
      <p className={sharedStyles.hint}>
        {compareMode
          ? 'The viewport is split -- left is the current tool\'s normal view (AFTER), right is the original automatic run (BEFORE), both real backend results.'
          : 'Switch to the Core/Cavity, Undercuts, and Side Cores tools to see the visual comparison for the current (AFTER) result, or turn on the toggle above to see BEFORE and AFTER side by side.'}
      </p>
    </section>
  );
}

function PartingLineExtras() {
  const mode = useAnalysisStore((s) => s.mode);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const partingLineResult = useAnalysisStore((s) => s.partingLineResult);
  const partingLineStage = useAnalysisStore((s) => s.partingLineStage);
  const partingLineError = useAnalysisStore((s) => s.partingLineError);
  const corePinFaceRefs = useAnalysisStore((s) => s.corePinFaceRefs);
  const delegations = useAnalysisStore((s) => s.delegations);
  const [showAuthorization, setShowAuthorization] = useState(false);

  const selected = partingLineResult?.selected;
  const path = partingLineResult?.parting_line_path;
  const authorizationCount = corePinFaceRefs.length + delegations.length;
  // The PRIMARY /core-cavity call is the authoritative source for "what the
  // on-screen result actually did" -- partingLineResult is a follow-up
  // fetch that could momentarily lag behind (or, after an authorization
  // edit, run ahead of) it, so this gate reads the primary orchestration
  // field, same as describeAnalysisOutcome does everywhere else.
  const authorizationRequired = analysisResult?.orchestration?.parting_line_v2_outcome === 'referred_to_side_action';

  return (
    <>
      <section className={sharedStyles.section}>
        <h4 className={sharedStyles.sectionTitle}>Parting Line (Authoritative Analysis)</h4>
        <p className={sharedStyles.hint}>
          The same engineering analysis the core/cavity solid split uses internally.
        </p>

        {!partingLineResult && partingLineStage !== 'running' && (
          <p className={sharedStyles.hint} data-testid="parting-line-curve-empty">
            Curve not fetched yet for this direction.
          </p>
        )}
        {partingLineStage === 'running' && <p className={sharedStyles.hint}>Running the authoritative parting-line analysis (candidate search → engineering gates)…</p>}
        {partingLineStage === 'error' && partingLineError && (
          <p className={sharedStyles.error}>{partingLineError}</p>
        )}

        {mode === 'expert' && (
          <button
            type="button"
            className={sharedStyles.runButton}
            disabled={!pullDirection || partingLineStage === 'running'}
            onClick={() => void runPartingLineOnly()}
            title={pullDirection ? undefined : 'Pull direction required — run Pull Direction first.'}
          >
            {pullDirection ? 'Refresh Parting Line' : 'Pull direction required — run Pull Direction first'}
          </button>
        )}

        {partingLineResult && (
          <div className={sharedStyles.badge} data-tone={OUTCOME_TONE[partingLineResult.outcome] ?? 'neutral'}>
            {OUTCOME_LABEL[partingLineResult.outcome] ?? partingLineResult.outcome}
          </div>
        )}

        {partingLineResult && (
          <dl className={sharedStyles.grid}>
            <div>
              <dt>Candidates evaluated</dt>
              <dd>{partingLineResult.candidate_count}</dd>
            </div>
            <div>
              <dt>Selected candidate</dt>
              <dd>{selected ? `#${selected.candidate_id}` : '—'}</dd>
            </div>
            <div>
              <dt>Loops / points</dt>
              <dd>{selected ? `${selected.loop_count} / ${selected.point_count}` : '—'}</dd>
            </div>
            <div>
              <dt>Won at tier</dt>
              <dd>{selected?.score?.won_at_tier ?? '—'}</dd>
            </div>
          </dl>
        )}

        {partingLineResult && !selected && Object.keys(partingLineResult.rejection_summary ?? {}).length > 0 && (
          <p className={sharedStyles.note}>
            Rejected at:{' '}
            {Object.entries(partingLineResult.rejection_summary)
              .map(([gate, count]) => `${gate} (${count})`)
              .join(', ')}
          </p>
        )}

        {partingLineResult && partingLineResult.notes.length > 0 && (
          <p className={sharedStyles.note}>{partingLineResult.notes.join(' ')}</p>
        )}
      </section>

      <BeforeAfterComparison />

      {authorizationRequired && <EngineeringAuthorizationRequired />}

      {path && (
        <section className={sharedStyles.section}>
          <h4 className={sharedStyles.sectionTitle}>Legend</h4>
          <Legend
            items={[
              { color: path.hex, label: path.label },
              ...(partingLineResult?.display_mesh?.pv2_delegation_rgb
                ? [{ color: 'var(--vis-side-action)', label: 'Validated secondary-action (delegation) faces' }]
                : []),
              ...(partingLineResult?.display_mesh?.pv2_core_pin_rgb
                ? [{ color: '#d926d9', label: 'Authorized core-pin faces' }]
                : []),
            ]}
          />
        </section>
      )}

      {!authorizationRequired &&
        (mode === 'expert' ? (
          <section className={sharedStyles.section}>
            <h4 className={sharedStyles.sectionTitle}>Authoritative Configuration (Expert)</h4>
            <p className={sharedStyles.hint}>
              Engineer-supplied core-pin/secondary-action authorization -- never discovered or inferred by the
              algorithm. Leave empty to run with no authorization (today's default).
            </p>
            <button
              type="button"
              className={sharedStyles.runButton}
              onClick={() => setShowAuthorization((v) => !v)}
              aria-expanded={showAuthorization}
            >
              {authorizationCount > 0 ? `Authorization active (${authorizationCount})` : 'No authorization set'}{' '}
              {showAuthorization ? '▾' : '▸'}
            </button>
            {showAuthorization && <AuthorizationEditor />}
          </section>
        ) : (
          authorizationCount > 0 && (
            <section className={sharedStyles.section}>
              <h4 className={sharedStyles.sectionTitle}>Authoritative Configuration</h4>
              <p className={sharedStyles.note}>
                {authorizationCount} authorization entr{authorizationCount === 1 ? 'y' : 'ies'} active from Expert
                mode. Switch to Expert to edit.
              </p>
            </section>
          )
        ))}
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
        <dl className={styles.grid} data-testid="core-cavity-verdict-face-counts">
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
