/**
 * The one shared application state (F1 spec, "STATE").
 *
 * This is deliberately the ONLY store in the app. The architecture this
 * replaces (F0 §1.5) let each Streamlit tab fetch and hold its own copy of
 * "the current part" and "the current direction" -- four independent
 * requests for one manual-override click, sometimes disagreeing. Viewport,
 * ToolRail, ContextInspector and (in later phases) every analysis panel all
 * read and write through this one store instead.
 *
 * F1 populates only the shell-level slice of this shape: active tool,
 * selection, camera, and the minimal part/connectivity state needed to
 * prove backend discovery. `pullDirection`/`pullDirectionSource`,
 * `selectedFaceIds`/`selectedEdgeIds`, and `overlay` are established here as
 * typed, empty-by-default state specifically so F2/F3 fill them in without
 * restructuring the store or the components that already read from it.
 */

import { create } from 'zustand';
import type {
  CoreCavityAnalysisResponse,
  CorePinFaceRefInput,
  DelegationInput,
  DraftAnalysisResponse,
  PartingLineV2Response,
  PartSummaryResponse,
  PartsListResponse,
  UndercutsAnalysisResponse,
} from '../api/types';
import type {
  PipelineStatus,
  PullDirectionSource,
  ToolId,
  Vec3,
  WorkstationMode,
} from '../domain/types';

export interface CameraState {
  position: Vec3;
  target: Vec3;
  zoom: number;
}

export const DEFAULT_CAMERA_STATE: CameraState = {
  position: [120, 90, 120],
  target: [0, 0, 0],
  zoom: 1,
};

/** F4: the Manual Pull Direction editor's starting vector -- +Z, matching `/core-cavity`'s own `dx=0&dy=0&dz=1` defaults. */
export const DEFAULT_MANUAL_PULL_DIRECTION: Vec3 = [0, 0, 1];

/** Which viewport overlay is active, if any. Empty until an analysis tool sets one. */
export type OverlayId = 'draft' | 'undercuts' | 'parting-line' | 'core-cavity' | 'side-cores' | null;

/** F12 §5: the Core/Cavity tool's independent viewport-layer toggles. */
export interface CoreCavityLayers {
  partingLine: boolean;
  /**
   * F13 §6: DISTINCT from `partingLine` (the curve) -- whether "parting
   * zone" faces (split/ambiguous region-classification faces) are shown as
   * their own distinct category. When off, those faces fall back to their
   * real `topological_side` (core or cavity, from the authoritative region
   * classification), never left visually ambiguous.
   */
  partingZone: boolean;
  core: boolean;
  cavity: boolean;
  corePin: boolean;
  sideAction: boolean;
  undercuts: boolean;
  pullDirection: boolean;
}

export const DEFAULT_CORE_CAVITY_LAYERS: CoreCavityLayers = {
  partingLine: true,
  partingZone: true,
  core: true,
  cavity: true,
  corePin: true,
  sideAction: true,
  undercuts: true,
  pullDirection: true,
};

/**
 * F6: shared by both the STEP mold-half export and the PDF report export --
 * "ready" (nothing started) -> "preparing" (request being built) ->
 * "generating" (backend request in flight -- these can take tens/hundreds
 * of seconds) -> "complete" | "failed". No percentage: the backend gives
 * no progress signal, so the UI shows elapsed time and stage text instead
 * of fabricating one.
 */
export type ExportStage = 'ready' | 'preparing' | 'generating' | 'complete' | 'failed';

export interface StepExportResult {
  downloadFilename: string;
  fileSizeBytes: number;
  solidCount: number;
}

/** The ONLY sections F6's Report Builder can actually toggle -- see `ExportPanel.tsx`'s own docstring for why the rest are fixed/unavailable. */
export interface PdfSectionSelection {
  executiveSummary: boolean;
  solidSplit: boolean;
  sideCores: boolean;
}

export const DEFAULT_PDF_SECTIONS: PdfSectionSelection = {
  executiveSummary: true,
  solidSplit: false,
  sideCores: false,
};

export type BackendConnectivity = 'unknown' | 'checking' | 'online' | 'offline';

