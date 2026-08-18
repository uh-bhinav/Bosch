/**
 * The ONE place that reads the already-fetched shared analysis state
 * (`analysisResult`/`recommendedResult`/`currentPartSummary`/`pullDirection`
 * -- exactly what F1-F4 already populate, nothing new fetched) and derives
 * the diagnostics workspace's display model. Pure function, no React, no
 * API calls, no store reads of its own -- callers pass in the exact store
 * slices they already have.
 *
 * Every field below was verified against the ACTUAL backend source this
 * session (`backend/api/main.py`'s `/core-cavity` endpoint,
 * `backend/geometry/mold_orchestration.py`'s `WinningDirectionMoldResult.
 * to_dict()`, `backend/geometry/core_cavity.py`'s `CoreCavityResult.
 * to_dict()`/`CoreCavitySolidResult.to_dict()`, `backend/geometry/
 * side_core.py`'s result classes) -- not assumed from the F0 spec's wish
 * list. Three real, confirmed gaps run through this file and are
 * surfaced as `unavailableEntry(...)`, never fabricated:
 *
 * 1. Pull-direction SEARCH detail (candidate count, search stage,
 *    refined/pruned counts, best score, evidence tier, cache stats,
 *    evaluation_failures) is on `DirectionOptimizationResult.to_dict()`
 *    (`/direction`'s OWN response) -- `/core-cavity` never serializes a
 *    `direction` key at all. Getting it would mean calling `/direction`
 *    separately, repeating the expensive optimizer search -- explicitly
 *    forbidden by F5's spec.
 * 2. UNDERCUT feature data (`UndercutFeature` list) is computed internally
 *    by `_resolve_mold_for_direction` but never serialized into
 *    `/core-cavity`'s response at any level.
 * 3. SIDE CORE per-feature results / `delegated_face_ids` /
 *    `excluded_feature_ids` are only populated when `generate_side_core`/
 *    `multi_feature_side_cores` is requested -- F3/F4's calls never
 *    request it, so these fields are always present but always empty in
 *    today's actual responses, not merely "sometimes" empty.
 *
 * H0-H7 per-gate measurements and the structured `SideActionReferral`
 * list live on `PartingLineV2Result.to_dict()` (`scorecard`/`referrals`),
 * which `/core-cavity` also never serializes -- only the derived
 * `parting_line_v2_outcome` string and a free-text `failure_reason`.
 */

import type {
  CorePinFaceRefInput,
  CoreCavityAnalysisResponse,
  DraftAnalysisResponse,
  PartingLineV2Response,
  PartSummaryResponse,
  UndercutsAnalysisResponse,
} from '../api/types';
import { describeAnalysisOutcome } from '../analysis/describeAnalysisOutcome';
import type { PullDirectionSource, Vec3 } from '../domain/types';
import type { SideCoreStatus } from '../store/analysisStore';
import {
  faceListEntry,
  rawEntry,
  textEntry,
  unavailableEntry,
  type DiagnosticGroupModel,
  type DiagnosticsModel,
} from './types';

export interface DeriveDiagnosticsInput {
  currentPartSummary: PartSummaryResponse | null;
  analysisResult: CoreCavityAnalysisResponse | null;
  recommendedResult: CoreCavityAnalysisResponse | null;
  pullDirection: Vec3 | null;
  pullDirectionSource: PullDirectionSource;
  lastRunDurationMs: number | null;
  /**
   * F9: the follow-up sweep's own results (`analysis/analysisShared.ts`'s
   * `runFollowUpAnalyses`) -- draft/undercuts/parting-line-v2 detail that
   * genuinely does NOT exist on `/core-cavity`'s own response (the reason
   * the groups below used to mark this "Not available from current
   * response" outright). Now that this workspace fetches them separately at
   * the SAME resolved direction, Diagnostics reads the real values instead
   * of a placeholder -- still `unavailableEntry(...)` whenever the specific
   * follow-up hasn't completed (or failed) for the CURRENT result.
   */
  // Optional (rather than required) so existing callers/fixtures built
  // before this addition keep type-checking unchanged; every group below
  // treats a missing/undefined value exactly like an explicit `null`.
  draftResult?: DraftAnalysisResponse | null;
  undercutsResult?: UndercutsAnalysisResponse | null;
  partingLineResult?: PartingLineV2Response | null;
  sideCoreStatus?: SideCoreStatus;
  sideCoreDetail?: CoreCavityAnalysisResponse | null;
  /** F13 §14: the engineer's own authorized core-pin face refs (Pull Direction tool's authorization editor) -- an INPUT, distinct from the validated `core_pin_interfaces` a candidate actually used. */
  corePinFaceRefs?: CorePinFaceRefInput[];
}

function formatVec3(v: Vec3 | number[] | null | undefined, digits = 3): string {
  if (!v) return '—';
  return `(${v.map((c) => c.toFixed(digits)).join(', ')})`;
}

