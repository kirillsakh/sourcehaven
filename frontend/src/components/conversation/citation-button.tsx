import type { ReactElement } from "react";

import styles from "@/components/conversation/citation-button.module.css";
import { displayLabel } from "@/lib/citations";

export function CitationButton({
  label,
  active,
  deleted,
  onActivate,
}: {
  label: string;
  active: boolean;
  deleted: boolean;
  onActivate: (label: string) => void;
}): ReactElement {
  const shown: string = displayLabel(label);
  return (
    <button
      type="button"
      className={deleted ? `${styles.citation} ${styles.deleted}` : styles.citation}
      aria-pressed={active}
      aria-label={deleted ? `Source ${shown}, document deleted` : `Source ${shown}`}
      onClick={() => onActivate(label)}
    >
      [{shown}]
    </button>
  );
}
