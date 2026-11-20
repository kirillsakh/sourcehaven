import type { ReactElement } from "react";
import Markdown from "react-markdown";

import styles from "@/components/conversation/answer-markdown.module.css";
import { CitationButton } from "@/components/conversation/citation-button";
import { remarkCitations } from "@/lib/citations";

export function AnswerMarkdown({
  text,
  knownLabels,
  activeLabel,
  onCitation,
}: {
  text: string;
  knownLabels: ReadonlySet<string>;
  activeLabel: string | null;
  onCitation: (label: string) => void;
}): ReactElement {
  return (
    <div className={styles.answer}>
      <Markdown
        remarkPlugins={[[remarkCitations, { knownLabels }]]}
        skipHtml
        components={{
          span: ({ node, children }): ReactElement => {
            const label: unknown = node?.properties.dataCitation;
            if (typeof label === "string") {
              return (
                <CitationButton
                  label={label}
                  active={label === activeLabel}
                  onActivate={onCitation}
                />
              );
            }
            if (node?.properties.dataUnmatched === true) {
              return <span className={styles.unmatched}>{children}</span>;
            }
            return <span>{children}</span>;
          },
          a: ({ children }): ReactElement => <span>{children}</span>,
          img: ({ alt }): ReactElement => <span>{alt}</span>,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
