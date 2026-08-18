/**
 * F7/F12: the ONE place that decides what the persistent viewport (F1) shows
 * for the currently active tool -- mesh overlay coloring, the parting-line
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
 * carries the right per-face color array -- safe against the ALREADY-loaded
 * mesh because `face_id` is a stable STEP-level identifier, not tied to any
 * one meshing call (see CLAUDE.md).
 *
 * F12 §15: every branch below is an exhaustive if/else keyed on `activeTool`
 * -- there is no "leave whatever was there" fallthrough, so switching tools
 * always fully replaces the previous tool's overlay/curve/arrow state
 * rather than accumulating it.
 */

import { useEffect } from 'react';
import * as THREE from 'three';
import { buildFaceColorMap } from '../geometry/overlayColors';
import { useAnalysisStore, type CoreCavityLayers } from '../store/analysisStore';
import type { Vec3 } from '../domain/types';
import { getViewportEngine } from './engineSingleton';

function vecEquals(a: Vec3 | null, b: Vec3 | null): boolean {
  if (!a || !b) return a === b;
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}

/** Backend's "not part of this group" placeholder for pv2_core_pin_rgb / pv2_delegation_rgb (backend/api/main.py). */
function isNeutralPlaceholder(triplet: unknown): boolean {
  if (!Array.isArray(triplet) || triplet.length !== 3) return true;
  const [r, g, b] = triplet as number[];
  return Math.abs(r - 0.55) < 0.02 && Math.abs(g - 0.55) < 0.02 && Math.abs(b - 0.55) < 0.02;
}

/** Only the faces the backend actually colored (excludes the neutral-grey "not in this group" placeholder) -- so merging this layer over another never blanks out unrelated faces. */
function buildFilteredColorMap(faceIds: number[] | undefined, rgb: unknown, color?: THREE.Color): Map<number, THREE.Color> | null {
  if (!faceIds || !Array.isArray(rgb) || rgb.length !== faceIds.length) return null;
  const map = new Map<number, THREE.Color>();
  faceIds.forEach((faceId, i) => {
    if (map.has(faceId)) return;
    const triplet = rgb[i];
    if (isNeutralPlaceholder(triplet)) return;
    if (color) {
      map.set(faceId, color);
      return;
    }
    const [r, g, b] = triplet as [number, number, number];
    map.set(faceId, new THREE.Color(r, g, b));
  });
  return map.size > 0 ? map : null;
}

/** F12 §10: undercuts are a single, unambiguous RED in the combined Core/Cavity view (the dedicated Undercuts tab keeps the richer 10-category legend) -- only genuine evidence categories count, not "parting"/"accessible"/"neutral"/"zero-draft, not testable". */
const REAL_UNDERCUT_CATEGORIES = new Set([
  'critical_boolean_confirmed', 'high_boolean_confirmed', 'medium_boolean_confirmed',
  'moderate_boolean_confirmed', 'low_boolean_confirmed', 'minor_boolean_confirmed',
  'proxy_undercut', 'manual_review_undercut',
]);
const UNDERCUT_RED = new THREE.Color('#ff2020');

function buildUndercutRedOverlay(faceIds: number[] | undefined, classifications: unknown): Map<number, THREE.Color> | null {
  if (!faceIds || !Array.isArray(classifications) || classifications.length !== faceIds.length) return null;
  const map = new Map<number, THREE.Color>();
  faceIds.forEach((faceId, i) => {
    if (map.has(faceId)) return;
    if (REAL_UNDERCUT_CATEGORIES.has(classifications[i] as string)) map.set(faceId, UNDERCUT_RED);
  });
  return map.size > 0 ? map : null;
}

const CORE_PIN_PURPLE = new THREE.Color('#c026d3');
const NEUTRAL_BASE = new THREE.Color('#7c8794');
const CORE_COLOR = new THREE.Color('#3264c8'); // matches backend's core_cavity_rgb core byte-triplet (50,100,200)
const CAVITY_COLOR = new THREE.Color('#32c864'); // matches backend's cavity byte-triplet (50,200,100)

/**
 * Core/cavity base classification, respecting the core/cavity/parting-zone
 * visibility toggles. `core`/`cavity` OFF falls back to neutral (so shape
 * stays legible, just uncolored). `partingZone` OFF is different (F13 §6):
 * those faces do NOT go neutral -- they fall back to their REAL
 * `topological_side` (core or cavity), read from the authoritative region
 * classification (`partingLineResult.regions.faces`, already fetched for
 * the Parting Line tool) matched by face_id, never left ambiguous and never
 * guessed from the parting classification alone.
 */
