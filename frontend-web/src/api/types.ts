/**
 * Typed shapes for backend responses.
 *
 * F1 called only `/health` and `/parts`. F2 adds `POST /parts/upload` and
 * `GET /parts/{filename}/summary` -- every field below was read directly
 * from `backend/api/main.py`/`backend/models/geometry_models.py`
 * (`PartGeometry.to_dict`) and `backend/geometry/visualize_raw.py`
 * (`RawMeshData.to_payload`), not assumed.
 */

export interface HealthResponse {
  status: string;
  parts_dir: string;
  parts_dir_exists: boolean;
}

export interface PartsListResponse {
  parts_dir: string;
  files: string[];
  warnings?: string[];
}

/**
 * `RawMeshData.to_payload()` (backend/geometry/visualize_raw.py:83).
 * `points`/`faces` are only present when the request asked for
 * `include_mesh_geometry=true`; endpoints additionally attach overlay arrays
 * as siblings on this same object (e.g. `draft_rgb`, `core_cavity_rgb`,
 * `core_cavity_classification`) -- modeled as an open index signature so the
 * adapter can read any overlay without this type needing to enumerate every
 * endpoint's overlay names.
 */
export interface DisplayMeshPayload {
  point_count: number;
  triangle_count: number;
  face_count: number;
  /** Per-triangle source STEP face_id, parallel to `faces`. */
  face_ids: number[];
  face_centers: Record<string, [number, number, number]>;
  /** Present only when `include_mesh_geometry=true` was requested. */
  points?: [number, number, number][];
  /** Triangle vertex indices into `points`. */
  faces?: [number, number, number][];
  /** Per-overlay color/classification arrays, endpoint-specific. */
  [overlayKey: string]: unknown;
}

/**
 * `WinningDirectionMoldResult.to_dict()` (backend/geometry/mold_orchestration.py).
 * `status` is one of "generated" | "blocked_optimal_not_found" |
 * "blocked_by_parting_line" | "blocked_by_core_cavity_split" | "no_feature"
 * | "invalid_direction" (the last two never occur on the automatic Guided
 * path used by `runFullAnalysis` -- "no_feature" only fires when side cores
 * are requested, which F3 does not; "invalid_direction" only fires for a
 * manually-supplied direction, F4's concern -- but the field is typed and
 * handled defensively regardless). `parting_line_v2_outcome` is the ONE
 * field distinguishing "no valid split exists" ("no_feasible_candidate")
 * from "this direction needs an authorized secondary action"
 * ("referred_to_side_action") -- see `PartingLineV2Result.outcome`
 * (backend/geometry/parting_line_v2/engine.py).
 */
export interface OrchestrationResult {
  status: string;
  failure_reason: string | null;
  pull_direction: [number, number, number] | null;
  optimal_found: boolean | null;
  parting_line_v2_outcome: 'feasible' | 'referred_to_side_action' | 'no_feasible_candidate' | null;
  solid_split: Record<string, unknown> | null;
  delegated_face_ids: number[];
  excluded_feature_ids: number[];
  side_cores: Record<string, unknown> | null;
  side_core_combined: Record<string, unknown>;
}

/**
 * `GET /parts/{filename}/core-cavity`'s response body
 * (backend/api/main.py:part_core_cavity), as called by `runFullAnalysis`
 * with `use_optimal_direction=true&solid_split=true` -- the single
 * authoritative endpoint that runs direction search -> parting line ->
 * core/cavity solid split in one request (F0 §1.5: "one call to
 * /core-cavity with use_optimal_direction=false now returns the complete,
 * authoritative, real-undercut-aware orchestration result", equally true
 * of the automatic path). `core_cavity`/`part`/`solid_split` are left
 * loosely typed -- F3 only reads `display_mesh`'s overlay arrays and
 * `orchestration`'s status fields, not the full face-classification detail.
 */
export interface CoreCavityAnalysisResponse {
  part: Record<string, unknown>;
  core_cavity: Record<string, unknown>;
  pull_direction_source: string;
  parting_line_v2_outcome: OrchestrationResult['parting_line_v2_outcome'];
  orchestration?: OrchestrationResult;
  solid_split?: Record<string, unknown> | null;
  display_mesh?: DisplayMeshPayload;
  /**
   * F7: only present when the request set `generate_side_core=true`
   * (`getSideCoreDetail`, api/endpoints.ts) -- `SideCoreResult.to_dict()`
   * (backend/geometry/side_core.py). Absent, not `null`, when side-core
   * generation was never requested on this particular call -- callers must
   * not read "no side_core key" as "no side core needed," only as "this
   * call didn't ask."
   */
  side_core?: Record<string, unknown>;
  side_cores?: Record<string, unknown>;
  side_core_combined?: Record<string, unknown>;
}

