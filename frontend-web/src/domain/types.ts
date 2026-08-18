/**
 * Shared domain vocabulary for the workstation shell.
 *
 * These mirror the backend's own vocabulary (Vec3, tool identifiers, pull-
 * direction provenance) so that when F2+ wires real analysis calls in, the
 * shared store and API layer do not need new concepts invented at that
 * point -- only real data filling in what's already typed here.
 */

/** A 3-component vector, matching backend `Vec3` (mm, or a unit direction). */
export type Vec3 = readonly [number, number, number];

/**
 * The nine tool-rail destinations. Order (F10 §3) matches the Guided
 * narrative -- Import -> Draft -> Pull Direction -> Undercuts -> Parting
 * Line -> Core/Cavity -> Side Cores -> Diagnostics -> Report -- purely a
 * navigation/display order, not an execution order: "Run Full Analysis"
 * (analysis/analysisShared.ts) always resolves the pull direction FIRST
 * (the one call that also runs core-cavity), then fetches draft/undercuts/
 * parting-line-v2/side-core-check using that same resolved direction,
 * regardless of which order the tools are listed in here.
 */
export const TOOL_IDS = [
  'import',
  'draft',
  'pull-direction',
  'undercuts',
  'parting-line',
  'core-cavity',
  'side-cores',
  'diagnostics',
  'report',
] as const;

export type ToolId = (typeof TOOL_IDS)[number];

export interface ToolDescriptor {
  readonly id: ToolId;
  readonly label: string;
  /** Short, restrained glyph -- no per-module decorative color (F0 §10). */
  readonly glyph: string;
}

export const TOOLS: readonly ToolDescriptor[] = [
  { id: 'import', label: 'Import', glyph: 'IM' },
  { id: 'draft', label: 'Draft', glyph: 'DR' },
  { id: 'pull-direction', label: 'Pull Direction', glyph: 'PD' },
  { id: 'undercuts', label: 'Undercuts', glyph: 'UC' },
  { id: 'parting-line', label: 'Parting Line', glyph: 'PL' },
  { id: 'core-cavity', label: 'Core / Cavity', glyph: 'CC' },
  { id: 'side-cores', label: 'Side Cores', glyph: 'SC' },
  { id: 'diagnostics', label: 'Diagnostics', glyph: 'DX' },
  { id: 'report', label: 'Report', glyph: 'RP' },
];

/**
 * Matches `PullDirectionInput.source` in
 * backend/geometry/parting_line_v2/contracts.py: "manual" means an engineer
 * explicitly chose it (Phase C15/C16); "optimizer" means the automatic
 * search chose it. `null` means no direction has been resolved yet.
 */
export type PullDirectionSource = 'optimizer' | 'manual' | null;

/** Guided vs. Expert (F0 §2) -- a lens over shared state, not a separate tree. */
export type WorkstationMode = 'guided' | 'expert';

/** Coarse pipeline status for the top bar / status strip placeholders. */
export type PipelineStatus = 'idle' | 'running' | 'complete' | 'blocked';
