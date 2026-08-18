/**
 * Backend endpoint functions. F1 implemented `getHealth`/`listParts`. F2
 * adds exactly the two calls the import flow needs: `uploadPart` (`POST
 * /parts/upload`) and `getSummary` (`GET /parts/{filename}/summary`).
 *
 * Every later phase's endpoint (draft, undercuts, direction, core-cavity,
 * orchestration, side-core, export) still belongs in this file, following
 * the same `apiGet`/`apiPost`/`apiUpload` pattern -- never inline in a
 * component.
 */

import { API_BASE, apiGet, apiPost, apiPostBinary, apiUpload } from './client';
import type {
  CoreCavityAnalysisResponse,
  CorePinFaceRefInput,
  DelegationInput,
  DraftAnalysisResponse,
  HealthResponse,
  MoldHalfExportResponse,
  PartingLineAnalysisResponse,
  PartingLineV2Response,
  PartsListResponse,
  PartSummaryResponse,
  UndercutsAnalysisResponse,
  UploadResponse,
} from './types';
import type { Vec3 } from '../domain/types';

export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/health');
}

export function listParts(): Promise<PartsListResponse> {
  return apiGet<PartsListResponse>('/parts');
}

export function uploadPart(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return apiUpload<UploadResponse>('/parts/upload', formData);
}

export interface GetSummaryOptions {
  includeMesh?: boolean;
  meshDeflection?: number;
}

export function getSummary(filename: string, options: GetSummaryOptions = {}): Promise<PartSummaryResponse> {
  return apiGet<PartSummaryResponse>(`/parts/${encodeURIComponent(filename)}/summary`, {
    include_mesh: options.includeMesh ?? false,
    mesh_deflection: options.meshDeflection ?? 0.5,
  });
}

/**
 * F3: the Guided "Run full analysis" call -- the single authoritative
 * endpoint (`/core-cavity` with `use_optimal_direction=true&solid_split=
 * true`) that runs direction search -> parting line -> core/cavity solid
 * split in one request. Side-core generation is deliberately never
 * requested here (`generate_side_core`/`multi_feature_side_cores` both
 * omitted, so the backend's own defaults of `false` apply) -- F3's scope
 * excludes side-action routing, and requesting it would also make
 * `orchestration.status` able to return `"no_feature"`, a state this
 * endpoint's automatic path otherwise never produces.
 */
export function runFullAnalysis(filename: string, meshDeflection = 0.5): Promise<CoreCavityAnalysisResponse> {
  return apiGet<CoreCavityAnalysisResponse>(`/parts/${encodeURIComponent(filename)}/core-cavity`, {
    use_optimal_direction: true,
    solid_split: true,
    include_faces: false,
    include_mesh: true,
    include_mesh_geometry: true,
    mesh_deflection: meshDeflection,
  });
}

/**
 * F7: Draft analysis for a specific pull direction (`GET /parts/{filename}/
 * draft`) -- called AFTER a direction has already been resolved (by Full
 * Analysis or Manual Analysis), never re-running the optimizer itself. Only
 * `include_mesh_geometry=false` (no `points`/`faces`) is requested by
 * default: the resulting `display_mesh.face_ids`/`draft_rgb` are zipped into
 * a face-id color map (`geometry/overlayColors.ts`) and applied to whichever
 * mesh geometry is already loaded, rather than reloading geometry a second
 * time for the same part.
 */
export function getDraft(filename: string, direction: Vec3, meshDeflection = 0.5): Promise<DraftAnalysisResponse> {
  return apiGet<DraftAnalysisResponse>(`/parts/${encodeURIComponent(filename)}/draft`, {
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    include_mesh: true,
    include_mesh_geometry: false,
    mesh_deflection: meshDeflection,
  });
}

/** F7: Undercut detection for a specific, already-resolved pull direction (`GET /parts/{filename}/undercuts`). See `getDraft` for why `include_mesh_geometry` stays `false` here. */
export function getUndercuts(
  filename: string,
  direction: Vec3,
  meshDeflection = 0.5,
): Promise<UndercutsAnalysisResponse> {
  return apiGet<UndercutsAnalysisResponse>(`/parts/${encodeURIComponent(filename)}/undercuts`, {
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    include_mesh: true,
    include_mesh_geometry: false,
    mesh_deflection: meshDeflection,
  });
}

