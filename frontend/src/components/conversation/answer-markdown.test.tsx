// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerMarkdown } from "@/components/conversation/answer-markdown";

function renderAnswer(
  text: string,
  knownLabels: string[],
  options: { activeLabel?: string | null; onCitation?: (label: string) => void } = {},
): ReturnType<typeof render> {
  return render(
    <AnswerMarkdown
      text={text}
      knownLabels={new Set(knownLabels)}
      activeLabel={options.activeLabel ?? null}
      onCitation={options.onCitation ?? vi.fn()}
    />,
  );
}

describe("AnswerMarkdown", () => {
  it("renders Markdown structure", () => {
    const { container } = renderAnswer("**three months**\n\n- one [S1]\n- two [S2]", ["S1", "S2"]);

    expect(container.querySelector("strong")?.textContent).toBe("three months");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Source 1" }).textContent).toBe("[1]");
    expect(screen.getByRole("button", { name: "Source 2" }).textContent).toBe("[2]");
  });

  it("calls onCitation with the server label", async () => {
    const onCitation = vi.fn();
    renderAnswer("one [S1] two [S2]", ["S1", "S2"], { onCitation });

    await userEvent.click(screen.getByRole("button", { name: "Source 2" }));

    expect(onCitation).toHaveBeenCalledExactlyOnceWith("S2");
  });

  it("marks the active citation", () => {
    renderAnswer("one [S1] two [S2]", ["S1", "S2"], { activeLabel: "S1" });

    expect(screen.getByRole("button", { name: "Source 1" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByRole("button", { name: "Source 2" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("shows unknown markers as plain [n] text", () => {
    const { container } = renderAnswer("see [S9]", ["S1"]);

    expect(screen.queryByRole("button")).toBeNull();
    expect(container.textContent).toContain("[9]");
    expect(container.textContent).not.toContain("S9");
  });

  it("keeps markers in code literal", () => {
    const { container } = renderAnswer("`[S1]`", ["S1"]);

    expect(container.querySelector("code")?.textContent).toBe("[S1]");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps markers in fenced code literal", () => {
    const { container } = renderAnswer("```\n[S1]\n```", ["S1"]);

    expect(container.querySelector("code")?.textContent).toContain("[S1]");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders citations inside emphasis and several in a row", () => {
    renderAnswer("*note [S1][S2]*", ["S1", "S2"]);

    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("does not render raw HTML, images or links", () => {
    const hostile =
      "<img src=x onerror=alert(1)> ![pic](http://evil.test/x.png) " +
      "[click](javascript:alert(1)) [site](https://example.com)";
    const { container } = renderAnswer(hostile, ["S1"]);

    expect(container.querySelector("img, script, a, [src], [href]")).toBeNull();
    expect(container.textContent).toContain("click");
    expect(container.textContent).toContain("site");
    expect(container.textContent).toContain("pic");
  });
});
