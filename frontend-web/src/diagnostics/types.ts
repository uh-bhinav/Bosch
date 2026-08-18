/**
 * The diagnostics workspace's own display vocabulary (F5, F0's three-tier
 * information hierarchy). A `DiagnosticEntry` is one row anywhere in the
 * workspace -- a plain fact, a clickable face/feature reference, or a raw
 * JSON dump (Advanced tier only). Nothing here computes or infers domain
 * conclusions; `deriveDiagnostics.ts` is the only place that reads backend
 * fields, and every entry's `value` is either a real backend-reported
 * number/string or the literal string "Not available from current
 * response" -- never a fabricated or re-derived engineering value.
 */

export type DiagnosticTone = 'ok' | 'warn' | 'bad' | 'neutral';

export const UNAVAILABLE = 'Not available from current response';

interface DiagnosticEntryBase {
  label: string;
  tooltip?: string;
}

export interface DiagnosticTextEntry extends DiagnosticEntryBase {
  kind: 'text';
  value: string;
  tone?: DiagnosticTone;
}

/** A row that highlights faces in the persistent viewport when clicked. */
export interface DiagnosticFaceListEntry extends DiagnosticEntryBase {
  kind: 'faceList';
  faceIds: number[];
  tone?: DiagnosticTone;
}

/** Advanced-tier only: a raw JSON value, rendered pretty-printed. */
export interface DiagnosticRawEntry extends DiagnosticEntryBase {
  kind: 'raw';
  json: unknown;
}

export type DiagnosticEntry = DiagnosticTextEntry | DiagnosticFaceListEntry | DiagnosticRawEntry;

export interface DiagnosticGroupModel {
  id: string;
  title: string;
  /** Always visible: the concise conclusion (F0 Tier 1). */
  tier1: DiagnosticEntry[];
  /** Behind "Details": supporting evidence (F0 Tier 2). */
  tier2: DiagnosticEntry[];
  /** Behind "Advanced": raw/debug information (F0 Tier 3). */
  tier3: DiagnosticEntry[];
}

export interface DiagnosticsModel {
  /** `false` only when no part is loaded at all -- distinct from "no analysis has run yet". */
  hasPart: boolean;
  groups: DiagnosticGroupModel[];
}

export function textEntry(
  label: string,
  value: string,
  opts: { tone?: DiagnosticTone; tooltip?: string } = {},
): DiagnosticTextEntry {
  return { kind: 'text', label, value, ...opts };
}

export function unavailableEntry(label: string, reason?: string): DiagnosticTextEntry {
  return {
    kind: 'text',
    label,
    value: UNAVAILABLE,
    tone: 'neutral',
    tooltip: reason,
  };
}

export function faceListEntry(
  label: string,
  faceIds: number[],
  opts: { tone?: DiagnosticTone; tooltip?: string } = {},
): DiagnosticFaceListEntry {
  return { kind: 'faceList', label, faceIds, ...opts };
}

export function rawEntry(label: string, json: unknown, tooltip?: string): DiagnosticRawEntry {
  return { kind: 'raw', label, json, tooltip };
}
