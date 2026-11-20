import { describe, expect, it } from "vitest";

import type { DocumentInfo } from "@/lib/api";
import { indexingDocuments, readySelectedIds, scopeLine, selectAllState } from "@/lib/selection";

function doc(id: string, state: DocumentInfo["state"]): DocumentInfo {
  return {
    id,
    display_name: `${id}.pdf`,
    state,
    error_code: null,
    page_count: null,
    progress: null,
    created_at: "2026-11-20T10:00:00Z",
  };
}

const ready = (id: string): DocumentInfo => doc(id, "ready");
const processing = (id: string): DocumentInfo => doc(id, "processing");

describe("selectAllState", () => {
  it("considers only ready documents", () => {
    expect(selectAllState([ready("a"), ready("b"), processing("c")], new Set(["a", "b"]))).toBe("all");
    expect(selectAllState([ready("a"), ready("b")], new Set(["a"]))).toBe("some");
    expect(selectAllState([ready("a")], new Set())).toBe("none");
    expect(selectAllState([processing("c")], new Set())).toBe("none");
  });

  it("ignores selected ids that are not ready documents", () => {
    expect(selectAllState([ready("a")], new Set(["c"]))).toBe("none");
  });
});

describe("readySelectedIds", () => {
  it("returns selected ready documents in list order", () => {
    expect(readySelectedIds([ready("a"), processing("c")], new Set(["a", "c"]))).toEqual(["a"]);
    expect(readySelectedIds([ready("b"), ready("a")], new Set(["a", "b"]))).toEqual(["b", "a"]);
  });
});

describe("scopeLine", () => {
  it("describes the answering scope", () => {
    expect(scopeLine(2, 3, 0)).toBe("Answering from 2 of 3 documents");
    expect(scopeLine(1, 1, 0)).toBe("Answering from 1 of 1 document");
    expect(scopeLine(0, 3, 0)).toBe("Select at least one ready document to ask a question.");
    expect(scopeLine(0, 0, 0)).toBe("Add a PDF to ask a question.");
  });

  it("says documents are still being indexed while none is ready", () => {
    expect(scopeLine(0, 0, 1)).toBe("Your document is still being indexed.");
    expect(scopeLine(0, 0, 2)).toBe("Your documents are still being indexed.");
  });

  it("keeps the ready-document lines while others are still indexed", () => {
    expect(scopeLine(1, 1, 2)).toBe("Answering from 1 of 1 document");
    expect(scopeLine(0, 1, 2)).toBe("Select at least one ready document to ask a question.");
  });
});

describe("indexingDocuments", () => {
  it("returns queued and processing documents only", () => {
    const failed: DocumentInfo = doc("f", "failed");
    const queued: DocumentInfo = doc("q", "queued");

    expect(indexingDocuments([ready("a"), processing("c"), failed, queued])).toEqual([
      processing("c"),
      queued,
    ]);
  });
});
