import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { downloadBlob } from './downloadBlob';

function spyOnObjectUrls() {
  const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url');
  const revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  return { createObjectURLSpy, revokeObjectURLSpy };
}

describe('downloadBlob', () => {
  let createObjectURLSpy: ReturnType<typeof spyOnObjectUrls>['createObjectURLSpy'];
  let revokeObjectURLSpy: ReturnType<typeof spyOnObjectUrls>['revokeObjectURLSpy'];

  beforeEach(() => {
    ({ createObjectURLSpy, revokeObjectURLSpy } = spyOnObjectUrls());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('creates an object URL, clicks a download anchor with it, then revokes it', () => {
    const clickSpy = vi.fn();
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === 'a') el.click = clickSpy;
      return el;
    });

    const blob = new Blob(['%PDF-1.4 fake'], { type: 'application/pdf' });
    downloadBlob(blob, 'Part1_dfm_report.pdf');

    expect(createObjectURLSpy).toHaveBeenCalledWith(blob);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url');
    createElementSpy.mockRestore();
  });

  it('sets the anchor\'s href and download filename correctly', () => {
    let capturedLink: HTMLAnchorElement | null = null;
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === 'a') {
        el.click = vi.fn();
        capturedLink = el as HTMLAnchorElement;
      }
      return el;
    });

    downloadBlob(new Blob(['x']), 'my_report.pdf');

    expect(capturedLink).not.toBeNull();
    expect(capturedLink!.href).toBe('blob:mock-url');
    expect(capturedLink!.download).toBe('my_report.pdf');
    createElementSpy.mockRestore();
  });

  it('revokes the object URL even if the click handler throws', () => {
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === 'a') {
        el.click = () => {
          throw new Error('blocked by a popup blocker');
        };
      }
      return el;
    });

    expect(() => downloadBlob(new Blob(['x']), 'f.pdf')).toThrow('blocked by a popup blocker');
    expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url');
    createElementSpy.mockRestore();
  });
});
