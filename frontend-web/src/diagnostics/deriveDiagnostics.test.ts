/**
 * F5 tests for the pure diagnostics derivation. Two fixtures are BYTE-
 * ACCURATE real captures from this session's live backend (not invented):
 * `REAL_PART1_MANUAL_PLUS_Z` (a real manual +Z `/core-cavity` call against
 * Part1.stp, 9.9s wall time, "generated"/"feasible") and
 * `REAL_PART3_AUTHORIZED_REFERRED` (the real candidate-110 core-pin/
 * delegation payload against Part3.stp, "blocked_by_parting_line"/
 * "referred_to_side_action" -- see CHANGELOG.md "Phase F4"). Other tests
 * use representative-but-realistic payloads to exercise specific branches
 * (optimal_found=true/false, missing data, etc.) -- these are clearly NOT
 * claimed as live captures.
 */

import { describe, expect, it } from 'vitest';
import { deriveDiagnostics, type DeriveDiagnosticsInput } from './deriveDiagnostics';
import { UNAVAILABLE, type DiagnosticEntry, type DiagnosticFaceListEntry, type DiagnosticTextEntry } from './types';
import type { CoreCavityAnalysisResponse, PartSummaryResponse } from '../api/types';

function findGroup(model: ReturnType<typeof deriveDiagnostics>, id: string) {
  const group = model.groups.find((g) => g.id === id);
  if (!group) throw new Error(`group ${id} not found`);
  return group;
}

function findRaw(entries: DiagnosticEntry[], label: string): DiagnosticEntry {
  const entry = entries.find((e) => e.label === label);
  if (!entry) throw new Error(`entry "${label}" not found among [${entries.map((e) => e.label).join(', ')}]`);
  return entry;
}

/** Finds a row and asserts it's a plain text entry (the common case in these tests). */
function findEntry(entries: DiagnosticEntry[], label: string): DiagnosticTextEntry {
  const entry = findRaw(entries, label);
  if (entry.kind !== 'text') throw new Error(`entry "${label}" is a ${entry.kind} entry, not text`);
  return entry;
}

/** Finds a row and asserts it's a clickable face-list entry. */
function findFaceListEntry(entries: DiagnosticEntry[], label: string): DiagnosticFaceListEntry {
  const entry = findRaw(entries, label);
  if (entry.kind !== 'faceList') throw new Error(`entry "${label}" is a ${entry.kind} entry, not faceList`);
  return entry;
}

// Real capture: manual +Z on Part1.stp, this session's live backend, 9.9s.
const REAL_PART1_SUMMARY: PartSummaryResponse = {
  source_file: 'Part1.stp',
  face_count: 311,
  edge_count: 762,
  vertex_count: 444,
  solid_count: 1,
  shell_count: 1,
  bounding_box: {
    xmin: -9.5016, ymin: -9.5016, zmin: -0.0016, xmax: 9.5016, ymax: 9.5016, zmax: 15.0016,
    diagonal_mm: 30.7789, center_mm: [0, 0, 7.5], dimensions_mm: [19.0032, 19.0032, 15.0032],
  },
  has_cadquery_shape: true,
  surface_type_counts: {},
  edge_type_counts: {},
  load_time_s: 0.4115,
  warnings: [],
  adjacency_stats: { is_manifold: true, non_manifold_edges: 0 },
};

const REAL_PART1_MANUAL_PLUS_Z: CoreCavityAnalysisResponse = {
  part: {},
  core_cavity: {
    pull_direction: [0, 0, 1],
    face_counts: { cavity: 24, core: 217, parting: 70, skipped: 0 },
    area_mm2: { cavity: 362.338, core: 1203.814, parting: 1311.475, total: 2877.627 },
    percentages: { cavity_pct: 12.59, core_pct: 41.83 },
    threshold_used: 0.0,
    analysis_time_s: 0.0001,
    warnings: [],
    inconsistent_face_ids: [],
    classification_source: 'parting_line_v2',
  },
  pull_direction_source: 'manual_query_direction',
  parting_line_v2_outcome: 'feasible',
  orchestration: {
    status: 'generated',
    failure_reason: null,
    pull_direction: [0.0, 0.0, 1.0],
    optimal_found: null,
    parting_line_v2_outcome: 'feasible',
    solid_split: {
      solid_split_status: 'split_ok',
      split_solid_count: 2,
      cavity_solid_volume_mm3: 9103.6221,
      core_solid_volume_mm3: 25300.812,
      blank_volume_mm3: 35950.051,
      failure_reason: null,
      split_tool_kind: 'planar_approximation',
      discarded_sliver_count: 1,
      discarded_sliver_volume_mm3: 105.4408,
      occ_available: true,
    },
    delegated_face_ids: [],
    excluded_feature_ids: [],
    side_cores: null,
    side_core_combined: {},
  },
};

