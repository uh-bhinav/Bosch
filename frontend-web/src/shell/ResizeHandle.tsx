/**
 * F12 §12: a draggable splitter between the viewport and the inspector --
 * the preferred fix for "the inspector must never require horizontal
 * scrolling" over a fixed width, since different judges/screens need
 * different amounts of room. Drags update `store.inspectorWidth` (clamped
 * [360, 720] in `setInspectorWidth`), which `ContextInspector.tsx` applies
 * as an inline style overriding the CSS default. Pure UI/layout state --
 * never touched by `resetAnalysisState`, exactly like `camera`.
 */

import { useCallback, useEffect, useRef, type PointerEvent } from 'react';
import { useAnalysisStore } from '../store/analysisStore';
import styles from './ResizeHandle.module.css';

export function ResizeHandle() {
  const setInspectorWidth = useAnalysisStore((s) => s.setInspectorWidth);
  const draggingRef = useRef(false);

  const handlePointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
  }, []);

  const handlePointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      // The inspector sits to the RIGHT of this handle -- moving the
      // pointer left grows it, right shrinks it, so width is measured from
      // the viewport's right edge (clientX) back to the window's right edge.
      const widthFromCursor = window.innerWidth - event.clientX;
      setInspectorWidth(widthFromCursor);
    },
    [setInspectorWidth],
  );

  const handlePointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  // Double-click resets to the default width -- a quick recovery if a judge
  // drags it to something unusable.
  const handleDoubleClick = useCallback(() => setInspectorWidth(420), [setInspectorWidth]);

  useEffect(() => () => {
    draggingRef.current = false;
  }, []);

  return (
    <div
      className={styles.handle}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onDoubleClick={handleDoubleClick}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize inspector (double-click to reset)"
      title="Drag to resize the inspector -- double-click to reset"
      data-testid="inspector-resize-handle"
    >
      <span className={styles.grip} />
    </div>
  );
}
