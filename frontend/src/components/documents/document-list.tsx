import type { ReactElement, Ref } from "react";

import { DocumentRow, UploadItem } from "@/components/documents/document-row";
import styles from "@/components/documents/document-list.module.css";
import type { DocumentInfo } from "@/lib/api";
import type { UploadRow } from "@/lib/use-documents";

export function DocumentList({
  documents,
  uploads,
  selected,
  onToggle,
  onDismissUpload,
  listRef,
}: {
  documents: DocumentInfo[];
  uploads: UploadRow[];
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
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
            onToggle={onToggle}
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
