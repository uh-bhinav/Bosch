import { useEffect, useRef, useState } from 'react';

/**
 * A real, live-counting elapsed-seconds clock -- used to prove to the user
 * that a long-running backend call (direction search -> parting line ->
 * core/cavity split, "tens to hundreds of seconds" per F0/F3) is still
 * alive, never frozen. Deliberately NOT a fake percentage bar: there is no
 * server-sent progress channel (the backend is stateless, one request per
 * call), so any number implying "38% done" would be fabricated. An honest
 * ticking clock is not.
 */
export function useElapsedSeconds(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      startRef.current = null;
      setSeconds(0);
      return;
    }
    startRef.current = Date.now();
    setSeconds(0);
    const id = window.setInterval(() => {
      setSeconds(Math.floor((Date.now() - (startRef.current ?? Date.now())) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [active]);

  return seconds;
}

/**
 * Rotating, honest stage narration for the Guided run -- reflects the
 * KNOWN, fixed backend pipeline order (`/core-cavity`'s automatic path:
 * direction search, then parting line, then the Boolean solid split; see
 * `backend/geometry/mold_orchestration.py`'s module docstring), not
 * fabricated telemetry. Thresholds are approximate wall-clock buckets, not
 * a claim about exact phase boundaries.
 */
const STAGE_LABELS: readonly [number, string][] = [
  [0, 'Optimizing pull direction…'],
  [20, 'Searching candidate directions…'],
  [60, 'Computing parting line…'],
  [120, 'Splitting core and cavity…'],
];

export function stageLabelForElapsed(seconds: number): string {
  let label = STAGE_LABELS[0][1];
  for (const [threshold, text] of STAGE_LABELS) {
    if (seconds >= threshold) label = text;
  }
  return label;
}
