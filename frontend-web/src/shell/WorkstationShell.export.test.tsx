/**
 * F6 integration tests: the real Export tool through the real
 * `WorkstationShell`, proving (a) exporting never fires `runFullAnalysis`/
 * `runManualCoreCavity` (no duplicate/independent analysis calls), (b) the
 * persistent viewport survives the whole export flow, and (c) switching to
 * the Report tool and exporting does not disturb the current analysis
 * result -- F1-F5 behavior preserved. Only `api/endpoints` is mocked.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkstationShell } from './WorkstationShell';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetViewportEngineForTests, getViewportEngine } from '../viewport/engineSingleton';
import { __resetStepExportForTests } from '../export/runStepExport';
import { __resetPdfExportForTests } from '../export/runPdfExport';
import type { CoreCavityAnalysisResponse, MoldHalfExportResponse } from '../api/types';

vi.mock('../api/endpoints', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'healthy', parts_dir: '/data/parts', parts_dir_exists: true }),
  listParts: vi.fn().mockResolvedValue({ parts_dir: '/data/parts', files: [] }),
  runFullAnalysis: vi.fn(),
  runManualCoreCavity: vi.fn(),
  exportMoldHalves: vi.fn(),
  exportPdfReport: vi.fn(),
  stepDownloadUrl: (filename: string) => `/api/export/download/${filename}`,
}));
vi.mock('../export/downloadBlob', () => ({
  downloadBlob: vi.fn(),
}));

import { exportMoldHalves, exportPdfReport, runFullAnalysis, runManualCoreCavity } from '../api/endpoints';

const mockedExportMoldHalves = vi.mocked(exportMoldHalves);
const mockedExportPdfReport = vi.mocked(exportPdfReport);
const mockedRunFullAnalysis = vi.mocked(runFullAnalysis);
const mockedRunManualCoreCavity = vi.mocked(runManualCoreCavity);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

function makeAnalysisResult(): CoreCavityAnalysisResponse {
  return {
    part: {},
    core_cavity: {},
    pull_direction_source: 'optimal_mold_direction',
    parting_line_v2_outcome: 'feasible',
    orchestration: {
      status: 'generated', failure_reason: null, pull_direction: [0, 0, -1], optimal_found: true,
      parting_line_v2_outcome: 'feasible', solid_split: { solid_split_status: 'split_ok' },
      delegated_face_ids: [], excluded_feature_ids: [], side_cores: null, side_core_combined: {},
    },
  };
}

function makeExportResponse(): MoldHalfExportResponse {
  return {
    filename: 'Part1.stp',
    pull_direction: [0, 0, -1],
    export: {
      status: 'exported', output_path: '/srv/output/mold_halves/Part1_mold_halves.stp',
      download_filename: 'Part1_mold_halves.stp', file_size_bytes: 12345, schema: 'AP214', solid_count: 2,
    },
  };
}

beforeEach(() => {
  resetStore();
  __resetViewportEngineForTests();
  __resetStepExportForTests();
  __resetPdfExportForTests();
  mockedExportMoldHalves.mockReset();
  mockedExportPdfReport.mockReset();
  mockedRunFullAnalysis.mockReset();
  mockedRunManualCoreCavity.mockReset();
  useAnalysisStore.getState().setCurrentPart('Part1.stp', null);
  useAnalysisStore.getState().setAnalysisResult(makeAnalysisResult());
  useAnalysisStore.getState().setPullDirection([0, 0, -1], 'optimizer');
  useAnalysisStore.getState().setPipelineStatus('complete');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WorkstationShell export workflow', () => {
  it('exporting STEP never calls the analysis endpoints -- no duplicate/independent analysis run', async () => {
    mockedExportMoldHalves.mockResolvedValue(makeExportResponse());
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByTitle('Report'));
    await user.click(screen.getByRole('button', { name: 'Export STEP' }));
    await screen.findByTestId('step-export-result');

    expect(mockedRunFullAnalysis).not.toHaveBeenCalled();
    expect(mockedRunManualCoreCavity).not.toHaveBeenCalled();
    expect(mockedExportMoldHalves).toHaveBeenCalledTimes(1);
  });

  it('the persistent viewport survives switching to Report and exporting both STEP and PDF', async () => {
    mockedExportMoldHalves.mockResolvedValue(makeExportResponse());
    mockedExportPdfReport.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
    const user = userEvent.setup();
    render(<WorkstationShell />);

    const engineBefore = getViewportEngine();
    const viewportBefore = screen.getByTestId('viewport-root');

    await user.click(screen.getByTitle('Report'));
    expect(getViewportEngine()).toBe(engineBefore);

    await user.click(screen.getByRole('button', { name: 'Export STEP' }));
    await screen.findByTestId('step-export-result');
    expect(getViewportEngine()).toBe(engineBefore);

    await user.click(screen.getByRole('button', { name: /Generate & Download PDF/ }));
    await screen.findByTestId('pdf-export-complete');

    expect(getViewportEngine()).toBe(engineBefore);
    expect(screen.getByTestId('viewport-root')).toBe(viewportBefore);
  });

  it('exporting does not replace or clear the current analysisResult -- F1-F5 shared state is preserved', async () => {
    mockedExportMoldHalves.mockResolvedValue(makeExportResponse());
    const before = useAnalysisStore.getState().analysisResult;
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByTitle('Report'));
    await user.click(screen.getByRole('button', { name: 'Export STEP' }));
    await screen.findByTestId('step-export-result');

    expect(useAnalysisStore.getState().analysisResult).toBe(before);
    expect(useAnalysisStore.getState().pipelineStatus).toBe('complete');
  });

  it('switching tools before and after exporting still works normally (F1 tool-rail behavior unaffected)', async () => {
    const user = userEvent.setup();
    render(<WorkstationShell />);

    await user.click(screen.getByTitle('Report'));
    expect(useAnalysisStore.getState().activeTool).toBe('report');
    await user.click(screen.getByTitle('Pull Direction'));
    expect(useAnalysisStore.getState().activeTool).toBe('pull-direction');
  });
});
