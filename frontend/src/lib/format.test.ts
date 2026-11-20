import { describe, expect, it } from "vitest";

import { formatPages, newRequestId, splitCitations } from "@/lib/format";

describe("formatPages", () => {
  it("formats a single page and a range", () => {
    expect(formatPages(4, 4)).toBe("page 4");
    expect(formatPages(9, 10)).toBe("pages 9–10");
  });
});

describe("splitCitations", () => {
  it("marks only known labels and keeps the rest as plain text", () => {
    expect(splitCitations("A [S1] B [S9] C", new Set(["S1"]))).toEqual([
      { text: "A ", label: null },
      { text: "[S1]", label: "S1" },
      { text: " B [S9] C", label: null },
    ]);
  });

  it("returns no segments for empty text", () => {
    expect(splitCitations("", new Set(["S1"]))).toEqual([]);
  });
});

describe("newRequestId", () => {
  it("returns a UUID", () => {
    expect(newRequestId()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});
