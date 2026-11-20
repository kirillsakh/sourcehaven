// @vitest-environment jsdom
import { act, renderHook, waitFor, type RenderHookResult } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createConversation,
  getConversation,
  streamQuestion,
  type Conversation,
  type SessionLimits,
  type TurnEvent,
  type TurnSource,
} from "@/lib/api";
import { useConversation } from "@/lib/use-conversation";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  streamQuestion: vi.fn(),
}));

const limits: SessionLimits = {
  max_documents: 10,
  max_pages_per_document: 300,
  max_upload_bytes: 20 * 1024 * 1024,
  max_question_chars: 2000,
};

const STORAGE_KEY = "sourcehaven.conversation";

const mockedCreate = vi.mocked(createConversation);
const mockedGet = vi.mocked(getConversation);
const mockedStream = vi.mocked(streamQuestion);

function source(label: string, cited: boolean): TurnSource {
  return {
    label,
    cited,
    document_id: "d1",
    document_name: "annex-b.pdf",
    pages: { start: 2, end: 2 },
    quote: `quote ${label}`,
  };
}

async function* events(...items: TurnEvent[]): AsyncGenerator<TurnEvent> {
  for (const item of items) {
    yield item;
  }
}

type Mounted = RenderHookResult<ReturnType<typeof useConversation>, unknown>;

function mount(): Mounted {
  return renderHook(() => useConversation(limits));
}