/** F7: shared idle/running/done/error lifecycle for the draft/undercuts/parting-line follow-up fetches. */
export type FollowUpStage = 'idle' | 'running' | 'done' | 'error';

/**
 * F7: the Side Cores tool's headline state.
 * - 'unknown': no analysis has run yet for the current part/direction.
 * - 'checking': the primary analysis is still resolving a direction.
 * - 'not-required': the orchestration reached a feasible split with NO
 *   `parting_line_v2_outcome==='referred_to_side_action'` -- a real,
 *   positive "no side cores needed" result, not an absence of data.
 * - 'available': a side-core WAS required, and `getSideCoreDetail` fetched
 *   the real generated solid's data.
 * - 'unavailable': side action was required but the follow-up fetch itself
 *   failed (network/backend error) -- distinct from 'not-required'.
 * - 'blocked': the primary analysis never reached a feasible parting line at
 *   all, so side-core requirement could not be determined either way.
 */
export type SideCoreStatus = 'unknown' | 'checking' | 'not-required' | 'available' | 'unavailable' | 'blocked';

/**
 * F2's import state machine (F0 §7): idle -> uploading -> loading-geometry
 * -> ready, with a dedicated error state carrying a human-readable message
 * in `partLoadError`.
 */
export type PartLoadStatus = 'idle' | 'uploading' | 'loading-geometry' | 'ready' | 'error';

export interface AnalysisState {
  // --- connectivity / part discovery (F1) ---------------------------------
  backendConnectivity: BackendConnectivity;
  availableParts: string[];

  // --- current part (F1: filename only; F2: real summary + load status) --
  currentPart: string | null;
  currentPartSummary: PartSummaryResponse | null;
  partLoadStatus: PartLoadStatus;
  partLoadError: string | null;

  // --- shell / navigation (F1) --------------------------------------------
  activeTool: ToolId;
  mode: WorkstationMode;
  pipelineStatus: PipelineStatus;

  // --- selection (F1: typed + empty; F2+: populated by real picking) -----
  selectedFaceIds: number[];
  selectedEdgeIds: number[];

  // --- pull direction (F1: typed + empty; F3/manual-override: populated) -
  pullDirection: Vec3 | null;
  pullDirectionSource: PullDirectionSource;

  // --- viewport (F1: populated, persists across tool switches) -----------
  camera: CameraState;
  overlay: OverlayId;
  /**
   * F10 §2: purely visual inspection toggle -- the real topological face
   * boundaries drawn over the shaded mesh. Independent of `overlay`
   * (analysis coloring) and never read by any API call; toggling it can
   * never change analysis scope or results (F10 §1/§9).
   */
  showFaceBoundaries: boolean;
  /** F12 §12: user-draggable inspector width (px) -- see `shell/ResizeHandle.tsx`. Persists across tool switches like `camera`, never reset by `resetAnalysisState`. */
  inspectorWidth: number;
  /**
   * F12 §5: independent visibility toggles for the Core/Cavity tool's
   * combined viewport overlay ONLY -- `useOverlaySync.ts` reads this
   * exclusively when `activeTool === 'core-cavity'`, so it can never leak
   * into Draft/Undercuts/Parting Line's own overlays (F12 §15). All default
   * `true` (show everything) so the tab looks complete before the user
   * touches anything.
   */
  coreCavityLayers: CoreCavityLayers;

  // --- Guided "Run full analysis" (F3) ------------------------------------
  // `pipelineStatus` (above) stays the coarse idle/running/complete/blocked
  // chip; `analysisResult` carries the full authoritative response so any
  // panel can read `orchestration.status`/`parting_line_v2_outcome`/
  // `optimal_found`/`delegated_face_ids` directly rather than the frontend
  // re-deriving its own verdict. `analysisError` is set only for a request
  // that never reached the backend's own structured response (network
  // failure, unhandled HTTP error) -- a normal "blocked" orchestration
  // result is NOT an error, it's a successful call with unfavorable
  // content, and leaves `analysisError` null.
  analysisResult: CoreCavityAnalysisResponse | null;
  analysisError: string | null;