function formatNumber(n: number | null | undefined, digits = 3, unit = ''): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  return `${n.toFixed(digits)}${unit ? ` ${unit}` : ''}`;
}

/** Real, computed comparison (basic vector math, not a backend re-derivation) -- angle in degrees between two direction vectors. */
function angleBetweenDeg(a: Vec3 | number[], b: Vec3 | number[]): number {
  const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const magA = Math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2);
  const magB = Math.sqrt(b[0] ** 2 + b[1] ** 2 + b[2] ** 2);
  if (magA < 1e-12 || magB < 1e-12) return NaN;
  const cos = Math.max(-1, Math.min(1, dot / (magA * magB)));
  return (Math.acos(cos) * 180) / Math.PI;
}

function deriveGeometryGroup(summary: PartSummaryResponse | null, result: CoreCavityAnalysisResponse | null): DiagnosticGroupModel {
  if (!summary) {
    return { id: 'geometry', title: 'Geometry', tier1: [unavailableEntry('Part', 'No part is loaded yet.')], tier2: [], tier3: [] };
  }

  const adjacency = summary.adjacency_stats as { is_manifold?: boolean; non_manifold_edges?: number; boundary_edges?: number } | undefined;
  const isValid = summary.warnings.length === 0 && adjacency?.is_manifold !== false;

  const solidSplit = result?.orchestration?.solid_split as { blank_volume_mm3?: number } | null | undefined;
  const volumeEntry = solidSplit?.blank_volume_mm3 !== undefined
    ? textEntry('Volume', formatNumber(solidSplit.blank_volume_mm3, 2, 'mm³'), {
        tooltip: 'From the mold-half solid split\'s blank_volume_mm3 -- there is no dedicated part-volume field, so this is only available once a split has succeeded for the current result.',
      })
    : unavailableEntry('Volume', 'No dedicated part-volume field exists; this is only derivable from a successful core/cavity solid split, and none is available for the current result.');

  return {
    id: 'geometry',
    title: 'Geometry',
    tier1: [
      textEntry('Part loaded / valid', isValid ? 'Yes' : 'Yes, with warnings', {
        tone: isValid ? 'ok' : 'warn',
        tooltip: 'Derived from zero load warnings and a manifold adjacency graph -- not a literal backend "is_valid" flag.',
      }),
      textEntry('Face count', String(summary.face_count)),
      textEntry('Edge count', String(summary.edge_count)),
      textEntry('Solid count', String(summary.solid_count)),
      volumeEntry,
      textEntry(
        'Bounding box',
        `${summary.bounding_box.dimensions_mm.map((v) => v.toFixed(1)).join(' × ')} mm (diagonal ${summary.bounding_box.diagonal_mm.toFixed(1)} mm)`,
      ),
    ],
    tier2: [
      textEntry('Manifold', adjacency?.is_manifold ? 'Yes' : 'No', { tone: adjacency?.is_manifold ? 'ok' : 'bad' }),
      textEntry('Non-manifold edges', String(adjacency?.non_manifold_edges ?? 0)),
      textEntry('Load warnings', summary.warnings.length > 0 ? summary.warnings.join('; ') : 'None'),
    ],
    tier3: [rawEntry('Raw part summary', summary)],
  };
}

