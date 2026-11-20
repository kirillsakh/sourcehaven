import type { ReactElement } from "react";

import styles from "@/components/app-header.module.css";

export function AppHeader(): ReactElement {
  return (
    <header className={styles.header}>
      <h1 className={styles.wordmark}>
        Source<span className={styles.tail}>haven</span>
      </h1>
      <p className={styles.retention}>
        Files and answers are deleted 24 hours after your last activity.
      </p>
    </header>
  );
}
