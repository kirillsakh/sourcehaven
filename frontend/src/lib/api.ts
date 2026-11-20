import type { components } from "@/lib/api-types";
import { parseSseStream } from "@/lib/sse";

type Schemas = components["schemas"];

export type SessionInfo = Schemas["SessionResponse"];
export type SessionLimits = Schemas["SessionLimits"];
export type Progress = Schemas["Progress"];
export type TurnSource = Schemas["TurnSourceResponse"];
export type Conversation = Schemas["ConversationResponse"];

export type DocumentState = "queued" | "processing" | "ready" | "failed";

export interface DocumentInfo extends Omit<Schemas["DocumentResponse"], "state"> {
  state: DocumentState;
}

export interface QuestionInput {
  clientRequestId: string;
  question: string;
  documentIds: string[];
}

export type TurnEvent =
  | { type: "turn"; turnId: string }
  | { type: "progress"; stage: string }
  | { type: "delta"; text: string }
  | { type: "sources"; sources: TurnSource[]; invalidCitationLabels: string[] }
  | { type: "done" }
  | { type: "error"; status: string; code: string; message: string; retryable: boolean };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message?: string) {
    super(message ?? code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "unknown_error";
  let message: string | undefined;
  try {
    const body: unknown = await response.json();
    if (isRecord(body)) {
      if (typeof body.code === "string") {
        code = body.code;
      }
      if (typeof body.message === "string") {
        message = body.message;
      }
    }
  } catch {
    // A non-JSON error body (for example a proxy error page) keeps the generic code.
  }
  return new ApiError(response.status, code, message);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

function jsonBody(payload: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

export function createSession(): Promise<SessionInfo> {
  return requestJson<SessionInfo>("/api/session", { method: "POST" });
}

export async function listDocuments(signal?: AbortSignal): Promise<DocumentInfo[]> {
  return requestJson<DocumentInfo[]>("/api/documents", { signal });
}

export function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file);
  return requestJson<DocumentInfo>("/api/documents", { method: "POST", body: form });
}

export async function createConversation(): Promise<string> {
  const created = await requestJson<Schemas["ConversationCreated"]>("/api/conversations", {
    method: "POST",
  });
  return created.id;
}

export function getConversation(conversationId: string): Promise<Conversation> {
  return requestJson<Conversation>(`/api/conversations/${encodeURIComponent(conversationId)}`);
}

function toTurnEvent(event: string, data: unknown): TurnEvent | null {
  if (!isRecord(data)) {
    return null;
  }
  switch (event) {
    case "turn":
      return typeof data.turn_id === "string" ? { type: "turn", turnId: data.turn_id } : null;
    case "progress":
      return typeof data.stage === "string" ? { type: "progress", stage: data.stage } : null;
    case "delta":
      return typeof data.text === "string" ? { type: "delta", text: data.text } : null;
    case "sources":
      return Array.isArray(data.sources)
        ? {
            type: "sources",
            sources: data.sources as TurnSource[],
            invalidCitationLabels: Array.isArray(data.invalid_citation_labels)
              ? data.invalid_citation_labels.filter(
                  (label): label is string => typeof label === "string",
                )
              : [],
          }
        : null;
    case "done":
      return { type: "done" };
    case "error":
      return {
        type: "error",
        status: typeof data.status === "string" ? data.status : "failed",
        code: typeof data.code === "string" ? data.code : "unknown_error",
        message: typeof data.message === "string" ? data.message : "",
        retryable: data.retryable === true,
      };
    default:
      return null;
  }
}

/**
 * Ask a question and stream the turn's events.
 *
 * Rejects with `ApiError` when the server refuses the request before streaming starts. Stream
 * failures after that are reported as an `error` event or by the generator throwing.
 */
export async function* streamQuestion(
  conversationId: string,
  input: QuestionInput,
  signal: AbortSignal,
): AsyncGenerator<TurnEvent> {
  const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/turns`, {
    credentials: "same-origin",
    signal,
    ...jsonBody({
      client_request_id: input.clientRequestId,
      kind: "question",
      question: input.question,
      document_ids: input.documentIds,
    }),
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.body === null) {
    throw new ApiError(response.status, "empty_stream");
  }
  for await (const { event, data } of parseSseStream(response.body)) {
    const turnEvent = toTurnEvent(event, data);
    if (turnEvent !== null) {
      yield turnEvent;
    }
  }
}
