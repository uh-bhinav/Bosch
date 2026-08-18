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
  PartSummaryResponse,
  PartsListResponse,
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
export type OverlayId = 'draft' | 'undercuts' | 'core-cavity' | 'side-cores' | null;

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
    }),
}));
