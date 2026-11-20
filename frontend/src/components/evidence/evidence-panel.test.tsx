// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvidencePanel } from "@/components/evidence/evidence-panel";
import type { TurnSource } from "@/lib/api";
import type { TurnViewModel } from "@/lib/use-conversation";

const CONTRACT_QUOTE = "Either party may terminate this agreement by giving three months’ notice.";
const ANNEX_QUOTE = "The notice period may be reduced only by mutual written agreement.";

function source(
  label: string,
  cited: boolean,
  documentName: string,
  start: number,
  end: number,
  quote: string,
): TurnSource {
  return {
    label,
    cited,
    document_id: documentName,
    document_name: documentName,
    pages: { start, end },
    quote,
  };
}

const SOURCES: TurnSource[] = [
  source("S2", true, "annex-b.pdf", 2, 2, ANNEX_QUOTE),
  source("S3", false, "annex-b.pdf", 3, 3, "Uncited passage three."),
  source("S1", true, "employment-contract.pdf", 4, 4, CONTRACT_QUOTE),
  source("S4", false, "employment-contract.pdf", 9, 10, "Uncited passage four."),
];

function turn(overrides: Partial<TurnViewModel> = {}): TurnViewModel {
  return {
    key: "t1",
    status: "complete",
    question: "How long is the notice period?",
    text: "Three months [S1], shortened by agreement [S2].",
    sources: SOURCES,
    invalidCitationLabels: [],
    errorMessage: null,
    retryable: false,
    progressStage: null,
    ...overrides,
  };
}

