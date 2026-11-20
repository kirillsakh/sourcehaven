// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EvidenceDrawer } from "@/components/evidence/evidence-drawer";
import { EvidenceItem } from "@/components/evidence/evidence-item";
import type { TurnSource } from "@/lib/api";

// jsdom does not implement the modal dialog methods.
const showModal = vi.fn(function (this: HTMLDialogElement): void {
  this.setAttribute("open", "");
});
const close = vi.fn(function (this: HTMLDialogElement): void {
  this.removeAttribute("open");
  this.dispatchEvent(new Event("close"));
});

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = showModal;
  HTMLDialogElement.prototype.close = close;
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderDrawer(open: boolean, onClose: () => void = vi.fn()): () => void {
  const { rerender } = render(
    <EvidenceDrawer open={open} onClose={onClose}>
      <p>Evidence content</p>
    </EvidenceDrawer>,
  );
  return (): void =>
    rerender(
      <EvidenceDrawer open={!open} onClose={onClose}>
        <p>Evidence content</p>
      </EvidenceDrawer>,
    );
}

describe("EvidenceDrawer", () => {
  it("stays closed while open is false", () => {
    renderDrawer(false);

    expect(showModal).not.toHaveBeenCalled();
  });

  it("opens the modal dialog when open becomes true", () => {
    const toggle: () => void = renderDrawer(false);

    toggle();

    expect(showModal).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "Evidence" })).toBeTruthy();
    expect(screen.getByText("Evidence content")).toBeTruthy();
  });

  it("closes the dialog when open becomes false", () => {
    const toggle: () => void = renderDrawer(true);

    toggle();

    expect(close).toHaveBeenCalledTimes(1);
  });

  it("reports a close from the Close evidence button", async () => {
    const onClose = vi.fn();
    renderDrawer(true, onClose);

    await userEvent.setup().click(screen.getByRole("button", { name: "Close evidence" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("reports a close from a click on the backdrop but not from its content", async () => {
    const onClose = vi.fn();
    renderDrawer(true, onClose);
    const user = userEvent.setup();

    await user.click(screen.getByText("Evidence content"));
    expect(onClose).not.toHaveBeenCalled();

    await user.click(screen.getByRole("dialog", { name: "Evidence" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores a text selection that starts in the sheet and ends on the backdrop", () => {
    const onClose = vi.fn();
    renderDrawer(true, onClose);

    fireEvent.pointerDown(screen.getByText("Evidence content"));
    fireEvent.click(screen.getByRole("dialog", { name: "Evidence" }));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("opens the dialog before the highlighted evidence scrolls into view", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const source: TurnSource = {
      label: "S2",
      cited: true,
      document_id: "d2",
      document_name: "annex-b.pdf",
      pages: { start: 2, end: 2 },
      quote: "The notice period may be reduced.",
    };
    try {
      const { rerender } = render(
        <EvidenceDrawer open={false} onClose={vi.fn()}>
          {null}
        </EvidenceDrawer>,
      );

      rerender(
        <EvidenceDrawer open onClose={vi.fn()}>
          <ul>
            <EvidenceItem source={source} active activation={0} onActivate={vi.fn()} />
          </ul>
        </EvidenceDrawer>,
      );

      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      expect(showModal.mock.invocationCallOrder[0]).toBeLessThan(
        scrollIntoView.mock.invocationCallOrder[0],
      );
    } finally {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });

  it("reports a close when the browser closes the dialog, as Escape does", () => {
    const onClose = vi.fn();
    renderDrawer(true, onClose);

    fireEvent(screen.getByRole("dialog", { name: "Evidence" }), new Event("close"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
