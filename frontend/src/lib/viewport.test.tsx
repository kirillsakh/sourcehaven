// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TWO_COLUMN_QUERY, useMediaQuery } from "@/lib/viewport";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useMediaQuery", () => {
  it("subscribes once across re-renders with the same query", () => {
    const addEventListener = vi.fn();
    vi.stubGlobal(
      "matchMedia",
      (query: string): MediaQueryList =>
        ({
          matches: false,
          media: query,
          addEventListener,
          removeEventListener: vi.fn(),
        }) as unknown as MediaQueryList,
    );
    const { result, rerender } = renderHook(() => useMediaQuery(TWO_COLUMN_QUERY));

    rerender();
    rerender();

    expect(result.current).toBe(false);
    expect(addEventListener).toHaveBeenCalledTimes(1);
  });
});