function deriveDirectionGroup(input: DeriveDiagnosticsInput): DiagnosticGroupModel {
  const { analysisResult, recommendedResult, pullDirection, pullDirectionSource } = input;
  const recommendedDirection = recommendedResult?.orchestration?.pull_direction ?? null;
  const optimalFound = analysisResult?.orchestration?.optimal_found;

  let optimalFoundEntry;
  if (!analysisResult) {
    optimalFoundEntry = unavailableEntry('optimal_found', 'No analysis has run yet.');
  } else if (pullDirectionSource === 'manual') {
    optimalFoundEntry = textEntry('optimal_found', 'Not applicable — engineer-supplied direction', {
      tone: 'neutral',
      tooltip: '"optimal_found" is a pure search/optimizer concept (Phase C15); it has no meaning for a manually chosen direction.',
    });
  } else if (optimalFound === true) {
    optimalFoundEntry = textEntry('optimal_found', 'Yes — verified optimum', { tone: 'ok' });
  } else if (optimalFound === false) {
    optimalFoundEntry = textEntry('optimal_found', 'No — search did not find a verified, parting-line-feasible optimum', { tone: 'bad' });
  } else {
    optimalFoundEntry = unavailableEntry('optimal_found');
  }

  const tier2: DiagnosticGroupModel['tier2'] = [
    unavailableEntry('Candidate count', 'Only on /direction\'s own response, not /core-cavity\'s -- calling /direction separately would repeat the expensive optimizer search.'),
    unavailableEntry('Search stage reached', 'Same as candidate count.'),
    unavailableEntry('Boolean-refined / pruned counts', 'Same as candidate count.'),
    unavailableEntry('Best score', 'Same as candidate count.'),
  ];
  if (pullDirection && recommendedDirection) {
    const angle = angleBetweenDeg(pullDirection, recommendedDirection);
    tier2.push(
      textEntry(
        'Current vs. recommended',
        Number.isFinite(angle)
          ? angle < 0.01
            ? 'Identical direction'
            : `${angle.toFixed(2)}° apart`
          : '—',
        { tooltip: 'Computed from the two already-known direction vectors -- not a backend-reported field.' },
      ),
    );
  } else {
    tier2.push(textEntry('Current vs. recommended', 'No comparison available yet — run both a Guided and a Manual analysis.'));
  }

  return {
    id: 'pull-direction',
    title: 'Pull Direction Search',
    tier1: [
      textEntry('Recommended direction', formatVec3(recommendedDirection), {
        tooltip: recommendedDirection ? undefined : 'Run "Run Full Analysis" in the top bar to populate this.',
      }),
      textEntry('Current direction', formatVec3(pullDirection)),
      textEntry('Direction source', pullDirectionSource ?? '—'),
      optimalFoundEntry,
      unavailableEntry('Evidence tier', 'Only on /direction\'s own response -- not requested to avoid repeating the expensive optimizer search.'),
    ],
    tier2,
    tier3: [
      unavailableEntry('Candidate table', 'Same reason as candidate count above.'),
      unavailableEntry('Direction cache statistics', 'Same reason.'),
      unavailableEntry('Evaluation failures', 'Lives on /direction\'s response only -- see the Advanced group for the general note.'),
      rawEntry('Raw orchestration', analysisResult?.orchestration ?? null),
    ],
  };
}

const PARTING_LINE_NOT_FETCHED_REASON =
  'The parting-line curve/scorecard is fetched separately, at the same resolved direction, as part of the Full/Manual Analysis follow-up sweep -- it has not completed (or was not run) for the current result yet. See the Parting Line tool.';

function derivePartingLineGroup(
  analysisResult: CoreCavityAnalysisResponse | null,
  partingLineResult: PartingLineV2Response | null,
): DiagnosticGroupModel {
  const orchestration = analysisResult?.orchestration;
  const outcome = partingLineResult?.outcome ?? orchestration?.parting_line_v2_outcome ?? analysisResult?.parting_line_v2_outcome ?? null;
  const verdict = describeAnalysisOutcome(analysisResult);
  const selected = partingLineResult?.selected;

  const referralEntry = outcome === 'referred_to_side_action'
    ? textEntry('Side-action referral', orchestration?.failure_reason ?? 'Referred, no further detail available.', { tone: 'warn' })
    : textEntry('Side-action referral', 'None');

  const tier2: DiagnosticGroupModel['tier2'] = partingLineResult
    ? [
        textEntry('Candidates evaluated (v2)', String(partingLineResult.candidate_count)),
        selected
          ? textEntry('Selected candidate', `#${selected.candidate_id} (${selected.discovered_by}, ${selected.loop_count} loop(s), ${selected.point_count} pts)`)
          : textEntry('Selected candidate', 'None selected'),
        selected?.score
          ? textEntry(
              'Score (won at)',
              `${selected.score.won_at_tier ?? '—'} — coverage ${selected.score.coverage.toFixed(3)}${selected.score.coverage_is_exact ? '' : ' (conservative under-estimate)'}`,
            )
          : unavailableEntry('Score', selected ? 'This candidate carries no CandidateScore.' : PARTING_LINE_NOT_FETCHED_REASON),
        Object.keys(partingLineResult.rejection_summary ?? {}).length > 0
          ? textEntry(
              'Rejection summary (by gate)',
              Object.entries(partingLineResult.rejection_summary)
                .map(([gate, count]) => `${gate}: ${count}`)
                .join(', '),
            )
          : textEntry('Rejection summary (by gate)', selected ? 'No rejected candidates.' : 'None recorded.'),
        (() => {
          const corePinInterfaces = selected?.core_pin_interfaces;
          const count = Array.isArray(corePinInterfaces) ? corePinInterfaces.length : 0;
          return count > 0
            ? textEntry('Core-pin interfaces (validated)', String(count), {
                tooltip: 'Coaxial core-pin faces the selected candidate treated as graph bridges (D-043) -- engineer-authorized, never inferred.',
              })
            : textEntry('Core-pin interfaces (validated)', 'None');
        })(),
        (() => {
          const validatedDelegations = selected?.feasibility?.validated_delegations;
          const count = Array.isArray(validatedDelegations) ? validatedDelegations.length : 0;
          return count > 0
            ? textEntry('Validated secondary-action delegations', String(count), {
                tooltip: 'Delegated face groups (D-044) that passed structural validation for this candidate and pull direction -- see the Parting Line tool for the full authorization editor.',
              })
            : textEntry('Validated secondary-action delegations', 'None');
        })(),
      ]
    : [
        unavailableEntry('H0–H7 gate results', PARTING_LINE_NOT_FETCHED_REASON),
        unavailableEntry('Gate-specific explanations', PARTING_LINE_NOT_FETCHED_REASON),
        unavailableEntry('Relevant measurements', PARTING_LINE_NOT_FETCHED_REASON),
      ];

  return {
    id: 'parting-line',
    title: 'Parting Line',
    tier1: [
      textEntry('parting_line_v2_outcome', outcome ?? (analysisResult ? '—' : UNAVAILABLE_NO_ANALYSIS)),
      verdict
        ? textEntry('State', verdict.label, { tone: verdict.tone })
        : unavailableEntry('State', 'No analysis has run yet.'),
      referralEntry,
      selected?.feasibility
        ? textEntry('Selected candidate feasibility', selected.feasibility.passed ? 'Passed all gates' : `Failed at ${selected.feasibility.failed_gate ?? 'unknown'}`, {
            tone: selected.feasibility.passed ? 'ok' : 'bad',
          })
        : unavailableEntry('Selected candidate feasibility', partingLineResult ? 'No candidate was selected for this direction.' : PARTING_LINE_NOT_FETCHED_REASON),
    ],
    tier2,
    tier3: [
      partingLineResult
        ? rawEntry('Raw scorecard (all candidates, engineering gates)', partingLineResult.scorecard)
        : unavailableEntry('Raw scorecard', PARTING_LINE_NOT_FETCHED_REASON),
      partingLineResult
        ? rawEntry('Raw referrals (structured)', partingLineResult.referrals)
        : unavailableEntry('Referral payload (structured)', PARTING_LINE_NOT_FETCHED_REASON),
      textEntry('Raw failure_reason (orchestration)', orchestration?.failure_reason ?? '—'),
      rawEntry('Raw orchestration', orchestration ?? null),
      rawEntry('Raw parting-line-v2 result', partingLineResult ?? null),
    ],
  };
}

