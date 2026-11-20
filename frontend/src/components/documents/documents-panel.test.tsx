// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DocumentsPanel } from "@/components/documents/documents-panel";
import type { DocumentInfo, SessionLimits } from "@/lib/api";
import type { UploadRow } from "@/lib/use-documents";

const limits: SessionLimits = {
  max_documents: 10,
  max_pages_per_document: 300,
  max_upload_bytes: 20 * 1024 * 1024,
  max_question_chars: 2000,
};

function doc(id: string, overrides: Partial<DocumentInfo> = {}): DocumentInfo {
  return {
    id,
    display_name: `${id}.pdf`,
    state: "ready",
    error_code: null,
    page_count: 14,
    progress: null,
    created_at: id,
    ...overrides,
  };
}

interface PanelHandlers {
  onFiles: (files: File[]) => void;
  onToggle: (id: string) => void;
  onSelectAll: (all: boolean) => void;
  onDismissUpload: (key: string) => void;
}

function handlers(): PanelHandlers {
  return {
    onFiles: vi.fn(),
    onToggle: vi.fn(),
    onSelectAll: vi.fn(),
    onDismissUpload: vi.fn(),
  };
}

function renderPanel(
  options: {
    limits?: SessionLimits | null;
    documents?: DocumentInfo[];
    uploads?: UploadRow[];
    selected?: string[];
    handlers?: PanelHandlers;
  } = {},
): ReturnType<typeof render> {
  const given: PanelHandlers = options.handlers ?? handlers();
  return render(
    <DocumentsPanel
      limits={options.limits === undefined ? limits : options.limits}
      documents={options.documents ?? []}
      uploads={options.uploads ?? []}
      selected={new Set(options.selected ?? [])}
      {...given}
    />,
  );
}

function checkbox(name: string): HTMLInputElement {
  const element: HTMLElement = screen.getByRole("checkbox", { name });
  if (!(element instanceof HTMLInputElement)) {
    throw new Error("not an input");
  }
  return element;
}

