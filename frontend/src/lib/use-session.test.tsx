// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, createSession, type SessionInfo } from "@/lib/api";
import { useSession } from "@/lib/use-session";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createSession: vi.fn(),
}));

const mockedCreate = vi.mocked(createSession);

function strict({ children }: { children: ReactNode }): ReactNode {
  return <StrictMode>{children}</StrictMode>;
}

afterEach(() => {
  vi.resetAllMocks();
});

describe("useSession", () => {
  it("creates the session once, even under strict-mode double effects", async () => {
    const session: SessionInfo = {
      idle_expires_at: "2026-11-21T00:00:00Z",
      absolute_expires_at: "2026-11-22T00:00:00Z",
      limits: {
        max_documents: 10,
        max_pages_per_document: 300,
        max_upload_bytes: 1024,
        max_question_chars: 2000,
      },
    };
    mockedCreate.mockResolvedValue(session);

    const { result } = renderHook(() => useSession(), { wrapper: strict });

    await waitFor(() => expect(result.current.limits).toEqual(session.limits));
    expect(result.current.error).toBeNull();
    expect(mockedCreate).toHaveBeenCalledTimes(1);
  });

  it("exposes a visitor-facing message when the session cannot be started", async () => {
    mockedCreate.mockRejectedValue(new ApiError(429, "rate_limited", "Too many sessions"));

    const { result } = renderHook(() => useSession());

    await waitFor(() => expect(result.current.error).toBe("Too many sessions"));
    expect(result.current.limits).toBeNull();
  });
});