const UNAVAILABLE_NO_ANALYSIS = 'No analysis has run yet';

function deriveCoreCavityGroup(analysisResult: CoreCavityAnalysisResponse | null): DiagnosticGroupModel {
  if (!analysisResult) {
    return {
      id: 'core-cavity',
      title: 'Core / Cavity',
      tier1: [unavailableEntry('Split status', UNAVAILABLE_NO_ANALYSIS)],
      tier2: [],
      tier3: [],
    };
  }

  const solidSplit = analysisResult.orchestration?.solid_split as
    | {
        solid_split_status?: string;
        cavity_solid_volume_mm3?: number;
        core_solid_volume_mm3?: number;
        blank_volume_mm3?: number;
        split_tool_kind?: string;
        discarded_sliver_count?: number;
        discarded_sliver_volume_mm3?: number;
        failure_reason?: string | null;
        occ_available?: boolean;
      }
    | null
    | undefined;

  const coreCavity = analysisResult.core_cavity as
    | {
        face_counts?: { cavity: number; core: number; parting: number; skipped: number };
        inconsistent_face_ids?: number[];
        classification_source?: string;
        warnings?: string[];
      }
    | undefined;

  let tier1: DiagnosticGroupModel['tier1'];
  if (!solidSplit) {
    tier1 = [unavailableEntry('Split status', 'No solid split was attempted or completed for this result (e.g. the parting line itself was blocked before a split could run).')];
  } else {
    const conservationError =
      solidSplit.blank_volume_mm3 !== undefined && solidSplit.cavity_solid_volume_mm3 !== undefined && solidSplit.core_solid_volume_mm3 !== undefined
        ? solidSplit.blank_volume_mm3 -
          (solidSplit.cavity_solid_volume_mm3 + solidSplit.core_solid_volume_mm3 + (solidSplit.discarded_sliver_volume_mm3 ?? 0))
        : null;

    tier1 = [
      textEntry('Split status', solidSplit.solid_split_status ?? '—', {
        tone: solidSplit.solid_split_status === 'split_ok' ? 'ok' : 'bad',
      }),
      textEntry('Cavity volume', formatNumber(solidSplit.cavity_solid_volume_mm3, 2, 'mm³')),
      textEntry('Core volume', formatNumber(solidSplit.core_solid_volume_mm3, 2, 'mm³')),
      textEntry('Blank / tooling volume', formatNumber(solidSplit.blank_volume_mm3, 2, 'mm³')),
      conservationError !== null
        ? textEntry('Conservation error', formatNumber(conservationError, 4, 'mm³'), {
            tooltip: 'Computed as blank − (cavity + core + discarded slivers) from the numbers above -- not a backend-reported field.',
            tone: Math.abs(conservationError) < 1 ? 'ok' : 'warn',
          })
        : unavailableEntry('Conservation error'),
      textEntry('split_tool_kind', solidSplit.split_tool_kind ?? '—', {
        tooltip: 'A "planar_approximation" split tool bisects the tooling with a flat plane, NOT the exact 3-D parting surface shown elsewhere.',
      }),
      textEntry('Discarded sliver count', String(solidSplit.discarded_sliver_count ?? 0)),
      textEntry('Discarded sliver volume', formatNumber(solidSplit.discarded_sliver_volume_mm3, 4, 'mm³')),
    ];
  }

  const tier2: DiagnosticGroupModel['tier2'] = [];
  if (coreCavity?.face_counts) {
    const fc = coreCavity.face_counts;
    tier2.push(textEntry('Face classification', `cavity ${fc.cavity} · core ${fc.core} · parting ${fc.parting} · skipped ${fc.skipped}`));
  } else {
    tier2.push(unavailableEntry('Face classification'));
  }
  tier2.push(textEntry('Classification source', coreCavity?.classification_source ?? '—'));
  if (coreCavity?.inconsistent_face_ids && coreCavity.inconsistent_face_ids.length > 0) {
    tier2.push(
      faceListEntry('Inconsistent face IDs', coreCavity.inconsistent_face_ids, {
        tone: 'warn',
        tooltip: 'Faces whose sampled normals straddle the parting plane despite carrying a single cavity/core/parting label. Click to select in the viewport.',
      }),
    );
  } else {
    tier2.push(textEntry('Inconsistent face IDs', 'None'));
  }
  tier2.push(textEntry('Validation warnings', coreCavity?.warnings && coreCavity.warnings.length > 0 ? coreCavity.warnings.join('; ') : 'None'));

  return {
    id: 'core-cavity',
    title: 'Core / Cavity',
    tier1,
    tier2,
    tier3: [
      textEntry('Raw split failure_reason', solidSplit?.failure_reason ?? '—'),
      textEntry('OCC available', solidSplit?.occ_available === undefined ? '—' : solidSplit.occ_available ? 'Yes' : 'No'),
      rawEntry('Raw core_cavity', coreCavity ?? null),
      rawEntry('Raw solid_split', solidSplit ?? null),
    ],
  };
}

