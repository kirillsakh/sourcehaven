import { describe, expect, it } from "vitest";

import { displayLabel } from "@/lib/citations";

describe("displayLabel", () => {
  it("strips the leading S from server labels", () => {
    expect(displayLabel("S3")).toBe("3");
    expect(displayLabel("S12")).toBe("12");
  });

  it("leaves anything else unchanged", () => {
    expect(displayLabel("X1")).toBe("X1");
    expect(displayLabel("S")).toBe("S");
    expect(displayLabel("S1a")).toBe("S1a");
  });
});
