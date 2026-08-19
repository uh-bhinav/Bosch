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

/** Full-intensity red -- genuine undercut evidence (Boolean-confirmed at any severity, proxy, or Boolean-inconclusive-with-risk-evidence). */
export const UNDERCUT_STRONG_HEX = '#ff2020';
/** Faint/desaturated red -- the tangent/zero-draft BOUNDARY member of a confirmed feature (see backend's `tangent_boundary_undercut`): real evidence, but a parting-line ambiguity, not independently confirmed trapped material, so it must never read as loudly as the feature's genuinely backward-facing member. */
export const UNDERCUT_BOUNDARY_HEX = '#612727'; //'#c96060'; 
/** Distinct teal -- `ray_verified_clear`: a real, positive geometric-clearance finding (adaptive ray casting, D-061), never Boolean proof, but genuine "checked and found not blocked" evidence worth seeing on the model, not just a legend count. */
export const RAY_VERIFIED_CLEAR_HEX = '#5fb894';

/**
 * F12 §10 / F15 / F16 (2026-08-19c): maps an undercut-classification style
 * key (backend/api/main.py's `UNDERCUT_FACE_VISUAL_STYLES`) to the ONE color
 * it actually paints in the Undercuts tab / Core-Cavity "Undercuts" layer --
 * `null` for every category that stays uncolored there ("parting"/
 * "accessible"/"zero_draft_not_applicable"/"neutral"). `useOverlaySync.ts`'s
 * overlay builder and `UndercutsPanel.tsx`'s legend swatches both call this
 * SAME function, so the legend can never imply a viewport color that isn't
 * actually on screen in this tab.
 */
export function undercutCategoryOverlayColorHex(category: string): string | null {
  switch (category) {
    case 'critical_boolean_confirmed':
    case 'high_boolean_confirmed':
    case 'medium_boolean_confirmed':
    case 'moderate_boolean_confirmed':
    case 'low_boolean_confirmed':
    case 'minor_boolean_confirmed':
    case 'proxy_undercut':
    case 'manual_review_undercut':
      return UNDERCUT_STRONG_HEX;
    case 'tangent_boundary_undercut':
      return UNDERCUT_BOUNDARY_HEX;
    case 'ray_verified_clear':
      return RAY_VERIFIED_CLEAR_HEX;
    default:
      return null;
  }
}

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