const DRAFT_UNAVAILABLE_REASON =
  'Draft analysis is fetched separately from /core-cavity (GET /parts/{filename}/draft, at the same resolved direction) as part of the Full/Manual Analysis follow-up sweep -- it has not completed (or was not run) for the current result yet. See the Draft tool.';

function deriveDraftGroup(
  analysisResult: CoreCavityAnalysisResponse | null,
  draftResult: DraftAnalysisResponse | null,
): DiagnosticGroupModel {
  if (!analysisResult) {
    return { id: 'draft', title: 'Draft', tier1: [unavailableEntry('Severity', UNAVAILABLE_NO_ANALYSIS)], tier2: [], tier3: [] };
  }

  const draft = draftResult?.draft;
  if (!draft) {
    return {
      id: 'draft',
      title: 'Draft',
      tier1: [
        unavailableEntry('Severity', DRAFT_UNAVAILABLE_REASON),
        unavailableEntry('Face counts', DRAFT_UNAVAILABLE_REASON),
      ],
      tier2: [unavailableEntry('Suggestions', DRAFT_UNAVAILABLE_REASON)],
      tier3: [unavailableEntry('Raw draft result', DRAFT_UNAVAILABLE_REASON)],
    };
  }

  const severityTone = draft.severity === 'none' ? 'ok' : draft.severity === 'minor' ? 'warn' : draft.severity === 'moderate' ? 'warn' : 'bad';

  return {
    id: 'draft',
    title: 'Draft',
    tier1: [
      textEntry('Severity', draft.severity, { tone: severityTone }),
      textEntry('Manufacturable', draft.is_manufacturable ? 'Yes' : 'No', { tone: draft.is_manufacturable ? 'ok' : 'bad' }),
      textEntry(
        'Face counts',
        `good ${draft.face_counts.good} · marginal ${draft.face_counts.marginal} · bad ${draft.face_counts.bad} · skipped ${draft.face_counts.skipped}`,
      ),
      textEntry('Bad-area %', formatNumber(draft.percentages.bad_pct, 1, '%'), {
        tone: draft.percentages.bad_pct > 20 ? 'bad' : draft.percentages.bad_pct > 5 ? 'warn' : 'ok',
      }),
      textEntry('Thresholds', `good ≥ ${draft.thresholds.good_deg}° · marginal ≥ ${draft.thresholds.marginal_deg}°`, {
        tooltip: 'From config.yaml dfm.draft.good_threshold_deg / marginal_threshold_deg.',
      }),
    ],
    tier2: [
      draft.face_counts.bad > 0
        ? faceListEntry('Bad-draft faces', draft.face_ids.bad, { tone: 'bad' })
        : textEntry('Bad-draft faces', 'None'),
      draft.face_counts.marginal > 0
        ? faceListEntry('Marginal-draft faces', draft.face_ids.marginal, { tone: 'warn' })
        : textEntry('Marginal-draft faces', 'None'),
      draft.suggestions.length > 0
        ? textEntry('Suggestions', draft.suggestions.slice(0, 5).map((s) => s.action_text).join(' | '))
        : textEntry('Suggestions', 'None'),
    ],
    tier3: [rawEntry('Raw draft result', draft)],
  };
}

