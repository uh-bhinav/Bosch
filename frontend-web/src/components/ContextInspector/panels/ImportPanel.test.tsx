/**
 * F2 component-level tests for the Import panel: file selection triggers
 * the load service, invalid files are rejected, part summary renders once
 * ready, and the recent-parts list re-opens an existing part.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAnalysisStore } from '../../../store/analysisStore';
import { ImportPanel } from './ImportPanel';

vi.mock('../../../import/loadPart', () => ({
  loadPartFromFile: vi.fn().mockResolvedValue(undefined),
  loadExistingPart: vi.fn().mockResolvedValue(undefined),
  isAcceptedStepFile: (file: File) => /\.(stp|step)$/i.test(file.name),
}));

import { loadExistingPart, loadPartFromFile } from '../../../import/loadPart';

function resetStore() {
  useAnalysisStore.setState(useAnalysisStore.getInitialState(), true);
}

beforeEach(() => {
  resetStore();
  vi.mocked(loadPartFromFile).mockClear();
  vi.mocked(loadExistingPart).mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ImportPanel', () => {
  it('shows the drop zone when no part is loaded', () => {
    render(<ImportPanel />);
    expect(screen.getByLabelText('Upload a STEP file')).toBeInTheDocument();
    expect(screen.getByText(/Drop a \.stp/)).toBeInTheDocument();
  });

  it('dispatches the selected file to the load service via the file input', async () => {
    const user = userEvent.setup();
    render(<ImportPanel />);

    const file = new File(['ISO-10303-21;'], 'Part1.stp', { type: 'application/octet-stream' });
    const input = screen.getByTestId('import-file-input') as HTMLInputElement;
    await user.upload(input, file);

    expect(loadPartFromFile).toHaveBeenCalledTimes(1);
    expect(loadPartFromFile).toHaveBeenCalledWith(file);
  });

  it('shows the backend error message when partLoadError is set', () => {
    useAnalysisStore.setState({ partLoadStatus: 'error', partLoadError: "'x.txt' is not a .stp/.step file." });
    render(<ImportPanel />);

    expect(screen.getByTestId('import-error')).toHaveTextContent("'x.txt' is not a .stp/.step file.");
  });

  it('shows a busy state while uploading', () => {
    useAnalysisStore.setState({ partLoadStatus: 'uploading' });
    render(<ImportPanel />);
    expect(screen.getByText('Uploading…')).toBeInTheDocument();
  });

  it('shows a busy state while loading geometry', () => {
    useAnalysisStore.setState({ partLoadStatus: 'loading-geometry' });
    render(<ImportPanel />);
    expect(screen.getByText('Loading geometry…')).toBeInTheDocument();
  });

  it('renders the geometry summary once a part is ready', () => {
    useAnalysisStore.setState({
      currentPart: 'abc123_Part1.stp',
      partLoadStatus: 'ready',
      currentPartSummary: {
        source_file: 'Part1.stp',
        face_count: 311,
        edge_count: 500,
        vertex_count: 400,
        solid_count: 1,
        shell_count: 1,
        bounding_box: {
          xmin: 0, ymin: 0, zmin: 0, xmax: 80, ymax: 60, zmax: 40,
          diagonal_mm: 100, center_mm: [40, 30, 20], dimensions_mm: [80, 60, 40],
        },
        has_cadquery_shape: false,
        surface_type_counts: {},
        edge_type_counts: {},
        load_time_s: 1.2,
        warnings: [],
        adjacency_stats: {},
      },
    });
    render(<ImportPanel />);

    const summary = screen.getByTestId('part-summary');
    expect(within(summary).getByText('abc123_Part1.stp')).toBeInTheDocument();
    expect(within(summary).getByText('311')).toBeInTheDocument();
    expect(within(summary).getByText('80 × 60 × 40 mm')).toBeInTheDocument();
  });

  it('lists other available parts and re-opens one on click', async () => {
    const user = userEvent.setup();
    useAnalysisStore.setState({
      currentPart: 'abc123_Part1.stp',
      availableParts: ['abc123_Part1.stp', 'Part3.stp', 'Dhukkan.stp'],
    });
    render(<ImportPanel />);

    // The current part is excluded from the "other parts" list.
    const list = screen.getByText('Available parts').closest('div')!;
    expect(within(list).queryByText('abc123_Part1.stp')).not.toBeInTheDocument();
    expect(within(list).getByText('Part3.stp')).toBeInTheDocument();

    await user.click(within(list).getByText('Part3.stp'));
    expect(loadExistingPart).toHaveBeenCalledWith('Part3.stp');
  });
});