function quote(text: string): HTMLElement {
  return screen.getByText(`“${text}”`);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EvidencePanel", () => {
  it("lists cited sources in label order with their document and page", () => {
    render(<EvidencePanel turn={turn()} activeLabel={null} activationCount={0} onActivate={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Evidence" })).toBeTruthy();
    expect(screen.getByText("For “How long is the notice period?”")).toBeTruthy();
    const cited: HTMLElement = screen.getByRole("list", { name: "Cited passages" });
    const items: HTMLElement[] = within(cited).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("[1]");
    expect(items[0].textContent).toContain("employment-contract.pdf, page 4");
    expect(items[0].textContent).toContain(`“${CONTRACT_QUOTE}”`);
    expect(items[1].textContent).toContain("[2]");
    expect(items[1].textContent).toContain("annex-b.pdf, page 2");
  });

  it("highlights the quote of the active citation", () => {
    render(<EvidencePanel turn={turn()} activeLabel="S2" activationCount={0} onActivate={vi.fn()} />);

    expect(quote(ANNEX_QUOTE).className).toMatch(/highlighted/);
    expect(quote(CONTRACT_QUOTE).className).not.toMatch(/highlighted/);
  });

  it("highlights the first cited source when no citation was chosen", () => {
    render(<EvidencePanel turn={turn()} activeLabel={null} activationCount={0} onActivate={vi.fn()} />);

    expect(quote(CONTRACT_QUOTE).className).toMatch(/highlighted/);
    expect(quote(ANNEX_QUOTE).className).not.toMatch(/highlighted/);
  });

  it("shows the deleted text instead of a deleted source's quote, without the highlighter", () => {
    const deleted: TurnSource[] = SOURCES.map((item: TurnSource) =>
      item.label === "S1" ? { ...item, document_id: null, quote: "" } : item,
    );
    render(
      <EvidencePanel turn={turn({ sources: deleted })} activeLabel="S1" activationCount={0} onActivate={vi.fn()} />,
    );

    const notice: HTMLElement = screen.getByText(
      "This document was deleted, so its quote is no longer available.",
    );
    expect(notice.className).not.toMatch(/highlighted/);
    expect(document.querySelector("[class*='highlighted']")).toBeNull();
    expect(screen.queryByText("“”")).toBeNull();
    const items: HTMLElement[] = within(
      screen.getByRole("list", { name: "Cited passages" }),
    ).getAllByRole("listitem");
    expect(items[0].textContent).toContain("employment-contract.pdf, page 4");
    expect(quote(ANNEX_QUOTE).className).not.toMatch(/highlighted/);
  });

  it("keeps a deleted first source as the default active item", () => {
    const deleted: TurnSource[] = SOURCES.map((item: TurnSource) =>
      item.label === "S1" ? { ...item, document_id: null, quote: "" } : item,
    );
    render(
      <EvidencePanel turn={turn({ sources: deleted })} activeLabel={null} activationCount={0} onActivate={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: "Highlight source 1" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(document.querySelector("[class*='highlighted']")).toBeNull();
  });

  it("scrolls the highlighted item into view, again for another turn", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    try {
      const { rerender } = render(
        <EvidencePanel turn={turn()} activeLabel="S2" activationCount={0} onActivate={vi.fn()} />,
      );
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });

      rerender(<EvidencePanel turn={turn({ key: "t2" })} activeLabel="S2" activationCount={0} onActivate={vi.fn()} />);
      expect(scrollIntoView).toHaveBeenCalledTimes(2);
    } finally {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });

  it("replays the highlight and the scroll when the same source is activated again", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    try {
      const { rerender } = render(
        <EvidencePanel turn={turn()} activeLabel="S2" activationCount={1} onActivate={vi.fn()} />,
      );
      const first: HTMLElement = quote(ANNEX_QUOTE);

      rerender(
        <EvidencePanel turn={turn()} activeLabel="S2" activationCount={2} onActivate={vi.fn()} />,
      );

      expect(scrollIntoView).toHaveBeenCalledTimes(2);
      // A new mark element restarts the sweep animation.
      expect(quote(ANNEX_QUOTE)).not.toBe(first);
      expect(quote(ANNEX_QUOTE).className).toMatch(/highlighted/);
    } finally {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });

  it("activates a source by its label", async () => {
    const onActivate = vi.fn();
    render(<EvidencePanel turn={turn()} activeLabel={null} activationCount={0} onActivate={onActivate} />);

    await userEvent.click(screen.getByRole("button", { name: "Highlight source 2" }));

    expect(onActivate).toHaveBeenCalledWith("S2");
  });

  it("collects uncited passages in a closed disclosure", () => {
    render(<EvidencePanel turn={turn()} activeLabel={null} activationCount={0} onActivate={vi.fn()} />);

    const summary: HTMLElement = screen.getByText("2 more passages were read but not cited");
    const details: HTMLDetailsElement | null = summary.closest("details");
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain("employment-contract.pdf, pages 9–10");
  });

  it("uses the singular for one uncited passage", () => {
    render(
      <EvidencePanel
        turn={turn({ sources: SOURCES.filter((item) => item.label !== "S4") })}
        activeLabel={null}
        activationCount={0}
        onActivate={vi.fn()}
      />,
    );

    expect(screen.getByText("1 more passage was read but not cited")).toBeTruthy();
  });

  it("explains where evidence appears before any question", () => {
    render(<EvidencePanel turn={null} activeLabel={null} activationCount={0} onActivate={vi.fn()} />);

    expect(screen.getByText("Evidence for each answer appears here.")).toBeTruthy();
  });

  it("waits for sources while the answer is generated", () => {
    render(
      <EvidencePanel
        turn={turn({ status: "generating", sources: [] })}
        activeLabel={null}
        activationCount={0}
        onActivate={vi.fn()}
      />,
    );

    expect(screen.getByText("Sources appear when the answer is finished.")).toBeTruthy();
  });

  it.each(["interrupted", "failed"])("shows no evidence for a %s answer", (status: string) => {
    render(
      <EvidencePanel turn={turn({ status, sources: [] })} activeLabel={null} activationCount={0} onActivate={vi.fn()} />,
    );

    expect(screen.getByText("No evidence for an incomplete answer.")).toBeTruthy();
  });

  it("cautions about a complete answer without cited sources", () => {
    render(
      <EvidencePanel
        turn={turn({ sources: SOURCES.filter((item) => !item.cited) })}
        activeLabel={null}
        activationCount={0}
        onActivate={vi.fn()}
      />,
    );

    expect(
      screen.getByText("No sources were cited. Treat this answer with caution."),
    ).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Cited passages" })).toBeNull();
  });
});
