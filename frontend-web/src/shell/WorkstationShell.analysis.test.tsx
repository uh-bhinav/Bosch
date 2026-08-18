/**
 * F3 integration tests: the real "Run Full Analysis" button
 * (`components/TopBar/TopBar.tsx`) through the real `runGuidedAnalysis`
 * service and into the real `WorkstationShell`, proving the UI actually
 * communicates the required states (running / completed / blocked) and
 * that the persistent viewport is untouched by the analysis call itself.
 * Only `api/endpoints` is mocked -- no network.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkstationShell } from './WorkstationShell';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests, getViewportEngine } from '../viewport/engineSingleton';
import { __resetGuidedAnalysisForTests } from '../analysis/runGuidedAnalysis';
import type { CoreCavityAnalysisResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'healthy', parts_dir: '/data/parts', parts_dir_exists: true }),
  listParts: vi.fn().mockResolvedValue({ parts_dir: '/data/parts', files: [] }),
  runFullAnalysis: vi.fn(),
}));

import { runFullAnalysis } from '../api/endpoints';

const mockedRunFullAnalysis = vi.mocked(runFullAnalysis);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeResult(overrides: Partial<CoreCavityAnalysisResponse['orchestration']> = {}): CoreCavityAnalysisResponse {
  return {
    part: {},
    core_cavity: { face_counts: { cavity: 3, core: 2, parting: 1, skipped: 0 } },
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
  __resetGuidedAnalysisForTests();
  mockedRunFullAnalysis.mockReset();
  // A part is already loaded -- import (F2) is proven separately; these
  // tests are about the analysis run itself.
  useAnalysisStore.getState().setCurrentPart('Part1.stp', null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WorkstationShell Guided analysis', () => {
  it('the run button is disabled until a part is loaded', () => {
    useAnalysisStore.getState().setCurrentPart(null);
    render(<WorkstationShell />);
    expect(screen.getByRole('button', { name: 'Run Full Analysis' })).toBeDisabled();
  });

  it('running the analysis shows live progress, then lands on the completed/feasible state without freezing the viewport', async () => {
    let resolveFn!: (value: CoreCavityAnalysisResponse) => void;
    mockedRunFullAnalysis.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const user = userEvent.setup();
    render(<WorkstationShell />);
    const engineBefore = getViewportEngine();
    const viewportBefore = screen.getByTestId('viewport-root');

    await user.click(screen.getByRole('button', { name: 'Run Full Analysis' }));

    // Running: the button is replaced by a live progress indicator, and the
    // top-bar chip reads Running -- the UI is never frozen/silent.
    expect(screen.getByTestId('run-analysis-progress')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run Full Analysis' })).not.toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();

    // The persistent viewport is untouched by the in-flight request.
    expect(getViewportEngine()).toBe(engineBefore);
    expect(screen.getByTestId('viewport-root')).toBe(viewportBefore);

    resolveFn(makeResult());
    await screen.findByText('Complete');

    expect(await screen.findByTestId('analysis-verdict-badge')).toHaveTextContent(
      'Feasible — mold split generated',
    );
    expect(getViewportEngine()).toBe(engineBefore);
  });

  it('a blocked/no-feasible-candidate result is clearly communicated, not shown as success', async () => {
    mockedRunFullAnalysis.mockResolvedValue(
      makeResult({ status: 'blocked_by_parting_line', parting_line_v2_outcome: 'no_feasible_candidate' }),
    );

    const user = userEvent.setup();
    render(<WorkstationShell />);
    await user.click(screen.getByRole('button', { name: 'Run Full Analysis' }));

    expect(await screen.findByText('Blocked')).toBeInTheDocument();
    const badge = await screen.findByTestId('analysis-verdict-badge');
    expect(badge).toHaveTextContent('No feasible parting line found');
    expect(badge).toHaveAttribute('data-tone', 'bad');
  });

  it('a referred-to-side-action result is distinguished from a plain "no feasible candidate" block', async () => {
    mockedRunFullAnalysis.mockResolvedValue(
      makeResult({ status: 'blocked_by_parting_line', parting_line_v2_outcome: 'referred_to_side_action' }),
    );

    const user = userEvent.setup();
    render(<WorkstationShell />);
    await user.click(screen.getByRole('button', { name: 'Run Full Analysis' }));

    const badge = await screen.findByTestId('analysis-verdict-badge');
    expect(badge).toHaveTextContent('Needs a side action or referral');
    expect(badge).toHaveAttribute('data-tone', 'warn');
  });

  it('a backend failure is surfaced in the status strip detail without crashing the shell', async () => {
    mockedRunFullAnalysis.mockRejectedValue(new Error('network down'));

    const user = userEvent.setup();
    render(<WorkstationShell />);
    await user.click(screen.getByRole('button', { name: 'Run Full Analysis' }));

    expect(await screen.findByText('Blocked')).toBeInTheDocument();
    // Expand the status strip to see the error detail.
    await user.click(screen.getByRole('button', { name: /IDLE|RUNNING|COMPLETE|BLOCKED/i }));
    expect(await screen.findByTestId('analysis-error-detail')).toHaveTextContent(
      'Something went wrong running the analysis.',
    );
  });

  it('the Expert-mode Core/Cavity panel displays the same result read-only, with no independent run control', async () => {
    mockedRunFullAnalysis.mockResolvedValue(makeResult());
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByRole('button', { name: 'Run Full Analysis' }));
    await screen.findByText('Complete');

    await user.click(screen.getByTitle('Core / Cavity'));
    const inspector = screen.getByTestId('inspector');
    const panel = within(inspector).getByTestId('analysis-summary-panel');
    expect(within(panel).getByText('Feasible — mold split generated')).toBeInTheDocument();
    // F13: the tool now also renders a legend with its own per-category
    // count (same "3"), so this must be scoped to the verdict grid
    // specifically, not the whole panel, to stay unambiguous.
    const verdictCounts = within(panel).getByTestId('core-cavity-verdict-face-counts');
    expect(within(verdictCounts).getByText('3')).toBeInTheDocument(); // cavity face count
    expect(within(inspector).queryByRole('button', { name: /run/i })).not.toBeInTheDocument();
  });
});
