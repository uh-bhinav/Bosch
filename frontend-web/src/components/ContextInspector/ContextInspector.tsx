/**
 * Contextual right inspector: content swaps with `activeTool`, read
 * entirely from the shared store. This is the component whose re-render
 * F1's persistence test measures against -- it must change on every tool
 * switch while `Viewport` (a sibling, not a parent/child of this component)
 * does not.
 *
 * F1 shipped a clean placeholder per tool. F2 replaced the `import`
 * placeholder with a real panel (`ImportPanel`). F3 replaced `parting-line`/
 * `core-cavity` (and, at the time, `pull-direction`) with a shared
 * `AnalysisSummaryPanel` (read-only display of the Guided analysis result).
 * F4 gives `pull-direction` its OWN real panel (`PullDirectionPanel`) --
 * recommended vs. manual direction, axis presets, face-normal pick,
 * authorization editor, and the "Run Manual Analysis" action -- while
 * `parting-line`/`core-cavity` keep the F3 read-only summary (F4 spec:
 * "Expert tool panels may display available results... unless required by
 * the existing backend contract" -- Pull Direction specifically needs a
 * real workflow, the other two still don't yet). F5 gives `diagnostics`
 * its own real panel (`DiagnosticsPanel`) -- the three-tier explanation
 * workspace. F6 gives `report` its own real panel (`ExportPanel`) -- STEP
 * mold-half export and the PDF Report Builder. `undercuts`, `side-cores`
 * still show their F1 placeholder -- later phases.
 */

import { TOOLS } from '../../domain/types';
import type { ToolId } from '../../domain/types';
import { useAnalysisStore } from '../../store/analysisStore';
import { AnalysisSummaryPanel } from './panels/AnalysisSummaryPanel';
import { DiagnosticsPanel } from './panels/DiagnosticsPanel';
import { ExportPanel } from './panels/ExportPanel';
import { ImportPanel } from './panels/ImportPanel';
import { PullDirectionPanel } from './panels/PullDirectionPanel';
import styles from './ContextInspector.module.css';

const ANALYSIS_SUMMARY_TOOLS: ReadonlySet<ToolId> = new Set(['parting-line', 'core-cavity']);

const TOOL_PLACEHOLDERS: Record<Exclude<ToolId, 'import'>, string> = {
  'pull-direction': 'Analysis not run.',
  'parting-line': 'Analysis not run.',
  'core-cavity': 'Analysis not run.',
  undercuts: 'Analysis not run.',
  'side-cores': 'Analysis not run.',
  diagnostics: 'No diagnostics available yet.',
  report: 'Nothing to export yet.',
};

export function ContextInspector() {
  const activeTool = useAnalysisStore((s) => s.activeTool);
  const selectedFaceIds = useAnalysisStore((s) => s.selectedFaceIds);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const pullDirectionSource = useAnalysisStore((s) => s.pullDirectionSource);

  const tool = TOOLS.find((t) => t.id === activeTool);

  return (
    <aside className={styles.inspector} aria-label="Inspector" data-testid="inspector">
      <div className={styles.header}>
        <span className={styles.eyebrow}>{tool?.glyph}</span>
        <h2 className={styles.title}>{tool?.label}</h2>
      </div>

      <div className={styles.body}>
        {activeTool === 'import' ? (
          <ImportPanel />
        ) : activeTool === 'pull-direction' ? (
          <PullDirectionPanel />
        ) : activeTool === 'diagnostics' ? (
          <DiagnosticsPanel />
        ) : activeTool === 'report' ? (
          <ExportPanel />
        ) : ANALYSIS_SUMMARY_TOOLS.has(activeTool) ? (
          <AnalysisSummaryPanel />
        ) : (
          <p className={styles.placeholder}>{TOOL_PLACEHOLDERS[activeTool]}</p>
        )}

        <dl className={styles.factList}>
          <div className={styles.factRow}>
            <dt>Selection</dt>
            <dd>
              {selectedFaceIds.length > 0
                ? `${selectedFaceIds.length} face${selectedFaceIds.length === 1 ? '' : 's'}`
                : 'None'}
            </dd>
          </div>
          <div className={styles.factRow}>
            <dt>Pull direction</dt>
            <dd>
              {pullDirection
                ? `(${pullDirection.map((v) => v.toFixed(2)).join(', ')})`
                : 'Not set'}
            </dd>
          </div>
          <div className={styles.factRow}>
            <dt>Source</dt>
            <dd>{pullDirectionSource ?? '—'}</dd>
          </div>
        </dl>
      </div>
    </aside>
  );
}
