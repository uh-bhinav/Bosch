/**
 * Tool rail: collapsed to icon-width by default, expands on hover or when
 * pinned. Selecting a tool only ever writes `activeTool` to the shared
 * store -- it never touches the viewport (F1's persistence requirement).
 *
 * No per-tool decorative color (F0 §10): every entry uses the same
 * restrained glyph treatment, and only the active entry differs, via the
 * one accent token.
 */

import { useState } from 'react';
import { TOOLS } from '../../domain/types';
import type { ToolId } from '../../domain/types';
import { useAnalysisStore } from '../../store/analysisStore';
import styles from './ToolRail.module.css';

export function ToolRail() {
  const [pinned, setPinned] = useState(false);
  const [hovered, setHovered] = useState(false);
  const activeTool = useAnalysisStore((s) => s.activeTool);
  const setActiveTool = useAnalysisStore((s) => s.setActiveTool);

  const expanded = pinned || hovered;

  const handleSelect = (id: ToolId) => setActiveTool(id);

  return (
    <nav
      className={styles.rail}
      data-expanded={expanded}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      aria-label="Tools"
    >
      <button
        type="button"
        className={styles.pinButton}
        onClick={() => setPinned((p) => !p)}
        aria-pressed={pinned}
        title={pinned ? 'Unpin tool rail' : 'Pin tool rail expanded'}
      >
        {pinned ? '«' : '»'}
      </button>

      <ul className={styles.toolList}>
        {TOOLS.map((tool) => (
          <li key={tool.id}>
            <button
              type="button"
              className={styles.toolButton}
              data-active={tool.id === activeTool}
              onClick={() => handleSelect(tool.id)}
              aria-current={tool.id === activeTool ? 'true' : undefined}
              title={tool.label}
            >
              <span className={styles.glyph}>{tool.glyph}</span>
              <span className={styles.label}>{tool.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
