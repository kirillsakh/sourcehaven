// @vitest-environment jsdom
import { act, renderHook, type RenderHookResult } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  deleteDocument,
  listDocuments,
  uploadDocumentWithProgress,
  type DocumentInfo,
  type SessionLimits,
} from "@/lib/api";
import { useDocuments } from "@/lib/use-documents";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  deleteDocument: vi.fn(),
  listDocuments: vi.fn(),
  uploadDocumentWithProgress: vi.fn(),
}));

const limits: SessionLimits = {
  max_documents: 10,
  max_pages_per_document: 300,
  max_upload_bytes: 20 * 1024 * 1024,
  max_question_chars: 2000,
};

const mockedDelete = vi.mocked(deleteDocument);
const mockedList = vi.mocked(listDocuments);
const mockedUpload = vi.mocked(uploadDocumentWithProgress);

function doc(id: string, state: DocumentInfo["state"] = "ready", createdAt = id): DocumentInfo {
  return {
    id,
    display_name: `${id}.pdf`,
    state,
    error_code: null,
    page_count: state === "ready" ? 3 : null,
    progress: null,
    created_at: createdAt,
  };
}

function pdf(name: string): File {
  return new File(["x"], name, { type: "application/pdf" });
}

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  let reject: (reason: unknown) => void = () => undefined;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type Mounted = RenderHookResult<ReturnType<typeof useDocuments>, { current: SessionLimits }>;

function mount(): Mounted {
  return renderHook(({ current }) => useDocuments(current), { initialProps: { current: limits } });
}

async function mountWith(initial: DocumentInfo[]): Promise<Mounted> {
  mockedList.mockResolvedValueOnce(initial);
  const hook: Mounted = mount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  return hook;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});