/**
 * F7: the parting-line curve for a specific, already-resolved pull direction
 * (`GET /parts/{filename}/parting-line`, `use_optimal_direction=false` so
 * the optimizer search is never repeated). Neither `/core-cavity` nor
 * `/direction` returns the actual curve geometry (`parting_line_paths`) --
 * this is the only endpoint that does, so a dedicated call is unavoidable to
 * visualize it. `include_mesh=false`: this call exists purely for the curve
 * points, never to re-color or reload the base mesh.
 */
export function getPartingLine(filename: string, direction: Vec3): Promise<PartingLineAnalysisResponse> {
  return apiGet<PartingLineAnalysisResponse>(`/parts/${encodeURIComponent(filename)}/parting-line`, {
    use_optimal_direction: false,
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    include_mesh: false,
    include_undercut_conflicts: false,
  });
}

/**
 * F8: the AUTHORITATIVE parting-line curve -- `/parting-line-v2`, the same
 * engine `/core-cavity` already uses internally for the real face split
 * (`analyse_parting_line`, via `resolve_authoritative_parting_line`). This
 * endpoint never runs the direction optimizer itself (enforced backend-side
 * by `test_no_module_imports_the_direction_optimizer`) -- it always takes
 * `direction` as a literal, already-resolved vector, exactly like the
 * legacy `getPartingLine` it replaces for the Parting Line tool. Threads the
 * SAME `core_pin_face_refs`/`delegations` authorization the primary
 * core-cavity call used, so the curve shown here is consistent with
 * whatever solid split it's illustrating -- never a second, differently-
 * authorized run.
 */
export function getPartingLineV2(
  filename: string,
  direction: Vec3,
  authorization: ManualAnalysisAuthorization = {},
): Promise<PartingLineV2Response> {
  const params: Record<string, string | number | boolean> = {
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    // F10 §6: include_mesh_geometry stays false (no points/faces -- geometry
    // is already loaded from the primary core-cavity call) but include_mesh
    // must be true to get face_ids + pv2_core_pin_rgb/pv2_delegation_rgb --
    // the only source of "which faces are the authorized core-pin/delegation
    // groups", needed to visualize authorization the same way draft/
    // undercuts/core-cavity are already visualized.
    include_mesh: true,
    include_mesh_geometry: false,
    ...authorizationParams(authorization),
  };
  return apiGet<PartingLineV2Response>(`/parts/${encodeURIComponent(filename)}/parting-line-v2`, params);
}

/**
 * F7: real side-core generation for an already-resolved direction --
 * `/core-cavity` with `generate_side_core=true&solid_split=true`, the ONLY
 * way to learn whether a specific highest-confidence critical feature at
 * this direction actually produces a side core (volume, containing half,
 * status) rather than just the orchestration's coarse
 * `parting_line_v2_outcome==='referred_to_side_action'` signal. Called only
 * when that signal is present (`analysisShared.ts`) -- never unconditionally,
 * since it is real additional Boolean computation.
 */
export function getSideCoreDetail(
  filename: string,
  direction: Vec3,
  authorization: ManualAnalysisAuthorization = {},
): Promise<CoreCavityAnalysisResponse> {
  const params: Record<string, string | number | boolean> = {
    use_optimal_direction: false,
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    solid_split: true,
    generate_side_core: true,
    include_mesh: false,
    ...authorizationParams(authorization),
  };
  return apiGet<CoreCavityAnalysisResponse>(`/parts/${encodeURIComponent(filename)}/core-cavity`, params);
}

export interface ManualAnalysisAuthorization {
  corePinFaceRefs?: CorePinFaceRefInput[];
  delegations?: DelegationInput[];
}

/**
 * Shared by every endpoint that accepts `core_pin_face_refs`/`delegations`
 * -- sent ONLY when non-empty and JSON-stringified exactly as
 * `_parse_core_pin_face_refs`/`_parse_delegations` (backend/api/main.py)
 * require, so omitting an empty list preserves each parameter's own
 * documented "omit for today's default behaviour" contract.
 */
function authorizationParams(authorization: ManualAnalysisAuthorization): Record<string, string> {
  const params: Record<string, string> = {};
  if (authorization.corePinFaceRefs && authorization.corePinFaceRefs.length > 0) {
    params.core_pin_face_refs = JSON.stringify(authorization.corePinFaceRefs);
  }
  if (authorization.delegations && authorization.delegations.length > 0) {
    params.delegations = JSON.stringify(authorization.delegations);
  }
  return params;
}

