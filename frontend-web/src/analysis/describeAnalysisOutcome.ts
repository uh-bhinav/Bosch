/**
 * The ONE place that translates the backend's authoritative orchestration
 * vocabulary (`orchestration.status` / `orchestration.parting_line_v2_
 * outcome`, `backend/geometry/mold_orchestration.py` /
 * `backend/geometry/parting_line_v2/engine.py`) into a short display label
 * and a semantic tone. Every value branch below reproduces a status/outcome
 * string already documented verbatim in the backend source (see the
 * comments on `WinningDirectionMoldResult`/`PartingLineV2Result.outcome`) --
 * this module writes the English, never a new state.
 */

import type { CoreCavityAnalysisResponse } from '../api/types';

export type VerdictTone = 'ok' | 'warn' | 'bad' | 'neutral';

export interface AnalysisVerdict {
  /** Mirrors the backend field(s) this verdict was read from -- stable, testable. */
  code: string;
  label: string;
  tone: VerdictTone;
  /** `orchestration.failure_reason`, surfaced verbatim when present. */
  detail: string | null;
}

/**
 * `null` means "no orchestration result to describe yet" (analysis has not
 * run, or the response carried no `orchestration` block at all -- every
 * `runFullAnalysis` call requests `solid_split=true` so this should not
 * normally happen, but is handled rather than assumed).
 */
export function describeAnalysisOutcome(result: CoreCavityAnalysisResponse | null): AnalysisVerdict | null {
  const orchestration = result?.orchestration;
  if (!orchestration) return null;

  const { status, parting_line_v2_outcome: outcome, failure_reason: detail } = orchestration;

  switch (status) {
    case 'generated':
      return { code: 'generated', label: 'Feasible — mold split generated', tone: 'ok', detail };
    case 'blocked_optimal_not_found':
      return { code: 'blocked_optimal_not_found', label: 'Blocked — no verified optimum found', tone: 'bad', detail };
    case 'blocked_by_parting_line':
      if (outcome === 'referred_to_side_action') {
        return { code: 'referred_to_side_action', label: 'Needs a side action or referral', tone: 'warn', detail };
      }
      return { code: 'no_feasible_candidate', label: 'No feasible parting line found', tone: 'bad', detail };
    case 'blocked_by_core_cavity_split':
      return { code: 'blocked_by_core_cavity_split', label: 'Core/cavity solid split failed', tone: 'bad', detail };
    case 'invalid_direction':
      return { code: 'invalid_direction', label: 'Invalid pull direction', tone: 'bad', detail };
    case 'no_feature':
      return { code: 'no_feature', label: 'No undercut feature at this direction', tone: 'neutral', detail };
    default:
      return { code: 'unknown', label: status, tone: 'neutral', detail };
  }
}
