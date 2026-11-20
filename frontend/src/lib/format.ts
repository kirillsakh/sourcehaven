export interface TextSegment {
  text: string;
  /** Set when the segment is a citation marker such as `[S1]`; holds its label, `S1`. */
  label: string | null;
}

export function formatPages(start: number, end: number): string {
  return start === end ? `page ${start}` : `pages ${start}–${end}`;
}

/**
 * Split answer text into plain segments and every citation marker such as `[S1]`.
 *
 * Whether a marker matches a source is left to the caller. The text is never interpreted as
 * markup.
 */
export function splitCitations(text: string): TextSegment[] {
  const segments: TextSegment[] = [];
  let plainStart = 0;
  for (const match of text.matchAll(/\[(S\d+)\]/g)) {
    const label = match[1];
    if (match.index > plainStart) {
      segments.push({ text: text.slice(plainStart, match.index), label: null });
    }
    segments.push({ text: match[0], label });
    plainStart = match.index + match[0].length;
  }
  if (plainStart < text.length) {
    segments.push({ text: text.slice(plainStart), label: null });
  }
  return segments;
}

export function newRequestId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // crypto.randomUUID exists only in secure contexts; plain-HTTP hosts need this fallback.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
