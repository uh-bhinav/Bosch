import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// jsdom has no ResizeObserver -- ViewportEngine.mount() uses one whenever a
// real WebGLRenderer exists. jsdom also has no WebGL context, so
// ViewportEngine.mount() already degrades to a headless (no-renderer) mode
// on its own; this stub exists only so importing the class never throws in
// case a future change constructs a ResizeObserver eagerly.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

afterEach(() => {
  cleanup();
});