  // --- Manual Pull Direction + authorization (F4) -------------------------
  // `recommendedResult` is a SEPARATE snapshot from `analysisResult`,
  // written only by the Guided/automatic run (`runGuidedAnalysis`'s
  // `isRecommended: true`) and left untouched by any manual run -- so the
  // engineer can always compare "what the optimizer recommended" against
  // "what I just tried manually" even after `analysisResult` has moved on
  // to the manual result (F4 spec: "preserve the optimizer's recommended
  // result so the engineer can compare"). `manualPullDirection` is the
  // RAW, unnormalized draft vector the engineer is editing -- sent to the
  // backend exactly as typed; this store never normalizes it (C16 is the
  // one normalization authority). `corePinFaceRefs`/`delegations` are the
  // structured authorization editor's committed (non-draft, contract-valid)
  // entries, kept in shared state so they -- like the manual vector --
  // survive tool switches (F4 spec: "must survive... entering
  // authorization").
  recommendedResult: CoreCavityAnalysisResponse | null;
  manualPullDirection: Vec3;
  corePinFaceRefs: CorePinFaceRefInput[];
  delegations: DelegationInput[];

  // --- Diagnostics (F5) ----------------------------------------------------
  // The wall-clock duration of the most recent analysis REQUEST (upload-to-
  // response round trip, measured by `Date.now()` deltas in
  // `analysisShared.ts`), never a per-stage breakdown -- F5 spec: "Do not
  // manufacture stage timings from frontend elapsed time." Diagnostics
  // labels this explicitly as frontend-measured, distinct from any
  // backend-reported timing (e.g. `core_cavity.analysis_time_s`).
  lastRunDurationMs: number | null;

  // --- Export (F6) -----------------------------------------------------------
  // STEP mold-half export and PDF report export each get their own
  // Ready/Preparing/Generating/Complete/Failed lifecycle -- both reuse the
  // SAME already-resolved `pullDirection` (never re-running the optimizer;
  // see `runStepExport.ts`/`runPdfExport.ts`), so neither introduces an
  // independent fetch that recomputes an expensive search. `*StartedAt` is
  // a real `Date.now()` timestamp for an honest elapsed-time readout --
  // never a fabricated percentage, and never a manufactured per-stage
  // breakdown (F6 spec).
  stepExportStage: ExportStage;
  stepExportError: string | null;
  stepExportResult: StepExportResult | null;
  stepExportStartedAt: number | null;

  pdfExportStage: ExportStage;
  pdfExportError: string | null;
  pdfExportStartedAt: number | null;
  pdfSections: PdfSectionSelection;

  // --- Draft / Undercuts / Parting Line follow-up calls (F7) --------------
  // `executeAnalysisRun` (analysisShared.ts) fetches these AFTER the primary
  // core-cavity call resolves a pull direction, using that SAME direction --
  // none of these ever re-runs the optimizer. Each gets its own
  // idle/running/done/error lifecycle, independent of `pipelineStatus` and
  // of each other, so one follow-up failing (e.g. a slow Boolean pass
  // timing out) never hides the other two or the primary core/cavity result
  // that already succeeded.
  draftResult: DraftAnalysisResponse | null;
  draftStage: FollowUpStage;
  draftError: string | null;
  undercutsResult: UndercutsAnalysisResponse | null;
  undercutsStage: FollowUpStage;
  undercutsError: string | null;
  partingLineResult: PartingLineV2Response | null;
  partingLineStage: FollowUpStage;
  partingLineError: string | null;

  // --- Draft direction inspection (F13 §4) ---------------------------------
  // A PURE VISUAL override for the Draft tool -- inspecting a different
  // direction's draft classification never touches `pullDirection`/
  // `manualPullDirection` or triggers any analysis rerun. `null` means "show
  // the resolved/automatic direction's draft" (the default, `draftResult`
  // above); once set, `draftInspectResult` is a SEPARATE snapshot so the
  // resolved-direction result is never overwritten by an inspection probe.
  draftInspectDirection: Vec3 | null;
  draftInspectResult: DraftAnalysisResponse | null;
  draftInspectStage: FollowUpStage;
  draftInspectError: string | null;

