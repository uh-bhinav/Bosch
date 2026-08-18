/**
 * Contextual right inspector: content swaps with `activeTool`, read
 * entirely from the shared store. This is the component whose re-render
 * F1's persistence test measures against -- it must change on every tool
 * switch while `Viewport` (a sibling, not a parent/child of this component)
 * does not.
 *
 * F1 shipped a clean placeholder per tool. F2 replaced the `import`
 * placeholder with a real panel (`ImportPanel`). F3-F6 gave `pull-direction`/
 * `diagnostics`/`report` their own real panels; `parting-line`/`core-cavity`
 * share `AnalysisSummaryPanel` (a common verdict block plus, since F7,
 * tool-specific sections it renders itself based on `activeTool`). F7 gives
 * `draft`/`undercuts`/`side-cores` their own real panels too -- every tool
 * now has real content, no placeholders remain.
 */

import { TOOLS } from '../../domain/types';
import { useAnalysisStore } from '../../store/analysisStore';
import { AnalysisSummaryPanel } from './panels/AnalysisSummaryPanel';
import { DiagnosticsPanel } from './panels/DiagnosticsPanel';
import { DraftPanel } from './panels/DraftPanel';
import { ExportPanel } from './panels/ExportPanel';
import { ImportPanel } from './panels/ImportPanel';
import { PullDirectionPanel } from './panels/PullDirectionPanel';
import { SideCoresPanel } from './panels/SideCoresPanel';
import { UndercutsPanel } from './panels/UndercutsPanel';
import styles from './ContextInspector.module.css';

export function ContextInspector() {
  const activeTool = useAnalysisStore((s) => s.activeTool);
  const selectedFaceIds = useAnalysisStore((s) => s.selectedFaceIds);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const pullDirectionSource = useAnalysisStore((s) => s.pullDirectionSource);

  const inspectorWidth = useAnalysisStore((s) => s.inspectorWidth);
  const tool = TOOLS.find((t) => t.id === activeTool);

  return (
    <aside
      className={styles.inspector}
      aria-label="Inspector"
      data-testid="inspector"
      // F12 §12: draggable width (ResizeHandle.tsx) -- overrides the CSS
      // `--inspector-width` default via inline style, the normal way to let
      // per-instance state win over a stylesheet default.
      style={{ width: inspectorWidth, flexBasis: inspectorWidth, maxWidth: inspectorWidth }}
    >
      <div className={styles.header}>
        <span className={styles.eyebrow}>{tool?.glyph}</span>
        <h2 className={styles.title}>{tool?.label}</h2>
      </div>

      <div className={styles.body}>
        {activeTool === 'import' ? (
          <ImportPanel />
        ) : activeTool === 'pull-direction' ? (
          <PullDirectionPanel />
        ) : activeTool === 'draft' ? (
          <DraftPanel />
        ) : activeTool === 'undercuts' ? (
          <UndercutsPanel />
        ) : activeTool === 'side-cores' ? (
          <SideCoresPanel />
        ) : activeTool === 'diagnostics' ? (
          <DiagnosticsPanel />
        ) : activeTool === 'report' ? (
          <ExportPanel />
        ) : (
          <AnalysisSummaryPanel />
        )}

        <dl className={styles.factList}>
          <div className={styles.factRow}>
            <dt>Analysis scope</dt>
            <dd>Full imported part</dd>
          </div>
          <div className={styles.factRow}>
            <dt title="Inspection/highlighting only -- never restricts what Full Analysis, Draft, Undercuts, or Core/Cavity operate on.">
              Face selection (view only)
            </dt>
            <dd>
              {selectedFaceIds.length === 0
                ? 'None'
                : selectedFaceIds.length === 1
                  ? `Face ${selectedFaceIds[0]}`
                  : `${selectedFaceIds.length} faces`}
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
