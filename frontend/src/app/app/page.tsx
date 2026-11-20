"use client";

import {
  useCallback,
  useRef,
  useState,
  type ReactElement,
  type RefObject,
  type ToggleEvent,
} from "react";
import { flushSync } from "react-dom";

import styles from "@/app/app/page.module.css";
import { AppHeader } from "@/components/app-header";
import { ConversationPanel } from "@/components/conversation/conversation-panel";
import { DocumentsPanel } from "@/components/documents/documents-panel";
import { DropOverlay } from "@/components/documents/drop-overlay";
import { EvidenceDrawer } from "@/components/evidence/evidence-drawer";
import { EvidencePanel } from "@/components/evidence/evidence-panel";
import { DOCUMENT_IN_USE_TEXT } from "@/lib/messages";
import { useConversation, type ConversationState, type TurnViewModel } from "@/lib/use-conversation";
import { useDocuments, type DocumentsState } from "@/lib/use-documents";
import { useSession, type SessionState } from "@/lib/use-session";
import {
  matchesQuery,
  TWO_COLUMN_QUERY,
  useMediaQuery,
  WIDE_LAYOUT_QUERY,
} from "@/lib/viewport";

export default function AppPage(): ReactElement {
  const { limits, error: startError }: SessionState = useSession();
  const documents: DocumentsState = useDocuments(limits);
  const conversation: ConversationState = useConversation(limits);
  const documentList: RefObject<HTMLUListElement | null> = useRef<HTMLUListElement | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [phoneDocumentsOpen, setPhoneDocumentsOpen] = useState<boolean | null>(null);
  const twoColumns: boolean = useMediaQuery(TWO_COLUMN_QUERY);
  const threeColumns: boolean = useMediaQuery(WIDE_LAYOUT_QUERY);

  const { activeTurnKey, activate }: ConversationState = conversation;
  const activeTurn: TurnViewModel | null =
    conversation.turns.find((turn: TurnViewModel) => turn.key === activeTurnKey) ?? null;
  const noDocuments: boolean = documents.documents.length === 0;
  // From 800px the documents are a plain column, so the disclosure is held open and its summary
  // hidden; on a phone the reader's choice wins over the default of open until a document is listed.
  const documentsOpen: boolean = twoColumns || (phoneDocumentsOpen ?? noDocuments);

  const { addFiles }: DocumentsState = documents;
  // On a phone the upload and rejection rows sit inside the disclosure, so adding files opens it.
  const addFilesAndShow: (files: File[]) => void = useCallback(
    (files: File[]): void => {
      if (files.length > 0) {
        setPhoneDocumentsOpen(true);
      }
      addFiles(files);
    },
    [addFiles],
  );

  // A modal drawer left open would keep the page inert once the evidence column is showing.
  if (threeColumns && drawerOpen) {
    setDrawerOpen(false);
  }

  const { remove }: DocumentsState = documents;
  const { markDocumentDeleted }: ConversationState = conversation;
  const removeDocument: (id: string) => void = useCallback(
    (id: string): void => {
      void remove(id).then((removed: boolean): void => {
        if (removed) {
          markDocumentDeleted(id);
        }
      });
    },
    [remove, markDocumentDeleted],
  );

  function focusDocuments(): void {
    flushSync(() => setPhoneDocumentsOpen(true));
    const list: HTMLUListElement | null = documentList.current;
    const checkbox: HTMLInputElement | null =
      list?.querySelector<HTMLInputElement>('input[type="checkbox"]:not(:disabled)') ?? null;
    (checkbox ?? list)?.focus();
  }

  function activateEvidence(label: string): void {
    if (activeTurnKey !== null) {
      activate(activeTurnKey, label);
    }
  }

  function showEvidence(): void {
    if (!matchesQuery(WIDE_LAYOUT_QUERY)) {
      setDrawerOpen(true);
    }
  }

  function activateTurn(turnKey: string, label?: string): void {
    activate(turnKey, label);
    if (label !== undefined) {
      showEvidence();
    }
  }

  if (startError !== null) {
    return (
      <div className={styles.page}>
        <AppHeader />
        <main className={styles.failed}>
          <p className={styles.alert} role="alert">
            {startError}
          </p>
        </main>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.columns}>
        <details
          className={`${styles.column} ${styles.documents}`}
          open={documentsOpen}
          onToggle={(event: ToggleEvent<HTMLDetailsElement>): void => {
            // Toggle events also follow the open attribute rendered above; only a differing state
            // is the reader's own click on the summary.
            if (event.currentTarget.open !== documentsOpen) {
              setPhoneDocumentsOpen(event.currentTarget.open);
            }
          }}
        >
          <summary className={styles.documentsSummary}>
            {limits === null
              ? "Your documents"
              : `Your documents, ${documents.documents.length} of ${limits.max_documents}`}
          </summary>
          <div className={styles.documentsBody}>
            {documents.pollError !== null && (
              <p className={styles.alert} role="alert">
                {documents.pollError}
              </p>
            )}
            <DocumentsPanel
              limits={limits}
              documents={documents.documents}
              uploads={documents.uploads}
              selected={documents.selected}
              removing={documents.removing}
              removeErrors={documents.removeErrors}
              removeDisabledReason={conversation.generating ? DOCUMENT_IN_USE_TEXT : null}
              onFiles={addFilesAndShow}
              onToggle={documents.toggle}
              onRemove={removeDocument}
              onSelectAll={documents.setAllSelected}
              onDismissUpload={documents.dismissUpload}
              listRef={documentList}
            />
          </div>
        </details>
        <div className={`${styles.column} ${styles.conversation}`}>
          <ConversationPanel
            limits={limits}
            documents={documents.documents}
            selected={documents.selected}
            turns={conversation.turns}
            activeTurnKey={activeTurnKey}
            activeLabel={conversation.activeLabel}
            generating={conversation.generating}
            question={conversation.question}
            askError={conversation.askError}
            onQuestionChange={conversation.setQuestion}
            onAsk={(text: string, documentIds: string[]): void => {
              void conversation.ask(text, documentIds);
            }}
            onStop={conversation.stop}
            onActivate={activateTurn}
            onShowEvidence={showEvidence}
            onFiles={addFilesAndShow}
            onScopeClick={focusDocuments}
          />
        </div>
        <div className={`${styles.column} ${styles.evidence}`}>
          <EvidencePanel
            turn={activeTurn}
            activeLabel={conversation.activeLabel}
            activationCount={conversation.activationCount}
            onActivate={activateEvidence}
          />
        </div>
      </main>
      <EvidenceDrawer open={drawerOpen} onClose={(): void => setDrawerOpen(false)}>
        {drawerOpen && (
          <EvidencePanel
            turn={activeTurn}
            activeLabel={conversation.activeLabel}
            activationCount={conversation.activationCount}
            onActivate={activateEvidence}
          />
        )}
      </EvidenceDrawer>
      <DropOverlay enabled={limits !== null} limits={limits} onFiles={addFilesAndShow} />
    </div>
  );
}