/**
 * F4: the Manual Pull Direction call -- the SAME `/core-cavity` endpoint
 * F3 uses, with `use_optimal_direction=false` and the engineer's raw
 * `dx`/`dy`/`dz` (never normalized here -- backend C16's
 * `resolve_manual_direction_mold`/`prepare_manual_direction` is the one
 * normalization/invalid-direction authority, via `normalize3`). Optional
 * `core_pin_face_refs`/`delegations` are sent ONLY when non-empty and
 * JSON-stringified exactly as `_parse_core_pin_face_refs`/
 * `_parse_delegations` (backend/api/main.py) require -- omitting an empty
 * list preserves each parameter's own documented "omit for today's
 * default behaviour" contract rather than sending a redundant `"[]"`.
 */
export function runManualCoreCavity(
  filename: string,
  direction: Vec3,
  authorization: ManualAnalysisAuthorization = {},
  meshDeflection = 0.5,
): Promise<CoreCavityAnalysisResponse> {
  const params: Record<string, string | number | boolean> = {
    use_optimal_direction: false,
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    solid_split: true,
    include_faces: false,
    include_mesh: true,
    include_mesh_geometry: true,
    mesh_deflection: meshDeflection,
    ...authorizationParams(authorization),
  };
  return apiGet<CoreCavityAnalysisResponse>(`/parts/${encodeURIComponent(filename)}/core-cavity`, params);
}

/**
 * F6: STEP mold-half export. ALWAYS calls with `use_optimal_direction=
 * false` and the caller-supplied `direction` (the frontend's own already-
 * resolved `pullDirection`, whichever of Guided/Manual produced the
 * current on-screen result) -- this endpoint runs its own complete
 * pipeline internally (`optimize_mold_direction` when
 * `use_optimal_direction=true`) and has no way to accept an
 * already-computed result, so this is the only way to avoid repeating the
 * expensive optimizer search a second time purely to export what was
 * already found. Undercut detection/parting-line/solid-split are still
 * re-run for that one already-known direction -- an unavoidable
 * consequence of the backend's stateless, no-cached-OCC-solids
 * architecture (`PartGeometry`/solids never survive between requests),
 * not something this call can skip.
 */
export function exportMoldHalves(
  filename: string,
  direction: Vec3,
  authorization: ManualAnalysisAuthorization = {},
): Promise<MoldHalfExportResponse> {
  const params: Record<string, string | number | boolean> = {
    use_optimal_direction: false,
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    ...authorizationParams(authorization),
  };
  return apiPost<MoldHalfExportResponse>(`/parts/${encodeURIComponent(filename)}/export/mold-halves`, params);
}

export function stepDownloadUrl(downloadFilename: string): string {
  return `${API_BASE}/export/download/${encodeURIComponent(downloadFilename)}`;
}

export interface PdfReportSections {
  executiveSummary: boolean;
  solidSplit: boolean;
  sideCores: boolean;
}

/**
 * F6: the PDF DfM report. Same direction-reuse rule as `exportMoldHalves`
 * -- always `use_optimal_direction=false` with the already-resolved
 * direction, so generating a report never repeats the optimizer search.
 * A real consequence, disclosed in the UI: because of this, the PDF's own
 * "Pull Direction Optimization" section (which only ever renders when the
 * backend itself ran `optimize_mold_direction`) never appears in a report
 * this frontend generates, regardless of which section checkboxes are
 * selected -- there is no flag that produces it without re-running the
 * search.
 */
export function exportPdfReport(
  filename: string,
  direction: Vec3,
  authorization: ManualAnalysisAuthorization,
  sections: PdfReportSections,
): Promise<Blob> {
  const params: Record<string, string | number | boolean> = {
    use_optimal_direction: false,
    dx: direction[0],
    dy: direction[1],
    dz: direction[2],
    include_executive_summary: sections.executiveSummary,
    include_solid_split: sections.solidSplit,
    include_side_core: sections.sideCores,
    ...authorizationParams(authorization),
  };
  return apiPostBinary(`/parts/${encodeURIComponent(filename)}/export/report`, params);
}
