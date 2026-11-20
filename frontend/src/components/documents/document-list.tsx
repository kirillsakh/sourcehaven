import type { ReactElement, Ref } from "react";

import { DocumentRow, UploadItem } from "@/components/documents/document-row";
import styles from "@/components/documents/document-list.module.css";
import type { DocumentInfo } from "@/lib/api";
import type { UploadRow } from "@/lib/use-documents";

export function DocumentList({
  documents,
  uploads,
  selected,
  removing,
  removeErrors,
  removeDisabledReason,
  onToggle,
  onRemove,
  onDismissUpload,
  listRef,
}: {
  documents: DocumentInfo[];
  uploads: UploadRow[];
  selected: ReadonlySet<string>;
  removing: ReadonlySet<string>;
  removeErrors: ReadonlyMap<string, string>;
  removeDisabledReason: string | null;
  onToggle: (id: string) => void;
  onRemove: (id: string) => void;
  onDismissUpload: (key: string) => void;
  listRef?: Ref<HTMLUListElement>;
}): ReactElement {
  if (documents.length === 0 && uploads.length === 0) {
    return <p className={styles.empty}>None yet</p>;
  }
  return (
    <ul ref={listRef} className={styles.list} tabIndex={-1} aria-label="Your documents">
      {documents.map(
        (document: DocumentInfo): ReactElement => (
          <DocumentRow
            key={document.id}
            document={document}
            checked={document.state === "ready" && selected.has(document.id)}
            removing={removing.has(document.id)}
            removeError={removeErrors.get(document.id) ?? null}
            removeDisabledReason={removeDisabledReason}
            onToggle={onToggle}
            onRemove={onRemove}
          />
        ),
      )}
      {uploads.map(
        (upload: UploadRow): ReactElement => (
          <UploadItem key={upload.key} upload={upload} onDismiss={onDismissUpload} />
        ),
      )}
    </ul>
  );
}
