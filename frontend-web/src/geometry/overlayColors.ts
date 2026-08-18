/**
 * Builds a `faceId -> THREE.Color` map from a backend display-mesh payload's
 * own per-triangle `face_ids` array zipped against a parallel per-triangle
 * RGB array (`draft_rgb` / `core_cavity_rgb` / `undercut_rgb`, all 0-1 float
 * triplets -- backend/api/main.py's `_rgb_byte_triplet` and the draft/
 * core-cavity inline `class_to_color` dicts both emit this same 0-1 shape).
 *
 * Deliberately independent of `meshAdapter.ts`/`adaptDisplayMesh` -- this
 * only needs `face_ids` + the color array (both present even with
 * `include_mesh_geometry=false`, keeping draft/undercut overlay fetches
 * lightweight), never the `points`/`faces` geometry itself. The resulting
 * map is applied via `ViewportEngine.setOverlayColors` against WHATEVER mesh
 * geometry is already loaded (from the one call that requested full
 * geometry) -- safe because `face_id` is a stable STEP-level identifier
 * (CLAUDE.md: "stable across reloads of the same .stp file"), not tied to a
 * particular mesh-building call's triangle order.
 */

import * as THREE from 'three';

/**
 * F12 §10 / F15: the undercut-classification style keys that carry genuine
 * undercut EVIDENCE (backend/api/main.py's `UNDERCUT_FACE_VISUAL_STYLES`) --
 * as opposed to "parting"/"accessible"/"zero_draft_not_applicable"/
 * "ray_verified_clear"/"neutral", which are real backend outcomes but never
 * undercut evidence itself. `useOverlaySync.ts`'s Undercuts-tab/Core-Cavity
 * overlays paint every one of these a single unambiguous red and leave
 * everything else uncolored (F12 §9); `UndercutsPanel.tsx`'s legend swatches
 * use the SAME set so the legend never implies a viewport color (e.g. the
 * backend's own pale-beige `proxy_undercut` RGB) that isn't actually what's
 * on screen in THIS tab -- one shared source of truth for both.
 */
export const REAL_UNDERCUT_CATEGORIES = new Set([
  'critical_boolean_confirmed', 'high_boolean_confirmed', 'medium_boolean_confirmed',
  'moderate_boolean_confirmed', 'low_boolean_confirmed', 'minor_boolean_confirmed',
  'proxy_undercut', 'manual_review_undercut',
]);

export function buildFaceColorMap(
  faceIds: number[] | undefined,
  rgb: unknown,
): Map<number, THREE.Color> | null {
  if (!faceIds || !Array.isArray(rgb) || rgb.length !== faceIds.length) return null;
  const colors = new Map<number, THREE.Color>();
  faceIds.forEach((faceId, i) => {
    if (colors.has(faceId)) return;
    const triplet = rgb[i] as [number, number, number] | undefined;
    if (!triplet) return;
    const [r, g, b] = triplet;
    colors.set(faceId, new THREE.Color(r, g, b));
  });
  return colors;
}
