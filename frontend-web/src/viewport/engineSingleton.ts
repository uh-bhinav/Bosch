/**
 * The `ViewportEngine` singleton.
 *
 * A module-level singleton (rather than a React ref owned by `Viewport.tsx`)
 * is the strongest available guarantee for the persistence requirement: the
 * engine's identity does not depend on `Viewport` never being unmounted by
 * some future refactor -- it is simply the same JS object for the lifetime
 * of the page, exactly like `useAnalysisStore`'s own module-level store.
 *
 * `__resetViewportEngineForTests` exists ONLY for test teardown (e.g. a test
 * that wants a fresh camera state) and must never be called from production
 * code.
 */

import { ViewportEngine } from './ViewportEngine';

let instance: ViewportEngine | null = null;

export function getViewportEngine(): ViewportEngine {
  if (!instance) {
    instance = new ViewportEngine();
  }
  return instance;
}

export function __resetViewportEngineForTests(): void {
  instance?.dispose();
  instance = null;
}
