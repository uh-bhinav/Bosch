/**
 * Triggers a real browser download for an in-memory `Blob` -- the standard
 * client-side pattern for a POST-originated binary response (a plain
 * `<a href>` only ever GETs). Creates a temporary object URL, clicks a
 * detached anchor, then revokes the URL -- nothing is appended to the
 * document, so this has no visible side effect beyond the browser's own
 * save/download UI.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