// Real capture: the exact candidate-110 core-pin/delegation payload
// (tests/test_parting_line_v2_region_balance.py's `_candidate_110_result`
// fixture) against Part3.stp, this session's live backend.
const REAL_PART3_AUTHORIZED_REFERRED: CoreCavityAnalysisResponse = {
  part: {},
  core_cavity: {
    face_counts: { cavity: 278, core: 39, parting: 97, skipped: 0 },
    inconsistent_face_ids: [],
    classification_source: 'single_normal',
  },
  pull_direction_source: 'manual_query_direction',
  parting_line_v2_outcome: 'referred_to_side_action',
  orchestration: {
    status: 'blocked_by_parting_line',
    failure_reason: "analyse_parting_line found no selected candidate for this direction (outcome='referred_to_side_action').",
    pull_direction: [0.0, 0.0, 1.0],
    optimal_found: null,
    parting_line_v2_outcome: 'referred_to_side_action',
    solid_split: null,
    delegated_face_ids: [],
    excluded_feature_ids: [],
    side_cores: null,
    side_core_combined: {},
  },
};

function baseInput(overrides: Partial<DeriveDiagnosticsInput> = {}): DeriveDiagnosticsInput {
  return {
    currentPartSummary: null,
    analysisResult: null,
    recommendedResult: null,
    pullDirection: null,
    pullDirectionSource: null,
    lastRunDurationMs: null,
    ...overrides,
  };
}

