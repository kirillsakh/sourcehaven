import { useRef, type ChangeEvent, type ReactElement, type RefObject } from "react";

import styles from "@/components/documents/drop-tray.module.css";
import type { SessionLimits } from "@/lib/api";

const BYTES_PER_MEGABYTE = 1024 * 1024;

export function describeLimits(limits: SessionLimits): string {
  const megabytes: number = Math.round(limits.max_upload_bytes / BYTES_PER_MEGABYTE);
  return `Up to ${megabytes} MB and ${limits.max_pages_per_document} pages each`;
}

export function DropTray({
  limits,
  disabled,
  onFiles,
  large = false,
}: {
  limits: SessionLimits | null;
  disabled: boolean;
  onFiles: (files: File[]) => void;
  large?: boolean;
}): ReactElement {
  const input: RefObject<HTMLInputElement | null> = useRef<HTMLInputElement | null>(null);

  function handleChange(event: ChangeEvent<HTMLInputElement>): void {
    const chosen: File[] = Array.from(event.target.files ?? []);
    // Clearing the value lets the same file be chosen again after it was rejected or dismissed.
    event.target.value = "";
    if (chosen.length > 0) {
      onFiles(chosen);
    }
  }

  return (
    <div className={large ? `${styles.tray} ${styles.large}` : styles.tray}>
      <p className={styles.title}>Drop PDFs here</p>
      <p className={styles.hint}>
        or{" "}
        <button
          type="button"
          className={styles.choose}
          disabled={disabled}
          onClick={(): void => input.current?.click()}
        >
          choose files
        </button>
        {limits === null ? "." : `. ${describeLimits(limits)}.`}
      </p>
      {disabled && limits !== null && <p className={styles.full}>This session is full. Remove a document to add another.</p>}
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="visually-hidden"
        tabIndex={-1}
        aria-hidden="true"
        disabled={disabled}
        onChange={handleChange}
      />
    </div>
  );
}
