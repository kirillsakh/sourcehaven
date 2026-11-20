import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, deleteDocument } from "@/lib/api";

const fetchMock = vi.fn<typeof fetch>();

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function stubFetch(response: Response): void {
  fetchMock.mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
}

describe("deleteDocument", () => {
  it("sends a same-origin DELETE and resolves on 204", async () => {
    stubFetch(new Response(null, { status: 204 }));

    await expect(deleteDocument("d 1")).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith("/api/documents/d%201", {
      credentials: "same-origin",
      method: "DELETE",
    });
  });

  it("rejects with the server's error code on 409", async () => {
    stubFetch(new Response(JSON.stringify({ code: "document_in_use" }), { status: 409 }));

    const failure: unknown = await deleteDocument("d1").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 409, code: "document_in_use" });
  });

  it("rejects with not_found on 404", async () => {
    stubFetch(new Response(JSON.stringify({ code: "not_found" }), { status: 404 }));

    await expect(deleteDocument("d1")).rejects.toMatchObject({ status: 404, code: "not_found" });
  });
});
