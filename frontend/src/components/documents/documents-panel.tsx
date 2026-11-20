import { useId, type ReactElement, type Ref } from "react";

import { DocumentList } from "@/components/documents/document-list";
import styles from "@/components/documents/documents-panel.module.css";
import { DropTray } from "@/components/documents/drop-tray";
import { SelectAll } from "@/components/documents/select-all";
import type { DocumentInfo, SessionLimits } from "@/lib/api";
import { selectAllState, type SelectAllState } from "@/lib/selection";
import type { UploadRow } from "@/lib/use-documents";

export function DocumentsPanel({
  limits,
  documents,
  uploads,
  selected,
  removing,
  removeErrors,
  removeDisabledReason,
  onFiles,
  onToggle,
  onRemove,
  onSelectAll,
  onDismissUpload,
  listRef,
  chooseFilesRef,
}: {
  limits: SessionLimits | null;
  documents: DocumentInfo[];
  uploads: UploadRow[];
  selected: ReadonlySet<string>;
  removing: ReadonlySet<string>;
  removeErrors: ReadonlyMap<string, string>;
  removeDisabledReason: string | null;
  onFiles: (files: File[]) => void;
  onToggle: (id: string) => void;
  onRemove: (id: string) => void;
  onSelectAll: (all: boolean) => void;
  onDismissUpload: (key: string) => void;
  listRef?: Ref<HTMLUListElement>;
  chooseFilesRef?: Ref<HTMLButtonElement>;
}): ReactElement {
  const headingId: string = useId();
  const full: boolean = limits !== null && documents.length >= limits.max_documents;
  const hasReady: boolean = documents.some((document: DocumentInfo) => document.state === "ready");
  const allState: SelectAllState = selectAllState(documents, selected);

  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <header className={styles.header}>
        <h2 id={headingId} className={styles.heading}>
          Your documents
        </h2>
        {limits !== null && (
          <span className={styles.count}>{`${documents.length} of ${limits.max_documents}`}</span>
        )}
      </header>
      <DropTray
        limits={limits}
        disabled={limits === null || full}
        onFiles={onFiles}
        chooseRef={chooseFilesRef}
      />
      {documents.length > 0 && (
        <SelectAll state={allState} disabled={!hasReady} onSelectAll={onSelectAll} />
      )}
      <DocumentList
        documents={documents}
        uploads={uploads}
        selected={selected}
        removing={removing}
        removeErrors={removeErrors}
        removeDisabledReason={removeDisabledReason}
        onToggle={onToggle}
        onRemove={onRemove}
        onDismissUpload={onDismissUpload}
        listRef={listRef}
      />
    </section>
  );
}
