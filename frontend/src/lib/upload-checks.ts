import type { SessionLimits } from "@/lib/api";

export type FileCheck = { file: File; ok: true } | { file: File; ok: false; reason: string };

const BYTES_PER_MB = 1024 * 1024;

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

function rejectionReason(file: File, limits: SessionLimits): string | null {
  if (!isPdf(file)) {
    return "Only PDF files are supported right now.";
  }
  if (file.size === 0) {
    return "This file is empty.";
  }
  if (file.size > limits.max_upload_bytes) {
    return `Files can be up to ${Math.round(limits.max_upload_bytes / BYTES_PER_MB)} MB. Try splitting or compressing the PDF.`;
  }
  return null;
}

/**
 * Check dropped or picked files before any upload request is made.
 *
 * Rejected files never consume a document slot; accepted files do, in order, until the session
 * limit is reached.
 *
 * Args:
 *   files: Files in the order the user supplied them.
 *   limits: Session limits reported by the server.
 *   usedSlots: Documents already in the session.
 *
 * Returns:
 *   One result per file, in input order.
 */
export function checkFiles(
  files: readonly File[],
  limits: SessionLimits,
  usedSlots: number,
): FileCheck[] {
  let accepted = 0;
  return files.map((file): FileCheck => {
    const reason: string | null = rejectionReason(file, limits);
    if (reason !== null) {
      return { file, ok: false, reason };
    }
    if (usedSlots + accepted >= limits.max_documents) {
      return {
        file,
        ok: false,
        reason: `This session can hold up to ${limits.max_documents} documents.`,
      };
    }
    accepted += 1;
    return { file, ok: true };
  });
}