beforeEach(() => {
  window.sessionStorage.clear();
  mockedCreate.mockResolvedValue("c1");
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("useConversation", () => {
  it("appends a turn, streams the answer into it and makes it the active turn", async () => {
    mockedStream.mockReturnValue(
      events(
        { type: "turn", turnId: "t1" },
        { type: "progress", stage: "searching" },
        { type: "delta", text: "Hello " },
        { type: "delta", text: "world" },
        { type: "done" },
      ),
    );
    const { result } = mount();

    await act(async () => {
      await result.current.ask("  What is it?  ", ["d1"]);
    });

    expect(result.current.turns).toHaveLength(1);
    expect(result.current.turns[0]).toMatchObject({
      status: "complete",
      question: "What is it?",
      text: "Hello world",
      progressStage: "searching",
      errorMessage: null,
    });
    expect(result.current.activeTurnKey).toBe(result.current.turns[0].key);
    expect(result.current.activeLabel).toBeNull();
    expect(result.current.generating).toBe(false);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe("c1");
    expect(mockedStream.mock.calls[0][0]).toBe("c1");
    expect(mockedStream.mock.calls[0][1]).toMatchObject({
      question: "What is it?",
      documentIds: ["d1"],
    });
  });

  it("clears the question once the turn is created", async () => {
    mockedStream.mockReturnValue(events({ type: "done" }));
    const { result } = mount();
    act(() => {
      result.current.setQuestion("Why?");
    });
    expect(result.current.question).toBe("Why?");

    await act(async () => {
      await result.current.ask("Why?", ["d1"]);
    });

    expect(result.current.question).toBe("");
  });

  it("ignores blank questions and empty selections", async () => {
    const { result } = mount();

    await act(async () => {
      await result.current.ask("   ", ["d1"]);
      await result.current.ask("Question", []);
    });

    expect(mockedCreate).not.toHaveBeenCalled();
    expect(result.current.turns).toEqual([]);
  });

  it("makes the first cited label active when sources arrive, and activate overrides it", async () => {
    mockedStream.mockReturnValue(
      events(
        { type: "delta", text: "Answer [S1] [S2]" },
        {
          type: "sources",
          sources: [source("S3", false), source("S1", true), source("S2", true)],
          invalidCitationLabels: [],
        },
        { type: "done" },
      ),
    );
    const { result } = mount();

    await act(async () => {
      await result.current.ask("Question", ["d1"]);
    });
    expect(result.current.activeLabel).toBe("S1");

    act(() => {
      result.current.activate(result.current.turns[0].key, "S2");
    });
    expect(result.current.activeLabel).toBe("S2");
  });

  it("counts every activation, including a repeat of the same citation", () => {
    const { result } = mount();
    expect(result.current.activationCount).toBe(0);

    act(() => {
      result.current.activate("t1", "S1");
    });
    act(() => {
      result.current.activate("t1", "S1");
    });

    expect(result.current.activeLabel).toBe("S1");
    expect(result.current.activationCount).toBe(2);
  });

  it("does not take over the label when sources arrive for a turn that is no longer active", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    mockedStream.mockImplementation(async function* (): AsyncGenerator<TurnEvent> {
      await gate;
      yield {
        type: "sources",
        sources: [source("S1", true)],
        invalidCitationLabels: ["S9"],
      };
      yield { type: "done" };
    });
    const { result } = mount();
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.ask("Question", ["d1"]);
    });
    await waitFor(() => expect(result.current.turns).toHaveLength(1));

    act(() => {
      result.current.activate("some-other-turn");
    });
    await act(async () => {
      release();
      await pending;
    });

    expect(result.current.activeTurnKey).toBe("some-other-turn");
    expect(result.current.activeLabel).toBeNull();
    expect(result.current.turns[0].invalidCitationLabels).toEqual(["S9"]);
  });

  it("marks the turn interrupted when the user stops mid-stream", async () => {
    mockedStream.mockImplementation(async function* (
      _id: string,
      _input: unknown,
      signal: AbortSignal,
    ): AsyncGenerator<TurnEvent> {
      yield { type: "delta", text: "Partial" };
      await new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
    });
    const { result } = mount();
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.ask("Question", ["d1"]);
    });
    await waitFor(() => expect(result.current.turns[0]?.text).toBe("Partial"));
    expect(result.current.generating).toBe(true);

    await act(async () => {
      result.current.stop();
      await pending;
    });

    expect(result.current.turns[0]).toMatchObject({
      status: "interrupted",
      text: "Partial",
      errorMessage: "Stopped. This answer is incomplete.",
    });
    expect(result.current.generating).toBe(false);
  });

  it("marks the turn interrupted with the connection text when the stream fails", async () => {
    mockedStream.mockImplementation(async function* (): AsyncGenerator<TurnEvent> {
      yield { type: "delta", text: "Partial" };
      throw new TypeError("network");
    });
    const { result } = mount();

    await act(async () => {
      await result.current.ask("Question", ["d1"]);
    });

    expect(result.current.turns[0]).toMatchObject({
      status: "interrupted",
      errorMessage: "The request failed. Check your connection and try again.",
    });
  });

  it("marks the turn interrupted when the stream ends without a final event", async () => {
    mockedStream.mockReturnValue(events({ type: "delta", text: "Partial" }));
    const { result } = mount();

    await act(async () => {
      await result.current.ask("Question", ["d1"]);
    });

    expect(result.current.turns[0]).toMatchObject({
      status: "interrupted",
      errorMessage: "The connection ended before the answer was complete.",
    });
  });

  it("records a server error event on the turn", async () => {
    mockedStream.mockReturnValue(
      events({
        type: "error",
        status: "failed",
        code: "generation_failed",
        message: "",
        retryable: true,
      }),
    );
    const { result } = mount();

    await act(async () => {
      await result.current.ask("Question", ["d1"]);
    });

    expect(result.current.turns[0]).toMatchObject({
      status: "failed",
      errorMessage: "generation_failed",
      retryable: true,
    });
  });

  it("removes the turn and restores the question when the request is rejected", async () => {
    mockedStream.mockImplementation(async function* (): AsyncGenerator<TurnEvent> {
      yield* [];
      throw new ApiError(409, "turn_in_progress");
    });
    const { result } = mount();

    await act(async () => {
      await result.current.ask("Question", ["d1"]);
    });

    expect(result.current.turns).toEqual([]);
    expect(result.current.question).toBe("Question");
    expect(result.current.askError).toBe(
      "Another answer is still being generated. Wait for it to finish.",
    );
    expect(result.current.generating).toBe(false);
  });

  it("treats a rejected conversation creation as a rejected question", async () => {
    mockedCreate.mockRejectedValue(new ApiError(401, "session_required"));
    const { result } = mount();

    await act(async () => {
      await result.current.ask("Question", ["d1"]);
    });

    expect(result.current.turns).toEqual([]);
    expect(result.current.question).toBe("Question");
    expect(result.current.askError).toBe(
      "Your session has expired. Reload the page to start a new one.",
    );
  });

  it("restores a stored conversation and makes its last turn active", async () => {
    window.sessionStorage.setItem(STORAGE_KEY, "c9");
    const conversation: Conversation = {
      id: "c9",
      turns: [
        {
          id: "t1",
          status: "complete",
          question: "First?",
          text: "One",
          sources: [],
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "t2",
          status: "complete",
          question: null,
          text: "Two [S1]",
          sources: [source("S1", true)],
          created_at: "2026-01-01T00:01:00Z",
        },
      ],
    };
    mockedGet.mockResolvedValue(conversation);

    const { result } = mount();

    await waitFor(() => expect(result.current.turns).toHaveLength(2));
    expect(mockedGet).toHaveBeenCalledWith("c9");
    expect(result.current.turns[1]).toMatchObject({
      key: "t2",
      question: "",
      progressStage: null,
      invalidCitationLabels: [],
    });
    expect(result.current.activeTurnKey).toBe("t2");
    expect(result.current.activeLabel).toBeNull();
  });

  it("forgets a stored conversation that can no longer be loaded", async () => {
    window.sessionStorage.setItem(STORAGE_KEY, "gone");
    mockedGet.mockRejectedValue(new ApiError(404, "not_found"));

    const { result } = mount();

    await waitFor(() => expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull());
    expect(result.current.turns).toEqual([]);
  });

  it("does not restore anything before the session limits are known", () => {
    window.sessionStorage.setItem(STORAGE_KEY, "c9");

    renderHook(() => useConversation(null));

    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("marks only the deleted document's sources as deleted, in every turn", async () => {
    window.sessionStorage.setItem(STORAGE_KEY, "c9");
    const fromDocument = (label: string, documentId: string): TurnSource => ({
      ...source(label, true),
      document_id: documentId,
    });
    mockedGet.mockResolvedValue({
      id: "c9",
      turns: ["t1", "t2"].map((id: string) => ({
        id,
        status: "complete",
        question: "Q?",
        text: "A [S1] [S2]",
        sources: [fromDocument("S1", "d1"), fromDocument("S2", "d2")],
        created_at: "2026-01-01T00:00:00Z",
      })),
    });
    const { result } = mount();
    await waitFor(() => expect(result.current.turns).toHaveLength(2));

    act(() => {
      result.current.markDocumentDeleted("d1");
    });

    for (const turn of result.current.turns) {
      expect(turn.sources[0]).toMatchObject({ label: "S1", document_id: null, quote: "" });
      expect(turn.sources[1]).toMatchObject({
        label: "S2",
        document_id: "d2",
        quote: "quote S2",
      });
    }
  });
});