const UNDERCUT_UNAVAILABLE_REASON =
  'Undercut feature data is fetched separately from /core-cavity (GET /parts/{filename}/undercuts, at the same resolved direction) as part of the Full/Manual Analysis follow-up sweep -- it has not completed (or was not run) for the current result yet. See the Undercuts tool.';

function deriveUndercutsGroup(
  analysisResult: CoreCavityAnalysisResponse | null,
  undercutsResult: UndercutsAnalysisResponse | null,
): DiagnosticGroupModel {
  if (!analysisResult) {
    return {
      id: 'undercuts',
      title: 'Undercuts',
      tier1: [unavailableEntry('Total feature count', UNAVAILABLE_NO_ANALYSIS)],
      tier2: [],
      tier3: [],
    };
  }

  const undercuts = undercutsResult?.undercuts;
  if (!undercuts) {
    return {
      id: 'undercuts',
      title: 'Undercuts',
      tier1: [
        unavailableEntry('Total feature count', UNDERCUT_UNAVAILABLE_REASON),
        unavailableEntry('Severity distribution', UNDERCUT_UNAVAILABLE_REASON),
        unavailableEntry('Confirmed / proxy evidence summary', UNDERCUT_UNAVAILABLE_REASON),
      ],
      tier2: [unavailableEntry('Feature list', UNDERCUT_UNAVAILABLE_REASON)],
      tier3: [unavailableEntry('Raw Boolean diagnostics', UNDERCUT_UNAVAILABLE_REASON)],
    };
  }

  const severityCounts: Record<string, number> = {};
  for (const feature of undercuts.features) {
    severityCounts[feature.severity] = (severityCounts[feature.severity] ?? 0) + 1;
  }
  const sideActionCount = undercuts.features.filter((f) => f.recommended_mold_action === 'side-action').length;

  return {
    id: 'undercuts',
    title: 'Undercuts',
    tier1: [
      textEntry('has_undercuts', undercuts.has_undercuts ? 'Yes' : 'No', { tone: undercuts.has_undercuts ? 'warn' : 'ok' }),
      textEntry('has_critical_undercut', undercuts.has_critical_undercut ? 'Yes' : 'No', {
        tone: undercuts.has_critical_undercut ? 'bad' : 'ok',
      }),
      textEntry('Total feature count', String(undercuts.feature_count)),
      textEntry('Major features', String(undercuts.major_undercut_features_count)),
      textEntry(
        'Severity distribution',
        Object.keys(severityCounts).length > 0
          ? Object.entries(severityCounts).map(([s, c]) => `${s}: ${c}`).join(', ')
          : 'None',
      ),
      textEntry('Undercut area %', formatNumber(undercuts.percentages.undercut_area_pct, 1, '%')),
      textEntry('Features recommending a side action', String(sideActionCount), {
        tooltip: 'Client-side tally of features whose own recommended_mold_action equals "side-action" -- no single backend field reports this count directly.',
      }),
    ],
    tier2:
      undercuts.features.length > 0
        ? undercuts.features.slice(0, 15).map((f) =>
            faceListEntry(
              `Feature ${f.feature_id} — ${f.severity} ${f.undercut_type}`,
              f.face_ids,
              {
                tone: f.severity === 'critical' ? 'bad' : f.severity === 'high' ? 'warn' : 'neutral',
                tooltip: `Evidence: ${f.evidence_source} · Recommended action: ${f.recommended_mold_action} (${f.action_confidence_label}) · ${f.action_explanation}`,
              },
            ),
          )
        : [textEntry('Feature list', 'No undercut features detected at this direction.')],
    tier3: [
      textEntry(
        'Boolean refinement',
        undercuts.boolean_refinement?.enabled ? 'Enabled' : 'Disabled',
      ),
      rawEntry('Raw undercuts result', undercuts),
    ],
  };
}

const SIDE_CORE_STATUS_LABEL: Record<SideCoreStatus, string> = {
  unknown: 'Not yet determined',
  checking: 'Referred to a side action — generating…',
  'not-required': 'Not required for this pull direction',
  available: 'Required — side core generated',
  unavailable: 'Required — generation did not succeed',
  blocked: 'Could not be determined (parting line not feasible)',
};

const SIDE_CORE_STATUS_TONE: Record<SideCoreStatus, 'ok' | 'warn' | 'bad' | 'neutral'> = {
  unknown: 'neutral',
  checking: 'warn',
  'not-required': 'ok',
  available: 'warn',
  unavailable: 'bad',
  blocked: 'neutral',
};

