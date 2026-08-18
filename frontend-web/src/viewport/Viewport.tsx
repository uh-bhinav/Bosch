/**
 * The persistent viewport (F1's central acceptance criterion).
 *
 * Rendered exactly once, by `WorkstationShell`, as a permanent sibling of
 * `ContextInspector` -- never conditionally, never keyed on `activeTool`.
 * Switching tools re-renders `ContextInspector`'s content only; this
 * component's effect body (which calls `getViewportEngine().mount(...)`)
 * never re-runs for that reason, so the loaded mesh, camera, and selection
 * highlighting are untouched by tool switches. The engine itself is a
 * module singleton (see engineSingleton.ts) for an even stronger guarantee
 * than component lifetime alone.
 */

import { useEffect, useRef, type MouseEvent } from 'react';
import * as THREE from 'three';
import { useAnalysisStore } from '../store/analysisStore';
import { getViewportEngine } from './engineSingleton';
import { ViewportEngine } from './ViewportEngine';
import { adaptDisplayMesh, buildSampleMesh } from '../geometry/meshAdapter';
import styles from './Viewport.module.css';

export function Viewport() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const compareContainerRef = useRef<HTMLDivElement | null>(null);
  const compareEngineRef = useRef<ViewportEngine | null>(null);
  const selectedFaceIds = useAnalysisStore((s) => s.selectedFaceIds);
  const toggleFaceSelection = useAnalysisStore((s) => s.toggleFaceSelection);
  const clearSelection = useAnalysisStore((s) => s.clearSelection);
  const setCamera = useAnalysisStore((s) => s.setCamera);
  const showFaceBoundaries = useAnalysisStore((s) => s.showFaceBoundaries);
  const setShowFaceBoundaries = useAnalysisStore((s) => s.setShowFaceBoundaries);
  const compareMode = useAnalysisStore((s) => s.compareMode);
  const recommendedResult = useAnalysisStore((s) => s.recommendedResult);

  // Mount-only: this effect's dependency array is empty, so it runs exactly
  // once for the lifetime of the app (the component is never unmounted --
  // see WorkstationShell.tsx). Re-running this on every tool switch is
  // precisely the bug this architecture exists to prevent.
  useEffect(() => {
    const engine = getViewportEngine();
    const container = containerRef.current;
    if (!container) return;
    engine.mount(container);
    // F1: a placeholder solid, not real backend geometry yet (F0 §1.4,
    // F2 wires `/parts/{filename}/summary` through the same adaptDisplayMesh
    // path this sample already exercises).
    engine.setMesh(buildSampleMesh());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    getViewportEngine().setSelection(selectedFaceIds);
  }, [selectedFaceIds]);

  // F10 §2: purely visual -- never touches selection, overlay coloring, or
  // any store field an API call reads. See ViewportEngine.setShowFaceBoundaries.
  useEffect(() => {
    getViewportEngine().setShowFaceBoundaries(showFaceBoundaries);
  }, [showFaceBoundaries]);

  // F14: before/after split-screen comparison -- a SECOND, disposable
  // engine, entirely separate from the persistent singleton above (which
  // keeps showing whatever the current tool already shows, unaffected).
  // Only created while `compareMode` is on; always disposed when it turns
  // off or this effect re-runs, so no stray WebGL context/render loop
  // survives a toggle. Loads `recommendedResult` -- the first automatic
  // run's own real `display_mesh`/`core_cavity_rgb`, the same "BEFORE"
  // response the Before/After panel already reads, never a fabricated
  // second geometry.
  useEffect(() => {
    if (!compareMode) return;
    const container = compareContainerRef.current;
    if (!container) return;
    const engine = new ViewportEngine();
    compareEngineRef.current = engine;
    engine.mount(container);

    const meshPayload = recommendedResult?.display_mesh;
    const adapted = meshPayload ? adaptDisplayMesh(meshPayload) : null;
    if (adapted) {
      engine.setMesh(adapted);
      const rgb = meshPayload?.core_cavity_rgb as [number, number, number][] | undefined;
      if (rgb && rgb.length === adapted.faceIds.length) {
        const colors = new Map<number, THREE.Color>();
        adapted.faceIds.forEach((faceId, i) => {
          if (colors.has(faceId)) return;
          const [r, g, b] = rgb[i];
          colors.set(faceId, new THREE.Color(r, g, b));
        });
        engine.setOverlayColors(colors);
      }
    } else {
      engine.setMesh(buildSampleMesh());
    }

    return () => {
      engine.dispose();
      compareEngineRef.current = null;
    };
  }, [compareMode, recommendedResult]);

  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    // F12 §6/§11: real click-to-inspect face picking -- a click that
    // doesn't land on the mesh (empty space, or no part loaded) leaves the
    // current selection untouched rather than clearing it or substituting
    // an arbitrary face. Multiple faces can accumulate: each click TOGGLES
    // that one face, same as before.
    //
    // Selection only fires on Shift+click -- a plain click is how OrbitControls
    // users click-drag to orbit, and without this gate an incidental
    // click-without-drag (e.g. after releasing a small rotate/pan) silently
    // toggled a random face. Shift+click is unambiguous, deliberate intent.
    if (!event.shiftKey) return;
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const ndcX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    const ndcY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const faceId = getViewportEngine().pickFaceId(ndcX, ndcY);
    if (faceId !== null) toggleFaceSelection(faceId);
  };

  const handlePointerUp = () => {
    setCamera(getViewportEngine().readCameraState());
  };

  return (
    <div className={styles.viewportRoot} data-testid="viewport-outer">
      <div
        ref={containerRef}
        className={styles.viewport}
        data-testid="viewport-root"
        onClick={handleClick}
        onPointerUp={handlePointerUp}
        role="img"
        aria-label="3D part viewport -- Shift+click a face to select it"
        style={compareMode ? { flex: '1 1 50%', maxWidth: '50%' } : undefined}
      >
        {compareMode && <span className={styles.paneLabel}>AFTER — current direction</span>}
        <span className={styles.selectionHint}>Shift+click a face to select</span>
        <button
          type="button"
          className={styles.clearSelectionButton}
          disabled={selectedFaceIds.length === 0}
          onClick={(e) => {
            // Purely a selection-state control -- must never also toggle a
            // face selection via the container's own onClick.
            e.stopPropagation();
            clearSelection();
          }}
          onPointerUp={(e) => e.stopPropagation()}
          title="Deselect all currently selected faces"
        >
          Clear Selection{selectedFaceIds.length > 0 ? ` (${selectedFaceIds.length})` : ''}
        </button>
        <button
          type="button"
          className={styles.boundaryToggle}
          data-active={showFaceBoundaries}
          onClick={(e) => {
            // Purely a view control -- must never also toggle a face
            // selection via the container's own onClick (F10 §1/§9: view
            // state and analysis/selection state stay separate).
            e.stopPropagation();
            setShowFaceBoundaries(!showFaceBoundaries);
          }}
          onPointerUp={(e) => e.stopPropagation()}
          aria-pressed={showFaceBoundaries}
          title="Toggle CAD face-boundary overlay (inspection only -- never changes analysis)"
        >
          {showFaceBoundaries ? '☑' : '☐'} Show Face Boundaries
        </button>
      </div>
      {compareMode && (
        <>
          <div className={styles.compareDivider} />
          <div ref={compareContainerRef} className={styles.compareViewport} data-testid="compare-viewport">
            <span className={styles.paneLabel}>
              BEFORE — automatic direction{recommendedResult ? '' : ' (no recommended run yet)'}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
