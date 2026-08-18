/**
 * The workstation shell (F0 §3.1 / F1 spec "ARCHITECTURE").
 *
 * `Viewport` is mounted here, once, as a permanent sibling of
 * `ContextInspector` -- never inside a conditional, never keyed on
 * `activeTool`. This is the structural guarantee the persistence
 * requirement depends on: React only ever re-renders `ContextInspector`
 * (and `StatusStrip`'s tool label) when `activeTool` changes; `Viewport`'s
 * subtree is untouched, so it never unmounts/remounts and its effects
 * never re-run.
 *
 * On mount, this component proves backend connectivity and existing-part
 * discovery (F1 spec, "Backend health / existing-part discovery only where
 * required to prove the shell") -- the only real API calls F1 makes.
 */

import { useEffect } from 'react';
import { TopBar } from '../components/TopBar/TopBar';
import { ToolRail } from '../components/ToolRail/ToolRail';
import { ContextInspector } from '../components/ContextInspector/ContextInspector';
import { StatusStrip } from '../components/StatusStrip/StatusStrip';
import { Viewport } from '../viewport/Viewport';
import { useOverlaySync } from '../viewport/useOverlaySync';
import { useAnalysisStore } from '../store/analysisStore';
import { getHealth, listParts } from '../api/endpoints';
import styles from './WorkstationShell.module.css';

export function WorkstationShell() {
  const setBackendConnectivity = useAnalysisStore((s) => s.setBackendConnectivity);
  const setAvailableParts = useAnalysisStore((s) => s.setAvailableParts);

  // F7: tool-driven viewport overlay/curve/arrow sync -- a side effect only,
  // never a conditional around `<Viewport />` below (F1's persistence
  // requirement).
  useOverlaySync();

  useEffect(() => {
    let cancelled = false;
    setBackendConnectivity('checking');

    getHealth()
      .then(() => {
        if (cancelled) return;
        setBackendConnectivity('online');
        return listParts();
      })
      .then((parts) => {
        if (cancelled || !parts) return;
        setAvailableParts(parts);
      })
      .catch(() => {
        if (!cancelled) setBackendConnectivity('offline');
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className={styles.shell}>
      <TopBar />
      <div className={styles.workArea}>
        <ToolRail />
        <main className={styles.viewportArea}>
          <Viewport />
        </main>
        <ContextInspector />
      </div>
      <StatusStrip />
    </div>
  );
}
