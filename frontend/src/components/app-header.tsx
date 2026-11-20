import type { ReactElement } from "react";

import styles from "@/components/app-header.module.css";
import { BrandMark } from "@/components/brand-mark";

export function AppHeader(): ReactElement {
  return (
    <header className={styles.header}>
      <h1 className={styles.wordmark}>
        <BrandMark size={24} />
        <span>
          Source<span className={styles.tail}>haven</span>
        </span>
      </h1>
      <p className={styles.retention}>
        Files and answers are deleted 24 hours after your last activity.
      </p>
    </header>
  );
}
