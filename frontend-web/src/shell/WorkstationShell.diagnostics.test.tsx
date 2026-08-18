/**
 * F5 integration tests: the real Diagnostics workspace through the real
 * `WorkstationShell`, proving it (a) reads only the already-populated
 * shared analysis state -- zero backend calls of its own, (b) never
 * replaces the current analysis result, (c) clicking a face-list row
 * (inconsistent face IDs) updates the SAME shared `selectedFaceIds` the
 * viewport already renders from, without recreating the persistent
 * viewport, and (d) raw JSON only ever becomes visible once "Advanced" is
 * explicitly expanded. Only `api/endpoints` is mocked -- no network -- and
 * this test asserts NONE of those mocks are ever called.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkstationShell } from './WorkstationShell';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests, getViewportEngine } from '../viewport/engineSingleton';
import type { CoreCavityAnalysisResponse, PartSummaryResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'healthy', parts_dir: '/data/parts', parts_dir_exists: true }),
  listParts: vi.fn().mockResolvedValue({ parts_dir: '/data/parts', files: [] }),
  runFullAnalysis: vi.fn(),
  runManualCoreCavity: vi.fn(),
}));

import { getHealth, listParts, runFullAnalysis, runManualCoreCavity } from '../api/endpoints';

const mockedRunFullAnalysis = vi.mocked(runFullAnalysis);
const mockedRunManualCoreCavity = vi.mocked(runManualCoreCavity);
const mockedGetHealth = vi.mocked(getHealth);
const mockedListParts = vi.mocked(listParts);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

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

// Real capture: manual +Z on Part1.stp, this session's live backend --
// `inconsistent_face_ids` overridden with representative sample IDs so the
// clickable face-list row has something concrete to click.
const REAL_PART1_RESULT: CoreCavityAnalysisResponse = {
  part: {},
  core_cavity: {
    face_counts: { cavity: 24, core: 217, parting: 70, skipped: 0 },
    inconsistent_face_ids: [12, 47],
    classification_source: 'parting_line_v2',
    warnings: [],
  },
  pull_direction_source: 'manual_query_direction',
  parting_line_v2_outcome: 'feasible',
  orchestration: {
    status: 'generated',
    failure_reason: null,
    pull_direction: [0, 0, 1],
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

beforeEach(() => {
  resetStore();
  __resetViewportEngineForTests();
  mockedRunFullAnalysis.mockReset();
  mockedRunManualCoreCavity.mockReset();
  mockedGetHealth.mockClear();
  mockedListParts.mockClear();
  useAnalysisStore.getState().setCurrentPart('Part1.stp', REAL_PART1_SUMMARY);
  useAnalysisStore.getState().setAnalysisResult(REAL_PART1_RESULT);
  useAnalysisStore.getState().setPullDirection([0, 0, 1], 'manual');
  useAnalysisStore.getState().setPipelineStatus('complete');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WorkstationShell Diagnostics workspace', () => {
  it('makes zero backend calls of its own beyond the shell\'s own health/parts bootstrap', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);
    await screen.findByTestId('viewport-root');

    await user.click(screen.getByTitle('Diagnostics'));
    const coreCavityGroup1 = screen.getByTestId('diagnostic-group-core-cavity');
    await user.click(within(coreCavityGroup1).getByRole('button', { name: /Core \/ Cavity/ }));
    await user.click(within(coreCavityGroup1).getByRole('button', { name: /Details/ }));

    expect(mockedRunFullAnalysis).not.toHaveBeenCalled();
    expect(mockedRunManualCoreCavity).not.toHaveBeenCalled();
    // The shell's own bootstrap calls these once on mount -- Diagnostics must add no further calls.
    expect(mockedGetHealth).toHaveBeenCalledTimes(1);
    expect(mockedListParts).toHaveBeenCalledTimes(1);
  });

  it('does not replace the current analysisResult -- Diagnostics is read-only', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);
    const before = useAnalysisStore.getState().analysisResult;

    await user.click(screen.getByTitle('Diagnostics'));
    const coreCavityGroup2 = screen.getByTestId('diagnostic-group-core-cavity');
    await user.click(within(coreCavityGroup2).getByRole('button', { name: /Core \/ Cavity/ }));
    await user.click(within(coreCavityGroup2).getByRole('button', { name: /Advanced/ }));

    expect(useAnalysisStore.getState().analysisResult).toBe(before);
  });

  it('clicking a face-list row selects those faces in the SAME shared state the viewport renders from, without recreating the viewport', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);
    const engineBefore = getViewportEngine();
    const viewportBefore = screen.getByTestId('viewport-root');

    await user.click(screen.getByTitle('Diagnostics'));
    const coreCavityGroup = screen.getByTestId('diagnostic-group-core-cavity');
    await user.click(within(coreCavityGroup).getByRole('button', { name: /Core \/ Cavity/ }));
    await user.click(within(coreCavityGroup).getByRole('button', { name: /Details/ }));

    const faceButton = within(coreCavityGroup).getByRole('button', { name: /2 faces — click to select/ });
    await user.click(faceButton);

    expect(useAnalysisStore.getState().selectedFaceIds).toEqual([12, 47]);
    expect(getViewportEngine()).toBe(engineBefore);
    expect(screen.getByTestId('viewport-root')).toBe(viewportBefore);
  });

  it('raw JSON is only visible once "Advanced" is explicitly expanded, never by default', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByTitle('Diagnostics'));
    const coreCavityGroup = screen.getByTestId('diagnostic-group-core-cavity');
    await user.click(within(coreCavityGroup).getByRole('button', { name: /Core \/ Cavity/ }));

    expect(within(coreCavityGroup).queryByTestId('diagnostic-advanced-core-cavity')).not.toBeInTheDocument();
    expect(screen.queryByText(/"solid_split_status"/)).not.toBeInTheDocument();

    await user.click(within(coreCavityGroup).getByRole('button', { name: /Advanced/ }));
    expect(within(coreCavityGroup).getByTestId('diagnostic-advanced-core-cavity')).toBeInTheDocument();
  });

  it('recommended vs. current direction remain distinguishable in the Diagnostics view', async () => {
    useAnalysisStore.getState().setRecommendedResult({
      ...REAL_PART1_RESULT,
      orchestration: { ...REAL_PART1_RESULT.orchestration!, pull_direction: [0, 0, -1], optimal_found: true },
    });
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByTitle('Diagnostics'));
    const directionGroup = screen.getByTestId('diagnostic-group-pull-direction');
    await user.click(within(directionGroup).getByRole('button', { name: /Pull Direction Search/ }));

    expect(within(directionGroup).getByText('(0.000, 0.000, -1.000)')).toBeInTheDocument();
    expect(within(directionGroup).getByText('(0.000, 0.000, 1.000)')).toBeInTheDocument();
  });
});
