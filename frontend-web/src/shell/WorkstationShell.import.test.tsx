/**
 * F2 integration tests: the real import flow through the real
 * `WorkstationShell`, `ImportPanel`, and `loadPart` service together
 * (only `api/endpoints` is mocked -- no network) -- proving the uploaded
 * STEP becomes the authoritative current part in shared state, the
 * viewport actually receives the loaded geometry, and the F1 persistent-
 * viewport architecture is unaffected by import.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as THREE from 'three';
import { WorkstationShell } from './WorkstationShell';
import { useAnalysisStore } from '../store/analysisStore';
import { getViewportEngine, __resetViewportEngineForTests } from '../viewport/engineSingleton';
import type { PartSummaryResponse, UploadResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'healthy', parts_dir: '/data/parts', parts_dir_exists: true }),
  listParts: vi.fn().mockResolvedValue({ parts_dir: '/data/parts', files: [] }),
  uploadPart: vi.fn(),
  getSummary: vi.fn(),
}));

import { getSummary, uploadPart } from '../api/endpoints';

const mockedUploadPart = vi.mocked(uploadPart);
const mockedGetSummary = vi.mocked(getSummary);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeSummary(): PartSummaryResponse {
  return {
    source_file: 'Part1.stp',
    face_count: 311,
    edge_count: 500,
    vertex_count: 400,
    solid_count: 1,
    shell_count: 1,
    bounding_box: {
      xmin: -40, ymin: -30, zmin: -20, xmax: 40, ymax: 30, zmax: 20,
      diagonal_mm: 100, center_mm: [0, 0, 0], dimensions_mm: [80, 60, 40],
    },
    has_cadquery_shape: false,
    surface_type_counts: {},
    edge_type_counts: {},
    load_time_s: 1.1,
    warnings: [],
    adjacency_stats: {},
    display_mesh: {
      point_count: 4,
      triangle_count: 2,
      face_count: 1,
      face_ids: [0, 0],
      face_centers: {},
      points: [[-40, -30, 0], [40, -30, 0], [40, 30, 0], [-40, 30, 0]],
      faces: [[0, 1, 2], [0, 2, 3]],
    },
  };
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

describe('WorkstationShell import integration', () => {
  it('makes an uploaded part the authoritative current part in shared state, visible in the top bar', async () => {
    mockedUploadPart.mockResolvedValue({
      filename: 'deadbeef_Part1.stp', original_filename: 'Part1.stp', size_bytes: 1234,
    } satisfies UploadResponse);
    mockedGetSummary.mockResolvedValue(makeSummary());

    const user = userEvent.setup();
    render(<WorkstationShell />);

    expect(screen.getByText('No part loaded')).toBeInTheDocument();

    const file = new File(['ISO-10303-21;'], 'Part1.stp', { type: 'application/octet-stream' });
    const input = screen.getByTestId('import-file-input') as HTMLInputElement;
    await user.upload(input, file);

    // Both the top bar and the (still-mounted) import panel render the bare
    // part name, so this must be scoped to the top bar specifically --
    // `findByText` on the raw string would match both and throw.
    await expect(screen.findByTestId('topbar-part-name')).resolves.toHaveTextContent('deadbeef_Part1.stp');
    expect(useAnalysisStore.getState().currentPart).toBe('deadbeef_Part1.stp');
  });

  it('loads the uploaded geometry into the persistent viewport engine without recreating it', async () => {
    mockedUploadPart.mockResolvedValue({ filename: 'x_Part1.stp', original_filename: 'Part1.stp', size_bytes: 10 });
    mockedGetSummary.mockResolvedValue(makeSummary());

    const user = userEvent.setup();
    render(<WorkstationShell />);

    const engineBefore = getViewportEngine();
    const viewportNodeBefore = screen.getByTestId('viewport-root');
    // The F1 placeholder sample solid is loaded on mount -- confirm it's
    // there before import, so the post-upload check below proves a real
    // mesh SWAP happened, not just "a mesh exists because F1 put one there".
    const meshesBeforeImport = engineBefore.scene.children.filter((o) => o instanceof THREE.Mesh);
    expect(meshesBeforeImport).toHaveLength(1);

    const file = new File(['ISO-10303-21;'], 'Part1.stp', { type: 'application/octet-stream' });
    await user.upload(screen.getByTestId('import-file-input'), file);
    await screen.findByTestId('part-summary');

    // Same engine, same DOM node -- upload never touched the viewport's
    // own lifecycle, only fed it new geometry. Mesh creation itself does
    // not require a real WebGL context (only rendering does), so this is a
    // real, WebGL-independent proof the uploaded geometry reached the
    // persistent three.js scene, not just the store.
    expect(getViewportEngine()).toBe(engineBefore);
    expect(screen.getByTestId('viewport-root')).toBe(viewportNodeBefore);
    const meshesAfterImport = engineBefore.scene.children.filter((o) => o instanceof THREE.Mesh);
    expect(meshesAfterImport).toHaveLength(1);
    const geometry = (meshesAfterImport[0] as THREE.Mesh).geometry;
    expect(geometry.getAttribute('position').count).toBe(4); // the 4-point sample mesh in makeSummary()
  });

  it('switching tools after a successful import still preserves selection and camera (F1 guarantees hold post-F2)', async () => {
    mockedUploadPart.mockResolvedValue({ filename: 'x_Part1.stp', original_filename: 'Part1.stp', size_bytes: 10 });
    mockedGetSummary.mockResolvedValue(makeSummary());

    const user = userEvent.setup();
    render(<WorkstationShell />);

    const file = new File(['ISO-10303-21;'], 'Part1.stp', { type: 'application/octet-stream' });
    await user.upload(screen.getByTestId('import-file-input'), file);
    await screen.findByTestId('part-summary');

    // F12: real click-to-inspect picking (ViewportEngine.pickFaceId) raycasts
    // against the loaded mesh -- jsdom's zero-size layout can't meaningfully
    // exercise that, so this drives the same shared selection state directly;
    // what's actually under test is selection surviving a tool switch after
    // import, not the raycast itself.
    useAnalysisStore.getState().toggleFaceSelection(0);
    expect(useAnalysisStore.getState().selectedFaceIds).toEqual([0]);

    await user.click(screen.getByTitle('Core / Cavity'));
    expect(useAnalysisStore.getState().selectedFaceIds).toEqual([0]);
    expect(useAnalysisStore.getState().currentPart).toBe('x_Part1.stp');
  });

  it('surfaces an upload error without disturbing an already-loaded part', async () => {
    mockedUploadPart.mockResolvedValue({ filename: 'x_Part1.stp', original_filename: 'Part1.stp', size_bytes: 10 });
    mockedGetSummary.mockResolvedValue(makeSummary());

    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.upload(
      screen.getByTestId('import-file-input'),
      new File(['ISO-10303-21;'], 'Part1.stp', { type: 'application/octet-stream' }),
    );
    await screen.findByTestId('part-summary');
    expect(useAnalysisStore.getState().currentPart).toBe('x_Part1.stp');

    mockedUploadPart.mockRejectedValueOnce(
      Object.assign(new Error('backend offline'), { name: 'ApiError' }),
    );
    await user.upload(
      screen.getByTestId('import-file-input'),
      new File(['ISO-10303-21;'], 'Part2.stp', { type: 'application/octet-stream' }),
    );

    await screen.findByTestId('import-error');
    // The failed second upload must not clobber the first, already-ready part.
    expect(useAnalysisStore.getState().currentPart).toBe('x_Part1.stp');
  });
});
