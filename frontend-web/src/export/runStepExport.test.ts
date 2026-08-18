/**
 * F6 acceptance tests for the STEP mold-half export service --
 * availability guards, successful export, failure handling (both a
 * blocked orchestration and a failed Boolean export), no-duplicate-calls,
 * and never touching the current `analysisResult`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetStepExportForTests, runStepExport } from './runStepExport';
import type { MoldHalfExportResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  exportMoldHalves: vi.fn(),
}));

import { exportMoldHalves } from '../api/endpoints';

const mockedExportMoldHalves = vi.mocked(exportMoldHalves);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeSuccessResponse(overrides: Partial<MoldHalfExportResponse> = {}): MoldHalfExportResponse {
  return {
    filename: 'Part1.stp',
    pull_direction: [0, 0, 1],
    orchestration: {
      status: 'generated', failure_reason: null, pull_direction: [0, 0, 1], optimal_found: null,
      parting_line_v2_outcome: 'feasible', solid_split: null,
      delegated_face_ids: [], excluded_feature_ids: [], side_cores: null, side_core_combined: {},
    },
    export: {
      status: 'exported',
      output_path: '/srv/output/mold_halves/Part1_mold_halves.stp',
      download_filename: 'Part1_mold_halves.stp',
      file_size_bytes: 45210,
      schema: 'AP214',
      solid_count: 2,
    },
    ...overrides,
  };
}

beforeEach(() => {
  resetStore();
  __resetStepExportForTests();
  mockedExportMoldHalves.mockReset();
  useAnalysisStore.getState().setCurrentPart('Part1.stp');
  useAnalysisStore.getState().setPullDirection([0, 0, 1], 'optimizer');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('runStepExport', () => {
  it('does nothing when no part is loaded', async () => {
    useAnalysisStore.getState().setCurrentPart(null);
    await runStepExport();
    expect(mockedExportMoldHalves).not.toHaveBeenCalled();
  });

  it('does nothing when no pull direction is resolved yet', async () => {
    useAnalysisStore.getState().setPullDirection(null, null);
    await runStepExport();
    expect(mockedExportMoldHalves).not.toHaveBeenCalled();
  });

  it('sends the already-resolved direction and authorization, never re-deriving it', async () => {
    mockedExportMoldHalves.mockResolvedValue(makeSuccessResponse());
    useAnalysisStore.getState().addCorePinFaceRef({ face_id: 35, axis_direction: [0, 0, 1], reason: 'through-bore' });

    await runStepExport();

    expect(mockedExportMoldHalves).toHaveBeenCalledWith('Part1.stp', [0, 0, 1], {
      corePinFaceRefs: [{ face_id: 35, axis_direction: [0, 0, 1], reason: 'through-bore' }],
      delegations: [],
    });
  });

  it('a successful export populates stepExportResult and marks the stage complete', async () => {
    mockedExportMoldHalves.mockResolvedValue(makeSuccessResponse());

    await runStepExport();

    const state = useAnalysisStore.getState();
    expect(state.stepExportStage).toBe('complete');
    expect(state.stepExportResult).toEqual({
      downloadFilename: 'Part1_mold_halves.stp',
      fileSizeBytes: 45210,
      solidCount: 2,
    });
    expect(state.stepExportError).toBeNull();
  });

  it('sets the stage to "generating" while the request is in flight', async () => {
    let resolveFn!: (value: MoldHalfExportResponse) => void;
    mockedExportMoldHalves.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const promise = runStepExport();
    // Allow the microtask queue to advance past "preparing" -> "generating".
    await Promise.resolve();
    expect(useAnalysisStore.getState().stepExportStage).toBe('generating');

    resolveFn(makeSuccessResponse());
    await promise;
    expect(useAnalysisStore.getState().stepExportStage).toBe('complete');
  });

  it('a blocked orchestration (export is null) is reported as failed with the real reason', async () => {
    mockedExportMoldHalves.mockResolvedValue({
      filename: 'Part1.stp',
      pull_direction: [1, 0, 0],
      orchestration: {
        status: 'blocked_by_parting_line', failure_reason: 'no selected candidate', pull_direction: [1, 0, 0],
        optimal_found: null, parting_line_v2_outcome: 'no_feasible_candidate', solid_split: null,
        delegated_face_ids: [], excluded_feature_ids: [], side_cores: null, side_core_combined: {},
      },
      export: null,
    });

    await runStepExport();

    const state = useAnalysisStore.getState();
    expect(state.stepExportStage).toBe('failed');
    expect(state.stepExportError).toBe('no selected candidate');
    expect(state.stepExportResult).toBeNull();
  });

  it('a failed Boolean export (export.status !== "exported") is reported as failed', async () => {
    mockedExportMoldHalves.mockResolvedValue(
      makeSuccessResponse({ export: { status: 'failed', failure_reason: 'degenerate sliver' } }),
    );

    await runStepExport();

    const state = useAnalysisStore.getState();
    expect(state.stepExportStage).toBe('failed');
    expect(state.stepExportError).toBe('degenerate sliver');
  });

  it('a network/backend failure is caught and reported, not thrown', async () => {
    mockedExportMoldHalves.mockRejectedValue(new ApiError('Could not reach the backend.', 0, '/parts/Part1.stp/export/mold-halves'));

    await runStepExport();

    const state = useAnalysisStore.getState();
    expect(state.stepExportStage).toBe('failed');
    expect(state.stepExportError).toBe('Could not reach the backend.');
  });

  it('a second call while one is already running does not fire a duplicate request', async () => {
    let resolveFn!: (value: MoldHalfExportResponse) => void;
    mockedExportMoldHalves.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const first = runStepExport();
    const second = runStepExport();
    expect(mockedExportMoldHalves).toHaveBeenCalledTimes(1);

    resolveFn(makeSuccessResponse());
    await Promise.all([first, second]);
    expect(mockedExportMoldHalves).toHaveBeenCalledTimes(1);
  });

  it('never touches analysisResult -- export is independent of the current analysis result', async () => {
    const existingResult = { part: {}, core_cavity: {}, pull_direction_source: 'optimal_mold_direction', parting_line_v2_outcome: 'feasible' } as never;
    useAnalysisStore.getState().setAnalysisResult(existingResult);
    mockedExportMoldHalves.mockResolvedValue(makeSuccessResponse());

    await runStepExport();

    expect(useAnalysisStore.getState().analysisResult).toBe(existingResult);
  });
});
