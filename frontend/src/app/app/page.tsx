"use client";

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";

import { TurnView, type TurnViewModel } from "@/app/app/turn-view";
import {
  ApiError,
  createConversation,
  createSession,
  getConversation,
  listDocuments,
  streamQuestion,
  uploadDocument,
  type Conversation,
  type DocumentInfo,
  type SessionLimits,
  type TurnEvent,
} from "@/lib/api";
import { newRequestId } from "@/lib/format";

const POLL_INTERVAL_MS = 2000;
const MAX_PARALLEL_UPLOADS = 3;
const CONVERSATION_STORAGE_KEY = "sourcehaven.conversation";

const ERROR_TEXT: Record<string, string> = {
  session_required: "Your session has expired. Reload the page to start a new one.",
  too_large: "The file is larger than the upload limit.",
  unsupported_type: "Only PDF files are supported.",
  empty_file: "The file is empty.",
  session_document_limit: "You have reached the document limit for this session.",
  document_not_ready: "A selected document is not ready yet.",
  turn_in_progress: "Another answer is still being generated. Wait for it to finish.",
  duplicate_request: "This question was already sent.",
};

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return ERROR_TEXT[error.code] ?? (error.message === error.code ? error.code : error.message);
  }
  return "The request failed. Check your connection and try again.";
}