describe("useDocuments", () => {
  it("does not list documents until the limits are known", () => {
    renderHook(() => useDocuments(null));

    expect(mockedList).not.toHaveBeenCalled();
  });

  it("lists documents once the limits are set and selects the ready ones", async () => {
    const { result } = await mountWith([doc("a"), doc("b", "processing")]);

    expect(result.current.documents.map((d) => d.id)).toEqual(["a", "b"]);
    expect([...result.current.selected]).toEqual(["a"]);
  });

  it("creates an uploading row and a rejected row for a mixed drop", async () => {
    mockedUpload.mockReturnValue(deferred<DocumentInfo>().promise);
    const { result } = await mountWith([]);

    act(() => {
      result.current.addFiles([pdf("a.pdf"), new File(["x"], "b.png", { type: "image/png" })]);
    });

    expect(result.current.uploads).toMatchObject([
      { name: "a.pdf", status: "uploading", fraction: 0 },
      { name: "b.png", status: "rejected", reason: "Only PDF files are supported right now." },
    ]);
    expect(mockedUpload).toHaveBeenCalledTimes(1);
  });

  it("uploads only as many files as there are free slots", async () => {
    mockedUpload.mockReturnValue(deferred<DocumentInfo>().promise);
    const nine = Array.from({ length: 9 }, (_, index) => doc(`d${index}`));
    const { result } = await mountWith(nine);

    act(() => {
      result.current.addFiles([pdf("1.pdf"), pdf("2.pdf"), pdf("3.pdf")]);
    });

    expect(mockedUpload).toHaveBeenCalledTimes(1);
    expect(result.current.uploads.filter((row) => row.status === "rejected")).toEqual([
      expect.objectContaining({ reason: "This session can hold up to 10 documents." }),
      expect.objectContaining({ reason: "This session can hold up to 10 documents." }),
    ]);
  });

  it("never runs more than three uploads at once", async () => {
    const pending: Deferred<DocumentInfo>[] = [];
    let inFlight = 0;
    let peak = 0;
    mockedUpload.mockImplementation(() => {
      const upload = deferred<DocumentInfo>();
      pending.push(upload);
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      return upload.promise.finally(() => {
        inFlight -= 1;
      });
    });
    const { result } = await mountWith([]);

    act(() => {
      result.current.addFiles(["1", "2", "3", "4", "5"].map((n) => pdf(`${n}.pdf`)));
    });
    expect(inFlight).toBe(3);

    for (let index = 0; index < 5; index += 1) {
      await act(async () => {
        pending[index].resolve(doc(`n${index}`, "ready", `${index}`));
        await vi.advanceTimersByTimeAsync(0);
      });
    }

    expect(peak).toBe(3);
    expect(mockedUpload).toHaveBeenCalledTimes(5);
    expect(result.current.documents).toHaveLength(5);
  });

  it("updates the row's progress while uploading", async () => {
    mockedUpload.mockImplementation((_file, onProgress) => {
      onProgress(0.4);
      return deferred<DocumentInfo>().promise;
    });
    const { result } = await mountWith([]);

    act(() => {
      result.current.addFiles([pdf("a.pdf")]);
    });

    expect(result.current.uploads[0]).toMatchObject({ status: "uploading", fraction: 0.4 });
  });

  it("removes the row and lists the document after a successful upload", async () => {
    const upload = deferred<DocumentInfo>();
    mockedUpload.mockReturnValue(upload.promise);
    const { result } = await mountWith([]);
    act(() => {
      result.current.addFiles([pdf("a.pdf")]);
    });

    await act(async () => {
      upload.resolve(doc("new", "queued"));
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.uploads).toEqual([]);
    expect(result.current.documents.map((d) => d.id)).toEqual(["new"]);
  });

  it("merges a duplicate upload into the existing document without an error", async () => {
    mockedUpload.mockResolvedValue(doc("a"));
    const { result } = await mountWith([doc("a")]);

    await act(async () => {
      result.current.addFiles([pdf("a.pdf")]);
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.documents).toHaveLength(1);
    expect(result.current.uploads).toEqual([]);
  });

  it("turns a failed upload into a rejected row that can be dismissed", async () => {
    mockedUpload.mockRejectedValue(new ApiError(413, "too_large"));
    const { result } = await mountWith([]);

    await act(async () => {
      result.current.addFiles([pdf("a.pdf")]);
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.uploads).toMatchObject([
      {
        name: "a.pdf",
        status: "rejected",
        reason: "Files can be up to 20 MB. Try splitting or compressing the PDF.",
      },
    ]);

    act(() => {
      result.current.dismissUpload(result.current.uploads[0].key);
    });
    expect(result.current.uploads).toEqual([]);
  });

  it("polls every 2000 ms while something is processing, then stops", async () => {
    mockedList
      .mockResolvedValueOnce([doc("a", "processing")])
      .mockResolvedValueOnce([doc("a", "processing")])
      .mockResolvedValueOnce([doc("a", "ready")]);
    mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockedList).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(mockedList).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockedList).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(mockedList).toHaveBeenCalledTimes(3);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(mockedList).toHaveBeenCalledTimes(3);
  });

  it("does not start a poll while the previous one is still pending", async () => {
    const slow = deferred<DocumentInfo[]>();
    const { result } = await mountWith([doc("a", "processing")]);
    mockedList.mockReturnValueOnce(slow.promise);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(mockedList).toHaveBeenCalledTimes(2);

    await act(async () => {
      slow.resolve([doc("a", "ready")]);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.documents[0].state).toBe("ready");
  });

  it("keeps an uploaded document that a slower poll response does not contain", async () => {
    const slow = deferred<DocumentInfo[]>();
    const { result } = await mountWith([doc("a", "processing", "1")]);
    mockedList.mockReturnValueOnce(slow.promise);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    mockedUpload.mockResolvedValue(doc("b", "queued", "2"));
    await act(async () => {
      result.current.addFiles([pdf("b.pdf")]);
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      slow.resolve([doc("a", "processing", "1")]);
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.documents.map((d) => d.id)).toEqual(["a", "b"]);
  });

  it("auto-selects a document that turns ready and supports select all and none", async () => {
    mockedList.mockResolvedValueOnce([doc("a", "ready", "1"), doc("b", "processing", "2")]);
    const { result } = mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect([...result.current.selected]).toEqual(["a"]);

    mockedList.mockResolvedValueOnce([doc("a", "ready", "1"), doc("b", "ready", "2")]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect([...result.current.selected].sort()).toEqual(["a", "b"]);

    act(() => {
      result.current.setAllSelected(false);
    });
    expect(result.current.selected.size).toBe(0);

    act(() => {
      result.current.setAllSelected(true);
    });
    expect([...result.current.selected].sort()).toEqual(["a", "b"]);

    act(() => {
      result.current.toggle("a");
    });
    expect([...result.current.selected]).toEqual(["b"]);
  });

  it("selects only ready ids when selecting all", async () => {
    const { result } = await mountWith([doc("a", "ready", "1"), doc("b", "failed", "2")]);
    act(() => {
      result.current.setAllSelected(false);
    });

    act(() => {
      result.current.setAllSelected(true);
    });

    expect([...result.current.selected]).toEqual(["a"]);
  });

  it("reports a lost session during polling and stops polling", async () => {
    mockedList
      .mockResolvedValueOnce([doc("a", "processing")])
      .mockRejectedValueOnce(new ApiError(401, "session_required"));
    const { result } = mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(result.current.pollError).toBe(
      "Your session has expired. Reload the page to start a new one.",
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(mockedList).toHaveBeenCalledTimes(2);
  });

  it("keeps polling after a transient poll failure", async () => {
    mockedList
      .mockResolvedValueOnce([doc("a", "processing")])
      .mockRejectedValueOnce(new TypeError("Network error"))
      .mockResolvedValueOnce([doc("a", "ready")]);
    const { result } = mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });

    expect(result.current.pollError).toBeNull();
    expect(result.current.documents[0].state).toBe("ready");
  });

  it("reports a failed first listing, since nothing else would show it", async () => {
    mockedList.mockRejectedValueOnce(new TypeError("Network error"));
    const { result } = mount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.pollError).toBe(
      "The request failed. Check your connection and try again.",
    );
  });

  it("clears the poll error when a later list succeeds", async () => {
    mockedList.mockRejectedValueOnce(new ApiError(401, "session_required"));
    const { result, rerender } = mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.pollError).not.toBeNull();

    mockedList.mockResolvedValueOnce([doc("a")]);
    rerender({ current: { ...limits } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.pollError).toBeNull();
    expect(result.current.documents).toHaveLength(1);
  });

  describe("remove", () => {
    it("drops the document and its selection and reports success", async () => {
      mockedDelete.mockResolvedValue(undefined);
      const { result } = await mountWith([doc("a", "ready", "1"), doc("b", "ready", "2")]);
      expect([...result.current.selected].sort()).toEqual(["a", "b"]);

      let removed = false;
      await act(async () => {
        removed = await result.current.remove("a");
      });

      expect(removed).toBe(true);
      expect(mockedDelete).toHaveBeenCalledWith("a");
      expect(result.current.documents.map((d) => d.id)).toEqual(["b"]);
      expect([...result.current.selected]).toEqual(["b"]);
      expect(result.current.removing.size).toBe(0);
      expect(result.current.removeErrors.size).toBe(0);
    });

    it("marks the id as removing until the request settles", async () => {
      const request = deferred<void>();
      mockedDelete.mockReturnValue(request.promise);
      const { result } = await mountWith([doc("a")]);

      let outcome: Promise<boolean> = Promise.resolve(false);
      act(() => {
        outcome = result.current.remove("a");
      });
      expect([...result.current.removing]).toEqual(["a"]);

      await act(async () => {
        request.resolve();
        await outcome;
      });
      expect(result.current.removing.size).toBe(0);
    });

    it("does not bring the document back when a poll that started before removal resolves", async () => {
      const slow = deferred<DocumentInfo[]>();
      mockedDelete.mockResolvedValue(undefined);
      const { result } = await mountWith([doc("a", "processing", "1"), doc("b", "ready", "2")]);
      mockedList.mockReturnValueOnce(slow.promise);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });

      await act(async () => {
        await result.current.remove("a");
      });
      await act(async () => {
        slow.resolve([doc("a", "ready", "1"), doc("b", "ready", "2")]);
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(result.current.documents.map((d) => d.id)).toEqual(["b"]);
      expect([...result.current.selected]).toEqual(["b"]);
    });

    it("keeps the document and reports the reason when the server refuses", async () => {
      mockedDelete.mockRejectedValue(new ApiError(409, "document_in_use"));
      const { result } = await mountWith([doc("a")]);

      let removed = true;
      await act(async () => {
        removed = await result.current.remove("a");
      });

      expect(removed).toBe(false);
      expect(result.current.documents.map((d) => d.id)).toEqual(["a"]);
      expect([...result.current.selected]).toEqual(["a"]);
      expect(result.current.removeErrors.get("a")).toBe(
        "An answer is still being written from this document. Remove it when the answer is finished.",
      );
      expect(result.current.removing.size).toBe(0);
    });

    it("clears an earlier error when the same document is removed again", async () => {
      mockedDelete.mockRejectedValueOnce(new ApiError(409, "document_in_use"));
      const { result } = await mountWith([doc("a")]);
      await act(async () => {
        await result.current.remove("a");
      });
      expect(result.current.removeErrors.has("a")).toBe(true);

      mockedDelete.mockResolvedValueOnce(undefined);
      await act(async () => {
        await result.current.remove("a");
      });

      expect(result.current.removeErrors.has("a")).toBe(false);
      expect(result.current.documents).toEqual([]);
    });

    it("sends one request when the same document is removed twice at once", async () => {
      const request = deferred<void>();
      mockedDelete.mockReturnValue(request.promise);
      const { result } = await mountWith([doc("a")]);

      const outcomes: boolean[] = [];
      await act(async () => {
        const first: Promise<boolean> = result.current.remove("a");
        const second: Promise<boolean> = result.current.remove("a");
        outcomes.push(await second);
        request.resolve();
        outcomes.push(await first);
      });

      expect(mockedDelete).toHaveBeenCalledTimes(1);
      expect(outcomes).toEqual([false, true]);
    });
  });
});
