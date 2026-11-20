// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/components/conversation/composer";

interface Handlers {
  onChange: (text: string) => void;
  onAsk: () => void;
  onStop: () => void;
  onScopeClick: () => void;
}

function renderComposer(
  options: {
    question?: string;
    generating?: boolean;
    readySelected?: number;
    readyTotal?: number;
    indexing?: number;
    error?: string | null;
    maxChars?: number;
  } = {},
): Handlers {
  const handlers: Handlers = {
    onChange: vi.fn(),
    onAsk: vi.fn(),
    onStop: vi.fn(),
    onScopeClick: vi.fn(),
  };
  render(
    <Composer
      question={options.question ?? "What is the notice period?"}
      maxChars={options.maxChars ?? 2000}
      generating={options.generating ?? false}
      readySelected={options.readySelected ?? 2}
      readyTotal={options.readyTotal ?? 3}
      indexing={options.indexing ?? 0}
      error={options.error ?? null}
      {...handlers}
    />,
  );
  return handlers;
}

describe("Composer", () => {
  it("asks on Enter", async () => {
    const handlers: Handlers = renderComposer();

    await userEvent.type(screen.getByRole("textbox", { name: "Question" }), "{Enter}");

    expect(handlers.onAsk).toHaveBeenCalledOnce();
  });

  it("does not ask on Shift+Enter", async () => {
    const handlers: Handlers = renderComposer();

    await userEvent.type(screen.getByRole("textbox", { name: "Question" }), "{Shift>}{Enter}{/Shift}");

    expect(handlers.onAsk).not.toHaveBeenCalled();
  });

  it("asks when the Ask button is clicked", async () => {
    const handlers: Handlers = renderComposer();

    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(handlers.onAsk).toHaveBeenCalledOnce();
  });

  it("reports typing through onChange", async () => {
    const handlers: Handlers = renderComposer({ question: "" });

    await userEvent.type(screen.getByRole("textbox", { name: "Question" }), "a");

    expect(handlers.onChange).toHaveBeenCalledWith("a");
  });

  it("disables Ask and ignores Enter when nothing is selected", async () => {
    const handlers: Handlers = renderComposer({ readySelected: 0, readyTotal: 2 });

    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(screen.getByRole("textbox", { name: "Question" }), "{Enter}");

    expect(handlers.onAsk).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Select at least one ready document to ask a question." }),
    ).toBeTruthy();
  });

  it("disables Ask and ignores Enter for a blank question", async () => {
    const handlers: Handlers = renderComposer({ question: "   " });

    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(screen.getByRole("textbox", { name: "Question" }), "{Enter}");

    expect(handlers.onAsk).not.toHaveBeenCalled();
  });

  it("shows Stop instead of Ask while generating and ignores Enter", async () => {
    const handlers: Handlers = renderComposer({ generating: true });

    expect(screen.queryByRole("button", { name: "Ask" })).toBeNull();
    await userEvent.type(screen.getByRole("textbox", { name: "Question" }), "{Enter}");
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(handlers.onAsk).not.toHaveBeenCalled();
    expect(handlers.onStop).toHaveBeenCalledOnce();
  });

  it("shows the scope line as a button that calls onScopeClick", async () => {
    const handlers: Handlers = renderComposer({ readySelected: 2, readyTotal: 3 });

    await userEvent.click(screen.getByRole("button", { name: "Answering from 2 of 3 documents" }));

    expect(handlers.onScopeClick).toHaveBeenCalledOnce();
  });

  it("limits the question length", () => {
    renderComposer({ maxChars: 500 });

    expect(screen.getByRole("textbox", { name: "Question" }).getAttribute("maxlength")).toBe("500");
  });

  it("shows an ask error as an alert", () => {
    renderComposer({ error: "Another answer is still being generated." });

    expect(screen.getByRole("alert").textContent).toBe("Another answer is still being generated.");
  });
});
