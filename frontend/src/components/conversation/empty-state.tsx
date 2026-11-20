import type { ReactElement } from "react";

import styles from "@/components/conversation/empty-state.module.css";
import { DropTray } from "@/components/documents/drop-tray";
import type { SessionLimits } from "@/lib/api";

export function EmptyState({
  limits,
  onFiles,
}: {
  limits: SessionLimits | null;
  onFiles: (files: File[]) => void;
}): ReactElement {
  return (
    <div className={styles.empty}>
      <h3 className={styles.heading}>Ask questions about your PDFs</h3>
      <p className={styles.line}>Every answer shows the passages it came from.</p>
      <div className={styles.tray}>
        <DropTray limits={limits} disabled={limits === null} onFiles={onFiles} large />
      </div>
    </div>
  );
}