  // --- Side cores (F7) ------------------------------------------------------
  // `sideCoreStatus` distinguishes "this pull direction genuinely needs no
  // side action" (a real, positive backend result) from "we don't know yet"
  // -- see `analysisShared.ts`'s docstring for exactly which orchestration
  // field ('parting_line_v2_outcome') drives this. `sideCoreDetail` is only
  // populated when status reaches 'available' (a real `generate_side_core`
  // call was made and returned a solid).
  sideCoreStatus: SideCoreStatus;
  sideCoreDetail: CoreCavityAnalysisResponse | null;
  sideCoreError: string | null;

  // --- actions -------------------------------------------------------------
  setBackendConnectivity: (status: BackendConnectivity) => void;
  setAvailableParts: (parts: PartsListResponse) => void;
  setCurrentPart: (part: string | null, summary?: PartSummaryResponse | null) => void;
  setPartLoadStatus: (status: PartLoadStatus) => void;
  setPartLoadError: (message: string | null) => void;
  setActiveTool: (tool: ToolId) => void;
  setMode: (mode: WorkstationMode) => void;
  setPipelineStatus: (status: PipelineStatus) => void;
  setSelectedFaceIds: (faceIds: number[]) => void;
  toggleFaceSelection: (faceId: number) => void;
  setSelectedEdgeIds: (edgeIds: number[]) => void;
  setPullDirection: (direction: Vec3 | null, source: PullDirectionSource) => void;
  setCamera: (camera: CameraState) => void;
  setOverlay: (overlay: OverlayId) => void;
  setShowFaceBoundaries: (show: boolean) => void;
  setCoreCavityLayer: (layer: keyof CoreCavityLayers, value: boolean) => void;
  setInspectorWidth: (width: number) => void;
  setAnalysisResult: (result: CoreCavityAnalysisResponse | null) => void;
  setAnalysisError: (message: string | null) => void;
  setRecommendedResult: (result: CoreCavityAnalysisResponse | null) => void;
  setLastRunDurationMs: (ms: number | null) => void;
  setManualPullDirection: (direction: Vec3) => void;
  addCorePinFaceRef: (ref: CorePinFaceRefInput) => void;
  removeCorePinFaceRef: (index: number) => void;
  addDelegation: (delegation: DelegationInput) => void;
  removeDelegation: (index: number) => void;
  clearAuthorization: () => void;
  setStepExportStage: (stage: ExportStage) => void;
  setStepExportError: (message: string | null) => void;
  setStepExportResult: (result: StepExportResult | null) => void;
  setStepExportStartedAt: (ms: number | null) => void;
  setPdfExportStage: (stage: ExportStage) => void;
  setPdfExportError: (message: string | null) => void;
  setPdfExportStartedAt: (ms: number | null) => void;
  setPdfSections: (sections: PdfSectionSelection) => void;
  setDraftResult: (result: DraftAnalysisResponse | null) => void;
  setDraftStage: (stage: FollowUpStage) => void;
  setDraftError: (message: string | null) => void;
  setUndercutsResult: (result: UndercutsAnalysisResponse | null) => void;
  setUndercutsStage: (stage: FollowUpStage) => void;
  setUndercutsError: (message: string | null) => void;
  setPartingLineResult: (result: PartingLineV2Response | null) => void;
  setPartingLineStage: (stage: FollowUpStage) => void;
  setPartingLineError: (message: string | null) => void;
  setDraftInspectDirection: (direction: Vec3 | null) => void;
  setDraftInspectResult: (result: DraftAnalysisResponse | null) => void;
  setDraftInspectStage: (stage: FollowUpStage) => void;
  setDraftInspectError: (message: string | null) => void;
  setSideCoreStatus: (status: SideCoreStatus) => void;
  setSideCoreDetail: (result: CoreCavityAnalysisResponse | null) => void;
  setSideCoreError: (message: string | null) => void;
  clearSelection: () => void;
  /**
   * Clears every analysis-derived field (selection, pull direction,
   * overlay, pipeline status, F3's `analysisResult`/`analysisError`, F4's
   * `recommendedResult`/`manualPullDirection`/`corePinFaceRefs`/
   * `delegations`, F6's STEP/PDF export stage/error/result/section
   * selection) while leaving workstation/UI state -- `activeTool`, `mode`,
   * `availableParts`, `backendConnectivity`, `camera` -- untouched. Called
   * before loading any new part (F2 spec: "loading a new part must
   * cleanly reset analysis-specific state while preserving workstation/UI
   * state"; F3/F4/F6 extend this same guarantee to the analysis result(s),
   * manual-direction/authorization drafts, and export state -- a stale
   * "Complete, ready to download" from the PREVIOUS part's export must not
   * survive into a new part's session). Does NOT touch `currentPart`/
   * `currentPartSummary`/`partLoadStatus`/`partLoadError` -- those are the
   * part-loading state machine itself, updated separately by the caller
   * (see src/import/loadPart.ts) as loading actually progresses.
   */
  resetAnalysisState: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  backendConnectivity: 'unknown',
  availableParts: [],