function buildCoreCavityBaseMap(
  faceIds: number[] | undefined,
  classifications: unknown,
  rgb: unknown,
  layers: CoreCavityLayers,
  topologicalSideByFaceId: Map<number, string> | null,
): Map<number, THREE.Color> | null {
  if (!faceIds || !Array.isArray(classifications) || !Array.isArray(rgb) || rgb.length !== faceIds.length) return null;
  const map = new Map<number, THREE.Color>();
  faceIds.forEach((faceId, i) => {
    if (map.has(faceId)) return;
    const cls = classifications[i];
    if ((cls === 'core' && !layers.core) || (cls === 'cavity' && !layers.cavity)) {
      map.set(faceId, NEUTRAL_BASE);
      return;
    }
    if (cls === 'parting' && !layers.partingZone) {
      const side = topologicalSideByFaceId?.get(faceId);
      if (side === 'core') {
        map.set(faceId, CORE_COLOR);
      } else if (side === 'cavity') {
        map.set(faceId, CAVITY_COLOR);
      } else {
        map.set(faceId, NEUTRAL_BASE); // genuinely 'split'/'unknown' -- no single real side to fall back to
      }
      return;
    }
    const triplet = rgb[i] as [number, number, number] | undefined;
    if (triplet) map.set(faceId, new THREE.Color(triplet[0], triplet[1], triplet[2]));
  });
  return map;
}

function mergeLayers(...layers: (Map<number, THREE.Color> | null)[]): Map<number, THREE.Color> | null {
  let result: Map<number, THREE.Color> | null = null;
  for (const layer of layers) {
    if (!layer) continue;
    if (!result) result = new Map();
    for (const [faceId, color] of layer) result.set(faceId, color);
  }
  return result;
}

