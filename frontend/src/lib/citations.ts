import type { Parents, Root, RootContent, Text } from "mdast";

import { splitCitations } from "@/lib/format";

const SERVER_LABEL = /^S\d+$/;

/** Convert a server source label such as `S3` into the number readers see, such as `3`. */
export function displayLabel(label: string): string {
  return SERVER_LABEL.test(label) ? label.slice(1) : label;
}

function markerNode(label: string, known: boolean): Text {
  const properties = known ? { dataCitation: label } : { dataUnmatched: true };
  return {
    type: "text",
    value: `[${displayLabel(label)}]`,
    data: { hName: "span", hProperties: properties },
  };
}

function splitTextNode(node: Text, knownLabels: ReadonlySet<string>): Text[] {
  return splitCitations(node.value).map((segment) =>
    segment.label === null
      ? { type: "text", value: segment.text }
      : markerNode(segment.label, knownLabels.has(segment.label)),
  );
}

function rewriteChildren(parent: Parents, knownLabels: ReadonlySet<string>): void {
  const children: RootContent[] = parent.children;
  const rewritten: RootContent[] = [];
  for (const child of children) {
    if (child.type === "text") {
      rewritten.push(...splitTextNode(child, knownLabels));
      continue;
    }
    if ("children" in child) {
      rewriteChildren(child, knownLabels);
    }
    rewritten.push(child);
  }
  children.splice(0, children.length, ...rewritten);
}

/**
 * Remark plugin that turns `[S1]`-style markers in text nodes into spans.
 *
 * Markers whose label is in `knownLabels` carry a `data-citation` attribute with the server
 * label; any other marker becomes a `data-unmatched` span showing only the number. Code spans and
 * code blocks are literal nodes, not text nodes, so they are never touched.
 */
export function remarkCitations(options: {
  knownLabels: ReadonlySet<string>;
}): (tree: Root) => void {
  return (tree: Root): void => {
    rewriteChildren(tree, options.knownLabels);
  };
}