  currentPart: null,
  currentPartSummary: null,
  partLoadStatus: 'idle',
  partLoadError: null,

  activeTool: 'import',
  mode: 'guided',
  pipelineStatus: 'idle',

  selectedFaceIds: [],
  selectedEdgeIds: [],

  pullDirection: null,
  pullDirectionSource: null,

  camera: DEFAULT_CAMERA_STATE,
  overlay: null,
  showFaceBoundaries: false,
  coreCavityLayers: DEFAULT_CORE_CAVITY_LAYERS,
  inspectorWidth: 420,

  analysisResult: null,
  analysisError: null,

  recommendedResult: null,
  manualPullDirection: DEFAULT_MANUAL_PULL_DIRECTION,
  corePinFaceRefs: [],
  delegations: [],

  lastRunDurationMs: null,

  stepExportStage: 'ready',
  stepExportError: null,
  stepExportResult: null,
  stepExportStartedAt: null,

  pdfExportStage: 'ready',
  pdfExportError: null,
  pdfExportStartedAt: null,
  pdfSections: DEFAULT_PDF_SECTIONS,

  draftResult: null,
  draftStage: 'idle',
  draftError: null,
  undercutsResult: null,
  undercutsStage: 'idle',
  undercutsError: null,
  partingLineResult: null,
  partingLineStage: 'idle',
  partingLineError: null,

  draftInspectDirection: null,
  draftInspectResult: null,
  draftInspectStage: 'idle',
  draftInspectError: null,

  sideCoreStatus: 'unknown',
  sideCoreDetail: null,
  sideCoreError: null,