/**
 * F4: the `core_pin_face_refs` / `delegations` JSON-array query-parameter
 * shapes (`_parse_core_pin_face_refs`/`_parse_delegations`,
 * backend/api/main.py -- plan D-043/D-044). These are REQUEST shapes the
 * frontend constructs and sends, not response types -- field names and
 * types mirror the parser's own required-key checks exactly (a malformed
 * shape is rejected server-side with a structured `invalid_input` error,
 * never silently coerced). `geometric_verification` is deliberately absent
 * -- the backend never accepts it as input; every delegation is
 * constructed through `DelegationEvidence`'s own default and always
 * reports `"unverified"` regardless of what a caller sends.
 */
export interface CorePinFaceRefInput {
  face_id: number;
  axis_direction: [number, number, number];
  reason: string;
}

export interface DelegationInput {
  face_ids: number[];
  movement_direction: [number, number, number];
  movement_type: string;
  source: string;
  note: string;
}

/**
 * F7: `GET /parts/{filename}/draft`'s response body (backend/api/main.py:
 * part_draft). `draft` is `DraftAnalysisResult.to_dict()`
 * (backend/geometry/draft_analyzer.py) -- left loosely typed beyond the
 * fields this phase actually reads (`face_counts`, `severity`,
 * `percentages`, `pull_direction`) since the rest (per-face results,
 * suggestions) are read straight out of the raw object where displayed,
 * matching this file's existing convention for less-traveled response
 * shapes (see `CoreCavityAnalysisResponse.core_cavity`/`solid_split`).
 */
export interface DraftAnalysisResponse {
  part: Record<string, unknown>;
  draft: {
    pull_direction: [number, number, number];
    pull_direction_label: string;
    analysis_pass: string;
    thresholds: { good_deg: number; marginal_deg: number };
    face_counts: { good: number; marginal: number; bad: number; skipped: number; total_analysed: number };
    face_ids: { good: number[]; marginal: number[]; bad: number[]; skipped: number[] };
    percentages: { good_pct: number; marginal_pct: number; bad_pct: number };
    severity: 'none' | 'minor' | 'moderate' | 'critical' | string;
    is_manufacturable: boolean;
    suggestions: Array<{
      face_ids: number[];
      classification: string;
      action_text: string;
      total_area_mm2: number;
      avg_angle_deg: number;
      suggested_delta_deg: number;
    }>;
    [key: string]: unknown;
  };
  display_mesh?: DisplayMeshPayload;
}

/**
 * F7: one entry of `UNDERCUT_FACE_VISUAL_STYLES` (backend/api/main.py) --
 * the SAME legend `display_mesh.undercut_visual_summary.legend` carries, so
 * the frontend renders the backend's own category set/labels/priority
 * rather than a hardcoded subset (the Streamlit reference UI hardcodes only
 * 6 of these 10 categories; this type exists specifically so nothing is
 * silently dropped).
 */
export interface UndercutVisualStyleEntry {
  label: string;
  rgb: [number, number, number];
  priority: number;
}

/**
 * F7: `GET /parts/{filename}/undercuts`'s response body (backend/api/
 * main.py:part_undercuts). `undercuts` is `UndercutResult.to_dict()`
 * (backend/geometry/undercut_detector.py) -- loosely typed for the same
 * reason as `DraftAnalysisResponse.draft` above.
 */
export interface UndercutsAnalysisResponse {
  part: Record<string, unknown>;
  undercuts: {
    has_undercuts: boolean;
    has_critical_undercut: boolean;
    face_counts: Record<string, number>;
    feature_count: number;
    major_undercut_features_count: number;
    percentages: { undercut_area_pct: number };
    features: Array<{
      feature_id: number;
      face_ids: number[];
      is_major_feature: boolean;
      severity: string;
      undercut_type: string;
      evidence_source: string;
      recommended_mold_action: string;
      side_action_candidate: boolean;
      action_confidence: number;
      action_confidence_label: string;
      action_explanation: string;
      release_direction: [number, number, number];
      depth_proxy_mm: number;
      interference_volume_mm3?: number;
    }>;
    boolean_refinement?: { enabled: boolean; reliability?: Record<string, unknown> };
    [key: string]: unknown;
  };
  display_mesh?: DisplayMeshPayload & {
    undercut_visual_summary?: {
      counts: Record<string, number>;
      legend: Record<string, UndercutVisualStyleEntry>;
      confirmed_face_count: number;
    };
  };
}

/**
 * F7: one styled curve within `parting_line_paths` (backend/api/main.py's
 * `_parting_line_paths_payload`) -- `points` is a flat list of `[x,y,z]` mm
 * coordinates in part space, ready for a `THREE.Line`, not a mesh.
 */
