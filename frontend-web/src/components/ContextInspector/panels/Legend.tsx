/**
 * F7: one small, consistent legend key -- every meaningful mesh overlay
 * (Draft, Undercuts, Core/Cavity, Parting Line) renders through this same
 * component so a colored swatch always means the same kind of thing across
 * tools (F7 §11: "the user should never have to guess what a colored thing
 * represents"). Colors are passed in as CSS color strings (the `--vis-*`
 * tokens, or a backend-supplied hex) -- this component only lays them out.
 */

import styles from './Legend.module.css';

export interface LegendItem {
  color: string;
  label: string;
  count?: number;
}

export function Legend({ items }: { items: LegendItem[] }) {
  if (items.length === 0) return null;
  return (
    <ul className={styles.legend} data-testid="legend">
      {items.map((item) => (
        <li key={item.label} className={styles.item}>
          <span className={styles.swatch} style={{ background: item.color }} />
          <span className={styles.label}>{item.label}</span>
          {item.count !== undefined && <span className={styles.count}>{item.count}</span>}
        </li>
      ))}
    </ul>
  );
}
