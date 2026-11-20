import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type RefObject,
} from "react";

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
  removing,
  removeError,
  removeDisabledReason,
  onToggle,
  onRemove,
}: {
  document: DocumentInfo;
  checked: boolean;
  removing: boolean;
  removeError: string | null;
  removeDisabledReason: string | null;
  onToggle: (id: string) => void;
  onRemove: (id: string) => void;
}): ReactElement {
  const checkboxId: string = useId();
  const statusId: string = useId();
  const questionId: string = useId();
  const reasonId: string = useId();
  const errorId: string = useId();
  const status: DocumentStatus = documentStatus(document);
  const [confirming, setConfirming] = useState<boolean>(false);
  const removeButton: RefObject<HTMLButtonElement | null> = useRef<HTMLButtonElement | null>(null);
  const cancelButton: RefObject<HTMLButtonElement | null> = useRef<HTMLButtonElement | null>(null);
  const returnFocusToRemove: RefObject<boolean> = useRef<boolean>(false);
  const asking: boolean = confirming || removing;
  const disabled: boolean = removeDisabledReason !== null;
  const described: string = [disabled ? reasonId : "", removeError !== null ? errorId : ""]
    .filter((id: string): boolean => id !== "")
    .join(" ");

  // Focus follows the row's state: Cancel when the question opens, and back to Remove once it
  // closes, whether the reader cancelled or the request failed.
  useEffect((): void => {
    if (confirming && !removing) {
      cancelButton.current?.focus();
    } else if (!asking && returnFocusToRemove.current) {
      returnFocusToRemove.current = false;
      removeButton.current?.focus();
    }
  }, [confirming, removing, asking]);

  function cancel(): void {
    returnFocusToRemove.current = true;
    setConfirming(false);
  }

  function confirm(): void {
    returnFocusToRemove.current = true;
    setConfirming(false);
    onRemove(document.id);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "Escape" && !removing) {
      event.stopPropagation();
      cancel();
    }
  }

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
        {removeError !== null && !removing && (
          <p id={errorId} className={`${styles.status} ${styles.bad}`}>
            {removeError}
          </p>
        )}
        {asking && (
          <div
            role="group"
            aria-labelledby={questionId}
            className={styles.confirm}
            onKeyDown={handleKeyDown}
          >
            <p id={questionId} className={styles.question}>
              {removing
                ? "Removing…"
                : `Remove ${document.display_name}? Its quotes in earlier answers will no longer be shown.`}
            </p>
            <div className={styles.choices}>
              <button
                type="button"
                className={`${styles.action} ${styles.danger}`}
                disabled={removing || disabled}
                aria-describedby={disabled ? reasonId : undefined}
                onClick={confirm}
              >
                Remove
              </button>
              <button
                ref={cancelButton}
                type="button"
                className={styles.action}
                disabled={removing}
                onClick={cancel}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        {disabled && (
          <span id={reasonId} className="visually-hidden">
            {removeDisabledReason}
          </span>
        )}
      </div>
      {!asking && (
        <button
          ref={removeButton}
          type="button"
          className={
            document.state === "failed" || removeError !== null
              ? `${styles.remove} ${styles.shown}`
              : styles.remove
          }
          disabled={disabled}
          aria-label={`Remove ${document.display_name}`}
          aria-describedby={described === "" ? undefined : described}
          onClick={(): void => {
            setConfirming(true);
          }}
        >
          Remove
        </button>
      )}
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