describe("DocumentsPanel", () => {
  it("shows the heading with the document count", () => {
    renderPanel({ documents: [doc("a"), doc("b"), doc("c")] });

    expect(screen.getByRole("heading", { name: "Your documents" })).toBeTruthy();
    expect(screen.getByText("3 of 10")).toBeTruthy();
  });

  it("hides the count while limits are unknown", () => {
    renderPanel({ limits: null, documents: [doc("a")] });

    expect(screen.queryByText(/ of \d+$/)).toBeNull();
  });

  it("lists rows with status word and detail", () => {
    renderPanel({
      documents: [
        doc("contract"),
        doc("report", {
          state: "processing",
          page_count: null,
          progress: { done: 3, total: 5, stage: "embedding" },
        }),
        doc("locked", { state: "failed", page_count: null, error_code: "encrypted" }),
      ],
    });

    const ready: HTMLElement = screen.getByText("contract.pdf").closest("li") as HTMLElement;
    expect(within(ready).getByText("Ready")).toBeTruthy();
    expect(within(ready).getByText("14 pages")).toBeTruthy();

    const indexing: HTMLElement = screen.getByText("report.pdf").closest("li") as HTMLElement;
    expect(within(indexing).getByText("Indexing")).toBeTruthy();
    expect(within(indexing).getByText("60%")).toBeTruthy();
    const bar: HTMLProgressElement = within(indexing).getByRole("progressbar");
    expect(bar.value).toBe(3);
    expect(bar.max).toBe(5);

    const failed: HTMLElement = screen.getByText("locked.pdf").closest("li") as HTMLElement;
    expect(within(failed).getByText("Failed")).toBeTruthy();
    expect(
      within(failed).getByText(
        "This PDF is password-protected. Remove the password and upload it again.",
      ),
    ).toBeTruthy();
  });

  it("renders an indeterminate progress bar when the total is zero", () => {
    renderPanel({
      documents: [
        doc("empty-total", {
          state: "processing",
          page_count: null,
          progress: { done: 0, total: 0, stage: null },
        }),
      ],
    });

    const bar: HTMLElement = screen.getByRole("progressbar");
    expect(bar.hasAttribute("value")).toBe(false);
    expect(bar.hasAttribute("max")).toBe(false);
  });

  it("disables the checkbox of a document that is not ready", () => {
    renderPanel({
      documents: [doc("ready"), doc("busy", { state: "processing", page_count: null })],
    });

    expect(checkbox("busy.pdf").disabled).toBe(true);
    expect(checkbox("ready.pdf").disabled).toBe(false);
  });

  it("toggles a ready document", async () => {
    const given: PanelHandlers = handlers();
    renderPanel({ documents: [doc("ready")], handlers: given });

    await userEvent.click(checkbox("ready.pdf"));

    expect(given.onToggle).toHaveBeenCalledExactlyOnceWith("ready");
  });

  it("checks the boxes of selected documents", () => {
    renderPanel({ documents: [doc("a"), doc("b")], selected: ["a"] });

    expect(checkbox("a.pdf").checked).toBe(true);
    expect(checkbox("b.pdf").checked).toBe(false);
  });

  describe("select all", () => {
    it("is checked when every ready document is selected and clears on click", async () => {
      const given: PanelHandlers = handlers();
      renderPanel({ documents: [doc("a"), doc("b")], selected: ["a", "b"], handlers: given });

      const all: HTMLInputElement = checkbox("Use all ready documents");
      expect(all.checked).toBe(true);
      expect(all.indeterminate).toBe(false);

      await userEvent.click(all);

      expect(given.onSelectAll).toHaveBeenCalledExactlyOnceWith(false);
    });

    it("is mixed when some are selected and selects all on click", async () => {
      const given: PanelHandlers = handlers();
      renderPanel({ documents: [doc("a"), doc("b")], selected: ["a"], handlers: given });

      const all: HTMLInputElement = checkbox("Use all ready documents");
      expect(all.indeterminate).toBe(true);

      await userEvent.click(all);

      expect(given.onSelectAll).toHaveBeenCalledExactlyOnceWith(true);
    });

    it("is unchecked when none are selected and selects all on click", async () => {
      const given: PanelHandlers = handlers();
      renderPanel({ documents: [doc("a")], handlers: given });

      const all: HTMLInputElement = checkbox("Use all ready documents");
      expect(all.checked).toBe(false);
      expect(all.indeterminate).toBe(false);

      await userEvent.click(all);

      expect(given.onSelectAll).toHaveBeenCalledExactlyOnceWith(true);
    });

    it("is disabled when no document is ready", () => {
      renderPanel({ documents: [doc("busy", { state: "queued", page_count: null })] });

      expect(checkbox("Use all ready documents").disabled).toBe(true);
    });

    it("is not shown without documents", () => {
      renderPanel();

      expect(screen.queryByRole("checkbox")).toBeNull();
    });
  });

  describe("uploads", () => {
    it("lists upload rows after the documents", () => {
      renderPanel({
        documents: [doc("server")],
        uploads: [{ key: "u1", name: "new.pdf", status: "uploading", fraction: 0.45 }],
      });

      const items: HTMLElement[] = screen.getAllByRole("listitem");
      expect(items.map((item) => item.textContent)).toEqual([
        expect.stringContaining("server.pdf"),
        expect.stringContaining("new.pdf"),
      ]);
      expect(screen.getByText("Uploading")).toBeTruthy();
      expect(screen.getByText("45%")).toBeTruthy();
      expect((screen.getByRole("progressbar") as HTMLProgressElement).value).toBeCloseTo(0.45);
    });

    it("does not count uploads against the document limit", () => {
      renderPanel({
        documents: [doc("server")],
        uploads: [{ key: "u1", name: "new.pdf", status: "uploading", fraction: 0 }],
      });

      expect(screen.getByText("1 of 10")).toBeTruthy();
    });

    it("shows a rejected row with its reason and dismisses it", async () => {
      const given: PanelHandlers = handlers();
      renderPanel({
        uploads: [{ key: "u9", name: "photo.png", status: "rejected", reason: "Only PDF files." }],
        handlers: given,
      });

      expect(screen.getByText("photo.png")).toBeTruthy();
      expect(screen.getByText("Only PDF files.")).toBeTruthy();

      await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

      expect(given.onDismissUpload).toHaveBeenCalledExactlyOnceWith("u9");
    });

    it("offers Dismiss only on rejected rows", () => {
      renderPanel({
        documents: [doc("server")],
        uploads: [{ key: "u1", name: "new.pdf", status: "uploading", fraction: 0.1 }],
      });

      expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    });
  });

  describe("tray", () => {
    it("shows the limits from the session", () => {
      renderPanel();

      expect(screen.getByText("Drop PDFs here")).toBeTruthy();
      expect(screen.getByText(/Up to 20 MB and 300 pages each\./)).toBeTruthy();
    });

    it("passes chosen files to onFiles", async () => {
      const given: PanelHandlers = handlers();
      const { container } = renderPanel({ handlers: given });
      const file: File = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
      const input: HTMLInputElement | null = container.querySelector('input[type="file"]');

      expect(input?.accept).toBe("application/pdf,.pdf");
      expect(input?.multiple).toBe(true);
      await userEvent.upload(input as HTMLInputElement, file);

      expect(given.onFiles).toHaveBeenCalledExactlyOnceWith([file]);
    });

    it("opens the file picker from the choose files button", async () => {
      const { container } = renderPanel();
      const input: HTMLInputElement = container.querySelector(
        'input[type="file"]',
      ) as HTMLInputElement;
      const click = vi.spyOn(input, "click");

      await userEvent.click(screen.getByRole("button", { name: "choose files" }));

      expect(click).toHaveBeenCalledOnce();
    });

    it("is disabled and says so when the session is full", () => {
      const documents: DocumentInfo[] = Array.from({ length: 10 }, (_, index) =>
        doc(`d${index}`),
      );
      renderPanel({ documents });

      expect((screen.getByRole("button", { name: "choose files" }) as HTMLButtonElement).disabled)
        .toBe(true);
      expect(screen.getByText("This session is full.")).toBeTruthy();
    });

    it("is disabled while limits are unknown", () => {
      renderPanel({ limits: null });

      expect((screen.getByRole("button", { name: "choose files" }) as HTMLButtonElement).disabled)
        .toBe(true);
    });
  });
});
