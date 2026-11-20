// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AppPage from "@/app/app/page";
import {
  ApiError,
  createConversation,
  createSession,
  deleteDocument,
  getConversation,
  listDocuments,
  streamQuestion,
  uploadDocumentWithProgress,
  type DocumentInfo,
  type SessionLimits,
  type TurnEvent,
  type TurnSource,
} from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createSession: vi.fn(),
  listDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  uploadDocumentWithProgress: vi.fn(),
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

const CONTRACT_QUOTE = "Either party may terminate this agreement by giving three months’ notice.";
const ANNEX_QUOTE = "The notice period may be reduced only by mutual written agreement.";

const mockedSession = vi.mocked(createSession);
const mockedList = vi.mocked(listDocuments);
const mockedDelete = vi.mocked(deleteDocument);
const mockedUpload = vi.mocked(uploadDocumentWithProgress);
const mockedCreate = vi.mocked(createConversation);
const mockedGet = vi.mocked(getConversation);
const mockedStream = vi.mocked(streamQuestion);

function readyDocument(id: string, name: string): DocumentInfo {
  return {
    id,
    display_name: name,
    state: "ready",
    error_code: null,
    page_count: 14,
    progress: null,
    created_at: `2026-11-20T10:00:0${id}Z`,
  };
}

const DOCUMENT_IDS: Record<string, string> = { "employment-contract.pdf": "1", "annex-b.pdf": "2" };

function source(label: string, cited: boolean, name: string, page: number, quote: string): TurnSource {
  return {
    label,
    cited,
    document_id: DOCUMENT_IDS[name] ?? name,
    document_name: name,
    pages: { start: page, end: page },
    quote,
  };
}

async function* events(...items: TurnEvent[]): AsyncGenerator<TurnEvent> {
  for (const item of items) {
    yield item;
  }
}

interface Viewport {
  showModal: ReturnType<typeof vi.fn>;
}

// jsdom has neither matchMedia nor the modal dialog methods; width drives the min-width queries.
function setViewport(width: number): Viewport {
  const showModal = vi.fn(function (this: HTMLDialogElement): void {
    this.setAttribute("open", "");
  });
  HTMLDialogElement.prototype.showModal = showModal;
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement): void {
    this.removeAttribute("open");
  };
  vi.stubGlobal(
    "matchMedia",
    (query: string): MediaQueryList =>
      ({
        matches: width >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0),
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
  return { showModal };
}

function pdf(name: string): File {
  return new File(["%PDF-1.7"], name, { type: "application/pdf" });
}

function fileInput(): HTMLInputElement {
  return document.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
}

function dropFiles(...files: File[]): void {
  const event: Event = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", {
    value: { types: ["Files"], items: { length: files.length }, files },
  });
  act(() => {
    window.dispatchEvent(event);
  });
}

async function askWithCitations(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  mockedList.mockResolvedValue([
    readyDocument("1", "employment-contract.pdf"),
    readyDocument("2", "annex-b.pdf"),
  ]);
  mockedStream.mockReturnValue(
    events(
      { type: "delta", text: "Three months [S1], shortened by agreement [S2]." },
      {
        type: "sources",
        sources: [
          source("S1", true, "employment-contract.pdf", 4, CONTRACT_QUOTE),
          source("S2", true, "annex-b.pdf", 2, ANNEX_QUOTE),
        ],
        invalidCitationLabels: [],
      },
      { type: "done" },
    ),
  );
  render(<AppPage />);
  await screen.findByText("Answering from 2 of 2 documents");
  await user.type(screen.getByLabelText("Question"), "How long is the notice period?");
  await user.click(screen.getByRole("button", { name: "Ask" }));
  await screen.findByRole("button", { name: "Show evidence" });
}

beforeEach(() => {
  window.sessionStorage.clear();
  mockedSession.mockResolvedValue({ limits } as Awaited<ReturnType<typeof createSession>>);
  mockedList.mockResolvedValue([]);
  mockedCreate.mockResolvedValue("c1");
});

