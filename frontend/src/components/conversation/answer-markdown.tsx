import type { ReactElement, ReactNode } from "react";
import Markdown from "react-markdown";

import styles from "@/components/conversation/answer-markdown.module.css";
import { CitationButton } from "@/components/conversation/citation-button";
import { remarkCitations } from "@/lib/citations";

// The page's own headings structure the screen; an answer's headings are styled text only.
function AnswerHeading({ children }: { children?: ReactNode }): ReactElement {
  return <p className={styles.heading}>{children}</p>;
}

/**
 * Render an answer's Markdown without raw HTML, links or images, with known `[S n]` markers as
 * citation buttons.
 *
 * While `streaming`, a blinking caret is drawn after the last block of the text.
 */
export function AnswerMarkdown({
  text,
  knownLabels,
  activeLabel,
  onCitation,
  streaming,
}: {
  text: string;
  knownLabels: ReadonlySet<string>;
  activeLabel: string | null;
  onCitation: (label: string) => void;
  streaming: boolean;
}): ReactElement {
  return (
    <div className={streaming ? `${styles.answer} ${styles.streaming}` : styles.answer}>
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
          h1: AnswerHeading,
          h2: AnswerHeading,
          h3: AnswerHeading,
          h4: AnswerHeading,
          h5: AnswerHeading,
          h6: AnswerHeading,
          a: ({ children }): ReactElement => <span>{children}</span>,
          img: ({ alt }): ReactElement => <span>{alt}</span>,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
