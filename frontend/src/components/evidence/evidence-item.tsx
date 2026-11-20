import { useEffect, useRef, type ReactElement, type RefObject } from "react";

import styles from "@/components/evidence/evidence-panel.module.css";
import type { TurnSource } from "@/lib/api";
import { displayLabel } from "@/lib/citations";
import { formatPages } from "@/lib/format";

const DELETED_TEXT = "This document was deleted, so its quote is no longer available.";

/**
 * Show one passage with its document and pages, highlighted while it is the active source.
 *
 * Every new `activation` number scrolls an active item into view again and replays the
 * highlighter sweep, so clicking the same citation twice is not a silent no-op. A deleted source
 * has no quote to mark: it shows a notice and is never highlighted, even while active.
 */
export function EvidenceItem({
  source,
  active,
  activation,
  onActivate,
}: {
  source: TurnSource;
  active: boolean;
  activation: number;
  onActivate: (label: string) => void;
}): ReactElement {
  const item: RefObject<HTMLLIElement | null> = useRef<HTMLLIElement | null>(null);
  const shown: string = displayLabel(source.label);
  const deleted: boolean = source.document_id === null;

  useEffect(() => {
    const element: HTMLLIElement | null = item.current;
    // jsdom and some older browsers do not implement scrollIntoView.
    if (active && element !== null && typeof element.scrollIntoView === "function") {
      element.scrollIntoView({ block: "nearest" });
    }
  }, [active, activation]);

  return (
    <li ref={item} className={styles.item}>
      <button
        type="button"
        className={styles.label}
        aria-pressed={active}
        aria-label={`Highlight source ${shown}`}
        onClick={(): void => onActivate(source.label)}
      >
        [{shown}]
      </button>
      <div className={styles.body}>
        <p className={styles.from}>
          <strong className={styles.document}>{source.document_name}</strong>,{" "}
          {formatPages(source.pages.start, source.pages.end)}
        </p>
        {deleted ? (
          <p className={styles.deletedQuote}>{DELETED_TEXT}</p>
        ) : (
          <blockquote className={styles.quote}>
            <span key={activation} className={active ? styles.highlighted : undefined}>
              &ldquo;{source.quote}&rdquo;
            </span>
          </blockquote>
        )}
      </div>
    </li>
  );
}
