// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerMarkdown } from "@/components/conversation/answer-markdown";

function renderAnswer(
  text: string,
  knownLabels: string[],
  options: {
    activeLabel?: string | null;
    deletedLabels?: string[];
    onCitation?: (label: string) => void;
    streaming?: boolean;
  } = {},
): ReturnType<typeof render> {
  return render(
    <AnswerMarkdown
      text={text}
      knownLabels={new Set(knownLabels)}
      deletedLabels={new Set(options.deletedLabels ?? [])}
      activeLabel={options.activeLabel ?? null}
      onCitation={options.onCitation ?? vi.fn()}
      streaming={options.streaming ?? false}
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

  it("renders headings as paragraphs so answers add nothing to the page outline", () => {
    const { container } = renderAnswer("## Title\n\nBody text.", []);

    expect(container.querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
    expect(screen.getByText("Title").tagName).toBe("P");
  });

  it("marks a streaming answer so the caret follows its last block", () => {
    const { container, rerender } = renderAnswer("Three months", [], { streaming: true });
    const answer: Element | null = container.firstElementChild;

    expect(answer?.className).toMatch(/streaming/);
    rerender(
      <AnswerMarkdown
        text="Three months"
        knownLabels={new Set()}
        deletedLabels={new Set()}
        activeLabel={null}
        onCitation={vi.fn()}
        streaming={false}
      />,
    );
    expect(container.firstElementChild?.className).not.toMatch(/streaming/);
  });

  it("calls onCitation with the server label", async () => {
    const onCitation = vi.fn();
    renderAnswer("one [S1] two [S2]", ["S1", "S2"], { onCitation });

    await userEvent.click(screen.getByRole("button", { name: "Source 2" }));

    expect(onCitation).toHaveBeenCalledExactlyOnceWith("S2");
  });

  it("names a citation of a deleted document and still activates it", async () => {
    const onCitation = vi.fn();
    renderAnswer("one [S1] two [S2]", ["S1", "S2"], { deletedLabels: ["S1"], onCitation });

    const deleted: HTMLElement = screen.getByRole("button", { name: "Source 1, document deleted" });
    expect(deleted.textContent).toBe("[1]");
    expect(deleted.className).toMatch(/deleted/);
    expect(screen.getByRole("button", { name: "Source 2" }).className).not.toMatch(/deleted/);

    await userEvent.click(deleted);

    expect(onCitation).toHaveBeenCalledExactlyOnceWith("S1");
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
