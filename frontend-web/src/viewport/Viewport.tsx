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

import { useEffect, useRef } from 'react';
import { useAnalysisStore } from '../store/analysisStore';
import { getViewportEngine } from './engineSingleton';
import { buildSampleMesh } from '../geometry/meshAdapter';
import styles from './Viewport.module.css';

export function Viewport() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectedFaceIds = useAnalysisStore((s) => s.selectedFaceIds);
  const toggleFaceSelection = useAnalysisStore((s) => s.toggleFaceSelection);
  const setCamera = useAnalysisStore((s) => s.setCamera);

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

  const handleClick = () => {
    // F1 placeholder interaction: proves selection round-trips through the
    // shared store and repaints the viewport, without real face-picking
    // (raycasting against backend face_ids) yet.
    toggleFaceSelection(0);
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
    />
  );
}