function deriveSideCoresGroup(
  analysisResult: CoreCavityAnalysisResponse | null,
  sideCoreStatus: SideCoreStatus,
  sideCoreDetail: CoreCavityAnalysisResponse | null,
): DiagnosticGroupModel {
  if (!analysisResult) {
    return { id: 'side-cores', title: 'Side Cores', tier1: [unavailableEntry('Status', UNAVAILABLE_NO_ANALYSIS)], tier2: [], tier3: [] };
  }

  const delegatedFaceIds = analysisResult.orchestration?.delegated_face_ids ?? [];
  const excludedFeatureIds = analysisResult.orchestration?.excluded_feature_ids ?? [];
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

  const tier1: DiagnosticGroupModel['tier1'] = [
    textEntry('Requirement status', SIDE_CORE_STATUS_LABEL[sideCoreStatus], { tone: SIDE_CORE_STATUS_TONE[sideCoreStatus] }),
  ];
  if (sideCoreStatus === 'available' && sideCore) {
    tier1.push(
      textEntry('Feature / containing half', `#${sideCore.feature_id ?? '—'} / ${sideCore.containing_half ?? '—'}`),
      textEntry('Side-core volume', formatNumber(sideCore.side_core_volume_mm3, 2, 'mm³')),
      textEntry('Reduced half volume', formatNumber(sideCore.reduced_half_volume_mm3, 2, 'mm³')),
      textEntry('Conservation error', formatNumber(sideCore.conservation_error, 6)),
    );
  } else if (sideCoreStatus === 'unavailable' && sideCore?.failure_reason) {
    tier1.push(textEntry('Failure reason', sideCore.failure_reason, { tone: 'bad' }));
  }

  return {
    id: 'side-cores',
    title: 'Side Cores',
    tier1,
    tier2: [
      delegatedFaceIds.length > 0
        ? faceListEntry('Delegated face IDs', delegatedFaceIds, {
            tooltip: 'Faces excluded from side-core selection because a validated delegation already covers them. Click to select in the viewport.',
          })
        : textEntry('Delegated face IDs', 'None'),
      excludedFeatureIds.length > 0
        ? textEntry('Excluded feature IDs', excludedFeatureIds.join(', '))
        : textEntry('Excluded feature IDs', 'None'),
    ],
    tier3: [
      sideCore ? rawEntry('Raw side_core result', sideCore) : unavailableEntry('Raw side_core result', 'No side-core generation call was made for this direction (only made when referred_to_side_action).'),
      rawEntry('Raw side_core_combined', analysisResult.orchestration?.side_core_combined ?? {}),
    ],
  };
}

/**
 * F13 §14: a distinct "Core Pins" group -- previously this data only
 * appeared folded into Parting Line's tier2 ("Core-pin interfaces
 * (validated)"). Two genuinely different things, both real backend/input
 * data, never conflated:
 *  - `corePinFaceRefs` (store input): what the engineer has AUTHORIZED as a
 *    coaxial core-pin face, via the Pull Direction tool's authorization
 *    editor -- necessary but never sufficient on its own.
 *  - `selected.core_pin_interfaces` (backend output): which of those (if
 *    any) the currently selected candidate's H3 evaluation actually used as
 *    a tooling-assigned split, for THIS specific candidate/direction.
 */
function deriveCorePinsGroup(
  partingLineResult: PartingLineV2Response | null,
  corePinFaceRefs: CorePinFaceRefInput[],
): DiagnosticGroupModel {
  const validated = partingLineResult?.selected?.core_pin_interfaces ?? [];

  const tier1: DiagnosticGroupModel['tier1'] = [
    corePinFaceRefs.length > 0
      ? faceListEntry(
          'Authorized core-pin face refs (input)',
          corePinFaceRefs.map((r) => r.face_id),
          { tooltip: 'Faces the engineer has authorized as coaxial core-pin candidates via the Pull Direction tool. Necessary but never sufficient -- H3 must also actually use it as a graph-bridge split for THIS candidate.' },
        )
      : textEntry('Authorized core-pin face refs (input)', 'None authorized'),
    partingLineResult
      ? validated.length > 0
        ? faceListEntry('Validated core-pin interfaces (used by selected candidate)', validated.map((c) => c.face_id), { tone: 'ok' })
        : textEntry('Validated core-pin interfaces (used by selected candidate)', partingLineResult.selected ? 'None used by this candidate.' : 'No candidate was selected for this direction.')
      : unavailableEntry('Validated core-pin interfaces (used by selected candidate)', PARTING_LINE_NOT_FETCHED_REASON),
  ];

  const tier2: DiagnosticGroupModel['tier2'] = [
    ...corePinFaceRefs.map((ref, i) =>
      textEntry(`Authorized ref #${i + 1}`, `face ${ref.face_id} — axis ${formatVec3(ref.axis_direction)} — "${ref.reason}"`),
    ),
    ...validated.map((c, i) =>
      textEntry(
        `Validated interface #${i + 1}`,
        `face ${c.face_id} — split_param ${c.split_param.toFixed(4)} — axis ${formatVec3(c.axis_direction)} — "${c.reason}"`,
        { tone: 'ok' },
      ),
    ),
  ];
  if (tier2.length === 0) {
    tier2.push(textEntry('Interfaces', 'No authorized refs and no validated interfaces for this direction.'));
  }

  return {
    id: 'core-pins',
    title: 'Core Pins',
    tier1,
    tier2,
    tier3: [
      rawEntry('Raw authorized core-pin face refs', corePinFaceRefs),
      partingLineResult
        ? rawEntry('Raw validated core_pin_interfaces (selected candidate)', validated)
        : unavailableEntry('Raw validated core_pin_interfaces', PARTING_LINE_NOT_FETCHED_REASON),
    ],
  };
}

