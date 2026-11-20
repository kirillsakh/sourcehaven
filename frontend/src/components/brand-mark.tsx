import type { ReactElement } from "react";

import styles from "@/components/brand-mark.module.css";

/**
 * The Sourcehaven mark: a stack of sources with one cited line.
 *
 * It is decorative; the wordmark next to it carries the name. `app/icon.svg` is the same drawing
 * as a static file, used as the browser-tab icon.
 */
export function BrandMark({ size }: { size: number }): ReactElement {
  return (
    <svg
      className={styles.mark}
      viewBox="0 0 64 64"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <rect className={styles.tile} x="2" y="2" width="60" height="60" rx="14" />
      <rect className={styles.back} x="22" y="9" width="32" height="38" rx="6" />
      <rect className={styles.front} x="10" y="18" width="33" height="39" rx="6" />
      <rect className={styles.line} x="16" y="26" width="21" height="4" rx="2" />
      <rect className={styles.cited} x="16" y="34" width="21" height="7" rx="2" />
      <rect className={styles.line} x="16" y="46" width="13" height="4" rx="2" />
    </svg>
  );
}
