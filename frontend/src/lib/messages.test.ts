import { describe, expect, it } from "vitest";

import { ApiError, type DocumentInfo } from "@/lib/api";
import { describeError, describeIngestionError, documentStatus } from "@/lib/messages";

function doc(overrides: Partial<DocumentInfo>): DocumentInfo {
  return {
    id: "d1",
    display_name: "a.pdf",
    state: "queued",
    error_code: null,
    page_count: null,
    progress: null,
    created_at: "2026-11-20T10:00:00Z",
    ...overrides,
  };
}

describe("describeError", () => {
  it("explains why a document in use cannot be removed", () => {
    expect(describeError(new ApiError(409, "document_in_use"))).toBe(
      "An answer is still being written from this document. Remove it when the answer is finished.",
    );
  });

  it("maps known codes to their text", () => {
    expect(describeError(new ApiError(413, "too_large"))).toBe(
      "Files can be up to 20 MB. Try splitting or compressing the PDF.",
    );
    expect(describeError(new ApiError(415, "unsupported_type"))).toBe(
      "Only PDF files are supported right now.",
    );
    expect(describeError(new ApiError(422, "empty_file"))).toBe("This file is empty.");
    expect(describeError(new ApiError(409, "session_document_limit"))).toBe(
      "This session can hold up to 10 documents.",
    );
    expect(describeError(new ApiError(401, "session_required"))).toBe(
      "Your session has expired. Reload the page to start a new one.",
    );
  });

  it("keeps the M1 texts for question errors", () => {
    expect(describeError(new ApiError(409, "document_not_ready"))).toBe(
      "A selected document is not ready yet.",
    );
    expect(describeError(new ApiError(409, "turn_in_progress"))).toBe(
      "Another answer is still being generated. Wait for it to finish.",
    );
    expect(describeError(new ApiError(409, "duplicate_request"))).toBe(
      "This question was already sent.",
    );
  });

  it("falls back to the server message, then to a generic text", () => {
    expect(describeError(new ApiError(500, "mystery"))).toBe("Something went wrong. Try again.");
    expect(describeError(new ApiError(422, "invalid_request", "question: too long"))).toBe(
      "question: too long",
    );
  });

  it("describes a non-API failure as a connection problem", () => {
    expect(describeError(new TypeError("x"))).toBe(
      "The request failed. Check your connection and try again.",
    );
  });
});

describe("describeIngestionError", () => {
  it("explains each failure code", () => {
    expect(describeIngestionError("encrypted")).toBe(
      "This PDF is password-protected. Remove the password and upload it again.",
    );
    expect(describeIngestionError("damaged")).toBe(
      "We couldn't read this PDF; it may be damaged. Re-export or re-save it and try again.",
    );
    expect(describeIngestionError("too_many_pages")).toBe(
      "PDFs can have up to 300 pages. Try splitting it.",
    );
    expect(describeIngestionError("empty")).toBe("We couldn't find any text in this PDF.");
    expect(describeIngestionError("embedding_unavailable")).toBe(
      "Processing is temporarily unavailable. Try again later.",
    );
  });

  it("uses a generic text for internal, unknown and missing codes", () => {
    const generic = "Something went wrong while processing this file.";
    expect(describeIngestionError("internal")).toBe(generic);
    expect(describeIngestionError("brand_new_code")).toBe(generic);
    expect(describeIngestionError(null)).toBe(generic);
  });
});

describe("documentStatus", () => {
  it("describes a queued document", () => {
    expect(documentStatus(doc({ state: "queued" }))).toEqual({
      word: "Queued",
      tone: "warn",
      detail: null,
      progress: null,
    });
  });

  it("describes indexing with a percentage and progress", () => {
    expect(
      documentStatus(doc({ state: "processing", progress: { stage: "embedding", done: 18, total: 30 } })),
    ).toEqual({ word: "Indexing", tone: "warn", detail: "60%", progress: { value: 18, max: 30 } });
  });

  it("calls the publishing stage finishing", () => {
    expect(
      documentStatus(doc({ state: "processing", progress: { stage: "publishing", done: 30, total: 30 } }))
        .word,
    ).toBe("Finishing");
  });

  it("handles processing without progress or with a zero total", () => {
    expect(documentStatus(doc({ state: "processing" }))).toEqual({
      word: "Indexing",
      tone: "warn",
      detail: null,
      progress: null,
    });
    expect(
      documentStatus(doc({ state: "processing", progress: { stage: null, done: 0, total: 0 } })).detail,
    ).toBe("0%");
  });

  it("describes a ready document with its page count", () => {
    expect(documentStatus(doc({ state: "ready", page_count: 14 }))).toEqual({
      word: "Ready",
      tone: "ok",
      detail: "14 pages",
      progress: null,
    });
    expect(documentStatus(doc({ state: "ready", page_count: 1 })).detail).toBe("1 page");
    expect(documentStatus(doc({ state: "ready", page_count: null })).detail).toBeNull();
  });

  it("describes a failed document with the reason", () => {
    const status = documentStatus(doc({ state: "failed", error_code: "encrypted" }));
    expect(status.word).toBe("Failed");
    expect(status.tone).toBe("bad");
    expect(status.detail).toBe(describeIngestionError("encrypted"));
    expect(status.progress).toBeNull();
  });
});
