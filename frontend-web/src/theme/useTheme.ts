/**
 * Light/dark workstation theme (F7). Persisted to `localStorage` and applied
 * as `data-theme` on `<html>`, which `styles/tokens.css`'s `[data-theme='light']`
 * block reads. Defaults to 'dark' -- the workstation's original, unchanged
 * look -- so a first-time visitor sees exactly what F0-F6 already shipped;
 * light is an explicit opt-in, never inferred from the OS.
 */

import { useCallback, useEffect, useState } from 'react';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'dfm-workstation-theme';

function readStoredTheme(): Theme {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === 'light' ? 'light' : 'dark';
}

/** The hex string currently bound to `--viewport-bg` for the active theme -- read once the DOM has the attribute applied. */
export function readViewportBackground(): string {
  if (typeof document === 'undefined') return '#101317';
  const value = getComputedStyle(document.documentElement).getPropertyValue('--viewport-bg').trim();
  return value || '#101317';
}

export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  return { theme, toggleTheme };
}
