/**
 * F6 acceptance tests for the PDF report export service -- correct
 * backend payload (section selection + reused direction/authorization),
 * successful download trigger, failure handling, no-duplicate-calls, and
 * never touching the current analysisResult.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { useAnalysisStore } from '../store/analysisStore';
import { __resetPdfExportForTests, runPdfExport } from './runPdfExport';

vi.mock('../api/endpoints', () => ({
  exportPdfReport: vi.fn(),
}));
vi.mock('./downloadBlob', () => ({
  downloadBlob: vi.fn(),
}));

import { exportPdfReport } from '../api/endpoints';
import { downloadBlob } from './downloadBlob';

const mockedExportPdfReport = vi.mocked(exportPdfReport);
const mockedDownloadBlob = vi.mocked(downloadBlob);

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

const FAKE_PDF_BLOB = new Blob(['%PDF-1.4 fake'], { type: 'application/pdf' });

beforeEach(() => {
  resetStore();
  __resetPdfExportForTests();
  mockedExportPdfReport.mockReset();
  mockedDownloadBlob.mockReset();
  useAnalysisStore.getState().setCurrentPart('Part1.stp');
  useAnalysisStore.getState().setPullDirection([0, 0, -1], 'optimizer');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('runPdfExport', () => {
  it('does nothing when no part is loaded', async () => {
    useAnalysisStore.getState().setCurrentPart(null);
    await runPdfExport();
    expect(mockedExportPdfReport).not.toHaveBeenCalled();
  });

  it('does nothing when no pull direction is resolved yet', async () => {
    useAnalysisStore.getState().setPullDirection(null, null);
    await runPdfExport();
    expect(mockedExportPdfReport).not.toHaveBeenCalled();
  });

  it('sends the exact section selection, direction, and authorization currently in the store', async () => {
    mockedExportPdfReport.mockResolvedValue(FAKE_PDF_BLOB);
    useAnalysisStore.getState().setPdfSections({ executiveSummary: true, solidSplit: true, sideCores: false });
    useAnalysisStore.getState().addDelegation({
      face_ids: [0, 1], movement_direction: [1, 0, 0], movement_type: 'radial_slide', source: 's', note: 'n',
    });

    await runPdfExport();

    expect(mockedExportPdfReport).toHaveBeenCalledWith(
      'Part1.stp',
      [0, 0, -1],
      { corePinFaceRefs: [], delegations: [{ face_ids: [0, 1], movement_direction: [1, 0, 0], movement_type: 'radial_slide', source: 's', note: 'n' }] },
      { executiveSummary: true, solidSplit: true, sideCores: false },
    );
  });

  it('a successful generation triggers a real download with a derived filename and marks the stage complete', async () => {
    mockedExportPdfReport.mockResolvedValue(FAKE_PDF_BLOB);

    await runPdfExport();

    expect(mockedDownloadBlob).toHaveBeenCalledWith(FAKE_PDF_BLOB, 'Part1_dfm_report.pdf');
    const state = useAnalysisStore.getState();
    expect(state.pdfExportStage).toBe('complete');
    expect(state.pdfExportError).toBeNull();
  });

  it('sets the stage to "generating" while the request is in flight', async () => {
    let resolveFn!: (value: Blob) => void;
    mockedExportPdfReport.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const promise = runPdfExport();
    await Promise.resolve();
    expect(useAnalysisStore.getState().pdfExportStage).toBe('generating');

    resolveFn(FAKE_PDF_BLOB);
    await promise;
    expect(useAnalysisStore.getState().pdfExportStage).toBe('complete');
  });

  it('a backend failure is caught and reported, not thrown, and never triggers a download', async () => {
    mockedExportPdfReport.mockRejectedValue(new ApiError('PDF generation failed.', 500, '/parts/Part1.stp/export/report'));

    await runPdfExport();

    const state = useAnalysisStore.getState();
    expect(state.pdfExportStage).toBe('failed');
    expect(state.pdfExportError).toBe('PDF generation failed.');
    expect(mockedDownloadBlob).not.toHaveBeenCalled();
  });

  it('a second call while one is already running does not fire a duplicate request', async () => {
    let resolveFn!: (value: Blob) => void;
    mockedExportPdfReport.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const first = runPdfExport();
    const second = runPdfExport();
    expect(mockedExportPdfReport).toHaveBeenCalledTimes(1);

    resolveFn(FAKE_PDF_BLOB);
    await Promise.all([first, second]);
    expect(mockedExportPdfReport).toHaveBeenCalledTimes(1);
  });

  it('never touches analysisResult -- report export is independent of the current analysis result', async () => {
    const existingResult = { part: {}, core_cavity: {}, pull_direction_source: 'optimal_mold_direction', parting_line_v2_outcome: 'feasible' } as never;
    useAnalysisStore.getState().setAnalysisResult(existingResult);
    mockedExportPdfReport.mockResolvedValue(FAKE_PDF_BLOB);

    await runPdfExport();

    expect(useAnalysisStore.getState().analysisResult).toBe(existingResult);
  });
});
