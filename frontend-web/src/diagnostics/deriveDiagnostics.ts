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

import type { CoreCavityAnalysisResponse, PartSummaryResponse } from '../api/types';
import { describeAnalysisOutcome } from '../analysis/describeAnalysisOutcome';
import type { PullDirectionSource, Vec3 } from '../domain/types';
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

function derivePartingLineGroup(analysisResult: CoreCavityAnalysisResponse | null): DiagnosticGroupModel {
  const orchestration = analysisResult?.orchestration;
  const outcome = orchestration?.parting_line_v2_outcome ?? analysisResult?.parting_line_v2_outcome ?? null;
  const verdict = describeAnalysisOutcome(analysisResult);

  const referralEntry = outcome === 'referred_to_side_action'
    ? textEntry('Side-action referral', orchestration?.failure_reason ?? 'Referred, no further detail available.', { tone: 'warn' })
    : textEntry('Side-action referral', 'None');

  return {
    id: 'parting-line',
    title: 'Parting Line',
    tier1: [
      textEntry('parting_line_v2_outcome', outcome ?? (analysisResult ? '—' : UNAVAILABLE_NO_ANALYSIS)),
      verdict
        ? textEntry('State', verdict.label, { tone: verdict.tone })
        : unavailableEntry('State', 'No analysis has run yet.'),
      referralEntry,
    ],
    tier2: [
      unavailableEntry('H0–H7 gate results', 'Per-gate measurements live on PartingLineV2Result.scorecard, which /core-cavity never serializes.'),
      unavailableEntry('Gate-specific explanations', 'Same reason.'),
      unavailableEntry('Relevant measurements', 'Same reason.'),
    ],
    tier3: [
      unavailableEntry('Raw gate diagnostics', 'Same reason as Tier 2.'),
      unavailableEntry('Referral payload (structured)', 'The structured SideActionReferral list lives on PartingLineV2Result.referrals, not serialized here -- only the free-text failure_reason above is available.'),
      textEntry('Raw failure_reason', orchestration?.failure_reason ?? '—'),
      rawEntry('Raw orchestration', orchestration ?? null),
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

const UNDERCUT_UNAVAILABLE_REASON =
  'Undercut feature data (UndercutFeature list) is computed internally while resolving this direction, but /core-cavity never serializes it into its response at any level. Fetching it would mean a separate /undercuts or /direction call, re-running Boolean-refined undercut detection -- avoided by this workspace.';

function deriveUndercutsGroup(analysisResult: CoreCavityAnalysisResponse | null): DiagnosticGroupModel {
  const reason = analysisResult ? UNDERCUT_UNAVAILABLE_REASON : UNAVAILABLE_NO_ANALYSIS;
  return {
    id: 'undercuts',
    title: 'Undercuts',
    tier1: [
      unavailableEntry('Total feature count', reason),
      unavailableEntry('Severity distribution', reason),
      unavailableEntry('Confirmed / proxy evidence summary', reason),
    ],
    tier2: [unavailableEntry('Feature list', reason)],
    tier3: [unavailableEntry('Raw Boolean diagnostics', reason)],
  };
}

const SIDE_CORE_NOT_REQUESTED_REASON =
  'Side-core generation was not requested for this analysis run (generate_side_core / multi_feature_side_cores are both left at their default "false" by the Guided and Manual run services) -- an empty result here does not mean no undercut features exist.';

function deriveSideCoresGroup(analysisResult: CoreCavityAnalysisResponse | null): DiagnosticGroupModel {
  if (!analysisResult) {
    return { id: 'side-cores', title: 'Side Cores', tier1: [unavailableEntry('Status', UNAVAILABLE_NO_ANALYSIS)], tier2: [], tier3: [] };
  }

  const sideCores = analysisResult.orchestration?.side_cores as
    | { feature_count?: number; generated_count?: number; results?: unknown[] }
    | null
    | undefined;
  const delegatedFaceIds = analysisResult.orchestration?.delegated_face_ids ?? [];
  const excludedFeatureIds = analysisResult.orchestration?.excluded_feature_ids ?? [];

  const tier1: DiagnosticGroupModel['tier1'] = sideCores
    ? [
        textEntry('Status', `${sideCores.generated_count ?? 0} of ${sideCores.feature_count ?? 0} generated`, {
          tone: (sideCores.generated_count ?? 0) > 0 ? 'ok' : 'warn',
        }),
        textEntry('Generated side cores', String(sideCores.generated_count ?? 0)),
      ]
    : [unavailableEntry('Status', SIDE_CORE_NOT_REQUESTED_REASON), unavailableEntry('Generated side cores', SIDE_CORE_NOT_REQUESTED_REASON)];

  return {
    id: 'side-cores',
    title: 'Side Cores',
    tier1,
    tier2: [
      sideCores?.results && sideCores.results.length > 0
        ? rawEntry('Per-feature results', sideCores.results)
        : unavailableEntry('Per-feature results', SIDE_CORE_NOT_REQUESTED_REASON),
      delegatedFaceIds.length > 0
        ? faceListEntry('Delegated face IDs', delegatedFaceIds, {
            tooltip: 'Faces excluded from side-core selection because a validated delegation already covers them. Click to select in the viewport.',
          })
        : textEntry('Delegated face IDs', 'None reported', {
            tooltip: 'Only populated when side-core generation is requested. ' + SIDE_CORE_NOT_REQUESTED_REASON,
          }),
      excludedFeatureIds.length > 0
        ? textEntry('Excluded feature IDs', excludedFeatureIds.join(', '))
        : textEntry('Excluded feature IDs', 'None reported', { tooltip: SIDE_CORE_NOT_REQUESTED_REASON }),
    ],
    tier3: [rawEntry('Raw side_cores', sideCores ?? null), rawEntry('Raw side_core_combined', analysisResult.orchestration?.side_core_combined ?? {})],
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
      unavailableEntry('side_action_referrals (structured)', 'Lives on /direction\'s and PartingLineV2Result\'s own responses -- only the free-text failure_reason (see Parting Line) is available here.'),
      textEntry('Raw failure_reason', analysisResult?.orchestration?.failure_reason ?? '—'),
      rawEntry('Full raw analysis response', analysisResult ?? null, 'The complete /core-cavity response this workspace derives everything above from.'),
    ],
  };
}

export function deriveDiagnostics(input: DeriveDiagnosticsInput): DiagnosticsModel {
  return {
    hasPart: input.currentPartSummary !== null,
    groups: [
      deriveGeometryGroup(input.currentPartSummary, input.analysisResult),
      deriveDirectionGroup(input),
      derivePartingLineGroup(input.analysisResult),
      deriveCoreCavityGroup(input.analysisResult),
      deriveUndercutsGroup(input.analysisResult),
      deriveSideCoresGroup(input.analysisResult),
      derivePerformanceGroup(input),
      deriveAdvancedGroup(input.analysisResult),
    ],
  };
}
