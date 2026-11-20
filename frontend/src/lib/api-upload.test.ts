import { describe, expect, it, vi } from "vitest";

import { ApiError, uploadDocumentWithProgress } from "@/lib/api";

class FakeRequest {
  status = 0;
  responseText = "";
  withCredentials = false;
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  openedWith: [string, string] | null = null;
  sent: unknown = null;

  open(method: string, url: string): void {
    this.openedWith = [method, url];
  }

  send(body: unknown): void {
    this.sent = body;
  }

  finish(status: number, body: string): void {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}

function start(): {
  request: FakeRequest;
  onProgress: (fraction: number) => void;
  result: ReturnType<typeof uploadDocumentWithProgress>;
} {
  const request = new FakeRequest();
  const onProgress = vi.fn<(fraction: number) => void>();
  const file = new File(["x"], "a.pdf", { type: "application/pdf" });
  // FakeRequest implements only the XMLHttpRequest members the upload uses.
  const result = uploadDocumentWithProgress(
    file,
    onProgress,
    () => request as unknown as XMLHttpRequest,
  );
  return { request, onProgress, result };
}

describe("uploadDocumentWithProgress", () => {
  it("posts the file as multipart form data", () => {
    const { request } = start();

    expect(request.openedWith).toEqual(["POST", "/api/documents"]);
    expect(request.sent).toBeInstanceOf(FormData);
    expect((request.sent as FormData).get("file")).toBeInstanceOf(File);
  });

  it("reports byte progress as a fraction", () => {
    const { request, onProgress } = start();

    request.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
    request.upload.onprogress?.({ lengthComputable: false, loaded: 1, total: 0 } as ProgressEvent);

    expect(onProgress).toHaveBeenCalledTimes(1);
    expect(onProgress).toHaveBeenCalledWith(0.5);
  });

  it("resolves with the parsed document on success", async () => {
    const { request, result } = start();

    request.finish(201, JSON.stringify({ id: "d1", display_name: "a.pdf", state: "queued" }));

    await expect(result).resolves.toMatchObject({ id: "d1", state: "queued" });
  });

  it("rejects with the server's error code and message", async () => {
    const { request, result } = start();

    request.finish(413, JSON.stringify({ code: "too_large", message: "File too large" }));

    await expect(result).rejects.toMatchObject({
      name: "ApiError",
      status: 413,
      code: "too_large",
      message: "File too large",
    });
    await expect(result).rejects.toBeInstanceOf(ApiError);
  });

  it("falls back to a generic code for a non-JSON error body", async () => {
    const { request, result } = start();

    request.finish(502, "<html>Bad gateway</html>");

    await expect(result).rejects.toMatchObject({ status: 502, code: "unknown_error" });
  });

  it("rejects with a TypeError on a network error", async () => {
    const { request, result } = start();

    request.onerror?.();

    await expect(result).rejects.toThrow(new TypeError("Network error"));
  });
});
