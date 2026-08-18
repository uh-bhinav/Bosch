/**
 * One diagnostics group, rendered with F0's three-tier progressive
 * disclosure: the group header (always visible, collapsed by default) +
 * Tier 1 once expanded (always shown), Tier 2 behind a "Details" toggle,
 * Tier 3 behind a separate "Advanced" toggle. No giant default table --
 * every group starts collapsed to a one-line status summary.
 *
 * Clicking a face-list row (`kind: 'faceList'`) selects those faces via
 * the SAME shared `selectedFaceIds` action the viewport's own click-to-
 * pick already uses (`useAnalysisStore`) -- this is the only viewport
 * interaction diagnostics performs, and it goes through existing shared
 * state, never a second selection mechanism or a second viewer.
 */

import { useState } from 'react';
import { useAnalysisStore } from '../../../store/analysisStore';
import type { DiagnosticEntry, DiagnosticGroupModel, DiagnosticTone } from '../../../diagnostics/types';
import styles from './DiagnosticGroupCard.module.css';

function worstTone(entries: DiagnosticEntry[]): DiagnosticTone {
  const order: DiagnosticTone[] = ['bad', 'warn', 'ok', 'neutral'];
  const present = new Set(entries.map((e) => (e.kind === 'raw' ? undefined : e.tone)).filter(Boolean) as DiagnosticTone[]);
  for (const tone of order) {
    if (present.has(tone)) return tone;
  }
  return 'neutral';
}

function EntryRow({ entry }: { entry: DiagnosticEntry }) {
  const setSelectedFaceIds = useAnalysisStore((s) => s.setSelectedFaceIds);

  if (entry.kind === 'raw') {
    return (
      <div className={styles.rawRow} title={entry.tooltip}>
        <div className={styles.rawLabel}>{entry.label}</div>
        <pre className={styles.rawBlock} data-testid={`raw-${entry.label}`}>
          {JSON.stringify(entry.json, null, 2)}
        </pre>
      </div>
    );
  }

  if (entry.kind === 'faceList') {
    return (
      <div className={styles.row} title={entry.tooltip}>
        <span className={styles.rowLabel}>{entry.label}</span>
        {entry.faceIds.length === 0 ? (
          <span className={styles.rowValue}>None</span>
        ) : (
          <button
            type="button"
            className={styles.faceListButton}
            data-tone={entry.tone ?? 'neutral'}
            onClick={() => setSelectedFaceIds(entry.faceIds)}
            title={`Select ${entry.faceIds.length} face(s) in the viewport`}
          >
            {entry.faceIds.length} face{entry.faceIds.length === 1 ? '' : 's'} — click to select
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={styles.row} title={entry.tooltip}>
      <span className={styles.rowLabel}>{entry.label}</span>
      <span className={styles.rowValue} data-tone={entry.tone ?? 'neutral'}>
        {entry.value}
      </span>
    </div>
  );
}

export function DiagnosticGroupCard({ group }: { group: DiagnosticGroupModel }) {
  const [expanded, setExpanded] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const tone = worstTone(group.tier1);

  return (
    <div className={styles.card} data-testid={`diagnostic-group-${group.id}`}>
      <button
        type="button"
        className={styles.header}
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className={styles.statusDot} data-tone={tone} />
        <span className={styles.title}>{group.title}</span>
        <span className={styles.chevron}>{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded && (
        <div className={styles.body}>
          {group.tier1.length > 0 && (
            <div className={styles.tier1}>
              {group.tier1.map((entry, i) => (
                <EntryRow key={i} entry={entry} />
              ))}
            </div>
          )}

          {group.tier2.length > 0 && (
            <div className={styles.tierSection}>
              <button type="button" className={styles.tierToggle} onClick={() => setShowDetails((v) => !v)} aria-expanded={showDetails}>
                Details {showDetails ? '▾' : '▸'}
              </button>
              {showDetails && (
                <div className={styles.tierContent} data-testid={`diagnostic-details-${group.id}`}>
                  {group.tier2.map((entry, i) => (
                    <EntryRow key={i} entry={entry} />
                  ))}
                </div>
              )}
            </div>
          )}

          {group.tier3.length > 0 && (
            <div className={styles.tierSection}>
              <button type="button" className={styles.tierToggle} onClick={() => setShowAdvanced((v) => !v)} aria-expanded={showAdvanced}>
                Advanced {showAdvanced ? '▾' : '▸'}
              </button>
              {showAdvanced && (
                <div className={styles.tierContent} data-testid={`diagnostic-advanced-${group.id}`}>
                  {group.tier3.map((entry, i) => (
                    <EntryRow key={i} entry={entry} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
