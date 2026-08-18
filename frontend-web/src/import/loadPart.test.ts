/**
 * F2 acceptance tests: upload, invalid file handling, current-part state,
 * viewport loading, and state reset -- for the orchestration service
 * itself, independent of any component. `api/endpoints` and the viewport
 * engine are mocked so these tests exercise exactly the sequencing this
 * module is responsible for.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests, getViewportEngine } from '../viewport/engineSingleton';
import type { PartSummaryResponse, UploadResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  uploadPart: vi.fn(),
  getSummary: vi.fn(),
}));

import { getSummary, uploadPart } from '../api/endpoints';
import { isAcceptedStepFile, loadExistingPart, loadPartFromFile } from './loadPart';

const mockedUploadPart = vi.mocked(uploadPart);
const mockedGetSummary = vi.mocked(getSummary);

function makeFile(name: string, content = 'ISO-10303-21;', type = 'application/octet-stream'): File {
  return new File([content], name, { type });
}

function makeSummary(overrides: Partial<PartSummaryResponse> = {}): PartSummaryResponse {
  return {
    source_file: 'part.stp',
    face_count: 42,
    edge_count: 90,
    vertex_count: 60,
    solid_count: 1,
    shell_count: 1,
    bounding_box: {
      xmin: -10, ymin: -10, zmin: -10, xmax: 10, ymax: 10, zmax: 10,
      diagonal_mm: 34.64, center_mm: [0, 0, 0], dimensions_mm: [20, 20, 20],
    },
    has_cadquery_shape: false,
    surface_type_counts: {},
    edge_type_counts: {},
    load_time_s: 0.5,
    warnings: [],
    adjacency_stats: {},
    display_mesh: {
      point_count: 4,
      triangle_count: 2,
      face_count: 1,
      face_ids: [0, 0],
      face_centers: {},
      points: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
      faces: [[0, 1, 2], [0, 2, 3]],
    },
    ...overrides,
  };
}

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

beforeEach(() => {
  resetStore();
  __resetViewportEngineForTests();
  mockedUploadPart.mockReset();
  mockedGetSummary.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('isAcceptedStepFile', () => {
  it('accepts .stp and .step, case-insensitively', () => {
    expect(isAcceptedStepFile(makeFile('Part1.stp'))).toBe(true);
    expect(isAcceptedStepFile(makeFile('Part1.STEP'))).toBe(true);
    expect(isAcceptedStepFile(makeFile('Part1.Step'))).toBe(true);
  });

  it('rejects everything else', () => {
    expect(isAcceptedStepFile(makeFile('notes.txt'))).toBe(false);
    expect(isAcceptedStepFile(makeFile('model.iges'))).toBe(false);
    expect(isAcceptedStepFile(makeFile('no-extension'))).toBe(false);
  });
});

describe('loadPartFromFile -- upload', () => {
  it('uploads, loads geometry, and makes the part the authoritative current part', async () => {
    const upload: UploadResponse = { filename: 'abc123_Part1.stp', original_filename: 'Part1.stp', size_bytes: 1000 };
    mockedUploadPart.mockResolvedValue(upload);
    mockedGetSummary.mockResolvedValue(makeSummary());

    await loadPartFromFile(makeFile('Part1.stp'));

    const state = useAnalysisStore.getState();
    expect(state.currentPart).toBe('abc123_Part1.stp');
    expect(state.currentPartSummary?.face_count).toBe(42);
    expect(state.partLoadStatus).toBe('ready');
    expect(state.partLoadError).toBeNull();
    expect(mockedUploadPart).toHaveBeenCalledTimes(1);
    expect(mockedGetSummary).toHaveBeenCalledWith('abc123_Part1.stp', { includeMesh: true, meshDeflection: 0.5 });
  });

  it('pushes the adapted mesh into the persistent viewport engine', async () => {
    mockedUploadPart.mockResolvedValue({ filename: 'x_Part.stp', original_filename: 'Part.stp', size_bytes: 10 });
    mockedGetSummary.mockResolvedValue(makeSummary());
    const engine = getViewportEngine();
    const setMeshSpy = vi.spyOn(engine, 'setMesh');
    const frameSpy = vi.spyOn(engine, 'frameToBoundingBox');

    await loadPartFromFile(makeFile('Part.stp'));

    expect(setMeshSpy).toHaveBeenCalledTimes(1);
    const adapted = setMeshSpy.mock.calls[0][0];
    expect(adapted.pointCount).toBe(4);
    expect(adapted.triangleCount).toBe(2);
    expect(frameSpy).toHaveBeenCalledWith([0, 0, 0], 34.64);
  });

  it('rejects an invalid extension before making any API call', async () => {
    await loadPartFromFile(makeFile('notes.txt'));

    const state = useAnalysisStore.getState();
    expect(state.partLoadStatus).toBe('error');
    expect(state.partLoadError).toMatch(/not a \.stp\/\.step file/);
    expect(mockedUploadPart).not.toHaveBeenCalled();
    expect(mockedGetSummary).not.toHaveBeenCalled();
    expect(state.currentPart).toBeNull();
  });

  it('surfaces a structured backend error when upload itself fails', async () => {
    mockedUploadPart.mockRejectedValue(
      new ApiError("'bad.stp' is not a .stp/.step file.", 400, '/parts/upload', {
        code: 'invalid_upload_extension',
        message: "'bad.stp' is not a .stp/.step file.",
        operation: 'STEP file upload',
        recovery_hint: 'Only .stp and .step files can be uploaded.',
        details: {},
      }),
    );

    await loadPartFromFile(makeFile('bad.stp'));

    const state = useAnalysisStore.getState();
    expect(state.partLoadStatus).toBe('error');
    expect(state.partLoadError).toBe("'bad.stp' is not a .stp/.step file.");
    expect(state.currentPart).toBeNull();
  });

  it('surfaces an error when the upload succeeds but geometry loading fails', async () => {
    mockedUploadPart.mockResolvedValue({ filename: 'y_bad.stp', original_filename: 'bad.stp', size_bytes: 5 });
    mockedGetSummary.mockRejectedValue(new ApiError('Malformed STEP content.', 422, '/parts/y_bad.stp/summary'));

    await loadPartFromFile(makeFile('bad.stp'));

    const state = useAnalysisStore.getState();
    expect(state.partLoadStatus).toBe('error');
    expect(state.partLoadError).toBe('Malformed STEP content.');
    // The upload DID happen and produced a filename, but it must not be
    // promoted to "current part" until geometry actually loads.
    expect(state.currentPart).toBeNull();
  });

  it('resets analysis-specific state but preserves workstation/UI state', async () => {
    mockedUploadPart.mockResolvedValue({ filename: 'z_Part2.stp', original_filename: 'Part2.stp', size_bytes: 10 });
    mockedGetSummary.mockResolvedValue(makeSummary());

    const store = useAnalysisStore.getState();
    store.setActiveTool('undercuts');
    store.setMode('expert');
    store.setSelectedFaceIds([1, 2, 3]);
    store.setPullDirection([0, 0, 1], 'manual');
    store.setOverlay('draft');
    store.setPipelineStatus('running');
    store.setAvailableParts({ parts_dir: '/data/parts', files: ['Part1.stp'] });
    store.setBackendConnectivity('online');

    await loadPartFromFile(makeFile('Part2.stp'));

    const after = useAnalysisStore.getState();
    // Analysis-specific: reset.
    expect(after.selectedFaceIds).toEqual([]);
    expect(after.pullDirection).toBeNull();
    expect(after.pullDirectionSource).toBeNull();
    expect(after.overlay).toBeNull();
    expect(after.pipelineStatus).toBe('idle');
    // Workstation/UI: preserved.
    expect(after.activeTool).toBe('undercuts');
    expect(after.mode).toBe('expert');
    expect(after.availableParts).toEqual(['Part1.stp']);
    expect(after.backendConnectivity).toBe('online');
  });
});

describe('loadExistingPart', () => {
  it('loads a known part without uploading anything', async () => {
    mockedGetSummary.mockResolvedValue(makeSummary({ source_file: 'Part3.stp' }));

    await loadExistingPart('Part3.stp');

    expect(mockedUploadPart).not.toHaveBeenCalled();
    expect(mockedGetSummary).toHaveBeenCalledWith('Part3.stp', { includeMesh: true, meshDeflection: 0.5 });
    const state = useAnalysisStore.getState();
    expect(state.currentPart).toBe('Part3.stp');
    expect(state.partLoadStatus).toBe('ready');
  });

  it('also resets analysis state while preserving workstation state', async () => {
    mockedGetSummary.mockResolvedValue(makeSummary());
    const store = useAnalysisStore.getState();
    store.setActiveTool('diagnostics');
    store.setSelectedFaceIds([9]);

    await loadExistingPart('Part1.stp');

    const after = useAnalysisStore.getState();
    expect(after.selectedFaceIds).toEqual([]);
    expect(after.activeTool).toBe('diagnostics');
  });
});
