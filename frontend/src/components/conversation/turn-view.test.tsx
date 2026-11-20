// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TurnView } from "@/components/conversation/turn-view";
import type { TurnSource } from "@/lib/api";
import type { TurnViewModel } from "@/lib/use-conversation";

function source(label: string, documentName: string, overrides: Partial<TurnSource> = {}): TurnSource {
  return {
    label,
    cited: true,
    document_id: documentName,
    document_name: documentName,
    pages: { start: 1, end: 1 },
    quote: `quote ${label}`,
    ...overrides,
  };
}

function turn(overrides: Partial<TurnViewModel> = {}): TurnViewModel {
  return {
    key: "t1",
    status: "complete",
    question: "How long is the notice period?",
    text: "Three months [S1].",
    sources: [source("S1", "contract.pdf")],
    invalidCitationLabels: [],
    errorMessage: null,
    retryable: false,
    progressStage: null,
    ...overrides,
  };
}

interface Handlers {
  onActivate: (turnKey: string, label?: string) => void;
  onRetry: (question: string) => void;
  onShowEvidence: () => void;
}

function renderTurn(
  model: TurnViewModel,
  options: { active?: boolean; activeLabel?: string | null; handlers?: Handlers } = {},
): Handlers {
  const handlers: Handlers = options.handlers ?? {
    onActivate: vi.fn(),
    onRetry: vi.fn(),
    onShowEvidence: vi.fn(),
  };
  render(
    <TurnView
      turn={model}
      active={options.active ?? false}
      activeLabel={options.activeLabel ?? null}
      {...handlers}
    />,
  );
  return handlers;
}

describe("TurnView", () => {
  it("shows the question and the answer text", () => {
    renderTurn(turn());

    expect(screen.getByText("How long is the notice period?")).toBeTruthy();
    expect(screen.getByText(/Three months/)).toBeTruthy();
  });

  it("says it is searching before the first token", () => {
    renderTurn(turn({ status: "generating", text: "", sources: [] }));

    expect(screen.getByText("Searching your documents…")).toBeTruthy();
  });

  it("shows a caret after the streamed text instead of the searching line", () => {
    const { container } = render(
      <TurnView
        turn={turn({ status: "generating", text: "Three", sources: [] })}
        active
        activeLabel={null}
        onActivate={vi.fn()}
        onRetry={vi.fn()}
        onShowEvidence={vi.fn()}
      />,
    );

    expect(screen.queryByText("Searching your documents…")).toBeNull();
    expect(container.querySelector("[class*='streaming'] > p")?.textContent).toBe("Three");
    // The caret is drawn after the last block, not as an element on its own line.
    expect(container.querySelector("[aria-hidden='true']")).toBeNull();
  });

  it("shows no caret once the answer is complete", () => {
    const { container } = render(
      <TurnView
        turn={turn()}
        active
        activeLabel={null}
        onActivate={vi.fn()}
        onRetry={vi.fn()}
        onShowEvidence={vi.fn()}
      />,
    );

    expect(container.querySelector("[class*='streaming']")).toBeNull();
  });

  it("summarises the distinct documents behind the cited sources", () => {
    renderTurn(
      turn({
        text: "One [S1] two [S2] three [S3].",
        sources: [
          source("S1", "contract.pdf"),
          source("S2", "annex-b.pdf"),
          source("S3", "contract.pdf"),
          source("S4", "other.pdf", { cited: false }),
        ],
      }),
    );

    expect(screen.getByText("Sources from 2 documents")).toBeTruthy();
  });

  it("uses the singular for one document", () => {
    renderTurn(turn());

    expect(screen.getByText("Sources from 1 document")).toBeTruthy();
  });

  it("calls onShowEvidence from the Show evidence button", async () => {
    const handlers: Handlers = renderTurn(turn(), { active: true });

    await userEvent.click(screen.getByRole("button", { name: "Show evidence" }));

    expect(handlers.onShowEvidence).toHaveBeenCalledOnce();
  });

  it("activates the turn with the citation label exactly once on a citation click", async () => {
    const handlers: Handlers = renderTurn(
      turn({
        text: "One [S1] two [S2].",
        sources: [source("S1", "contract.pdf"), source("S2", "annex-b.pdf")],
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Source 2" }));

    expect(handlers.onActivate).toHaveBeenCalledExactlyOnceWith("t1", "S2");
  });

  it("activates an inactive turn when its text is clicked", async () => {
    const handlers: Handlers = renderTurn(turn());

    await userEvent.click(screen.getByText("How long is the notice period?"));

    expect(handlers.onActivate).toHaveBeenCalledExactlyOnceWith("t1");
  });

  it("does not re-activate the active turn on a click", async () => {
    const handlers: Handlers = renderTurn(turn(), { active: true });

    await userEvent.click(screen.getByText("How long is the notice period?"));

    expect(handlers.onActivate).not.toHaveBeenCalled();
  });

  it("marks the active turn and the active citation", () => {
    renderTurn(turn(), { active: true, activeLabel: "S1" });

    expect(screen.getByRole("article").getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("button", { name: "Source 1" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("offers Try again for a retryable failure and passes the question", async () => {
    const handlers: Handlers = renderTurn(
      turn({
        status: "failed",
        text: "",
        sources: [],
        errorMessage: "The answer service is busy.",
        retryable: true,
      }),
    );

    expect(screen.getByText("The answer service is busy.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(handlers.onRetry).toHaveBeenCalledExactlyOnceWith("How long is the notice period?");
  });

  it("offers no Try again for a failure that is not retryable", () => {
    renderTurn(
      turn({ status: "failed", sources: [], errorMessage: "Nope.", retryable: false }),
    );

    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("shows the message of an interrupted turn", () => {
    renderTurn(
      turn({
        status: "interrupted",
        text: "Three",
        sources: [],
        errorMessage: "Stopped. This answer is incomplete.",
      }),
    );

    expect(screen.getByText("Stopped. This answer is incomplete.")).toBeTruthy();
    expect(screen.queryByText(/No sources were cited/)).toBeNull();
  });

  it("warns when a complete answer cites no source", () => {
    renderTurn(turn({ text: "Plain answer.", sources: [] }));

    expect(screen.getByText("No sources were cited. Treat this answer with caution.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show evidence" })).toBeNull();
  });

  it("notes citation markers that could not be matched", () => {
    renderTurn(turn({ invalidCitationLabels: ["S9"] }));

    expect(screen.getByText("Some citation markers could not be matched to sources.")).toBeTruthy();
  });
});
