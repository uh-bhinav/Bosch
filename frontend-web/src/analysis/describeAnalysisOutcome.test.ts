import { describe, expect, it } from 'vitest';
import { describeAnalysisOutcome } from './describeAnalysisOutcome';
import type { CoreCavityAnalysisResponse, OrchestrationResult } from '../api/types';

function makeResult(orchestration: Partial<OrchestrationResult> | undefined): CoreCavityAnalysisResponse {
  return {
    part: {},
    core_cavity: {},
    pull_direction_source: 'optimal_mold_direction',
    parting_line_v2_outcome: null,
    orchestration: orchestration
      ? ({
          status: 'generated',
          failure_reason: null,
          pull_direction: null,
          optimal_found: null,
          parting_line_v2_outcome: null,
          solid_split: null,
          delegated_face_ids: [],
          excluded_feature_ids: [],
          side_cores: null,
          side_core_combined: {},
          ...orchestration,
        } as OrchestrationResult)
      : undefined,
  };
}

describe('describeAnalysisOutcome', () => {
  it('returns null when there is no orchestration result', () => {
    expect(describeAnalysisOutcome(null)).toBeNull();
    expect(describeAnalysisOutcome(makeResult(undefined))).toBeNull();
  });

  it('maps "generated" to a successful, ok-tone verdict', () => {
    const verdict = describeAnalysisOutcome(makeResult({ status: 'generated' }));
    expect(verdict).toMatchObject({ code: 'generated', tone: 'ok' });
  });

  it('maps blocked_by_parting_line + no_feasible_candidate to "no feasible candidate"', () => {
    const verdict = describeAnalysisOutcome(
      makeResult({
        status: 'blocked_by_parting_line',
        parting_line_v2_outcome: 'no_feasible_candidate',
        failure_reason: 'no selected candidate',
      }),
    );
    expect(verdict).toMatchObject({ code: 'no_feasible_candidate', tone: 'bad', detail: 'no selected candidate' });
  });

  it('maps blocked_by_parting_line + referred_to_side_action to "needs a side action" (warn, not bad)', () => {
    const verdict = describeAnalysisOutcome(
      makeResult({ status: 'blocked_by_parting_line', parting_line_v2_outcome: 'referred_to_side_action' }),
    );
    expect(verdict).toMatchObject({ code: 'referred_to_side_action', tone: 'warn' });
  });

  it('maps blocked_optimal_not_found to a blocked verdict', () => {
    const verdict = describeAnalysisOutcome(makeResult({ status: 'blocked_optimal_not_found' }));
    expect(verdict).toMatchObject({ code: 'blocked_optimal_not_found', tone: 'bad' });
  });

  it('maps blocked_by_core_cavity_split to a core/cavity failure verdict', () => {
    const verdict = describeAnalysisOutcome(makeResult({ status: 'blocked_by_core_cavity_split' }));
    expect(verdict).toMatchObject({ code: 'blocked_by_core_cavity_split', tone: 'bad' });
  });

  it('maps invalid_direction to an invalid-direction verdict (handled defensively, even though the automatic path never produces it)', () => {
    const verdict = describeAnalysisOutcome(makeResult({ status: 'invalid_direction' }));
    expect(verdict).toMatchObject({ code: 'invalid_direction', tone: 'bad' });
  });

  it('falls back to the raw status string for an unrecognized value rather than throwing', () => {
    const verdict = describeAnalysisOutcome(makeResult({ status: 'some_future_status' }));
    expect(verdict).toMatchObject({ code: 'unknown', label: 'some_future_status', tone: 'neutral' });
  });
});
