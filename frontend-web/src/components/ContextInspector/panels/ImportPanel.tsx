/**
 * The Import tool's real panel (F2) -- replaces the F1 placeholder for
 * `activeTool === 'import'` only; every other tool's placeholder is
 * untouched (F2 spec: no other tool's functionality yet).
 *
 * Journey (F0 §7): select -> validate -> upload -> load geometry -> ready,
 * with a compact recent-parts list for re-opening. All state transitions
 * are driven by `src/import/loadPart.ts`; this component only renders
 * `useAnalysisStore`'s part-loading slice and dispatches user actions --
 * no fetch, no viewport-engine call here.
 */

import { useRef, useState, type DragEvent } from 'react';
import { useAnalysisStore } from '../../../store/analysisStore';
import { loadExistingPart, loadPartFromFile } from '../../../import/loadPart';
import styles from './ImportPanel.module.css';

export function ImportPanel() {
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const currentPart = useAnalysisStore((s) => s.currentPart);
  const currentPartSummary = useAnalysisStore((s) => s.currentPartSummary);
  const partLoadStatus = useAnalysisStore((s) => s.partLoadStatus);
  const partLoadError = useAnalysisStore((s) => s.partLoadError);
  const availableParts = useAnalysisStore((s) => s.availableParts);

  const isBusy = partLoadStatus === 'uploading' || partLoadStatus === 'loading-geometry';

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (file) {
      void loadPartFromFile(file);
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(false);
    if (isBusy) return;
    handleFiles(event.dataTransfer.files);
  };

  const otherParts = availableParts.filter((name) => name !== currentPart);

  return (
    <div className={styles.panel} data-testid="import-panel">
      <div
        className={styles.dropZone}
        data-drag-over={isDragOver}
        data-busy={isBusy}
        onDragOver={(e) => {
          e.preventDefault();
          if (!isBusy) setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !isBusy && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload a STEP file"
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !isBusy) fileInputRef.current?.click();
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".stp,.step"
          className={styles.hiddenInput}
          data-testid="import-file-input"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = '';
          }}
        />
        {partLoadStatus === 'uploading' && <p className={styles.dropZoneText}>Uploading…</p>}
        {partLoadStatus === 'loading-geometry' && <p className={styles.dropZoneText}>Loading geometry…</p>}
        {!isBusy && (
          <>
            <p className={styles.dropZoneText}>Drop a .stp / .step file here</p>
            <p className={styles.dropZoneHint}>or click to browse</p>
          </>
        )}
      </div>

      {partLoadStatus === 'error' && partLoadError && (
        <p className={styles.errorText} role="alert" data-testid="import-error">
          {partLoadError}
        </p>
      )}

      {currentPart && currentPartSummary && partLoadStatus === 'ready' && (
        <div className={styles.summary} data-testid="part-summary">
          <div className={styles.summaryHeader}>
            <span className={styles.readyDot} />
            <span className={styles.summaryName}>{currentPart}</span>
          </div>
          <p className={styles.summaryNote}>
            Part loaded. Every analysis (Full Analysis, Draft, Undercuts, Parting Line, Core/Cavity) always
            covers the complete imported model -- all {currentPartSummary.solid_count} solid
            {currentPartSummary.solid_count === 1 ? '' : 's'}, {currentPartSummary.face_count} faces, and{' '}
            {currentPartSummary.edge_count} edges. Clicking or highlighting a face in the viewport is for
            inspection only and never narrows what gets analyzed.
          </p>
          <dl className={styles.summaryGrid}>
            <div>
              <dt>Faces</dt>
              <dd>{currentPartSummary.face_count}</dd>
            </div>
            <div>
              <dt>Edges</dt>
              <dd>{currentPartSummary.edge_count}</dd>
            </div>
            <div>
              <dt>Solids</dt>
              <dd>{currentPartSummary.solid_count}</dd>
            </div>
            <div>
              <dt>Bounding box</dt>
              <dd>
                {currentPartSummary.bounding_box.dimensions_mm.map((v) => Math.round(v)).join(' × ')} mm
              </dd>
            </div>
          </dl>
          {currentPartSummary.warnings.length > 0 && (
            <ul className={styles.warnings}>
              {currentPartSummary.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {otherParts.length > 0 && (
        <div className={styles.recent}>
          <h3 className={styles.recentTitle}>Available parts</h3>
          <ul className={styles.recentList}>
            {otherParts.map((name) => (
              <li key={name}>
                <button
                  type="button"
                  className={styles.recentButton}
                  disabled={isBusy}
                  onClick={() => void loadExistingPart(name)}
                >
                  {name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
