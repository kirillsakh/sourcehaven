// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AppPage from "@/app/app/page";
import {
  ApiError,
  createConversation,
  createSession,
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

function source(label: string, cited: boolean, name: string, page: number, quote: string): TurnSource {
  return {
    label,
    cited,
    document_id: name,
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

beforeEach(() => {
  window.sessionStorage.clear();
  mockedSession.mockResolvedValue({ limits } as Awaited<ReturnType<typeof createSession>>);
  mockedList.mockResolvedValue([]);
  mockedCreate.mockResolvedValue("c1");
});

afterEach(() => {
  vi.resetAllMocks();
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

    expect(annexQuote.className).toMatch(/highlighted/);
    expect(contractQuote.className).not.toMatch(/highlighted/);
    expect(mockedStream.mock.calls[0][1]).toMatchObject({ documentIds: ["1", "2"] });
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

  it("replaces the columns with an alert when the session cannot start", async () => {
    mockedSession.mockRejectedValue(new ApiError(503, "service_unavailable"));
    render(<AppPage />);

    const alert: HTMLElement = await screen.findByRole("alert");
    expect(alert.textContent).not.toBe("");
    expect(screen.getByRole("heading", { level: 1, name: "Sourcehaven" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("Your documents")).toBeNull());
    expect(mockedList).not.toHaveBeenCalled();
  });
});
