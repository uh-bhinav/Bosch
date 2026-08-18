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
import { useAnalysisStore } from '../store/analysisStore';
import { getViewportEngine } from './engineSingleton';
import { buildSampleMesh } from '../geometry/meshAdapter';
import styles from './Viewport.module.css';

export function Viewport() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectedFaceIds = useAnalysisStore((s) => s.selectedFaceIds);
  const toggleFaceSelection = useAnalysisStore((s) => s.toggleFaceSelection);
  const setCamera = useAnalysisStore((s) => s.setCamera);
  const showFaceBoundaries = useAnalysisStore((s) => s.showFaceBoundaries);
  const setShowFaceBoundaries = useAnalysisStore((s) => s.setShowFaceBoundaries);

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

  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    // F12 §6/§11: real click-to-inspect face picking -- a click that
    // doesn't land on the mesh (empty space, or no part loaded) leaves the
    // current selection untouched rather than clearing it or substituting
    // an arbitrary face. Multiple faces can accumulate: each click TOGGLES
    // that one face, same as before.
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
    <div
      ref={containerRef}
      className={styles.viewport}
      data-testid="viewport-root"
      onClick={handleClick}
      onPointerUp={handlePointerUp}
      role="img"
      aria-label="3D part viewport"
    >
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
  );
}
