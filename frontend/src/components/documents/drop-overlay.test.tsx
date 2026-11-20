// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DropOverlay } from "@/components/documents/drop-overlay";
import type { SessionLimits } from "@/lib/api";

const limits: SessionLimits = {
  max_documents: 10,
  max_pages_per_document: 300,
  max_upload_bytes: 20 * 1024 * 1024,
  max_question_chars: 2000,
};

interface TransferStub {
  types: string[];
  items: { length: number };
  files: File[];
}

function dispatchDrag(
  type: string,
  target: EventTarget,
  transfer: Partial<TransferStub> = {},
): Event {
  const event: Event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", {
    value: { types: ["Files"], items: { length: 0 }, files: [], ...transfer },
  });
  act(() => {
    target.dispatchEvent(event);
  });
  return event;
}

function mountOverlay(
  enabled = true,
): { onFiles: (files: File[]) => void; child: HTMLElement; other: HTMLElement } {
  const onFiles: (files: File[]) => void = vi.fn();
  const child: HTMLElement = document.createElement("div");
  const other: HTMLElement = document.createElement("div");
  document.body.append(child, other);
  render(<DropOverlay enabled={enabled} limits={limits} onFiles={onFiles} />);
  return { onFiles, child, other };
}

describe("DropOverlay", () => {
  it("renders nothing until files are dragged over the window", () => {
    const { container } = render(<DropOverlay enabled limits={limits} onFiles={vi.fn()} />);

    expect(container.firstChild).toBeNull();
  });

  it("shows the file count from the dragged items", () => {
    mountOverlay();

    dispatchDrag("dragenter", document.body, { items: { length: 2 } });

    expect(screen.getByText("Drop to upload 2 PDFs")).toBeTruthy();
  });

  it("falls back to a generic line when the count is unknown", () => {
    mountOverlay();

    dispatchDrag("dragenter", document.body);

    expect(screen.getByText("Drop to upload PDFs")).toBeTruthy();
  });

  it("uses the singular for one item", () => {
    mountOverlay();

    dispatchDrag("dragenter", document.body, { items: { length: 1 } });

    expect(screen.getByText("Drop to upload 1 PDF")).toBeTruthy();
  });

  it("stays visible while the pointer moves between child elements", () => {
    const { child, other } = mountOverlay();

    dispatchDrag("dragenter", child);
    dispatchDrag("dragenter", other);
    dispatchDrag("dragleave", child);

    expect(screen.getByText("Drop to upload PDFs")).toBeTruthy();
  });

  it("hides after the final dragleave", () => {
    const { child, other } = mountOverlay();

    dispatchDrag("dragenter", child);
    dispatchDrag("dragenter", other);
    dispatchDrag("dragleave", child);
    dispatchDrag("dragleave", other);

    expect(screen.queryByText(/Drop to upload/)).toBeNull();
  });

  it("hides on dragend", () => {
    mountOverlay();

    dispatchDrag("dragenter", document.body);
    dispatchDrag("dragend", document.body);

    expect(screen.queryByText(/Drop to upload/)).toBeNull();
  });

  it("ignores drags that carry no files", () => {
    mountOverlay();

    dispatchDrag("dragenter", document.body, { types: ["text/plain"] });

    expect(screen.queryByText(/Drop to upload/)).toBeNull();
  });

  it("passes dropped files to onFiles and hides", () => {
    const { onFiles } = mountOverlay();
    const file: File = new File(["%PDF"], "a.pdf", { type: "application/pdf" });

    dispatchDrag("dragenter", document.body, { files: [file] });
    const event: Event = dispatchDrag("drop", document.body, { files: [file] });

    expect(onFiles).toHaveBeenCalledExactlyOnceWith([file]);
    expect(event.defaultPrevented).toBe(true);
    expect(screen.queryByText(/Drop to upload/)).toBeNull();
  });

  it("prevents the browser from opening a file dragged over the window", () => {
    mountOverlay();

    const event: Event = dispatchDrag("dragover", document.body);

    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves drags without files to the browser", () => {
    mountOverlay();

    const event: Event = dispatchDrag("dragover", document.body, { types: ["text/plain"] });

    expect(event.defaultPrevented).toBe(false);
  });

  it("does nothing when disabled, but still stops the browser from navigating", () => {
    const { onFiles } = mountOverlay(false);

    dispatchDrag("dragenter", document.body);
    const over: Event = dispatchDrag("dragover", document.body);
    const drop: Event = dispatchDrag("drop", document.body);

    expect(screen.queryByText(/Drop to upload/)).toBeNull();
    expect(over.defaultPrevented).toBe(true);
    expect(drop.defaultPrevented).toBe(true);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("hides when uploads become unavailable mid-drag and stays hidden after the drag ends", () => {
    const { rerender } = render(<DropOverlay enabled limits={limits} onFiles={vi.fn()} />);

    dispatchDrag("dragenter", document.body);
    expect(screen.getByText("Drop to upload PDFs")).toBeTruthy();

    rerender(<DropOverlay enabled={false} limits={limits} onFiles={vi.fn()} />);
    expect(screen.queryByText(/Drop to upload/)).toBeNull();

    dispatchDrag("dragleave", document.body);
    rerender(<DropOverlay enabled limits={limits} onFiles={vi.fn()} />);
    expect(screen.queryByText(/Drop to upload/)).toBeNull();
  });

  it("keeps the depth count when props change mid-drag", () => {
    const { rerender } = render(<DropOverlay enabled limits={limits} onFiles={vi.fn()} />);
    const child: HTMLElement = document.createElement("div");
    document.body.append(child);

    dispatchDrag("dragenter", document.body);
    dispatchDrag("dragenter", child);
    rerender(<DropOverlay enabled limits={limits} onFiles={vi.fn()} />);
    dispatchDrag("dragleave", document.body);

    expect(screen.getByText("Drop to upload PDFs")).toBeTruthy();
  });

  it("shows the limits line when limits are given", () => {
    mountOverlay();

    dispatchDrag("dragenter", document.body);

    expect(screen.getByText("Up to 20 MB and 300 pages each")).toBeTruthy();
  });

  it("omits the limits line while limits are unknown", () => {
    render(<DropOverlay enabled limits={null} onFiles={vi.fn()} />);

    dispatchDrag("dragenter", document.body);

    expect(screen.getByText("Drop to upload PDFs")).toBeTruthy();
    expect(screen.queryByText(/Up to/)).toBeNull();
  });
});
