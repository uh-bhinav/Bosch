/**
 * F6 component-level tests for the Export panel: STEP export availability
 * gating, PDF section selection (fixed vs. real vs. unavailable rows),
 * unavailable-section handling, and dispatching to the export services
 * (mocked -- no network).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAnalysisStore } from '../../../store/analysisStore';
import { ExportPanel } from './ExportPanel';
import type { CoreCavityAnalysisResponse } from '../../../api/types';

vi.mock('../../../export/runStepExport', () => ({
  runStepExport: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('../../../export/runPdfExport', () => ({
  runPdfExport: vi.fn().mockResolvedValue(undefined),
}));

import { runPdfExport } from '../../../export/runPdfExport';
import { runStepExport } from '../../../export/runStepExport';

const mockedRunStepExport = vi.mocked(runStepExport);
const mockedRunPdfExport = vi.mocked(runPdfExport);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeResult(status: string): CoreCavityAnalysisResponse {
  return {
    part: {},
    core_cavity: {},
    pull_direction_source: 'optimal_mold_direction',
    parting_line_v2_outcome: null,
    orchestration: {
      status, failure_reason: null, pull_direction: [0, 0, -1], optimal_found: true,
      parting_line_v2_outcome: null, solid_split: status === 'generated' ? { solid_split_status: 'split_ok' } : null,
      delegated_face_ids: [], excluded_feature_ids: [], side_cores: null, side_core_combined: {},
    },
  };
}

beforeEach(() => {
  resetStore();
  mockedRunStepExport.mockClear();
  mockedRunPdfExport.mockClear();
  useAnalysisStore.getState().setCurrentPart('Part1.stp');
  useAnalysisStore.getState().setPullDirection([0, 0, -1], 'optimizer');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ExportPanel', () => {
  it('disables STEP export and shows a gating hint when there is no successful solid split', () => {
    render(<ExportPanel />);
    expect(screen.getByRole('button', { name: 'Export STEP' })).toBeDisabled();
    expect(screen.getByTestId('step-export-gate-hint')).toHaveTextContent('Run an analysis first.');
  });

  it('shows a specific gating hint when an analysis ran but did not reach a successful split', () => {
    useAnalysisStore.getState().setAnalysisResult(makeResult('blocked_by_parting_line'));
    render(<ExportPanel />);
    expect(screen.getByRole('button', { name: 'Export STEP' })).toBeDisabled();
    expect(screen.getByTestId('step-export-gate-hint')).toHaveTextContent(/Requires a successful core\/cavity solid split/);
  });

  it('enables STEP export once the current result shows a successful split', () => {
    useAnalysisStore.getState().setAnalysisResult(makeResult('generated'));
    render(<ExportPanel />);
    expect(screen.getByRole('button', { name: 'Export STEP' })).toBeEnabled();
    expect(screen.queryByTestId('step-export-gate-hint')).not.toBeInTheDocument();
  });

  it('clicking Export STEP calls the service exactly once', async () => {
    useAnalysisStore.getState().setAnalysisResult(makeResult('generated'));
    const user = userEvent.setup();
    render(<ExportPanel />);

    await user.click(screen.getByRole('button', { name: 'Export STEP' }));
    expect(mockedRunStepExport).toHaveBeenCalledTimes(1);
  });

  it('the always-included PDF sections render checked and disabled', () => {
    render(<ExportPanel />);
    const list = screen.getByTestId('pdf-section-list');
    for (const label of ['Part / Geometry', 'Parting Line', 'Core / Cavity classification', 'Undercuts']) {
      const row = screen.getByText(new RegExp(label)).closest('label')!;
      const checkbox = row.querySelector('input[type="checkbox"]') as HTMLInputElement;
      expect(checkbox).toBeChecked();
      expect(checkbox).toBeDisabled();
    }
    expect(list).toBeInTheDocument();
  });

  it('unavailable PDF sections (Pull Direction, Diagnostics/Metrics) render unchecked and disabled, never silently omitted', () => {
    render(<ExportPanel />);
    for (const label of ['Pull Direction', 'Diagnostics / Metrics']) {
      const row = screen.getByText(new RegExp(label)).closest('label')!;
      const checkbox = row.querySelector('input[type="checkbox"]') as HTMLInputElement;
      expect(checkbox).not.toBeChecked();
      expect(checkbox).toBeDisabled();
      expect(row).toHaveTextContent('not available');
    }
  });

  it('Executive Summary and Side Cores are real, independently toggleable checkboxes', async () => {
    const user = userEvent.setup();
    render(<ExportPanel />);

    const execRow = screen.getByText(/Executive Summary/).closest('label')!;
    const execCheckbox = execRow.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(execCheckbox).toBeEnabled();
    expect(execCheckbox).toBeChecked(); // default true

    const sideCoreRow = screen.getByText(/Side Cores/).closest('label')!;
    const sideCoreCheckbox = sideCoreRow.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(sideCoreCheckbox).toBeEnabled();
    expect(sideCoreCheckbox).not.toBeChecked(); // default false, opt-in

    await user.click(sideCoreCheckbox);
    expect(useAnalysisStore.getState().pdfSections.sideCores).toBe(true);

    await user.click(execCheckbox);
    expect(useAnalysisStore.getState().pdfSections.executiveSummary).toBe(false);
  });

  it('the Core/Cavity solid-split checkbox defaults from whether the current result already has a successful split', () => {
    useAnalysisStore.getState().setAnalysisResult(makeResult('generated'));
    render(<ExportPanel />);
    expect(useAnalysisStore.getState().pdfSections.solidSplit).toBe(true);
  });

  it('clicking Generate & Download PDF calls the service exactly once', async () => {
    const user = userEvent.setup();
    render(<ExportPanel />);

    await user.click(screen.getByRole('button', { name: /Generate & Download PDF/ }));
    expect(mockedRunPdfExport).toHaveBeenCalledTimes(1);
  });

  it('shows live elapsed-time progress text while an export is generating, not a frozen UI', () => {
    useAnalysisStore.getState().setAnalysisResult(makeResult('generated'));
    useAnalysisStore.getState().setStepExportStage('generating');
    render(<ExportPanel />);
    expect(screen.getByTestId('export-generating')).toHaveTextContent(/Generating STEP export…/);
  });

  it('shows the download link and result summary once STEP export completes', () => {
    useAnalysisStore.getState().setAnalysisResult(makeResult('generated'));
    useAnalysisStore.getState().setStepExportStage('complete');
    useAnalysisStore.getState().setStepExportResult({ downloadFilename: 'Part1_mold_halves.stp', fileSizeBytes: 45210, solidCount: 2 });
    render(<ExportPanel />);

    const link = screen.getByTestId('step-download-link');
    expect(link).toHaveAttribute('download', 'Part1_mold_halves.stp');
    expect(link.getAttribute('href')).toContain('/export/download/Part1_mold_halves.stp');
    expect(screen.getByText(/2 solid\(s\)/)).toBeInTheDocument();
  });

  it('shows a clear error message when STEP export fails', () => {
    useAnalysisStore.getState().setAnalysisResult(makeResult('generated'));
    useAnalysisStore.getState().setStepExportStage('failed');
    useAnalysisStore.getState().setStepExportError('degenerate sliver');
    render(<ExportPanel />);
    expect(screen.getByTestId('step-export-error')).toHaveTextContent('degenerate sliver');
  });
});
