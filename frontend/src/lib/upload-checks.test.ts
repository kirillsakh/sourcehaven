import { describe, expect, it } from "vitest";

import type { SessionLimits } from "@/lib/api";
import { checkFiles } from "@/lib/upload-checks";

const limits: SessionLimits = {
  max_documents: 10,
  max_pages_per_document: 300,
  max_upload_bytes: 20 * 1024 * 1024,
  max_question_chars: 2000,
};

function file(name: string, type: string, size = 10): File {
  const created = new File(["x"], name, { type });
  // Avoids allocating megabytes of data just to exceed the size limit.
  Object.defineProperty(created, "size", { value: size });
  return created;
}

function pdf(name: string, size = 10): File {
  return file(name, "application/pdf", size);
}

function png(name: string): File {
  return file(name, "image/png");
}

describe("checkFiles", () => {
  it("accepts PDFs and rejects other types and empty files", () => {
    const results = checkFiles([pdf("a.pdf"), png("b.png"), pdf("c.pdf", 0)], limits, 2);
    expect(results.map((r) => r.ok)).toEqual([true, false, false]);
    expect(results[1]).toMatchObject({ ok: false, reason: "Only PDF files are supported right now." });
    expect(results[2]).toMatchObject({ ok: false, reason: "This file is empty." });
  });

  it("accepts by extension when the browser reports no MIME type", () => {
    expect(checkFiles([file("x.PDF", "")], limits, 0)[0].ok).toBe(true);
  });

  it("rejects files over the size limit", () => {
    expect(checkFiles([pdf("big.pdf", 20 * 1024 * 1024 + 1)], limits, 0)[0]).toMatchObject({
      ok: false,
      reason: "Files can be up to 20 MB. Try splitting or compressing the PDF.",
    });
    expect(checkFiles([pdf("edge.pdf", 20 * 1024 * 1024)], limits, 0)[0].ok).toBe(true);
  });

  it("rejects files beyond the free slots without letting invalid files use them", () => {
    const results = checkFiles([pdf("1.pdf"), png("x.png"), pdf("2.pdf"), pdf("3.pdf")], limits, 9);
    expect(results.map((r) => r.ok)).toEqual([true, false, false, false]);
    expect(checkFiles([pdf("1.pdf"), pdf("2.pdf")], limits, 9)[1]).toMatchObject({
      reason: "This session can hold up to 10 documents.",
    });
  });

  it("keeps the input order and file references", () => {
    const files: File[] = [pdf("a.pdf"), png("b.png")];
    expect(checkFiles(files, limits, 0).map((r) => r.file)).toEqual(files);
  });
});
