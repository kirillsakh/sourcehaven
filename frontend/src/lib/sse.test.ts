import { describe, expect, it } from "vitest";

import { parseSseStream, type SseEvent } from "@/lib/sse";

const encoder = new TextEncoder();

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      }
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of parseSseStream(body)) {
    events.push(event);
  }
  return events;
}

describe("parseSseStream", () => {
  it("yields events split across chunks", async () => {
    const events = await collect(streamOf(['event: delta\nda', 'ta: {"text":"Hello"}\n\n']));
    expect(events).toEqual([{ event: "delta", data: { text: "Hello" } }]);
  });

  it("handles a multibyte character split between chunks", async () => {
    const bytes = encoder.encode('event: delta\ndata: {"text":"—"}\n\n');
    const cut = bytes.indexOf(0xe2) + 1;
    expect(cut).toBeGreaterThan(0);
    const events = await collect(streamOf([bytes.slice(0, cut), bytes.slice(cut)]));
    expect(events).toEqual([{ event: "delta", data: { text: "—" } }]);
  });

  it("ignores comment keep-alives", async () => {
    expect(await collect(streamOf([": ping\n\n"]))).toEqual([]);
  });

  it("joins multi-line data", async () => {
    const events = await collect(streamOf(['event: sources\ndata: {"a":\ndata: 1}\n\n']));
    expect(events).toEqual([{ event: "sources", data: { a: 1 } }]);
  });

  it("handles CRLF line endings split between chunks", async () => {
    const events = await collect(
      streamOf(["event: done\r", '\ndata: {"status":"complete"}\r', "\n\r", "\n"]),
    );
    expect(events).toEqual([{ event: "done", data: { status: "complete" } }]);
  });

  it("ignores a keep-alive between events", async () => {
    const events = await collect(
      streamOf(['event: a\ndata: {"n":1}\n\n: ping\n\nevent: b\ndata: {"n":2}\n\n']),
    );
    expect(events).toEqual([
      { event: "a", data: { n: 1 } },
      { event: "b", data: { n: 2 } },
    ]);
  });
});
