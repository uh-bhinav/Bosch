/**
 * F7: the ONE place that decides what the persistent viewport (F1) shows for
 * the currently active tool -- mesh overlay coloring, the parting-line
 * curve, and both direction arrows. Runs as a side effect only (never
 * touches whether/how `Viewport` itself mounts), so it does not compromise
 * F1's persistence guarantee: switching tools recolors the already-loaded
 * mesh and adds/removes line/arrow objects, it never reloads geometry or
 * remounts the canvas.
 *
 * Mesh geometry itself is loaded exactly once per analysis run (`applyCore
 * CavityOverlay` in `analysis/analysisShared.ts`, the only place that calls
 * `ViewportEngine.setMesh`). This hook only ever calls `setOverlayColors`
 * with a `faceId -> color` map built from whichever tool's own response
 * carries the right per-face color array (`geometry/overlayColors.ts`) --
 * safe against the ALREADY-loaded mesh because `face_id` is a stable
 * STEP-level identifier, not tied to any one meshing call (see CLAUDE.md).
 */

import { useEffect } from 'react';
import { buildFaceColorMap } from '../geometry/overlayColors';
import { useAnalysisStore } from '../store/analysisStore';
import type { Vec3 } from '../domain/types';
import { getViewportEngine } from './engineSingleton';

function vecEquals(a: Vec3 | null, b: Vec3 | null): boolean {
  if (!a || !b) return a === b;
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}

export function useOverlaySync(): void {
  const activeTool = useAnalysisStore((s) => s.activeTool);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const manualPullDirection = useAnalysisStore((s) => s.manualPullDirection);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const draftResult = useAnalysisStore((s) => s.draftResult);
  const undercutsResult = useAnalysisStore((s) => s.undercutsResult);
  const partingLineResult = useAnalysisStore((s) => s.partingLineResult);

  useEffect(() => {
    const engine = getViewportEngine();

    // The resolved direction is visible on every tool, once known -- "look
    // at the viewport and immediately understand this is the mold pull
    // direction" (F7 §4) should not depend on which tool happens to be open.
    engine.setDirectionArrow(pullDirection);

    // The manual live-edit preview only makes sense while the Pull
    // Direction tool is open, and only when it differs from the resolved
    // direction (otherwise it would sit exactly on top of the resolved
    // arrow, drawing two indistinguishable arrows).
    if (activeTool === 'pull-direction' && !vecEquals(manualPullDirection, pullDirection)) {
      engine.setManualDirectionPreview(manualPullDirection);
    } else {
      engine.setManualDirectionPreview(null);
    }

    // Parting-line curve: only on its own tool.
    if (activeTool === 'parting-line' && partingLineResult) {
      const paths = partingLineResult.parting_line_paths;
      engine.setPartingLines(
        [
          { points: paths.raw.points, colorHex: paths.raw.hex, opacity: paths.raw.opacity ?? 0.4 },
          { points: paths.refined.points, colorHex: paths.refined.hex, opacity: 1 },
        ].filter((p) => p.points.length > 1),
      );
    } else {
      engine.setPartingLines(null);
    }

    // Mesh face-color overlay: one tool-specific classification color set,
    // or a clear (neutral) mesh for tools that have none of their own.
    if (activeTool === 'draft' && draftResult?.display_mesh) {
      engine.setOverlayColors(
        buildFaceColorMap(draftResult.display_mesh.face_ids, draftResult.display_mesh.draft_rgb),
      );
    } else if (activeTool === 'undercuts' && undercutsResult?.display_mesh) {
      engine.setOverlayColors(
        buildFaceColorMap(undercutsResult.display_mesh.face_ids, undercutsResult.display_mesh.undercut_rgb),
      );
    } else if ((activeTool === 'core-cavity' || activeTool === 'side-cores') && analysisResult?.display_mesh) {
      engine.setOverlayColors(
        buildFaceColorMap(analysisResult.display_mesh.face_ids, analysisResult.display_mesh.core_cavity_rgb),
      );
    } else {
      engine.setOverlayColors(null);
    }

    useAnalysisStore.getState().setOverlay(
      activeTool === 'draft' || activeTool === 'undercuts' || activeTool === 'core-cavity' || activeTool === 'side-cores'
        ? (activeTool as 'draft' | 'undercuts' | 'core-cavity' | 'side-cores')
        : null,
    );
  }, [activeTool, pullDirection, manualPullDirection, analysisResult, draftResult, undercutsResult, partingLineResult]);
}
