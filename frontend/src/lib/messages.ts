import { ApiError, type DocumentInfo } from "@/lib/api";

const ERROR_TEXT: Record<string, string> = {
  session_required: "Your session has expired. Reload the page to start a new one.",
  too_large: "Files can be up to 20 MB. Try splitting or compressing the PDF.",
  unsupported_type: "Only PDF files are supported right now.",
  empty_file: "This file is empty.",
  session_document_limit: "This session can hold up to 10 documents.",
  document_not_ready: "A selected document is not ready yet.",
  turn_in_progress: "Another answer is still being generated. Wait for it to finish.",
  document_in_use:
    "An answer is still being written from this document. Remove it when the answer is finished.",
  duplicate_request: "This question was already sent.",
};

const INGESTION_ERROR_TEXT: Record<string, string> = {
  encrypted: "This PDF is password-protected. Remove the password and upload it again.",
  damaged: "We couldn't read this PDF; it may be damaged. Re-export or re-save it and try again.",
  too_many_pages: "PDFs can have up to 300 pages. Try splitting it.",
  empty: "We couldn't find any text in this PDF.",
  // The UI only sees this code once the automatic retries are exhausted.
  embedding_unavailable: "Processing is temporarily unavailable. Try again later.",
};

const GENERIC_INGESTION_ERROR = "Something went wrong while processing this file.";

export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "The request failed. Check your connection and try again.";
  }
  const known: string | undefined = ERROR_TEXT[error.code];
  if (known !== undefined) {
    return known;
  }
  return error.message !== error.code ? error.message : "Something went wrong. Try again.";
}

export function describeIngestionError(code: string | null): string {
  return (code !== null ? INGESTION_ERROR_TEXT[code] : undefined) ?? GENERIC_INGESTION_ERROR;
}

export type StatusTone = "ok" | "warn" | "bad";

export interface DocumentStatus {
  word: string;
  tone: StatusTone;
  detail: string | null;
  progress: { value: number; max: number } | null;
}

export function documentStatus(document: DocumentInfo): DocumentStatus {
  switch (document.state) {
    case "queued":
      return { word: "Queued", tone: "warn", detail: null, progress: null };
    case "processing": {
      const word: string = document.progress?.stage === "publishing" ? "Finishing" : "Indexing";
      if (document.progress === null) {
        return { word, tone: "warn", detail: null, progress: null };
      }
      const { done, total } = document.progress;
      return {
        word,
        tone: "warn",
        detail: `${Math.round((done / Math.max(total, 1)) * 100)}%`,
        progress: { value: done, max: total },
      };
    }
    case "ready":
      return {
        word: "Ready",
        tone: "ok",
        detail:
          document.page_count === null
            ? null
            : `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}`,
        progress: null,
      };
    case "failed":
      return {
        word: "Failed",
        tone: "bad",
        detail: describeIngestionError(document.error_code),
        progress: null,
      };
  }
}