afterEach(() => {
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

describe("AppPage", () => {
  it("shows the header and the first-visit empty state without documents", async () => {
    render(<AppPage />);

    expect(await screen.findByText("Ask questions about your PDFs")).toBeTruthy();
    expect(
      screen.getByText("Files and answers are deleted 24 hours after your last activity."),
    ).toBeTruthy();
    expect(screen.getByText("Evidence for each answer appears here.")).toBeTruthy();
    expect(mockedUpload).not.toHaveBeenCalled();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("marks the evidence of a clicked citation after a streamed answer", async () => {
    mockedList.mockResolvedValue([
      readyDocument("1", "employment-contract.pdf"),
      readyDocument("2", "annex-b.pdf"),
    ]);
    mockedStream.mockReturnValue(
      events(
        { type: "delta", text: "Three months [S1], shortened by agreement [S2]." },
        {
          type: "sources",
          sources: [
            source("S1", true, "employment-contract.pdf", 4, CONTRACT_QUOTE),
            source("S2", true, "annex-b.pdf", 2, ANNEX_QUOTE),
            source("S3", false, "annex-b.pdf", 3, "Not cited."),
          ],
          invalidCitationLabels: [],
        },
        { type: "done" },
      ),
    );
    const user = userEvent.setup();
    render(<AppPage />);
    await screen.findByText("Answering from 2 of 2 documents");

    await user.type(screen.getByLabelText("Question"), "How long is the notice period?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    const evidence: HTMLElement = screen.getByRole("region", { name: "Evidence" });
    const annexQuote: HTMLElement = await within(evidence).findByText(`“${ANNEX_QUOTE}”`);
    const contractQuote: HTMLElement = within(evidence).getByText(`“${CONTRACT_QUOTE}”`);
    expect(contractQuote.className).toMatch(/highlighted/);
    expect(annexQuote.className).not.toMatch(/highlighted/);

    await user.click(screen.getByRole("button", { name: "Source 2" }));

    // Each activation re-creates the quote marks to replay the sweep, so they are looked up again.
    expect(within(evidence).getByText(`“${ANNEX_QUOTE}”`).className).toMatch(/highlighted/);
    expect(within(evidence).getByText(`“${CONTRACT_QUOTE}”`).className).not.toMatch(/highlighted/);
    expect(mockedStream.mock.calls[0][1]).toMatchObject({ documentIds: ["1", "2"] });
  });

  it("scrolls to the evidence again when the same citation is clicked twice", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    try {
      const user = userEvent.setup();
      await askWithCitations(user);
      await user.click(screen.getByRole("button", { name: "Source 2" }));
      const afterFirst: number = scrollIntoView.mock.calls.length;

      await user.click(screen.getByRole("button", { name: "Source 2" }));

      expect(scrollIntoView.mock.calls.length).toBe(afterFirst + 1);
    } finally {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });

  it("moves focus to the first document checkbox from the scope line", async () => {
    mockedList.mockResolvedValue([
      readyDocument("1", "employment-contract.pdf"),
      readyDocument("2", "annex-b.pdf"),
    ]);
    const user = userEvent.setup();
    render(<AppPage />);

    await user.click(await screen.findByRole("button", { name: "Answering from 2 of 2 documents" }));

    expect(document.activeElement).toBe(
      screen.getByRole("checkbox", { name: /employment-contract\.pdf/ }),
    );
  });

  it("shows a document listing failure", async () => {
    mockedList.mockRejectedValue(new ApiError(401, "session_required"));
    render(<AppPage />);

    expect(
      await screen.findByText("Your session has expired. Reload the page to start a new one."),
    ).toBeTruthy();
  });

  it("explains why a PDF dropped on a full session is not uploaded", async () => {
    mockedList.mockResolvedValue(
      Array.from({ length: 10 }, (_: unknown, index: number): DocumentInfo =>
        readyDocument(String(index), `document-${index}.pdf`),
      ),
    );
    render(<AppPage />);
    await screen.findByText("Answering from 10 of 10 documents");

    dropFiles(pdf("one-more.pdf"));

    expect(await screen.findByText("This session can hold up to 10 documents.")).toBeTruthy();
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("disables Ask and updates the scope line when the only selected document is removed", async () => {
    mockedList.mockResolvedValue([
      readyDocument("1", "employment-contract.pdf"),
      readyDocument("2", "annex-b.pdf"),
    ]);
    mockedDelete.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AppPage />);
    await screen.findByText("Answering from 2 of 2 documents");
    await user.click(screen.getByRole("checkbox", { name: /annex-b\.pdf/ }));
    await user.type(screen.getByLabelText("Question"), "How long is the notice period?");
    await screen.findByText("Answering from 1 of 2 documents");
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(false);

    await user.click(screen.getByRole("button", { name: "Remove employment-contract.pdf" }));
    await user.click(within(screen.getByRole("group", { name: /^Remove .+\?/ })).getByRole("button", { name: "Remove" }));

    expect(mockedDelete).toHaveBeenCalledExactlyOnceWith("1");
    expect(
      await screen.findByRole("button", {
        name: "Select at least one ready document to ask a question.",
      }),
    ).toBeTruthy();
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("checkbox", { name: /employment-contract\.pdf/ })).toBeNull();
  });

  it("disables Remove with the reason while an answer is being written", async () => {
    mockedList.mockResolvedValue([readyDocument("1", "employment-contract.pdf")]);
    mockedStream.mockReturnValue(
      (async function* (): AsyncGenerator<TurnEvent> {
        await new Promise<void>(() => {});
      })(),
    );
    const user = userEvent.setup();
    render(<AppPage />);
    await screen.findByText("Answering from 1 of 1 document");
    const remove: HTMLButtonElement = screen.getByRole("button", {
      name: "Remove employment-contract.pdf",
    });
    expect(remove.disabled).toBe(false);

    await user.type(screen.getByLabelText("Question"), "How long is the notice period?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(remove.disabled).toBe(true));
    const reasonId: string = remove.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(reasonId)?.textContent).toBe(
      "An answer is still being written from this document. Remove it when the answer is finished.",
    );
  });

  it("detaches the sources of a removed document from the conversation", async () => {
    mockedList.mockResolvedValue([
      readyDocument("1", "employment-contract.pdf"),
      readyDocument("2", "annex-b.pdf"),
    ]);
    mockedStream.mockReturnValue(
      events(
        { type: "delta", text: "Three months [S1], shortened by agreement [S2]." },
        {
          type: "sources",
          sources: [
            source("S1", true, "employment-contract.pdf", 4, CONTRACT_QUOTE),
            source("S2", true, "annex-b.pdf", 2, ANNEX_QUOTE),
          ],
          invalidCitationLabels: [],
        },
        { type: "done" },
      ),
    );
    mockedDelete.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AppPage />);
    await screen.findByText("Answering from 2 of 2 documents");
    await user.type(screen.getByLabelText("Question"), "How long is the notice period?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    const evidence: HTMLElement = screen.getByRole("region", { name: "Evidence" });
    await within(evidence).findByText(`“${ANNEX_QUOTE}”`);

    await user.click(screen.getByRole("button", { name: "Remove annex-b.pdf" }));
    await user.click(
      within(screen.getByRole("group", { name: /^Remove .+\?/ })).getByRole("button", {
        name: "Remove",
      }),
    );

    await waitFor(() => expect(within(evidence).queryByText(`“${ANNEX_QUOTE}”`)).toBeNull());
    expect(within(evidence).getByText(`“${CONTRACT_QUOTE}”`)).toBeTruthy();
    expect(mockedDelete).toHaveBeenCalledExactlyOnceWith("2");
  });

  it("shows the deleted text for the highlighted quote when its document is removed", async () => {
    mockedDelete.mockResolvedValue(undefined);
    const user = userEvent.setup();
    await askWithCitations(user);
    const evidence: HTMLElement = screen.getByRole("region", { name: "Evidence" });
    expect(within(evidence).getByText(`“${CONTRACT_QUOTE}”`).className).toMatch(/highlighted/);

    await user.click(screen.getByRole("button", { name: "Remove employment-contract.pdf" }));
    await user.click(
      within(screen.getByRole("group", { name: /^Remove .+\?/ })).getByRole("button", {
        name: "Remove",
      }),
    );

    expect(
      await within(evidence).findByText(
        "This document was deleted, so its quote is no longer available.",
      ),
    ).toBeTruthy();
    expect(within(evidence).queryByText(`“${CONTRACT_QUOTE}”`)).toBeNull();
    expect(evidence.querySelector("[class*='highlighted']")).toBeNull();
    expect(screen.getByRole("button", { name: "Source 1, document deleted" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Source 2" })).toBeTruthy();
    expect(screen.getByText("A source of this answer was deleted.")).toBeTruthy();
  });

  it("replaces the columns with an alert when the session cannot start", async () => {
    mockedSession.mockRejectedValue(new ApiError(503, "service_unavailable"));
    render(<AppPage />);

    const alert: HTMLElement = await screen.findByRole("alert");
    expect(alert.textContent).not.toBe("");
    expect(screen.getByRole("heading", { level: 1, name: "Sourcehaven" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("Your documents")).toBeNull());
    expect(mockedList).not.toHaveBeenCalled();
  });

  describe("evidence drawer", () => {
    it("opens from a citation below the three-column width", async () => {
      const { showModal } = setViewport(1024);
      const user = userEvent.setup();
      await askWithCitations(user);
      expect(showModal).not.toHaveBeenCalled();

      await user.click(screen.getByRole("button", { name: "Source 2" }));

      expect(showModal).toHaveBeenCalledTimes(1);
      const drawer: HTMLElement = screen.getByRole("dialog", { name: "Evidence" });
      expect(within(drawer).getByText(`“${ANNEX_QUOTE}”`).className).toMatch(/highlighted/);
    });

    it("opens from Show evidence below the three-column width", async () => {
      const { showModal } = setViewport(1024);
      const user = userEvent.setup();
      await askWithCitations(user);

      await user.click(screen.getByRole("button", { name: "Show evidence" }));

      expect(showModal).toHaveBeenCalledTimes(1);
    });

    it("closes with Close evidence", async () => {
      setViewport(1024);
      const user = userEvent.setup();
      await askWithCitations(user);
      await user.click(screen.getByRole("button", { name: "Show evidence" }));

      await user.click(screen.getByRole("button", { name: "Close evidence" }));

      expect(screen.queryByRole("dialog", { name: "Evidence" })).toBeNull();
    });

    it("stays closed at the three-column width, where the panel is already visible", async () => {
      const { showModal } = setViewport(1440);
      const user = userEvent.setup();
      await askWithCitations(user);

      await user.click(screen.getByRole("button", { name: "Source 2" }));
      await user.click(screen.getByRole("button", { name: "Show evidence" }));

      expect(showModal).not.toHaveBeenCalled();
    });
  });

  describe("documents disclosure", () => {
    function disclosure(): HTMLDetailsElement {
      const summary: HTMLElement = screen.getByText(/^Your documents, \d+ of 10$/);
      return summary.closest("details") as HTMLDetailsElement;
    }

    it("is collapsed on a phone while documents exist and opens from the scope line", async () => {
      setViewport(390);
      mockedList.mockResolvedValue([
        readyDocument("1", "employment-contract.pdf"),
        readyDocument("2", "annex-b.pdf"),
      ]);
      const user = userEvent.setup();
      render(<AppPage />);

      await user.click(await screen.findByRole("button", { name: "Answering from 2 of 2 documents" }));

      expect(disclosure().open).toBe(true);
      expect(document.activeElement).toBe(
        screen.getByRole("checkbox", { name: /employment-contract\.pdf/ }),
      );
    });

    it("starts collapsed on a phone once documents are listed", async () => {
      setViewport(390);
      mockedList.mockResolvedValue([readyDocument("1", "employment-contract.pdf")]);
      render(<AppPage />);

      await screen.findByText("Answering from 1 of 1 document");

      expect(screen.getByText("Your documents, 1 of 10")).toBeTruthy();
      expect(disclosure().open).toBe(false);
    });

    it("is open on a phone while there are no documents", async () => {
      setViewport(390);
      render(<AppPage />);

      await screen.findByText("Ask questions about your PDFs");

      expect(disclosure().open).toBe(true);
    });

    it("stays open on a phone while an upload is in progress and no document is listed", async () => {
      setViewport(390);
      mockedUpload.mockReturnValue(new Promise<DocumentInfo>(() => {}));
      const user = userEvent.setup();
      render(<AppPage />);
      await screen.findByText("Ask questions about your PDFs");

      await user.upload(fileInput(), pdf("contract.pdf"));

      expect(await screen.findByText("contract.pdf")).toBeTruthy();
      expect(disclosure().open).toBe(true);
    });

    it("keeps the reader's choice on a phone when the documents list changes", async () => {
      setViewport(390);
      let listNow: (listed: DocumentInfo[]) => void = (): void => undefined;
      mockedList.mockReturnValue(
        new Promise<DocumentInfo[]>((resolve: (listed: DocumentInfo[]) => void): void => {
          listNow = resolve;
        }),
      );
      const user = userEvent.setup();
      render(<AppPage />);
      await screen.findByText("Ask questions about your PDFs");
      // Closing and reopening makes "open" the reader's choice, not the default for an empty list.
      await user.click(screen.getByText("Your documents, 0 of 10"));
      await waitFor(() => expect(disclosure().open).toBe(false));
      await user.click(screen.getByText("Your documents, 0 of 10"));
      await waitFor(() => expect(disclosure().open).toBe(true));

      await act(async (): Promise<void> => {
        listNow([readyDocument("1", "employment-contract.pdf")]);
      });

      await screen.findByText("Answering from 1 of 1 document");
      expect(disclosure().open).toBe(true);
    });

    it("opens on a phone when PDFs are chosen while it is collapsed", async () => {
      setViewport(390);
      mockedList.mockResolvedValue([readyDocument("1", "employment-contract.pdf")]);
      mockedUpload.mockReturnValue(new Promise<DocumentInfo>(() => {}));
      const user = userEvent.setup();
      render(<AppPage />);
      await screen.findByText("Answering from 1 of 1 document");
      expect(disclosure().open).toBe(false);

      await user.upload(fileInput(), pdf("annex-b.pdf"));

      expect(await screen.findByText("annex-b.pdf")).toBeTruthy();
      expect(disclosure().open).toBe(true);
    });

    it("opens on a phone when PDFs are dropped while it is collapsed", async () => {
      setViewport(390);
      mockedList.mockResolvedValue([readyDocument("1", "employment-contract.pdf")]);
      mockedUpload.mockReturnValue(new Promise<DocumentInfo>(() => {}));
      render(<AppPage />);
      await screen.findByText("Answering from 1 of 1 document");
      expect(disclosure().open).toBe(false);

      dropFiles(pdf("annex-b.pdf"));

      expect(await screen.findByText("annex-b.pdf")).toBeTruthy();
      expect(disclosure().open).toBe(true);
    });

    it("stays open on a phone once the first upload is listed", async () => {
      setViewport(390);
      mockedUpload.mockResolvedValue(readyDocument("1", "contract.pdf"));
      const user = userEvent.setup();
      render(<AppPage />);
      await screen.findByText("Ask questions about your PDFs");

      await user.upload(fileInput(), pdf("contract.pdf"));

      await screen.findByText("Answering from 1 of 1 document");
      expect(disclosure().open).toBe(true);
    });

    it("is always open on wider screens", async () => {
      setViewport(1024);
      mockedList.mockResolvedValue([readyDocument("1", "employment-contract.pdf")]);
      render(<AppPage />);

      await screen.findByText("Answering from 1 of 1 document");

      expect(disclosure().open).toBe(true);
    });
  });
});
