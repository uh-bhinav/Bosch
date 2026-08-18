/**
 * F3 acceptance tests for the Guided analysis orchestration service --
 * successful/blocked/referred/failed outcomes, shared-state population,
 * viewport delivery, no-duplicate-calls, and reset-on-new-part-load.
 * `api/endpoints` and the viewport engine are mocked so these exercise
 * exactly the sequencing this module owns.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import { ApiError } from '../api/client';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests, getViewportEngine } from '../viewport/engineSingleton';
import type { CoreCavityAnalysisResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  runFullAnalysis: vi.fn(),
}));

import { runFullAnalysis } from '../api/endpoints';
import { __resetGuidedAnalysisForTests, runGuidedAnalysis } from './runGuidedAnalysis';

const mockedRunFullAnalysis = vi.mocked(runFullAnalysis);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeMeshPayload() {
  return {
    point_count: 4,
    triangle_count: 2,
    face_count: 2,
    face_ids: [0, 1],
    face_centers: {},
    points: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]] as [number, number, number][],
    faces: [[0, 1, 2], [0, 2, 3]] as [number, number, number][],
    core_cavity_classification: ['cavity', 'core'],
    core_cavity_rgb: [[0.2, 0.8, 0.4], [0.2, 0.4, 0.8]] as [number, number, number][],
  };
}

function makeResult(overrides: Partial<CoreCavityAnalysisResponse> = {}): CoreCavityAnalysisResponse {
  return {
    part: {},
    core_cavity: { face_counts: { cavity: 1, core: 1, parting: 0, skipped: 0 } },
    pull_direction_source: 'optimal_mold_direction',
    parting_line_v2_outcome: null,
    orchestration: {
      status: 'generated',
      failure_reason: null,
      pull_direction: [0, 0, 1],
      optimal_found: true,
      parting_line_v2_outcome: null,
      solid_split: { solid_split_status: 'split_ok' },
      delegated_face_ids: [],
      excluded_feature_ids: [],
      side_cores: null,
      side_core_combined: {},
    },
    display_mesh: makeMeshPayload(),
    ...overrides,
  };
}

beforeEach(() => {
  resetStore();
  __resetViewportEngineForTests();
  __resetGuidedAnalysisForTests();
  mockedRunFullAnalysis.mockReset();
  useAnalysisStore.getState().setCurrentPart('Part1.stp');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('runGuidedAnalysis', () => {
  it('does nothing when no part is loaded', async () => {
    useAnalysisStore.getState().setCurrentPart(null);
    await runGuidedAnalysis();
    expect(mockedRunFullAnalysis).not.toHaveBeenCalled();
  });

  it('a successful "generated" result populates shared state and marks the pipeline complete', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult());

    await runGuidedAnalysis();

    const state = useAnalysisStore.getState();
    expect(state.pipelineStatus).toBe('complete');
    expect(state.analysisResult?.orchestration?.status).toBe('generated');
    expect(state.analysisError).toBeNull();
  });

  it('populates the shared pull direction from the result, mapping the backend source string', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult());

    await runGuidedAnalysis();

    const state = useAnalysisStore.getState();
    expect(state.pullDirection).toEqual([0, 0, 1]);
    expect(state.pullDirectionSource).toBe('optimizer');
  });

  it('sets the overlay to "core-cavity" and pushes the mesh into the persistent viewport engine', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult());
    const engine = getViewportEngine();
    const setMeshSpy = vi.spyOn(engine, 'setMesh');
    const setOverlayColorsSpy = vi.spyOn(engine, 'setOverlayColors');

    await runGuidedAnalysis();

    expect(setMeshSpy).toHaveBeenCalledTimes(1);
    expect(setOverlayColorsSpy).toHaveBeenCalledTimes(1);
    const colors = setOverlayColorsSpy.mock.calls[0][0];
    expect(colors?.get(0)).toEqual(new THREE.Color(0.2, 0.8, 0.4));
    expect(colors?.get(1)).toEqual(new THREE.Color(0.2, 0.4, 0.8));
    expect(useAnalysisStore.getState().overlay).toBe('core-cavity');
  });

  it('does not recreate the viewport engine -- same instance before and after', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult());
    const engineBefore = getViewportEngine();

    await runGuidedAnalysis();

    expect(getViewportEngine()).toBe(engineBefore);
  });

  it('a "no feasible candidate" result is reported as blocked, not a thrown error', async () => {
    mockedRunFullAnalysis.mockResolvedValue(
      makeResult({
        orchestration: {
          status: 'blocked_by_parting_line',
          failure_reason: 'analyse_parting_line found no selected candidate',
          pull_direction: [0.5, 0.5, 0.707],
          optimal_found: true,
          parting_line_v2_outcome: 'no_feasible_candidate',
          solid_split: null,
          delegated_face_ids: [],
          excluded_feature_ids: [],
          side_cores: null,
          side_core_combined: {},
        },
      }),
    );

    await runGuidedAnalysis();

    const state = useAnalysisStore.getState();
    expect(state.pipelineStatus).toBe('blocked');
    expect(state.analysisResult?.orchestration?.status).toBe('blocked_by_parting_line');
    expect(state.analysisResult?.orchestration?.parting_line_v2_outcome).toBe('no_feasible_candidate');
    expect(state.analysisError).toBeNull();
  });

  it('a "referred to side action" result is reported as blocked with the referral outcome intact', async () => {
    mockedRunFullAnalysis.mockResolvedValue(
      makeResult({
        orchestration: {
          status: 'blocked_by_parting_line',
          failure_reason: 'requires side action',
          pull_direction: [0, 1, 0],
          optimal_found: true,
          parting_line_v2_outcome: 'referred_to_side_action',
          solid_split: null,
          delegated_face_ids: [],
          excluded_feature_ids: [],
          side_cores: null,
          side_core_combined: {},
        },
      }),
    );

    await runGuidedAnalysis();

    expect(useAnalysisStore.getState().analysisResult?.orchestration?.parting_line_v2_outcome).toBe(
      'referred_to_side_action',
    );
    expect(useAnalysisStore.getState().pipelineStatus).toBe('blocked');
  });

  it('a backend/network failure sets analysisError and marks the pipeline blocked, without touching analysisResult', async () => {
    mockedRunFullAnalysis.mockRejectedValue(
      new ApiError('Could not reach the backend.', 0, '/parts/Part1.stp/core-cavity'),
    );

    await runGuidedAnalysis();

    const state = useAnalysisStore.getState();
    expect(state.pipelineStatus).toBe('blocked');
    expect(state.analysisError).toBe('Could not reach the backend.');
    expect(state.analysisResult).toBeNull();
  });

  it('sets pipelineStatus to "running" while the request is in flight', async () => {
    let resolveFn!: (value: CoreCavityAnalysisResponse) => void;
    mockedRunFullAnalysis.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const promise = runGuidedAnalysis();
    expect(useAnalysisStore.getState().pipelineStatus).toBe('running');

    resolveFn(makeResult());
    await promise;
    expect(useAnalysisStore.getState().pipelineStatus).toBe('complete');
  });

  it('a second call while one is already running does not fire a duplicate backend request', async () => {
    let resolveFn!: (value: CoreCavityAnalysisResponse) => void;
    mockedRunFullAnalysis.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const first = runGuidedAnalysis();
    const second = runGuidedAnalysis();
    expect(mockedRunFullAnalysis).toHaveBeenCalledTimes(1);

    resolveFn(makeResult());
    await Promise.all([first, second]);
    expect(mockedRunFullAnalysis).toHaveBeenCalledTimes(1);
  });

  it('loading a new part resets the previous analysis result, error, and pipeline status', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult());
    await runGuidedAnalysis();
    expect(useAnalysisStore.getState().analysisResult).not.toBeNull();

    useAnalysisStore.getState().resetAnalysisState();

    const state = useAnalysisStore.getState();
    expect(state.analysisResult).toBeNull();
    expect(state.analysisError).toBeNull();
    expect(state.pipelineStatus).toBe('idle');
  });
});