function derivePerformanceGroup(input: DeriveDiagnosticsInput): DiagnosticGroupModel {
  const { analysisResult, currentPartSummary, lastRunDurationMs } = input;
  const coreCavity = analysisResult?.core_cavity as { analysis_time_s?: number } | undefined;

  return {
    id: 'performance',
    title: 'Performance',
    tier1: [
      lastRunDurationMs !== null
        ? textEntry('Last analysis request', `${(lastRunDurationMs / 1000).toFixed(1)} s`, {
            tooltip: 'Frontend-measured wall-clock round trip for the whole request -- not a backend-reported figure, and not broken down by stage.',
          })
        : unavailableEntry('Last analysis request', 'No analysis has run yet.'),
    ],
    tier2: [
      unavailableEntry('Stage timings', 'The backend does not report a per-stage breakdown on this endpoint, and this workspace deliberately never manufactures one from frontend elapsed time.'),
      unavailableEntry('Candidate count', 'Only on /direction\'s own response -- not requested here.'),
      unavailableEntry('Boolean-refined / pruned counts', 'Same reason.'),
      unavailableEntry('Cache hit/miss statistics', 'Same reason.'),
      coreCavity?.analysis_time_s !== undefined
        ? textEntry('Face-classification time (backend-reported)', formatNumber(coreCavity.analysis_time_s, 4, 's'))
        : unavailableEntry('Face-classification time'),
      currentPartSummary
        ? textEntry('STEP load time (backend-reported)', formatNumber(currentPartSummary.load_time_s, 3, 's'))
        : unavailableEntry('STEP load time', UNAVAILABLE_NO_ANALYSIS),
    ],
    tier3: [],
  };
}

function deriveAdvancedGroup(analysisResult: CoreCavityAnalysisResponse | null): DiagnosticGroupModel {
  return {
    id: 'advanced',
    title: 'Advanced / Engineering Diagnostics',
    tier1: [],
    tier2: [],
    tier3: [
      unavailableEntry('evaluation_failures', 'Lives on /direction\'s own response (DirectionOptimizationResult.to_dict()) -- not requested here to avoid repeating the expensive optimizer search.'),
      unavailableEntry('side_action_referrals (structured)', 'Lives on the direction-search and parting-line engine\'s own internal results -- only the free-text failure_reason (see Parting Line) is available here.'),
      textEntry('Raw failure_reason', analysisResult?.orchestration?.failure_reason ?? '—'),
      rawEntry('Full raw analysis response', analysisResult ?? null, 'The complete /core-cavity response this workspace derives everything above from.'),
    ],
  };
}

export function deriveDiagnostics(input: DeriveDiagnosticsInput): DiagnosticsModel {
  return {
    hasPart: input.currentPartSummary !== null,
    // Structured as an engineering report (F9 §5, F13 §14): headline
    // verdict/key metrics (Geometry, Pull Direction) -> Parting Line ->
    // Draft -> Undercuts -> Core/Cavity -> Side Cores -> Core Pins ->
    // Performance -> Advanced.
    groups: [
      deriveGeometryGroup(input.currentPartSummary, input.analysisResult),
      deriveDirectionGroup(input),
      derivePartingLineGroup(input.analysisResult, input.partingLineResult ?? null),
      deriveDraftGroup(input.analysisResult, input.draftResult ?? null),
      deriveUndercutsGroup(input.analysisResult, input.undercutsResult ?? null),
      deriveCoreCavityGroup(input.analysisResult),
      deriveSideCoresGroup(input.analysisResult, input.sideCoreStatus ?? 'unknown', input.sideCoreDetail ?? null),
      deriveCorePinsGroup(input.partingLineResult ?? null, input.corePinFaceRefs ?? []),
      derivePerformanceGroup(input),
      deriveAdvancedGroup(input.analysisResult),
    ],
  };
}
