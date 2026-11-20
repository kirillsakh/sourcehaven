// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationPanel } from "@/components/conversation/conversation-panel";
import type { DocumentInfo, SessionLimits } from "@/lib/api";
import type { TurnViewModel } from "@/lib/use-conversation";

const limits: SessionLimits = {
  max_documents: 10,
  max_pages_per_document: 300,
  max_upload_bytes: 20 * 1024 * 1024,
  max_question_chars: 2000,
};

function doc(id: string, state: DocumentInfo["state"] = "ready"): DocumentInfo {
  return {
    id,
    display_name: `${id}.pdf`,
    state,
    error_code: null,
    page_count: 3,
    progress: null,
    created_at: id,
  };
}

function turn(key: string, question: string): TurnViewModel {
  return {
    key,
    status: "failed",
    question,
    text: "",
    sources: [],
    invalidCitationLabels: [],
    errorMessage: "The answer service is busy.",
    retryable: true,
    progressStage: null,
  };
}

interface Handlers {
  onQuestionChange: (text: string) => void;
  onAsk: (text: string, documentIds: string[]) => void;
  onStop: () => void;
  onActivate: (turnKey: string, label?: string) => void;
  onShowEvidence: () => void;
  onFiles: (files: File[]) => void;
  onScopeClick: () => void;
}

function renderPanel(
  options: {
    documents?: DocumentInfo[];
    selected?: string[];
    turns?: TurnViewModel[];
    question?: string;
  } = {},
): Handlers {
  const handlers: Handlers = {
    onQuestionChange: vi.fn(),
    onAsk: vi.fn(),
    onStop: vi.fn(),
    onActivate: vi.fn(),
    onShowEvidence: vi.fn(),
    onFiles: vi.fn(),
    onScopeClick: vi.fn(),
  };
  render(
    <ConversationPanel
      limits={limits}
      documents={options.documents ?? []}
      selected={new Set(options.selected ?? [])}
      turns={options.turns ?? []}
      activeTurnKey={null}
      activeLabel={null}
      generating={false}
      question={options.question ?? ""}
      askError={null}
      {...handlers}
    />,
  );
  return handlers;
}

describe("ConversationPanel", () => {
  it("shows the empty state with a drop tray when there are no documents", () => {
    renderPanel();

    expect(screen.getByText("Ask questions about your PDFs")).toBeTruthy();
    expect(screen.getByText("Every answer shows the passages it came from.")).toBeTruthy();
    expect(screen.getByText("Drop PDFs here")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Question" })).toBeTruthy();
  });

  it("names the only ready document in the hint", () => {
    renderPanel({ documents: [doc("contract")], selected: ["contract"] });

    expect(screen.getByText("Ask something about contract.pdf")).toBeTruthy();
    expect(screen.queryByText("Ask questions about your PDFs")).toBeNull();
  });

  it("counts ready documents in the hint", () => {
    renderPanel({
      documents: [doc("a"), doc("b"), doc("c"), doc("d", "processing")],
      selected: ["a"],
    });

    expect(screen.getByText("Ask something about your 3 documents")).toBeTruthy();
  });

  it("explains that the only document is being indexed", () => {
    renderPanel({ documents: [doc("contract", "processing"), doc("scan", "failed")] });

    expect(
      screen.getByText("contract.pdf is being indexed. You can ask once it is ready."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Your document is still being indexed." })).toBeTruthy();
  });

  it("explains that several documents are being indexed", () => {
    renderPanel({ documents: [doc("a", "queued"), doc("b", "processing")] });

    expect(
      screen.getByText("Your documents are being indexed. You can ask once one is ready."),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Your documents are still being indexed." }),
    ).toBeTruthy();
  });

  it("asks for a PDF when every document failed", () => {
    renderPanel({ documents: [doc("scan", "failed")] });

    expect(screen.getByRole("button", { name: "Add a PDF to ask a question." })).toBeTruthy();
    expect(screen.queryByText(/being indexed/)).toBeNull();
  });

  it("shows turns instead of the hint once there are some", () => {
    renderPanel({ documents: [doc("a")], turns: [turn("t1", "First question?")] });

    expect(screen.getByText("First question?")).toBeTruthy();
    expect(screen.queryByText(/Ask something about/)).toBeNull();
  });

  it("asks with the ready selected document ids", async () => {
    const handlers: Handlers = renderPanel({
      documents: [doc("a"), doc("b"), doc("c", "processing")],
      selected: ["b", "c"],
      question: "Who signed?",
    });

    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(handlers.onAsk).toHaveBeenCalledExactlyOnceWith("Who signed?", ["b"]);
  });

  it("retries a turn with its question and the ready selected ids", async () => {
    const handlers: Handlers = renderPanel({
      documents: [doc("a")],
      selected: ["a"],
      turns: [turn("t1", "First question?")],
    });

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(handlers.onAsk).toHaveBeenCalledExactlyOnceWith("First question?", ["a"]);
  });
});

describe("ConversationPanel scrolling", () => {
  let scrollHeight: number = 500;

  function panel(turns: TurnViewModel[]): ReactElement {
    return (
      <ConversationPanel
        limits={limits}
        documents={[doc("a")]}
        selected={new Set(["a"])}
        turns={turns}
        activeTurnKey={null}
        activeLabel={null}
        generating={false}
        question=""
        askError={null}
        onQuestionChange={vi.fn()}
        onAsk={vi.fn()}
        onStop={vi.fn()}
        onActivate={vi.fn()}
        onShowEvidence={vi.fn()}
        onFiles={vi.fn()}
        onScopeClick={vi.fn()}
      />
    );
  }

  function withText(item: TurnViewModel, text: string): TurnViewModel {
    return { ...item, status: "generating", errorMessage: null, text };
  }

  function turnsList(): HTMLElement {
    const list: HTMLElement | null = screen.getByText("First question?").closest("[aria-live]");
    if (list === null) {
      throw new Error("The turns list is not rendered");
    }
    return list;
  }

  function scrollUserTo(list: HTMLElement, top: number): void {
    list.scrollTop = top;
    fireEvent.scroll(list);
  }

  beforeEach(() => {
    scrollHeight = 500;
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get: (): number => scrollHeight,
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get: (): number => 100,
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(HTMLElement.prototype, "scrollHeight");
    Reflect.deleteProperty(HTMLElement.prototype, "clientHeight");
  });

  it("scrolls a newly asked question into view", () => {
    const first: TurnViewModel = turn("t1", "First question?");
    const { rerender } = render(panel([first]));
    const list: HTMLElement = turnsList();
    scrollUserTo(list, 0);

    scrollHeight = 700;
    rerender(panel([first, withText(turn("t2", "Second question?"), "")]));

    expect(list.scrollTop).toBe(700);
  });

  it("follows the streamed answer until the reader scrolls up", () => {
    const first: TurnViewModel = withText(turn("t1", "First question?"), "Three");
    const { rerender } = render(panel([first]));
    const list: HTMLElement = turnsList();
    expect(list.scrollTop).toBe(500);

    scrollHeight = 800;
    rerender(panel([withText(first, "Three months")]));
    expect(list.scrollTop).toBe(800);

    scrollUserTo(list, 100);
    scrollHeight = 900;
    rerender(panel([withText(first, "Three months of notice")]));
    expect(list.scrollTop).toBe(100);
  });
});