describe('deriveDiagnostics', () => {
  it('renders Tier 1 geometry from the real Part1.stp part summary', () => {
    const model = deriveDiagnostics(baseInput({ currentPartSummary: REAL_PART1_SUMMARY }));
    const geometry = findGroup(model, 'geometry');

    expect(findEntry(geometry.tier1, 'Face count').value).toEqual('311');
    expect(findEntry(geometry.tier1, 'Edge count').value).toEqual('762');
    expect(findEntry(geometry.tier1, 'Solid count').value).toEqual('1');
    expect(findEntry(geometry.tier1, 'Part loaded / valid')).toMatchObject({ value: 'Yes', tone: 'ok' });
    expect(findEntry(geometry.tier1, 'Bounding box').value).toContain('19.0');
  });

  it('renders the recommended and current direction, distinguishably, from real Part1 data', () => {
    const model = deriveDiagnostics(
      baseInput({
        currentPartSummary: REAL_PART1_SUMMARY,
        analysisResult: REAL_PART1_MANUAL_PLUS_Z,
        recommendedResult: { ...REAL_PART1_MANUAL_PLUS_Z, orchestration: { ...REAL_PART1_MANUAL_PLUS_Z.orchestration!, pull_direction: [0, 0, -1], optimal_found: true } },
        pullDirection: [0, 0, 1],
        pullDirectionSource: 'manual',
      }),
    );
    const direction = findGroup(model, 'pull-direction');

    expect(findEntry(direction.tier1, 'Recommended direction').value).toBe('(0.000, 0.000, -1.000)');
    expect(findEntry(direction.tier1, 'Current direction').value).toBe('(0.000, 0.000, 1.000)');
    expect(findEntry(direction.tier1, 'Recommended direction').value).not.toBe(findEntry(direction.tier1, 'Current direction').value);
    expect(findEntry(direction.tier1, 'Direction source').value).toBe('manual');

    // 180 degrees apart -- a real, computed comparison, not a backend field.
    const comparison = findEntry(direction.tier2, 'Current vs. recommended');
    expect(comparison.value).toBe('180.00° apart');
  });

  it('optimal_found=true renders as a verified optimum (automatic path)', () => {
    const model = deriveDiagnostics(
      baseInput({
        currentPartSummary: REAL_PART1_SUMMARY,
        analysisResult: {
          ...REAL_PART1_MANUAL_PLUS_Z,
          pull_direction_source: 'optimal_mold_direction',
          orchestration: { ...REAL_PART1_MANUAL_PLUS_Z.orchestration!, optimal_found: true, pull_direction: [0, 0, -1] },
        },
        pullDirection: [0, 0, -1],
        pullDirectionSource: 'optimizer',
      }),
    );
    const entry = findEntry(findGroup(model, 'pull-direction').tier1, 'optimal_found');
    expect(entry).toMatchObject({ value: 'Yes — verified optimum', tone: 'ok' });
  });

  it('optimal_found=false renders as blocked, not a verified optimum', () => {
    const model = deriveDiagnostics(
      baseInput({
        analysisResult: {
          part: {}, core_cavity: {}, pull_direction_source: 'optimal_mold_direction', parting_line_v2_outcome: null,
          orchestration: {
            status: 'blocked_optimal_not_found', failure_reason: 'no verified optimum', pull_direction: [1, 0, 0],
            optimal_found: false, parting_line_v2_outcome: null, solid_split: null,
            delegated_face_ids: [], excluded_feature_ids: [], side_cores: null, side_core_combined: {},
          },
        },
        pullDirectionSource: 'optimizer',
      }),
    );
    const entry = findEntry(findGroup(model, 'pull-direction').tier1, 'optimal_found');
    expect(entry.tone).toBe('bad');
    expect(entry.value).toContain('No');
  });

  it('a real no_feasible_candidate result renders the blocked state, not success', () => {
    const model = deriveDiagnostics(
      baseInput({
        analysisResult: {
          part: {}, core_cavity: {}, pull_direction_source: 'manual_query_direction', parting_line_v2_outcome: 'no_feasible_candidate',
          orchestration: {
            status: 'blocked_by_parting_line', failure_reason: "outcome='no_feasible_candidate'", pull_direction: [1, 1, 0],
            optimal_found: null, parting_line_v2_outcome: 'no_feasible_candidate', solid_split: null,
            delegated_face_ids: [], excluded_feature_ids: [], side_cores: null, side_core_combined: {},
          },
        },
      }),
    );
    const partingLine = findGroup(model, 'parting-line');
    expect(findEntry(partingLine.tier1, 'parting_line_v2_outcome').value).toBe('no_feasible_candidate');
    expect(findEntry(partingLine.tier1, 'State')).toMatchObject({ tone: 'bad' });
    expect(findEntry(partingLine.tier1, 'Side-action referral').value).toBe('None');
  });

  it('the real Part3 candidate-110 referred_to_side_action result surfaces the referral text prominently', () => {
    const model = deriveDiagnostics(baseInput({ analysisResult: REAL_PART3_AUTHORIZED_REFERRED }));
    const partingLine = findGroup(model, 'parting-line');

    expect(findEntry(partingLine.tier1, 'parting_line_v2_outcome').value).toBe('referred_to_side_action');
    expect(findEntry(partingLine.tier1, 'State')).toMatchObject({ tone: 'warn' });
    const referral = findEntry(partingLine.tier1, 'Side-action referral');
    expect(referral.value).toContain('referred_to_side_action');
    expect(referral.tone).toBe('warn');

    // The structured referral payload is honestly marked unavailable, never fabricated.
    const payloadEntry = findEntry(partingLine.tier3, 'Referral payload (structured)');
    expect(payloadEntry.value).toBe(UNAVAILABLE);
  });

  it('renders real core/cavity split metrics from the real Part1 manual +Z capture', () => {
    const model = deriveDiagnostics(baseInput({ analysisResult: REAL_PART1_MANUAL_PLUS_Z }));
    const coreCavity = findGroup(model, 'core-cavity');

    expect(findEntry(coreCavity.tier1, 'Split status')).toMatchObject({ value: 'split_ok', tone: 'ok' });
    expect(findEntry(coreCavity.tier1, 'Cavity volume').value).toBe('9103.62 mm³');
    expect(findEntry(coreCavity.tier1, 'Core volume').value).toBe('25300.81 mm³');
    expect(findEntry(coreCavity.tier1, 'Blank / tooling volume').value).toBe('35950.05 mm³');
    expect(findEntry(coreCavity.tier1, 'split_tool_kind').value).toBe('planar_approximation');
  });

  it('renders real discarded-sliver metrics', () => {
    const model = deriveDiagnostics(baseInput({ analysisResult: REAL_PART1_MANUAL_PLUS_Z }));
    const coreCavity = findGroup(model, 'core-cavity');

    expect(findEntry(coreCavity.tier1, 'Discarded sliver count').value).toBe('1');
    expect(findEntry(coreCavity.tier1, 'Discarded sliver volume').value).toBe('105.4408 mm³');
    // Computed conservation error: blank - (cavity + core + slivers), clearly labeled as computed.
    const conservation = findEntry(coreCavity.tier1, 'Conservation error');
    expect(conservation.tooltip).toContain('Computed as');
    expect(Number(conservation.value.split(' ')[0])).toBeCloseTo(35950.051 - (9103.6221 + 25300.812 + 105.4408), 2);
  });

  it('undercut feature data is honestly marked unavailable, never fabricated', () => {
    const model = deriveDiagnostics(baseInput({ analysisResult: REAL_PART1_MANUAL_PLUS_Z }));
    const undercuts = findGroup(model, 'undercuts');

    expect(findEntry(undercuts.tier1, 'Total feature count').value).toBe(UNAVAILABLE);
    expect(findEntry(undercuts.tier1, 'Total feature count').tooltip).toContain('/core-cavity never serializes it');
    expect(findEntry(undercuts.tier2, 'Feature list').value).toBe(UNAVAILABLE);
  });

  it('side-core delegation/exclusion is shown as real-but-empty, with a tooltip explaining why, not "unavailable"', () => {
    const model = deriveDiagnostics(baseInput({ analysisResult: REAL_PART3_AUTHORIZED_REFERRED }));
    const sideCores = findGroup(model, 'side-cores');

    const status = findEntry(sideCores.tier1, 'Status');
    expect(status.value).toBe(UNAVAILABLE);
    expect(status.tooltip).toContain('not requested');

    const delegated = findEntry(sideCores.tier2, 'Delegated face IDs');
    expect(delegated.value).toBe('None reported');
    expect(delegated.tooltip).toContain('Only populated when side-core generation is requested');
  });

  it('evaluation_failures and structured side_action_referrals are marked unavailable in the Advanced group', () => {
    const model = deriveDiagnostics(baseInput({ analysisResult: REAL_PART3_AUTHORIZED_REFERRED }));
    const advanced = findGroup(model, 'advanced');

    expect(findEntry(advanced.tier3, 'evaluation_failures').value).toBe(UNAVAILABLE);
    expect(findEntry(advanced.tier3, 'side_action_referrals (structured)').value).toBe(UNAVAILABLE);
    expect(findEntry(advanced.tier3, 'Raw failure_reason').value).toContain('referred_to_side_action');
  });

  it('gracefully handles no analysis having run yet -- no crashes, clear "no analysis" messaging', () => {
    const model = deriveDiagnostics(baseInput({ currentPartSummary: REAL_PART1_SUMMARY }));
    expect(model.hasPart).toBe(true);

    const partingLine = findGroup(model, 'parting-line');
    expect(findEntry(partingLine.tier1, 'State').value).toBe(UNAVAILABLE);
    const coreCavity = findGroup(model, 'core-cavity');
    expect(findEntry(coreCavity.tier1, 'Split status').value).toBe(UNAVAILABLE);
  });

  it('gracefully handles no part loaded at all', () => {
    const model = deriveDiagnostics(baseInput());
    expect(model.hasPart).toBe(false);
    const geometry = findGroup(model, 'geometry');
    expect(findEntry(geometry.tier1, 'Part').value).toBe(UNAVAILABLE);
  });

  it('raw JSON entries only ever appear in tier3 (Advanced), never tier1/tier2', () => {
    const model = deriveDiagnostics(baseInput({ currentPartSummary: REAL_PART1_SUMMARY, analysisResult: REAL_PART3_AUTHORIZED_REFERRED }));
    for (const group of model.groups) {
      expect(group.tier1.some((e) => e.kind === 'raw')).toBe(false);
      expect(group.tier2.some((e) => e.kind === 'raw')).toBe(false);
    }
    const advanced = findGroup(model, 'advanced');
    expect(advanced.tier3.some((e) => e.kind === 'raw')).toBe(true);
  });

  it('inconsistent face IDs are offered as a clickable face-list entry when present', () => {
    const model = deriveDiagnostics(
      baseInput({
        analysisResult: {
          ...REAL_PART1_MANUAL_PLUS_Z,
          core_cavity: { ...(REAL_PART1_MANUAL_PLUS_Z.core_cavity as object), inconsistent_face_ids: [12, 47] },
        },
      }),
    );
    const entry = findFaceListEntry(findGroup(model, 'core-cavity').tier2, 'Inconsistent face IDs');
    expect(entry.faceIds).toEqual([12, 47]);
  });

  it('the frontend-measured last-run duration is labeled as such, never presented as a backend stage timing', () => {
    const model = deriveDiagnostics(baseInput({ lastRunDurationMs: 9897 }));
    const performance = findGroup(model, 'performance');
    const entry = findEntry(performance.tier1, 'Last analysis request');
    expect(entry.value).toBe('9.9 s');
    expect(entry.tooltip).toContain('Frontend-measured');
    const stageTimings = findEntry(performance.tier2, 'Stage timings');
    expect(stageTimings.value).toBe(UNAVAILABLE);
  });
});
