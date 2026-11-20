import type { DocumentInfo } from "@/lib/api";

export type SelectAllState = "all" | "some" | "none";

export function readySelectedIds(
  documents: readonly DocumentInfo[],
  selected: ReadonlySet<string>,
): string[] {
  return documents
    .filter((document) => document.state === "ready" && selected.has(document.id))
    .map((document) => document.id);
}

export function selectAllState(
  documents: readonly DocumentInfo[],
  selected: ReadonlySet<string>,
): SelectAllState {
  const readyTotal: number = documents.filter((document) => document.state === "ready").length;
  const chosen: number = readySelectedIds(documents, selected).length;
  if (chosen === 0) {
    return "none";
  }
  return chosen === readyTotal ? "all" : "some";
}

/** Documents that are queued or processing, in list order. */
export function indexingDocuments(documents: readonly DocumentInfo[]): DocumentInfo[] {
  return documents.filter(
    (document: DocumentInfo) => document.state === "queued" || document.state === "processing",
  );
}

/**
 * Describe which documents a question would be answered from, or why none can be asked about.
 *
 * Args:
 *   readySelected: Ready documents currently selected.
 *   readyTotal: Ready documents in the session.
 *   indexing: Documents still queued or processing.
 *
 * Returns:
 *   The line shown under the composer.
 */
export function scopeLine(readySelected: number, readyTotal: number, indexing: number): string {
  if (readySelected > 0) {
    return `Answering from ${readySelected} of ${readyTotal} ${readyTotal === 1 ? "document" : "documents"}`;
  }
  if (readyTotal > 0) {
    return "Select at least one ready document to ask a question.";
  }
  if (indexing > 0) {
    return indexing === 1
      ? "Your document is still being indexed."
      : "Your documents are still being indexed.";
  }
  return "Add a PDF to ask a question.";
}