export interface PartingLinePathStyle {
  label: string;
  points: [number, number, number][];
  point_count: number;
  rgb: [number, number, number];
  hex: string;
  width: number;
  opacity?: number;
  visible_by_default: boolean;
  smoothing_iterations?: number;
  quality?: string;
  fallback_to_raw?: boolean;
}

export interface PartingLinePathsPayload {
  raw: PartingLinePathStyle;
  refined: PartingLinePathStyle;
  legend: { raw: PartingLinePathStyle; refined: PartingLinePathStyle };
}

/**
 * F7: `GET /parts/{filename}/parting-line`'s response body (backend/api/
 * main.py:part_parting_line). `parting_line` is `ParTingLineResult.to_dict()`
 * (backend/geometry/parting_line.py) -- loosely typed; `analysis_quality`
 * mirrors `parting_line.diagnostic_gate`, promoted to the top level by the
 * backend itself.
 */
export interface PartingLineAnalysisResponse {
  part: Record<string, unknown>;
  parting_line: {
    pull_direction_source: string;
    diagnostic_gate?: Record<string, unknown>;
    diagnostics?: Record<string, unknown>;
    readiness?: Record<string, unknown>;
    [key: string]: unknown;
  };
  parting_line_paths: PartingLinePathsPayload;
  analysis_quality: Record<string, unknown>;
  display_mesh?: DisplayMeshPayload;
}

/** `POST /parts/upload`'s response body (backend/api/main.py:part_upload). */
export interface UploadResponse {
  /** The stored, uuid-prefixed filename -- use this for every subsequent `/parts/{filename}/...` call. */
  filename: string;
  original_filename: string;
  size_bytes: number;
}

/** `BoundingBox.to_dict()` (backend/models/geometry_models.py:135). */
export interface BoundingBoxPayload {
  xmin: number;
  ymin: number;
  zmin: number;
  xmax: number;
  ymax: number;
  zmax: number;
  diagonal_mm: number;
  center_mm: [number, number, number];
  dimensions_mm: [number, number, number];
}

/**
 * `PartGeometry.to_dict()` (backend/models/geometry_models.py:727), as
 * returned by `GET /parts/{filename}/summary`. `faces` is only present with
 * `include_faces=true` (F2 never requests it -- large payload, not needed
 * for the geometry summary chip); `display_mesh` only with `include_mesh=true`.
 */
export interface PartSummaryResponse {
  source_file: string;
  face_count: number;
  edge_count: number;
  vertex_count: number;
  solid_count: number;
  shell_count: number;
  bounding_box: BoundingBoxPayload;
  has_cadquery_shape: boolean;
  surface_type_counts: Record<string, number>;
  edge_type_counts: Record<string, number>;
  load_time_s: number;
  warnings: string[];
  adjacency_stats: Record<string, unknown>;
  optimal_pull_direction?: [number, number, number];
  direction_score?: number;
  inaccessible_face_count?: number;
  display_mesh?: DisplayMeshPayload;
}

/**
 * F6: `export_mold_halves()`'s own return dict
 * (backend/geometry/core_cavity.py) as embedded in `POST /parts/{filename}/
 * export/mold-halves`'s `export` field. `download_filename` (F6 addition)
 * is present ONLY when the file landed in the backend's default export
 * directory (`GET /export/download/{filename}` only ever serves from
 * there) -- absent for a `"failed"`/`"not_attempted"` status, or in the
 * (never actually exercised by this frontend) case of a caller-supplied
 * `output_dir`.
 */
export interface MoldHalfExportResult {
  status: 'exported' | 'failed' | 'not_attempted';
  output_path?: string;
  download_filename?: string;
  file_size_bytes?: number;
  schema?: string;
  solid_count?: number;
  failure_reason?: string;
  attempted_path?: string;
}

/**
 * F6: `POST /parts/{filename}/export/mold-halves`'s response body
 * (backend/api/main.py:export_mold_halves_endpoint). `export` is `null`
 * when the orchestration never reached a Boolean split at all (e.g. the
 * parting line itself was blocked) -- `orchestration.status`/
 * `orchestration.failure_reason` explain why in that case, exactly the
 * same `OrchestrationResult` shape F3/F4 already established.
 */
export interface MoldHalfExportResponse {
  filename: string;
  pull_direction: [number, number, number];
  orchestration?: OrchestrationResult;
  solid_split?: Record<string, unknown>;
  export: MoldHalfExportResult | null;
  side_core?: Record<string, unknown>;
  side_cores?: Record<string, unknown>;
  side_core_combined?: Record<string, unknown>;
}