export function useOverlaySync(): void {
  const activeTool = useAnalysisStore((s) => s.activeTool);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const manualPullDirection = useAnalysisStore((s) => s.manualPullDirection);
  const analysisResult = useAnalysisStore((s) => s.analysisResult);
  const draftResult = useAnalysisStore((s) => s.draftResult);
  const draftInspectDirection = useAnalysisStore((s) => s.draftInspectDirection);
  const draftInspectResult = useAnalysisStore((s) => s.draftInspectResult);
  const undercutsResult = useAnalysisStore((s) => s.undercutsResult);
  const partingLineResult = useAnalysisStore((s) => s.partingLineResult);
  const coreCavityLayers = useAnalysisStore((s) => s.coreCavityLayers);

  useEffect(() => {
    const engine = getViewportEngine();

    // The resolved direction is visible on every tool once known, EXCEPT
    // Core/Cavity's own "Pull Direction" layer toggle can hide it there
    // specifically (F12 §5) -- everywhere else it's unconditional (F7 §4).
    const showResolvedArrow = activeTool === 'core-cavity' ? coreCavityLayers.pullDirection : true;
    engine.setDirectionArrow(showResolvedArrow ? pullDirection : null);

    // The manual live-edit preview only makes sense while the Pull
    // Direction tool is open, and only when it differs from the resolved
    // direction (otherwise it would sit exactly on top of the resolved
    // arrow, drawing two indistinguishable arrows).
    if (activeTool === 'pull-direction' && !vecEquals(manualPullDirection, pullDirection)) {
      engine.setManualDirectionPreview(manualPullDirection);
    } else {
      engine.setManualDirectionPreview(null);
    }

    // Parting-line curve: its own tool always, plus Core/Cavity's "Parting
    // Line" layer toggle (F12 §5) -- the v2 engine's single selected-
    // candidate curve (`parting_line_path`), absent whenever v2 found no
    // feasible candidate for this direction, never fabricated.
    const partingLinePath = partingLineResult?.parting_line_path;
    const showPartingLine =
      activeTool === 'parting-line' || (activeTool === 'core-cavity' && coreCavityLayers.partingLine);
    if (showPartingLine && partingLinePath && partingLinePath.points.length > 1) {
      engine.setPartingLines([{ points: partingLinePath.points, colorHex: partingLinePath.hex, opacity: 1 }]);
    } else {
      engine.setPartingLines(null);
    }

    // F13 §8: side-action movement arrows -- one per backend-VALIDATED
    // delegation group (`selected.feasibility.validated_delegations`, D-044),
    // drawn only where side-action faces are already shown: Parting Line's
    // own tab, Side Cores, or Core/Cavity's "Side Action" layer toggle. Real
    // `movement_direction` vectors only -- `ViewportEngine.setSideActionArrows`
    // itself skips any group with no valid (non-zero) vector or no matching
    // faces in the loaded mesh, so this never fabricates an arrow.
    const validatedDelegations = partingLineResult?.selected?.feasibility?.validated_delegations ?? [];
    const showSideActionArrows =
      activeTool === 'parting-line' ||
      activeTool === 'side-cores' ||
      (activeTool === 'core-cavity' && coreCavityLayers.sideAction);
    engine.setSideActionArrows(
      showSideActionArrows && validatedDelegations.length > 0
        ? validatedDelegations.map((d) => ({ faceIds: d.face_ids, direction: d.movement_direction }))
        : null,
    );

    // Mesh face-color overlay: one tool-specific classification color set,
    // or a clear (neutral) mesh for tools that have none of their own.
    if (activeTool === 'draft') {
      // F13 §4: while the engineer is inspecting a non-resolved direction,
      // the viewport shows THAT direction's draft classification instead of
      // the resolved-direction snapshot -- a pure visual override that never
      // touches `draftResult`/`pullDirection` themselves.
      const inspecting = draftInspectDirection !== null;
      const active = inspecting ? draftInspectResult : draftResult;
      if (active?.display_mesh) {
        engine.setOverlayColors(buildFaceColorMap(active.display_mesh.face_ids, active.display_mesh.draft_rgb));
      } else {
        engine.setOverlayColors(null);
      }
    } else if (activeTool === 'undercuts' && undercutsResult?.display_mesh) {
      // F12 §9/§10: a single, unambiguous RED for every face with genuine
      // undercut evidence, ALL shown simultaneously (never one-at-a-time) --
      // the rich 10-category backend breakdown (severity/evidence-source)
      // stays available as counts/text in the Undercuts panel and its own
      // legend, this is just the headline viewport color. Clicking a face
      // still only SELECTS it (accent highlight, ViewportEngine's existing
      // selection-wins-over-overlay precedence) -- it never removes any
      // other undercut face from view.
      engine.setOverlayColors(
        buildUndercutRedOverlay(
          undercutsResult.display_mesh.face_ids,
          undercutsResult.display_mesh.undercut_classification,
        ),
      );
    } else if (activeTool === 'parting-line' && partingLineResult?.display_mesh) {
      // F10 §6: prefer the authorization-driven overlays -- validated
      // delegation groups (side-action faces, each a distinct color) take
      // priority over the core-pin interface highlight, since a candidate
      // with validated delegations is the richer "why this now passes"
      // picture; core-pin alone still shows which faces were excluded as
      // coaxial features. Falls back to the SAME response's undercut
      // overlay (still real backend data) so the tab is never a flat grey
      // mesh with nothing indicating why a direction was referred.
      const mesh = partingLineResult.display_mesh;
      const overlay =
        buildFaceColorMap(mesh.face_ids, mesh.pv2_delegation_rgb) ??
        buildFaceColorMap(mesh.face_ids, mesh.pv2_core_pin_rgb) ??
        buildFaceColorMap(mesh.face_ids, mesh.undercut_rgb);
      engine.setOverlayColors(overlay);
    } else if (activeTool === 'core-cavity' && analysisResult?.display_mesh) {
      // F12 §5/§6/§7/§10: a real combined view -- base cavity/core/parting
      // classification (each half independently toggleable), with the
      // undercut/core-pin/side-action layers from the SAME resolved
      // direction's OTHER already-fetched responses drawn on top, each its
      // own independently toggleable layer, each only touching the faces it
      // actually applies to (buildFilteredColorMap/buildUndercutRedOverlay
      // never overwrite an unrelated face with a neutral placeholder).
      const mesh = analysisResult.display_mesh;
      const topologicalSideByFaceId = coreCavityLayers.partingZone
        ? null
        : new Map((partingLineResult?.regions?.faces ?? []).map((f) => [f.face_id, f.topological_side]));
      const baseLayer = buildCoreCavityBaseMap(
        mesh.face_ids,
        mesh.core_cavity_classification,
        mesh.core_cavity_rgb,
        coreCavityLayers,
        topologicalSideByFaceId,
      );
      const pv2Mesh = partingLineResult?.display_mesh;
      const sideActionLayer =
        coreCavityLayers.sideAction && pv2Mesh ? buildFilteredColorMap(pv2Mesh.face_ids, pv2Mesh.pv2_delegation_rgb) : null;
      const corePinLayer =
        coreCavityLayers.corePin && pv2Mesh
          ? buildFilteredColorMap(pv2Mesh.face_ids, pv2Mesh.pv2_core_pin_rgb, CORE_PIN_PURPLE)
          : null;
      const undercutLayer =
        coreCavityLayers.undercuts && undercutsResult?.display_mesh
          ? buildUndercutRedOverlay(undercutsResult.display_mesh.face_ids, undercutsResult.display_mesh.undercut_classification)
          : null;
      engine.setOverlayColors(mergeLayers(baseLayer, sideActionLayer, corePinLayer, undercutLayer));
    } else if (activeTool === 'side-cores' && analysisResult?.display_mesh) {
      engine.setOverlayColors(
        buildFaceColorMap(analysisResult.display_mesh.face_ids, analysisResult.display_mesh.core_cavity_rgb),
      );
    } else {
      engine.setOverlayColors(null);
    }

    useAnalysisStore.getState().setOverlay(
      activeTool === 'draft' ||
        activeTool === 'undercuts' ||
        activeTool === 'parting-line' ||
        activeTool === 'core-cavity' ||
        activeTool === 'side-cores'
        ? (activeTool as 'draft' | 'undercuts' | 'parting-line' | 'core-cavity' | 'side-cores')
        : null,
    );
  }, [
    activeTool,
    pullDirection,
    manualPullDirection,
    analysisResult,
    draftResult,
    draftInspectDirection,
    draftInspectResult,
    undercutsResult,
    partingLineResult,
    coreCavityLayers,
  ]);
}
