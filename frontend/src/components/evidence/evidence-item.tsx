import { useEffect, useRef, type ReactElement, type RefObject } from "react";

import styles from "@/components/evidence/evidence-panel.module.css";
import type { TurnSource } from "@/lib/api";
import { displayLabel } from "@/lib/citations";
import { formatPages } from "@/lib/format";

export function EvidenceItem({
  source,
  active,
  onActivate,
}: {
  source: TurnSource;
  active: boolean;
  onActivate: (label: string) => void;
}): ReactElement {
  const item: RefObject<HTMLLIElement | null> = useRef<HTMLLIElement | null>(null);
  const shown: string = displayLabel(source.label);

  useEffect(() => {
    const element: HTMLLIElement | null = item.current;
    // jsdom and some older browsers do not implement scrollIntoView.
    if (active && element !== null && typeof element.scrollIntoView === "function") {
      element.scrollIntoView({ block: "nearest" });
    }
  }, [active]);

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
        <blockquote className={styles.quote}>
          <span className={active ? `${styles.mark} ${styles.highlighted}` : styles.mark}>
            &ldquo;{source.quote}&rdquo;
          </span>
        </blockquote>
      </div>
    </li>
  );
}
