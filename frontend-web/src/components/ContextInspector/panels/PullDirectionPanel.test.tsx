/**
 * F4 component-level tests for the Pull Direction panel: recommended
 * direction display, manual vector input (no client-side normalization),
 * axis presets, and the recommended-vs-manual comparison staying available.
 * `runManualAnalysis` is mocked so these assert exactly what the panel
 * hands the service, without needing a real viewport/network.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAnalysisStore } from '../../../store/analysisStore';
import { PullDirectionPanel } from './PullDirectionPanel';
import type { CoreCavityAnalysisResponse } from '../../../api/types';

vi.mock('../../../analysis/runManualAnalysis', () => ({
  runManualAnalysis: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('../../../viewport/engineSingleton', () => ({
  getViewportEngine: () => ({
    setDirectionArrow: vi.fn(),
    getFaceNormal: vi.fn((faceId: number) => (faceId === 7 ? [0, 1, 0] : null)),
  }),
}));

import { runManualAnalysis } from '../../../analysis/runManualAnalysis';

const mockedRunManualAnalysis = vi.mocked(runManualAnalysis);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeResult(overrides: Partial<CoreCavityAnalysisResponse['orchestration']> = {}): CoreCavityAnalysisResponse {
  return {
    part: {},
    core_cavity: {},
    pull_direction_source: 'optimal_mold_direction',
    parting_line_v2_outcome: null,
    orchestration: {
      status: 'generated',
      failure_reason: null,
      pull_direction: [0, 0, 1],
      optimal_found: true,
      parting_line_v2_outcome: null,
      solid_split: null,
      delegated_face_ids: [],
      excluded_feature_ids: [],
      side_cores: null,
      side_core_combined: {},
      ...overrides,
    },
  };
}

beforeEach(() => {
  resetStore();
  mockedRunManualAnalysis.mockClear();
  useAnalysisStore.getState().setCurrentPart('Part1.stp');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('PullDirectionPanel', () => {
  it('shows a hint when no recommendation has run yet', () => {
    render(<PullDirectionPanel />);
    expect(screen.getByTestId('recommended-result-empty')).toBeInTheDocument();
  });

  it('displays the recommended direction and verdict once the Guided run has populated recommendedResult', () => {
    useAnalysisStore.getState().setRecommendedResult(makeResult());
    render(<PullDirectionPanel />);

    const card = screen.getByTestId('recommended-result-card');
    expect(within(card).getByText('(0.000, 0.000, 1.000)')).toBeInTheDocument();
    expect(within(card).getByText('Feasible — mold split generated')).toBeInTheDocument();
  });

  it('typing a manual vector sends exactly what was typed, unnormalized, when running', async () => {
    const user = userEvent.setup();
    render(<PullDirectionPanel />);

    const xInput = screen.getByLabelText('Manual pull direction X component');
    const yInput = screen.getByLabelText('Manual pull direction Y component');
    await user.clear(xInput);
    await user.type(xInput, '3');
    await user.clear(yInput);
    await user.type(yInput, '-4');
    // Z is left at its default (1) -- (3, -4, 1) has magnitude 5.09..., a
    // deliberately non-unit vector so any client-side normalization would
    // be caught by the exact-args assertion below.

    await user.click(screen.getByRole('button', { name: 'Run Manual Analysis' }));

    expect(mockedRunManualAnalysis).toHaveBeenCalledTimes(1);
    expect(mockedRunManualAnalysis).toHaveBeenCalledWith([3, -4, 1], [], []);
  });

  it('disables the run button while a vector field is not a valid number, without silently substituting a value', async () => {
    const user = userEvent.setup();
    render(<PullDirectionPanel />);

    const xInput = screen.getByLabelText('Manual pull direction X component');
    await user.clear(xInput);
    await user.type(xInput, 'not-a-number');

    expect(screen.getByRole('button', { name: 'Run Manual Analysis' })).toBeDisabled();
  });

  it('allows submitting an exact zero vector -- the frontend does not reject it, the backend does', async () => {
    const user = userEvent.setup();
    render(<PullDirectionPanel />);

    for (const label of [
      'Manual pull direction X component',
      'Manual pull direction Y component',
      'Manual pull direction Z component',
    ]) {
      const input = screen.getByLabelText(label);
      await user.clear(input);
      await user.type(input, '0');
    }

    const runButton = screen.getByRole('button', { name: 'Run Manual Analysis' });
    expect(runButton).toBeEnabled();
    await user.click(runButton);

    expect(mockedRunManualAnalysis).toHaveBeenCalledWith([0, 0, 0], [], []);
  });

  it('an axis preset sets the vector fields and is sent verbatim on run', async () => {
    const user = userEvent.setup();
    render(<PullDirectionPanel />);

    await user.click(screen.getByRole('button', { name: '−X' }));
    expect(screen.getByLabelText('Manual pull direction X component')).toHaveValue('-1');
    expect(screen.getByLabelText('Manual pull direction Y component')).toHaveValue('0');
    expect(screen.getByLabelText('Manual pull direction Z component')).toHaveValue('0');

    await user.click(screen.getByRole('button', { name: 'Run Manual Analysis' }));
    expect(mockedRunManualAnalysis).toHaveBeenCalledWith([-1, 0, 0], [], []);
  });

  it('"use selected face normal" fills the vector from the picked face, only when exactly one face is selected', async () => {
    const user = userEvent.setup();
    useAnalysisStore.getState().setSelectedFaceIds([7]);
    render(<PullDirectionPanel />);

    const useNormalButton = screen.getByRole('button', { name: 'Use selected face normal' });
    expect(useNormalButton).toBeEnabled();
    await user.click(useNormalButton);

    expect(screen.getByLabelText('Manual pull direction Y component')).toHaveValue('1');
  });

  it('the recommended result stays available for comparison after a manual run replaces the current result', () => {
    useAnalysisStore.getState().setRecommendedResult(makeResult({ status: 'generated' }));
    useAnalysisStore.getState().setAnalysisResult(
      makeResult({ status: 'blocked_by_parting_line', parting_line_v2_outcome: 'no_feasible_candidate' }),
    );
    useAnalysisStore.getState().setPullDirection([1, 1, 0], 'manual');

    render(<PullDirectionPanel />);

    const comparison = screen.getByTestId('comparison-table');
    expect(within(comparison).getByText('Feasible — mold split generated')).toBeInTheDocument();
    expect(within(comparison).getByText('No feasible parting line found')).toBeInTheDocument();
    // The recommended card is untouched, independent of the comparison section.
    expect(within(screen.getByTestId('recommended-result-card')).getByText('(0.000, 0.000, 1.000)')).toBeInTheDocument();
  });

  it('propagates committed authorization entries to the run call', async () => {
    useAnalysisStore.getState().addCorePinFaceRef({ face_id: 35, axis_direction: [0, 0, 1], reason: 'through-bore' });
    useAnalysisStore.getState().addDelegation({
      face_ids: [0, 1],
      movement_direction: [1, 0, 0],
      movement_type: 'radial_slide',
      source: 'manual_engineering',
      note: 'rib stack',
    });
    const user = userEvent.setup();
    render(<PullDirectionPanel />);

    await user.click(screen.getByRole('button', { name: 'Run Manual Analysis' }));

    expect(mockedRunManualAnalysis).toHaveBeenCalledWith(
      [0, 0, 1],
      [{ face_id: 35, axis_direction: [0, 0, 1], reason: 'through-bore' }],
      [{ face_ids: [0, 1], movement_direction: [1, 0, 0], movement_type: 'radial_slide', source: 'manual_engineering', note: 'rib stack' }],
    );
  });
});
