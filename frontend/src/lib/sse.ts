export interface SseEvent {
  event: string;
  data: unknown;
}

const DEFAULT_EVENT = "message";

function parseData(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

/**
 * Parse a Server-Sent Events byte stream into events.
 *
 * Chunks may be split anywhere, including inside a multibyte UTF-8 character or between the
 * `\r` and `\n` of a line ending. Comment lines (keep-alives) are ignored, multi-line `data:`
 * fields are joined with `\n`, and the joined data is parsed as JSON (raw text if it is not JSON).
 * An event still incomplete when the stream ends is dropped, as the SSE specification requires.
 */
export async function* parseSseStream(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let eventName = DEFAULT_EVENT;
  let dataLines: string[] = [];
  let atStart = true;

  const applyLine = (line: string): SseEvent | null => {
    if (line === "") {
      const dispatched: SseEvent | null =
        dataLines.length > 0
          ? { event: eventName, data: parseData(dataLines.join("\n")) }
          : null;
      eventName = DEFAULT_EVENT;
      dataLines = [];
      return dispatched;
    }
    if (line.startsWith(":")) {
      return null;
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }
    if (field === "event") {
      eventName = value === "" ? DEFAULT_EVENT : value;
    } else if (field === "data") {
      dataLines.push(value);
    }
    return null;
  };

  // Locates the next complete line. A trailing "\r" is held back until the next chunk shows
  // whether it is the first half of "\r\n".
  const nextTerminatorEnd = (text: string): { lineEnd: number; next: number } | null => {
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (char === "\n") {
        return { lineEnd: index, next: index + 1 };
      }
      if (char === "\r") {
        if (index + 1 === text.length) {
          return null;
        }
        return { lineEnd: index, next: text[index + 1] === "\n" ? index + 2 : index + 1 };
      }
    }
    return null;
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (atStart && buffer.length > 0) {
        buffer = buffer.startsWith("﻿") ? buffer.slice(1) : buffer;
        atStart = false;
      }
      if (done && buffer.endsWith("\r")) {
        buffer += "\n";
      }
      for (let found = nextTerminatorEnd(buffer); found !== null; found = nextTerminatorEnd(buffer)) {
        const line = buffer.slice(0, found.lineEnd);
        buffer = buffer.slice(found.next);
        const dispatched = applyLine(line);
        if (dispatched !== null) {
          yield dispatched;
        }
      }
      if (done) {
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}
