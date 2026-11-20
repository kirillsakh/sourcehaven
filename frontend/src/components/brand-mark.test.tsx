// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppHeader } from "@/components/app-header";
import { BrandMark } from "@/components/brand-mark";

describe("BrandMark", () => {
  it("is decorative, so screen readers skip it", () => {
    const { container } = render(<BrandMark size={24} />);
    const svg: SVGSVGElement | null = container.querySelector("svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.getAttribute("width")).toBe("24");
    expect(svg?.getAttribute("focusable")).toBe("false");
  });
});

describe("AppHeader", () => {
  it("shows the mark next to the wordmark without changing the heading's name", () => {
    const { container } = render(<AppHeader />);
    expect(screen.getByRole("heading", { level: 1, name: "Sourcehaven" })).toBeTruthy();
    expect(container.querySelector("h1 svg[aria-hidden='true']")).not.toBeNull();
  });
});