function readStoredConversation(): string | null {
  try {
    return window.sessionStorage.getItem(CONVERSATION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeConversation(conversationId: string | null): void {
  try {
    if (conversationId === null) {
      window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
    } else {
      window.sessionStorage.setItem(CONVERSATION_STORAGE_KEY, conversationId);
    }
  } catch {
    // Without storage the conversation is simply not restored after a reload.
  }
}

function turnsFromConversation(conversation: Conversation): TurnViewModel[] {
  return conversation.turns.map((turn) => ({
    key: turn.id,
    status: turn.status,
    question: turn.question ?? "",
    text: turn.text,
    sources: turn.sources,
    invalidCitationLabels: [],
    errorMessage: null,
    retryable: false,
  }));
}

function applyEvent(turn: TurnViewModel, event: TurnEvent): TurnViewModel {
  switch (event.type) {
    case "delta":
      return { ...turn, text: turn.text + event.text };
    case "sources":
      return {
        ...turn,
        sources: event.sources,
        invalidCitationLabels: event.invalidCitationLabels,
      };
    case "done":
      return { ...turn, status: "complete" };
    case "error":
      return {
        ...turn,
        status: event.status,
        errorMessage: event.message !== "" ? event.message : event.code,
        retryable: event.retryable,
      };
    default:
      return turn;
  }
}

function isActive(document: DocumentInfo): boolean {
  return document.state === "queued" || document.state === "processing";
}

function DocumentRow({
  document,
  checked,
  onToggle,
}: {
  document: DocumentInfo;
  checked: boolean;
  onToggle: (id: string) => void;
}): ReactElement {
  const ready = document.state === "ready";
  return (
    <li>
      <label>
        <input
          type="checkbox"
          checked={checked}
          disabled={!ready}
          onChange={() => onToggle(document.id)}
        />
        <span>
          {document.display_name} <span className={`badge ${document.state}`}>{document.state}</span>
        </span>
      </label>
      {isActive(document) && document.progress !== null && (
        <div className="doc-note">
          <progress value={document.progress.done} max={Math.max(document.progress.total, 1)} />
          <span className="muted">
            {document.progress.stage ?? "working"} {document.progress.done}/{document.progress.total}
          </span>
        </div>
      )}
      {document.state === "failed" && (
        <div className="doc-note error">Failed: {document.error_code ?? "unknown_error"}</div>
      )}
      {ready && document.page_count !== null && (
        <div className="doc-note muted">{document.page_count} pages</div>
      )}
    </li>
  );
}

export default function AppPage(): ReactElement {
  const [limits, setLimits] = useState<SessionLimits | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [uploading, setUploading] = useState<number>(0);
  const [turns, setTurns] = useState<TurnViewModel[]>([]);
  const [question, setQuestion] = useState<string>("");
  const [askError, setAskError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<boolean>(false);

  const started = useRef<boolean>(false);
  const knownReady = useRef<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const conversationRef = useRef<string | null>(null);

  const mergeDocuments = useCallback((incoming: DocumentInfo[], replaceAll: boolean) => {
    setDocuments((previous) => {
      const merged = new Map<string, DocumentInfo>(
        replaceAll ? [] : previous.map((doc) => [doc.id, doc]),
      );
      for (const doc of incoming) {
        merged.set(doc.id, doc);
      }
      return Array.from(merged.values()).sort((a, b) => a.created_at.localeCompare(b.created_at));
    });
    const newlyReady: string[] = incoming
      .filter((doc) => doc.state === "ready" && !knownReady.current.has(doc.id))
      .map((doc) => doc.id);
    if (newlyReady.length > 0) {
      for (const id of newlyReady) {
        knownReady.current.add(id);
      }
      setSelected((previous) => new Set([...previous, ...newlyReady]));
    }
  }, []);

  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;
    void (async () => {
      try {
        const session = await createSession();
        setLimits(session.limits);
        mergeDocuments(await listDocuments(), true);
        const stored = readStoredConversation();
        if (stored !== null) {
          try {
            const conversation = await getConversation(stored);
            conversationRef.current = conversation.id;
            setTurns(turnsFromConversation(conversation));
          } catch {
            storeConversation(null);
          }
        }
      } catch (error) {
        setStartError(describeError(error));
      }
    })();
  }, [mergeDocuments]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const hasActiveDocuments: boolean = documents.some(isActive);

  useEffect(() => {
    if (!hasActiveDocuments) {
      return;
    }
    const controller = new AbortController();
    let timer: number | undefined;
    // Each poll is scheduled only after the previous one settles, so requests never overlap.
    const poll = async (): Promise<void> => {
      try {
        // Merge instead of replace: an upload that finished after this request began must stay
        // listed.
        mergeDocuments(await listDocuments(controller.signal), false);
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        if (error instanceof ApiError && error.code === "session_required") {
          setPollError(describeError(error));
          return;
        }
      }
      timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };
    timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [hasActiveDocuments, mergeDocuments]);

  async function uploadFiles(files: File[]): Promise<void> {
    const queue: File[] = [...files];
    setUploadErrors([]);
    setUploading((count) => count + files.length);
    const worker = async (): Promise<void> => {
      for (let file = queue.shift(); file !== undefined; file = queue.shift()) {
        try {
          mergeDocuments([await uploadDocument(file)], false);
        } catch (error) {
          setUploadErrors((previous) => [...previous, `${file.name}: ${describeError(error)}`]);
        } finally {
          setUploading((count) => count - 1);
        }
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(MAX_PARALLEL_UPLOADS, files.length) }, () => worker()),
    );
  }

  function toggleDocument(id: string): void {
    setSelected((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) {
        next.add(id);
      }
      return next;
    });
  }

  const updateTurn = useCallback((key: string, change: (turn: TurnViewModel) => TurnViewModel) => {
    setTurns((previous) => previous.map((turn) => (turn.key === key ? change(turn) : turn)));
  }, []);

  async function ask(text: string): Promise<void> {
    const trimmed = text.trim();
    const documentIds: string[] = documents
      .filter((doc) => doc.state === "ready" && selected.has(doc.id))
      .map((doc) => doc.id);
    if (trimmed === "" || documentIds.length === 0 || generating) {
      return;
    }
    setAskError(null);
    setGenerating(true);
    const key: string = newRequestId();
    const controller = new AbortController();
    abortRef.current = controller;
    let streamEnded = false;
    try {
      let activeConversation: string | null = conversationRef.current;
      if (activeConversation === null) {
        activeConversation = await createConversation();
        conversationRef.current = activeConversation;
        storeConversation(activeConversation);
      }
      setTurns((previous) => [
        ...previous,
        {
          key,
          status: "generating",
          question: trimmed,
          text: "",
          sources: [],
          invalidCitationLabels: [],
          errorMessage: null,
          retryable: false,
        },
      ]);
      setQuestion("");
      for await (const event of streamQuestion(
        activeConversation,
        { clientRequestId: key, question: trimmed, documentIds },
        controller.signal,
      )) {
        if (event.type === "done" || event.type === "error") {
          streamEnded = true;
        }
        updateTurn(key, (turn) => applyEvent(turn, event));
      }
      if (!streamEnded) {
        updateTurn(key, (turn) => ({
          ...turn,
          status: "interrupted",
          errorMessage: "The connection ended before the answer was complete.",
        }));
      }
    } catch (error) {
      if (error instanceof ApiError) {
        setTurns((previous) => previous.filter((turn) => turn.key !== key));
        setQuestion(trimmed);
        setAskError(describeError(error));
      } else {
        const stopped = controller.signal.aborted;
        updateTurn(key, (turn) => ({
          ...turn,
          status: "interrupted",
          errorMessage: stopped ? "Stopped." : describeError(error),
        }));
      }
    } finally {
      abortRef.current = null;
      setGenerating(false);
    }
  }

  const readySelected: number = documents.filter(
    (doc) => doc.state === "ready" && selected.has(doc.id),
  ).length;
  const limitReached: boolean = limits !== null && documents.length >= limits.max_documents;
  const maxQuestionChars: number = limits?.max_question_chars ?? 2000;

  if (startError !== null) {
    return (
      <main className="shell">
        <h1>Sourcehaven</h1>
        <p className="error" role="alert">
          {startError}
        </p>
      </main>
    );
  }

  return (
    <main className="shell">
      <header>
        <h1>Sourcehaven</h1>
        <span className="muted">
          Your documents belong to this browser session and are deleted when it expires.
        </span>
      </header>
      <div className="layout">
        <section className="panel" aria-labelledby="documents-heading">
          <h2 id="documents-heading">
            Your documents
            {limits !== null && ` (${documents.length}/${limits.max_documents})`}
          </h2>
          {limits !== null && (
            <p className="muted">
              PDF only, up to {Math.round(limits.max_upload_bytes / (1024 * 1024))} MB and{" "}
              {limits.max_pages_per_document} pages each.
            </p>
          )}
          <input
            type="file"
            accept="application/pdf,.pdf"
            multiple
            disabled={limits === null || limitReached}
            aria-label="Upload PDF documents"
            onChange={(event) => {
              const files: File[] = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (files.length > 0) {
                void uploadFiles(files);
              }
            }}
          />
          {uploading > 0 && <p className="muted">Uploading {uploading}&hellip;</p>}
          {pollError !== null && (
            <p className="error" role="alert">
              {pollError}
            </p>
          )}
          {uploadErrors.map((message, index) => (
            <p key={`${index}:${message}`} className="error" role="alert">
              {message}
            </p>
          ))}
          <ul className="doc-list">
            {documents.map((doc) => (
              <DocumentRow
                key={doc.id}
                document={doc}
                checked={selected.has(doc.id)}
                onToggle={toggleDocument}
              />
            ))}
          </ul>
          {limits !== null && documents.length === 0 && (
            <p className="muted">No documents yet.</p>
          )}
        </section>

        <section className="panel" aria-labelledby="conversation-heading">
          <h2 id="conversation-heading" className="visually-hidden">
            Conversation
          </h2>
          <div aria-live="polite">
            {turns.map((turn) => (
              <TurnView key={turn.key} turn={turn} onRetry={(text) => void ask(text)} />
            ))}
          </div>
          <form
            className="ask"
            onSubmit={(event) => {
              event.preventDefault();
              void ask(question);
            }}
          >
            <label htmlFor="question" className="visually-hidden">
              Question
            </label>
            <textarea
              id="question"
              rows={3}
              maxLength={maxQuestionChars}
              placeholder="Ask about the selected documents…"
              value={question}
              disabled={limits === null}
              onChange={(event) => setQuestion(event.target.value)}
            />
            {askError !== null && (
              <p className="error" role="alert">
                {askError}
              </p>
            )}
            <div className="actions">
              <button
                type="submit"
                className="primary"
                disabled={generating || question.trim() === "" || readySelected === 0}
              >
                Ask
              </button>
              {generating && (
                <button type="button" onClick={() => abortRef.current?.abort()}>
                  Stop
                </button>
              )}
              <span className="muted">
                {readySelected === 0
                  ? "Select a ready document to ask about."
                  : `${readySelected} document${readySelected === 1 ? "" : "s"} selected`}
              </span>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
