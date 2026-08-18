/**
 * Acceptance tests 1-3 and 7 from the F1 spec:
 *   1. Application shell renders.
 *   2. All tool-rail tools are reachable.
 *   3. Switching tools changes the inspector.
 *   7. Tool selection and viewport selection use shared state.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkstationShell } from './WorkstationShell';
import { TOOLS } from '../domain/types';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests } from '../viewport/engineSingleton';

vi.mock('../api/endpoints', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'healthy', parts_dir: '/data/parts', parts_dir_exists: true }),
  listParts: vi.fn().mockResolvedValue({ parts_dir: '/data/parts', files: ['Part1.stp', 'Part3.stp'] }),
}));

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

beforeEach(() => {
  resetStore();
  __resetViewportEngineForTests();
});

describe('WorkstationShell', () => {
  it('renders the shell regions: top bar, tool rail, viewport, inspector, status strip', () => {
    render(<WorkstationShell />);

    expect(screen.getByText('Mold Workstation')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Tools' })).toBeInTheDocument();
    expect(screen.getByTestId('viewport-root')).toBeInTheDocument();
    expect(screen.getByTestId('inspector')).toBeInTheDocument();
    expect(screen.getByText(/READY|IDLE/)).toBeInTheDocument();
  });

  it('makes every tool-rail tool reachable and selectable', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);
    const rail = screen.getByRole('navigation', { name: 'Tools' });

    for (const tool of TOOLS) {
      const button = within(rail).getByTitle(tool.label);
      await user.click(button);
      expect(useAnalysisStore.getState().activeTool).toBe(tool.id);
    }
  });

  it('changes the inspector content when the active tool changes', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);
    const rail = screen.getByRole('navigation', { name: 'Tools' });
    const inspector = screen.getByTestId('inspector');

    expect(within(inspector).getByText('Import')).toBeInTheDocument();

    await user.click(within(rail).getByTitle('Undercuts'));

    expect(within(inspector).getByText('Undercuts')).toBeInTheDocument();
    expect(within(inspector).queryByText('Import')).not.toBeInTheDocument();
  });

  it('drives tool selection and viewport selection through the same shared store', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);
    const viewport = screen.getByTestId('viewport-root');
    const rail = screen.getByRole('navigation', { name: 'Tools' });

    expect(useAnalysisStore.getState().selectedFaceIds).toEqual([]);

    await user.click(viewport);
    expect(useAnalysisStore.getState().selectedFaceIds).toEqual([0]);

    // Selecting a different tool must not clear a selection that lives in
    // the shared store, not in the tool panel.
    await user.click(within(rail).getByTitle('Core / Cavity'));
    expect(useAnalysisStore.getState().selectedFaceIds).toEqual([0]);

    const inspector = screen.getByTestId('inspector');
    expect(within(inspector).getByText('1 face')).toBeInTheDocument();
  });
});
