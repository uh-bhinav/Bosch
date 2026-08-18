/**
 * F4 integration tests: the real Pull Direction tool (manual vector,
 * authorization editor, "Run Manual Analysis") through the real
 * `WorkstationShell`, proving the persistent viewport survives the whole
 * flow -- changing tool, entering authorization, running manual analysis,
 * receiving the result -- and that the recommended/manual comparison
 * renders end to end. Only `api/endpoints` is mocked -- no network.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkstationShell } from './WorkstationShell';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests, getViewportEngine } from '../viewport/engineSingleton';
import { __resetAnalysisRunLockForTests } from '../analysis/analysisShared';
import type { CoreCavityAnalysisResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'healthy', parts_dir: '/data/parts', parts_dir_exists: true }),
  listParts: vi.fn().mockResolvedValue({ parts_dir: '/data/parts', files: [] }),
  runFullAnalysis: vi.fn(),
  runManualCoreCavity: vi.fn(),
}));

import { runFullAnalysis, runManualCoreCavity } from '../api/endpoints';

const mockedRunFullAnalysis = vi.mocked(runFullAnalysis);
const mockedRunManualCoreCavity = vi.mocked(runManualCoreCavity);

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
      pull_direction: [0, 0, -1],
      optimal_found: null,
      parting_line_v2_outcome: 'feasible',
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
  mockedRunFullAnalysis.mockReset();
  mockedRunManualCoreCavity.mockReset();
  useAnalysisStore.getState().setCurrentPart('Part1.stp', null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WorkstationShell manual pull direction', () => {
  it('the persistent viewport survives switching to Pull Direction, editing the vector, entering authorization, and running manual analysis', async () => {
    mockedRunManualCoreCavity.mockResolvedValue(makeResult());
    const user = userEvent.setup();
    render(<WorkstationShell />);

    const engineBefore = getViewportEngine();
    const viewportBefore = screen.getByTestId('viewport-root');

    await user.click(screen.getByTitle('Pull Direction'));
    expect(getViewportEngine()).toBe(engineBefore);
    expect(screen.getByTestId('viewport-root')).toBe(viewportBefore);

    await user.click(screen.getByRole('button', { name: '+X' }));
    expect(getViewportEngine()).toBe(engineBefore);

    await user.click(screen.getByRole('button', { name: /Authorization/ }));
    expect(screen.getByTestId('authorization-editor')).toBeInTheDocument();
    expect(getViewportEngine()).toBe(engineBefore);

    await user.click(screen.getByRole('button', { name: 'Run Manual Analysis' }));
    expect(getViewportEngine()).toBe(engineBefore);
    expect(screen.getByTestId('viewport-root')).toBe(viewportBefore);

    await screen.findByTestId('current-result-card');
    expect(getViewportEngine()).toBe(engineBefore);
  });

  it('the manual run replaces the top-bar/status-strip current result while a prior Guided recommendation stays comparable', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult({ status: 'generated', parting_line_v2_outcome: 'feasible', pull_direction: [0, 0, 1] }));
    mockedRunManualCoreCavity.mockResolvedValue(
      makeResult({ status: 'blocked_by_parting_line', parting_line_v2_outcome: 'no_feasible_candidate', pull_direction: [1, 0, 0] }),
    );
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByRole('button', { name: 'Run Full Analysis' }));
    await screen.findByText('Complete');

    await user.click(screen.getByTitle('Pull Direction'));
    await user.click(screen.getByRole('button', { name: '+X' }));
    await user.click(screen.getByRole('button', { name: 'Run Manual Analysis' }));
    await screen.findByText('Blocked');

    const inspector = screen.getByTestId('inspector');
    const comparison = within(inspector).getByTestId('comparison-table');
    expect(within(comparison).getByText('Feasible — mold split generated')).toBeInTheDocument();
    expect(within(comparison).getByText('No feasible parting line found')).toBeInTheDocument();
  });

  it('entering the real Part3 candidate-110 authorization through the structured editor and running it renders the real live outcome (needs a side action/referral)', async () => {
    // The mocked response here is byte-for-byte the REAL response this
    // session's backend returned for this exact core-pin/delegation
    // payload against Part3.stp (2026-08-17 F4 verification) --
    // `blocked_by_parting_line`/`referred_to_side_action`, not `feasible`
    // (the frozen unit-test fixture at tests/test_parting_line_v2_region_
    // balance.py uses `UndercutInput.empty()`; this endpoint's manual path
    // deliberately uses real undercut evidence, so the two are not expected
    // to agree -- see CHANGELOG.md "Phase F4"). This test drives the actual
    // structured authorization editor (not a store shortcut) to prove the
    // engineer-facing form produces the exact backend contract shape.
    useAnalysisStore.getState().setCurrentPart('Part3.stp', null);
    mockedRunManualCoreCavity.mockResolvedValue(
      makeResult({
        status: 'blocked_by_parting_line',
        failure_reason:
          "analyse_parting_line found no selected candidate for this direction (outcome='referred_to_side_action').",
        parting_line_v2_outcome: 'referred_to_side_action',
        pull_direction: [0, 0, 1],
      }),
    );
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByTitle('Pull Direction'));
    await user.click(screen.getByRole('button', { name: '+Z' }));
    await user.click(screen.getByRole('button', { name: /Authorization/ }));

    // Core-pin face reference: face 35, axis (0,0,1) -- default-prefilled
    // from the manual direction, left as-is -- reason "straight coaxial
    // through-bore".
    await user.type(screen.getByLabelText('Face ID'), '35');
    await user.type(screen.getByLabelText('Reason'), 'straight coaxial through-bore');
    await user.click(screen.getByRole('button', { name: 'Add core-pin reference' }));

    // Delegation 1: original rib stack, faces 0-16, radial outward +X.
    await user.type(screen.getByLabelText('Face IDs (comma-separated)'), '0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16');
    const delX = screen.getByLabelText('Delegation movement direction X component');
    await user.clear(delX);
    await user.type(delX, '1');
    await user.type(screen.getByLabelText('Note'), 'original rib stack, radial outward +X');
    await user.click(screen.getByRole('button', { name: 'Add delegation' }));

    // Delegation 2: mirror rib stack, faces 18-34, radial outward -X.
    await user.type(screen.getByLabelText('Face IDs (comma-separated)'), '18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34');
    await user.clear(delX);
    await user.type(delX, '-1');
    await user.type(screen.getByLabelText('Note'), 'mirror rib stack, radial outward -X');
    await user.click(screen.getByRole('button', { name: 'Add delegation' }));

    expect(screen.getByTestId('core-pin-list')).toHaveTextContent('Face 35');
    expect(screen.getByTestId('delegation-list')).toHaveTextContent('original rib stack');
    expect(screen.getByTestId('delegation-list')).toHaveTextContent('mirror rib stack');

    await user.click(screen.getByRole('button', { name: 'Run Manual Analysis' }));

    expect(mockedRunManualCoreCavity).toHaveBeenCalledWith('Part3.stp', [0, 0, 1], {
      corePinFaceRefs: [{ face_id: 35, axis_direction: [0, 0, 1], reason: 'straight coaxial through-bore' }],
      delegations: [
        {
          face_ids: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
          movement_direction: [1, 0, 0],
          movement_type: 'radial_slide',
          source: 'manual_engineering',
          note: 'original rib stack, radial outward +X',
        },
        {
          face_ids: [18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34],
          movement_direction: [-1, 0, 0],
          movement_type: 'radial_slide',
          source: 'manual_engineering',
          note: 'mirror rib stack, radial outward -X',
        },
      ],
    });

    const card = await screen.findByTestId('current-result-card');
    expect(within(card).getByText('Needs a side action or referral')).toBeInTheDocument();
  });
});
