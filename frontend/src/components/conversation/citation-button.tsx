import type { ReactElement } from "react";

import styles from "@/components/conversation/citation-button.module.css";
import { displayLabel } from "@/lib/citations";

export function CitationButton({
  label,
  active,
  onActivate,
}: {
  label: string;
  active: boolean;
  onActivate: (label: string) => void;
}): ReactElement {
  const shown: string = displayLabel(label);
  return (
    <button
      type="button"
      className={styles.citation}
      aria-pressed={active}
      aria-label={`Source ${shown}`}
      onClick={() => onActivate(label)}
    >
      [{shown}]
    </button>
  );
}
