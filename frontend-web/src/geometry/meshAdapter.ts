/**
 * Geometry adapter -- the ONLY place that knows how a backend
 * `DisplayMeshPayload` (backend/geometry/visualize_raw.py) turns into
 * three.js-ready typed arrays. The viewport engine and every future
 * overlay renderer consume `AdaptedMesh`, never the raw payload directly,
 * so wiring F2's real `/parts/{filename}/summary` call in later is a matter
 * of calling `adaptDisplayMesh` on its response -- no viewport/UI code
 * changes (F1 spec, "isolate the geometry adapter").
 */

import type { DisplayMeshPayload } from '../api/types';

export interface AdaptedMesh {
  /** Flat Float32Array-ready vertex positions, 3 per vertex. */
  positions: Float32Array;
  /** Flat Uint32Array-ready triangle vertex indices, 3 per triangle. */
  indices: Uint32Array;
  /** Source STEP face_id per triangle, parallel to `indices.length / 3`. */
  faceIds: Int32Array;
  triangleCount: number;
  pointCount: number;
}

/**
 * Convert a backend display-mesh payload into flat typed arrays a
 * three.js `BufferGeometry` can consume directly. Requires the payload to
 * have been fetched with `include_mesh_geometry=true` (the `points`/`faces`
 * fields are otherwise omitted server-side to keep the summary payload
 * small) -- returns `null` rather than throwing if geometry is absent, so a
 * caller can fall back to a summary-only display.
 */
export function adaptDisplayMesh(payload: DisplayMeshPayload): AdaptedMesh | null {
  if (!payload.points || !payload.faces) {
    return null;
  }

  const positions = new Float32Array(payload.points.length * 3);
  payload.points.forEach(([x, y, z], i) => {
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;
  });

  const indices = new Uint32Array(payload.faces.length * 3);
  payload.faces.forEach(([a, b, c], i) => {
    indices[i * 3] = a;
    indices[i * 3 + 1] = b;
    indices[i * 3 + 2] = c;
  });

  const faceIds = Int32Array.from(payload.face_ids);

  return {
    positions,
    indices,
    faceIds,
    triangleCount: payload.triangle_count,
    pointCount: payload.point_count,
  };
}

/**
 * A small, deterministic placeholder solid (a rounded-look faceted block)
 * used only until F2 wires real `/parts/{filename}/summary` geometry in.
 * Exists so F1 can prove the viewport renders and persists real
 * `AdaptedMesh` data through the exact same adapter shape a real part will
 * use -- never a special-cased "demo mode" in the viewport itself.
 */
export function buildSampleMesh(): AdaptedMesh {
  // A simple box, 6 faces / 12 triangles, with each face carrying a
  // distinct synthetic face_id (0-5) so per-face selection has something
  // real to select against.
  const hx = 40;
  const hy = 26;
  const hz = 18;

  const facePositions: [number, number, number][][] = [
    // +X, -X, +Y, -Y, +Z, -Z (each 4 corners, wound for outward normals)
    [[hx, -hy, -hz], [hx, hy, -hz], [hx, hy, hz], [hx, -hy, hz]],
    [[-hx, -hy, hz], [-hx, hy, hz], [-hx, hy, -hz], [-hx, -hy, -hz]],
    [[-hx, hy, -hz], [hx, hy, -hz], [hx, hy, hz], [-hx, hy, hz]],
    [[-hx, -hy, hz], [hx, -hy, hz], [hx, -hy, -hz], [-hx, -hy, -hz]],
    [[-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz]],
    [[-hx, hy, -hz], [hx, hy, -hz], [hx, -hy, -hz], [-hx, -hy, -hz]],
  ];

  const points: number[][] = [];
  const faces: [number, number, number][] = [];
  const faceIds: number[] = [];

  facePositions.forEach((corners, faceId) => {
    const base = points.length;
    points.push(...corners);
    faces.push([base, base + 1, base + 2], [base, base + 2, base + 3]);
    faceIds.push(faceId, faceId);
  });

  return adaptDisplayMesh({
    point_count: points.length,
    triangle_count: faces.length,
    face_count: facePositions.length,
    face_ids: faceIds,
    face_centers: {},
    points: points as [number, number, number][],
    faces,
  }) as AdaptedMesh;
}
