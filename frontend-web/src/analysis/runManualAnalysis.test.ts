/**
 * F4 acceptance tests for the Manual Pull Direction orchestration service --
 * exactly-once calls to the authoritative `/core-cavity` manual path, no
 * client-side normalization, authorization JSON propagation, invalid/zero
 * direction, blocked direction, the real Part3 candidate-110 authorized +Z
 * fixture, shared-state replacement, and reset-on-new-part-load.
 * `api/endpoints` and the viewport engine are mocked so these exercise
 * exactly the sequencing this module owns -- no network.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests, getViewportEngine } from '../viewport/engineSingleton';
import { __resetAnalysisRunLockForTests } from './analysisShared';
import type { CoreCavityAnalysisResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  runManualCoreCavity: vi.fn(),
  runFullAnalysis: vi.fn(),
}));

import { runFullAnalysis, runManualCoreCavity } from '../api/endpoints';
import { runGuidedAnalysis } from './runGuidedAnalysis';
import { runManualAnalysis } from './runManualAnalysis';

const mockedRunManualCoreCavity = vi.mocked(runManualCoreCavity);
const mockedRunFullAnalysis = vi.mocked(runFullAnalysis);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeResult(overrides: Partial<CoreCavityAnalysisResponse['orchestration']> = {}): CoreCavityAnalysisResponse {
  return {
    part: {},
    core_cavity: { face_counts: { cavity: 1, core: 1, parting: 0, skipped: 0 } },
    pull_direction_source: 'manual_query_direction',
    parting_line_v2_outcome: null,
    orchestration: {
      status: 'generated',
      failure_reason: null,
      pull_direction: [0, 0, 1],
      optimal_found: null,
      parting_line_v2_outcome: null,
      solid_split: { solid_split_status: 'split_ok' },
      delegated_face_ids: [],
      excluded_feature_ids: [],
      side_cores: null,
      side_core_combined: {},
      ...overrides,
    },
    display_mesh: {
      point_count: 4,
      triangle_count: 2,
      face_count: 1,
      face_ids: [0, 0],
      face_centers: {},
      points: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
      faces: [[0, 1, 2], [0, 2, 3]],
      core_cavity_rgb: [[0.2, 0.8, 0.4], [0.2, 0.8, 0.4]],
    },
  };
}

beforeEach(() => {
  resetStore();
  __resetViewportEngineForTests();
  __resetAnalysisRunLockForTests();
  mockedRunManualCoreCavity.mockReset();
  mockedRunFullAnalysis.mockReset();
  useAnalysisStore.getState().setCurrentPart('Part1.stp');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('runManualAnalysis', () => {
  it('does nothing when no part is loaded', async () => {
    useAnalysisStore.getState().setCurrentPart(null);
    await runManualAnalysis([0, 0, 1]);
    expect(mockedRunManualCoreCavity).not.toHaveBeenCalled();
  });

  it('sends the raw, unnormalized vector exactly as given -- never computes a magnitude or divides it', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(makeResult());

    // A deliberately non-unit vector -- if this module normalized it before
    // sending, the call would receive something other than these exact
    // three numbers.
    await runManualAnalysis([2, -3, 5]);

    expect(mockedRunManualCoreCavity).toHaveBeenCalledWith('Part1.stp', [2, -3, 5], {
      corePinFaceRefs: [],
      delegations: [],
    });
  });

  it('calls the manual /core-cavity path exactly once per run, never the automatic path', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(makeResult());

    await runManualAnalysis([0, 0, 1]);

    expect(mockedRunManualCoreCavity).toHaveBeenCalledTimes(1);
    expect(mockedRunFullAnalysis).not.toHaveBeenCalled();
  });

  it('a second manual call while one is already running does not fire a duplicate request', async () => {
    let resolveFn!: (value: CoreCavityAnalysisResponse) => void;
    mockedRunManualCoreCavity.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const first = runManualAnalysis([0, 0, 1]);
    const second = runManualAnalysis([1, 0, 0]);
    expect(mockedRunManualCoreCavity).toHaveBeenCalledTimes(1);

    resolveFn(makeResult());
    await Promise.all([first, second]);
    expect(mockedRunManualCoreCavity).toHaveBeenCalledTimes(1);
  });

  it('a manual run cannot fire while a guided run is already in flight (shared lock)', async () => {
    let resolveGuided!: (value: CoreCavityAnalysisResponse) => void;
    mockedRunFullAnalysis.mockReturnValue(
      new Promise((resolve) => {
        resolveGuided = resolve;
      }),
    );

    const guided = runGuidedAnalysis();
    const manual = runManualAnalysis([0, 0, 1]); // returns the SAME in-flight promise as `guided`, never fires its own request
    expect(mockedRunManualCoreCavity).not.toHaveBeenCalled();

    resolveGuided(makeResult());
    await Promise.all([guided, manual]);
    expect(mockedRunManualCoreCavity).not.toHaveBeenCalled();
  });

  it('propagates core-pin and delegation authorization straight through, unmodified', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(makeResult());

    const corePinFaceRefs = [{ face_id: 35, axis_direction: [0, 0, 1] as [number, number, number], reason: 'straight coaxial through-bore' }];
    const delegations = [
      {
        face_ids: [0, 1, 2],
        movement_direction: [1, 0, 0] as [number, number, number],
        movement_type: 'radial_slide',
        source: 'manual_engineering',
        note: 'rib stack',
      },
    ];

    await runManualAnalysis([0, 0, 1], corePinFaceRefs, delegations);

    expect(mockedRunManualCoreCavity).toHaveBeenCalledWith('Part1.stp', [0, 0, 1], {
      corePinFaceRefs,
      delegations,
    });
  });

  it('an invalid/zero direction result (backend-detected, not client-checked) is applied without throwing', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(
      makeResult({
        status: 'invalid_direction',
        failure_reason: 'Cannot normalise zero vector: (0.0, 0.0, 0.0)',
        pull_direction: null,
      }),
    );

    await runManualAnalysis([0, 0, 0]);

    const state = useAnalysisStore.getState();
    expect(mockedRunManualCoreCavity).toHaveBeenCalledWith('Part1.stp', [0, 0, 0], { corePinFaceRefs: [], delegations: [] });
    expect(state.analysisResult?.orchestration?.status).toBe('invalid_direction');
    expect(state.analysisError).toBeNull();
    expect(state.pipelineStatus).toBe('blocked');
  });

  it('a blocked (no feasible candidate) manual direction is reported as blocked, not thrown', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(
      makeResult({
        status: 'blocked_by_parting_line',
        parting_line_v2_outcome: 'no_feasible_candidate',
        pull_direction: [1, 0, 0],
      }),
    );

    await runManualAnalysis([1, 0, 0]);

    const state = useAnalysisStore.getState();
    expect(state.pipelineStatus).toBe('blocked');
    expect(state.analysisResult?.orchestration?.parting_line_v2_outcome).toBe('no_feasible_candidate');
  });

  it('the Part3 candidate-110 authorization payload propagates correctly and a "generated" response is applied end to end', async () => {
    // The exact core-pin/delegation payload from tests/test_parting_line_v2_
    // region_balance.py's `_candidate_110_result` helper -- verified live
    // against this session's real backend to confirm the payload shape and
    // query-parameter contract are correct (200, well-formed `orchestration`
    // body). Disclosed finding: the LIVE result for this exact payload is
    // currently `blocked_by_parting_line`/`referred_to_side_action`, not
    // `feasible` -- the frozen unit test uses `UndercutInput.empty()`, while
    // this endpoint's manual path deliberately computes REAL undercut
    // evidence (C15/C16: "the SAME final-direction convention the
    // optimizer's own last step uses"), so the two are not expected to
    // agree. This test still asserts the "generated" branch (with a mocked
    // response) because the frontend must handle that outcome correctly
    // whenever the backend does produce it -- the referral branch is
    // covered by a separate mocked test above, and confirmed against the
    // real live response in this session's F4 verification (see
    // CHANGELOG.md "Phase F4").
    const corePinFaceRefs = [{ face_id: 35, axis_direction: [0, 0, 1] as [number, number, number], reason: 'straight coaxial through-bore' }];
    const delegations = [
      {
        face_ids: Array.from({ length: 17 }, (_, i) => i),
        movement_direction: [1, 0, 0] as [number, number, number],
        movement_type: 'radial_slide',
        source: 'manual_engineering',
        note: 'original rib stack, radial outward +X',
      },
      {
        face_ids: Array.from({ length: 17 }, (_, i) => i + 18),
        movement_direction: [-1, 0, 0] as [number, number, number],
        movement_type: 'radial_slide',
        source: 'manual_engineering',
        note: 'mirror rib stack, radial outward -X',
      },
    ];
    mockedRunManualCoreCavity.mockResolvedValue(
      makeResult({
        status: 'generated',
        parting_line_v2_outcome: 'feasible',
        pull_direction: [0, 0, 1],
        delegated_face_ids: [...delegations[0].face_ids, ...delegations[1].face_ids],
      }),
    );
    useAnalysisStore.getState().setCurrentPart('Part3.stp');

    await runManualAnalysis([0, 0, 1], corePinFaceRefs, delegations);

    expect(mockedRunManualCoreCavity).toHaveBeenCalledWith('Part3.stp', [0, 0, 1], {
      corePinFaceRefs,
      delegations,
    });
    const state = useAnalysisStore.getState();
    expect(state.analysisResult?.orchestration?.status).toBe('generated');
    expect(state.analysisResult?.orchestration?.parting_line_v2_outcome).toBe('feasible');
    expect(state.analysisResult?.orchestration?.delegated_face_ids).toHaveLength(34);
    expect(state.pipelineStatus).toBe('complete');
  });

  it('the ACTUAL live response for the Part3 candidate-110 payload (referred_to_side_action) is applied correctly', async () => {
    // This is the real, live-verified response body for this exact
    // core-pin/delegation payload against Part3.stp on this session's
    // backend (2026-08-17): HTTP 200, `status="blocked_by_parting_line"`,
    // `parting_line_v2_outcome="referred_to_side_action"`. Byte-for-byte
    // reproduction of the captured response's `orchestration` object.
    const corePinFaceRefs = [{ face_id: 35, axis_direction: [0, 0, 1] as [number, number, number], reason: 'straight coaxial through-bore' }];
    const delegations = [
      {
        face_ids: Array.from({ length: 17 }, (_, i) => i),
        movement_direction: [1, 0, 0] as [number, number, number],
        movement_type: 'radial_slide',
        source: 'manual_engineering',
        note: 'original rib stack, radial outward +X',
      },
      {
        face_ids: Array.from({ length: 17 }, (_, i) => i + 18),
        movement_direction: [-1, 0, 0] as [number, number, number],
        movement_type: 'radial_slide',
        source: 'manual_engineering',
        note: 'mirror rib stack, radial outward -X',
      },
    ];
    mockedRunManualCoreCavity.mockResolvedValue({
      part: {},
      core_cavity: {},
      pull_direction_source: 'manual_query_direction',
      parting_line_v2_outcome: 'referred_to_side_action',
      orchestration: {
        status: 'blocked_by_parting_line',
        failure_reason:
          "analyse_parting_line found no selected candidate for this direction (outcome='referred_to_side_action').",
        pull_direction: [0.0, 0.0, 1.0],
        optimal_found: null,
        parting_line_v2_outcome: 'referred_to_side_action',
        solid_split: null,
        delegated_face_ids: [],
        excluded_feature_ids: [],
        side_cores: null,
        side_core_combined: {},
      },
    });
    useAnalysisStore.getState().setCurrentPart('Part3.stp');

    await runManualAnalysis([0, 0, 1], corePinFaceRefs, delegations);

    const state = useAnalysisStore.getState();
    expect(state.analysisResult?.orchestration?.status).toBe('blocked_by_parting_line');
    expect(state.analysisResult?.orchestration?.parting_line_v2_outcome).toBe('referred_to_side_action');
    expect(state.pipelineStatus).toBe('blocked');
    expect(state.analysisError).toBeNull();
  });

  it('replaces the shared analysisResult/pullDirection/pullDirectionSource -- there is exactly one current result', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(makeResult({ pull_direction: [0, 1, 0] }));

    await runManualAnalysis([0, 1, 0]);

    const state = useAnalysisStore.getState();
    expect(state.pullDirection).toEqual([0, 1, 0]);
    expect(state.pullDirectionSource).toBe('manual');
    expect(state.analysisResult?.orchestration?.pull_direction).toEqual([0, 1, 0]);
  });

  it('never writes to recommendedResult -- the optimizer recommendation stays available for comparison', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult({ status: 'generated' }));
    await runGuidedAnalysis();
    const recommendedBefore = useAnalysisStore.getState().recommendedResult;
    expect(recommendedBefore).not.toBeNull();

    mockedRunManualCoreCavity.mockResolvedValue(
      makeResult({ status: 'blocked_by_parting_line', parting_line_v2_outcome: 'no_feasible_candidate' }),
    );
    await runManualAnalysis([1, 1, 0]);

    const state = useAnalysisStore.getState();
    expect(state.recommendedResult).toBe(recommendedBefore);
    expect(state.recommendedResult?.orchestration?.status).toBe('generated');
    expect(state.analysisResult?.orchestration?.status).toBe('blocked_by_parting_line');
  });

  it('pushes the mesh into the persistent viewport engine without recreating it', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(makeResult());
    const engineBefore = getViewportEngine();
    const setMeshSpy = vi.spyOn(engineBefore, 'setMesh');

    await runManualAnalysis([0, 0, 1]);

    expect(setMeshSpy).toHaveBeenCalledTimes(1);
    expect(getViewportEngine()).toBe(engineBefore);
  });

  it('loading a new part (resetAnalysisState) clears the manual result, recommendation, and authorization drafts', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult({ status: 'generated' }));
    await runGuidedAnalysis();
    mockedRunManualCoreCavity.mockResolvedValue(makeResult());
    useAnalysisStore.getState().addCorePinFaceRef({ face_id: 35, axis_direction: [0, 0, 1], reason: 'test' });
    useAnalysisStore
      .getState()
      .addDelegation({ face_ids: [0], movement_direction: [1, 0, 0], movement_type: 'radial_slide', source: 's', note: 'n' });
    useAnalysisStore.getState().setManualPullDirection([1, 1, 1]);
    await runManualAnalysis([1, 1, 1]);

    useAnalysisStore.getState().resetAnalysisState();

    const state = useAnalysisStore.getState();
    expect(state.analysisResult).toBeNull();
    expect(state.recommendedResult).toBeNull();
    expect(state.corePinFaceRefs).toEqual([]);
    expect(state.delegations).toEqual([]);
    expect(state.manualPullDirection).toEqual([0, 0, 1]);
  });
});
