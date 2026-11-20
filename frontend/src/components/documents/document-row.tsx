import { useId, type ReactElement } from "react";

import styles from "@/components/documents/document-row.module.css";
import type { DocumentInfo } from "@/lib/api";
import { documentStatus, type DocumentStatus } from "@/lib/messages";
import type { UploadRow } from "@/lib/use-documents";

function StatusLine({
  status,
  name,
  id,
}: {
  status: DocumentStatus;
  name: string;
  id: string;
}): ReactElement {
  return (
    <>
      <p id={id} className={`${styles.status} ${styles[status.tone]}`}>
        <span className={styles.word}>{status.word}</span>
        {status.detail !== null && <span className={styles.detail}>{status.detail}</span>}
      </p>
      {status.progress !== null && (
        <Bar progress={status.progress} label={`${status.word} ${name}`} />
      )}
    </>
  );
}

function Bar({
  progress,
  label,
}: {
  progress: { value: number; max: number };
  label: string;
}): ReactElement {
  // A zero total would make the browser fall back to its own max of 1 and show a bogus bar.
  return progress.max > 0 ? (
    <progress className={styles.bar} value={progress.value} max={progress.max} aria-label={label} />
  ) : (
    <progress className={styles.bar} aria-label={label} />
  );
}

export function DocumentRow({
  document,
  checked,
  onToggle,
}: {
  document: DocumentInfo;
  checked: boolean;
  onToggle: (id: string) => void;
}): ReactElement {
  const checkboxId: string = useId();
  const statusId: string = useId();
  const status: DocumentStatus = documentStatus(document);

  return (
    <li className={styles.row}>
      <input
        id={checkboxId}
        type="checkbox"
        className={styles.checkbox}
        checked={checked}
        disabled={document.state !== "ready"}
        aria-describedby={statusId}
        onChange={(): void => onToggle(document.id)}
      />
      <div className={styles.body}>
        <label htmlFor={checkboxId} className={styles.name}>
          {document.display_name}
        </label>
        <StatusLine status={status} name={document.display_name} id={statusId} />
      </div>
    </li>
  );
}

export function UploadItem({
  upload,
  onDismiss,
}: {
  upload: UploadRow;
  onDismiss: (key: string) => void;
}): ReactElement {
  const nameId: string = useId();
  const statusId: string = useId();

  return (
    <li className={styles.row}>
      <span aria-hidden="true" />
      <div className={styles.body}>
        <p id={nameId} className={styles.name}>
          {upload.name}
        </p>
        {upload.status === "uploading" ? (
          <StatusLine
            id={statusId}
            name={upload.name}
            status={{
              word: "Uploading",
              tone: "warn",
              detail: `${Math.round(upload.fraction * 100)}%`,
              progress: { value: upload.fraction, max: 1 },
            }}
          />
        ) : (
          <>
            <p className={`${styles.status} ${styles.bad}`}>{upload.reason}</p>
            <button
              type="button"
              className={styles.dismiss}
              aria-describedby={nameId}
              onClick={(): void => onDismiss(upload.key)}
            >
              Dismiss
            </button>
          </>
        )}
      </div>
    </li>
  );
}
