/**
 * The import orchestration service (F2).
 *
 * Deliberately NOT inside the Zustand store (the store stays pure data,
 * per F1's "STATE" architecture) and NOT inside a component (components
 * must not call the API layer or the viewport engine directly). This is
 * the one place that sequences: reset analysis state -> call the API ->
 * adapt the returned mesh -> push it into the persistent viewport -> update
 * the shared store's `currentPart`/`currentPartSummary`/`partLoadStatus`.
 *
 * Both entry points -- a fresh upload and re-opening an already-known part
 * -- converge on the same `applySummary` step, so "the uploaded STEP
 * becomes the authoritative current part" and "select an existing part"
 * behave identically from here down.
 */

import { ApiError } from '../api/client';
import { getSummary, uploadPart } from '../api/endpoints';
import type { PartSummaryResponse } from '../api/types';
import { adaptDisplayMesh } from '../geometry/meshAdapter';
import { useAnalysisStore } from '../store/analysisStore';
import { getViewportEngine } from '../viewport/engineSingleton';

const ACCEPTED_EXTENSIONS = ['.stp', '.step'];

export function isAcceptedStepFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function applySummary(filename: string, summary: PartSummaryResponse): void {
  const store = useAnalysisStore.getState();
  store.setCurrentPart(filename, summary);

  const engine = getViewportEngine();
  const adapted = summary.display_mesh ? adaptDisplayMesh(summary.display_mesh) : null;
  if (adapted) {
    engine.setMesh(adapted);
  }
  engine.frameToBoundingBox(summary.bounding_box.center_mm, summary.bounding_box.diagonal_mm);

  store.setPartLoadStatus('ready');
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return 'Something went wrong loading this part.';
}

/**
 * Upload a new STEP file and make it the current part. Client-side
 * extension check first (immediate feedback, no round trip for an obvious
 * mistake) -- the backend re-validates independently regardless (never
 * trust the client alone), so this is a UX shortcut, not the real
 * validation boundary.
 */
export async function loadPartFromFile(file: File): Promise<void> {
  const store = useAnalysisStore.getState();
  store.resetAnalysisState();
  store.setPartLoadError(null);

  if (!isAcceptedStepFile(file)) {
    store.setPartLoadStatus('error');
    store.setPartLoadError(`'${file.name}' is not a .stp/.step file.`);
    return;
  }

  store.setPartLoadStatus('uploading');
  try {
    const uploaded = await uploadPart(file);
    store.setPartLoadStatus('loading-geometry');
    const summary = await getSummary(uploaded.filename, { includeMesh: true, meshDeflection: 0.5 });
    applySummary(uploaded.filename, summary);
  } catch (error) {
    store.setPartLoadStatus('error');
    store.setPartLoadError(describeError(error));
  }
}

/** Re-open a part already known to the backend (from `availableParts`). */
export async function loadExistingPart(filename: string): Promise<void> {
  const store = useAnalysisStore.getState();
  store.resetAnalysisState();
  store.setPartLoadError(null);
  store.setPartLoadStatus('loading-geometry');
  try {
    const summary = await getSummary(filename, { includeMesh: true, meshDeflection: 0.5 });
    applySummary(filename, summary);
  } catch (error) {
    store.setPartLoadStatus('error');
    store.setPartLoadError(describeError(error));
  }
}