  setBackendConnectivity: (status) => set({ backendConnectivity: status }),
  setAvailableParts: (parts) => set({ availableParts: parts.files }),
  setCurrentPart: (part, summary = null) => set({ currentPart: part, currentPartSummary: summary }),
  setPartLoadStatus: (status) => set({ partLoadStatus: status }),
  setPartLoadError: (message) => set({ partLoadError: message }),
  setActiveTool: (tool) => set({ activeTool: tool }),
  setMode: (mode) => set({ mode }),
  setPipelineStatus: (status) => set({ pipelineStatus: status }),
  setSelectedFaceIds: (faceIds) => set({ selectedFaceIds: faceIds }),
  toggleFaceSelection: (faceId) =>
    set((state) => {
      const isSelected = state.selectedFaceIds.includes(faceId);
      return {
        selectedFaceIds: isSelected
          ? state.selectedFaceIds.filter((id) => id !== faceId)
          : [...state.selectedFaceIds, faceId],
      };
    }),
  setSelectedEdgeIds: (edgeIds) => set({ selectedEdgeIds: edgeIds }),
  setPullDirection: (direction, source) =>
    set({ pullDirection: direction, pullDirectionSource: source }),
  setCamera: (camera) => set({ camera }),
  setOverlay: (overlay) => set({ overlay }),
  setShowFaceBoundaries: (show) => set({ showFaceBoundaries: show }),
  setCoreCavityLayer: (layer, value) =>
    set((state) => ({ coreCavityLayers: { ...state.coreCavityLayers, [layer]: value } })),
  setInspectorWidth: (width) => set({ inspectorWidth: Math.round(Math.min(720, Math.max(360, width))) }),
  setAnalysisResult: (result) => set({ analysisResult: result }),
  setAnalysisError: (message) => set({ analysisError: message }),
  setRecommendedResult: (result) => set({ recommendedResult: result }),
  setLastRunDurationMs: (ms) => set({ lastRunDurationMs: ms }),
  setManualPullDirection: (direction) => set({ manualPullDirection: direction }),
  addCorePinFaceRef: (ref) => set((state) => ({ corePinFaceRefs: [...state.corePinFaceRefs, ref] })),
  removeCorePinFaceRef: (index) =>
    set((state) => ({ corePinFaceRefs: state.corePinFaceRefs.filter((_, i) => i !== index) })),
  addDelegation: (delegation) => set((state) => ({ delegations: [...state.delegations, delegation] })),
  removeDelegation: (index) =>
    set((state) => ({ delegations: state.delegations.filter((_, i) => i !== index) })),
  clearAuthorization: () => set({ corePinFaceRefs: [], delegations: [] }),
  setStepExportStage: (stage) => set({ stepExportStage: stage }),
  setStepExportError: (message) => set({ stepExportError: message }),
  setStepExportResult: (result) => set({ stepExportResult: result }),
  setStepExportStartedAt: (ms) => set({ stepExportStartedAt: ms }),
  setPdfExportStage: (stage) => set({ pdfExportStage: stage }),
  setPdfExportError: (message) => set({ pdfExportError: message }),
  setPdfExportStartedAt: (ms) => set({ pdfExportStartedAt: ms }),
  setPdfSections: (sections) => set({ pdfSections: sections }),
  setDraftResult: (result) => set({ draftResult: result }),
  setDraftStage: (stage) => set({ draftStage: stage }),
  setDraftError: (message) => set({ draftError: message }),
  setUndercutsResult: (result) => set({ undercutsResult: result }),
  setUndercutsStage: (stage) => set({ undercutsStage: stage }),
  setUndercutsError: (message) => set({ undercutsError: message }),
  setPartingLineResult: (result) => set({ partingLineResult: result }),
  setPartingLineStage: (stage) => set({ partingLineStage: stage }),
  setPartingLineError: (message) => set({ partingLineError: message }),
  setDraftInspectDirection: (direction) => set({ draftInspectDirection: direction }),
  setDraftInspectResult: (result) => set({ draftInspectResult: result }),
  setDraftInspectStage: (stage) => set({ draftInspectStage: stage }),
  setDraftInspectError: (message) => set({ draftInspectError: message }),
  setSideCoreStatus: (status) => set({ sideCoreStatus: status }),
  setSideCoreDetail: (result) => set({ sideCoreDetail: result }),
  setSideCoreError: (message) => set({ sideCoreError: message }),
  clearSelection: () => set({ selectedFaceIds: [], selectedEdgeIds: [] }),
  resetAnalysisState: () =>
    set({
      selectedFaceIds: [],
      selectedEdgeIds: [],
      pullDirection: null,
      pullDirectionSource: null,
      overlay: null,
      pipelineStatus: 'idle',
      analysisResult: null,
      analysisError: null,
      recommendedResult: null,
      manualPullDirection: DEFAULT_MANUAL_PULL_DIRECTION,
      corePinFaceRefs: [],
      delegations: [],
      lastRunDurationMs: null,
      stepExportStage: 'ready',
      stepExportError: null,
      stepExportResult: null,
      stepExportStartedAt: null,
      pdfExportStage: 'ready',
      pdfExportError: null,
      pdfExportStartedAt: null,
      pdfSections: DEFAULT_PDF_SECTIONS,
      draftResult: null,
      draftStage: 'idle',
      draftError: null,
      undercutsResult: null,
      undercutsStage: 'idle',
      undercutsError: null,
      partingLineResult: null,
      partingLineStage: 'idle',
      partingLineError: null,
      draftInspectDirection: null,
      draftInspectResult: null,
      draftInspectStage: 'idle',
      draftInspectError: null,
      sideCoreStatus: 'unknown',
      sideCoreDetail: null,
      sideCoreError: null,
    }),
}));
