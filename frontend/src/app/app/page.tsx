"use client";

import { useRef, type ReactElement, type RefObject } from "react";

import styles from "@/app/app/page.module.css";
import { AppHeader } from "@/components/app-header";
import { ConversationPanel } from "@/components/conversation/conversation-panel";
import { DocumentsPanel } from "@/components/documents/documents-panel";
import { DropOverlay } from "@/components/documents/drop-overlay";
import { EvidencePanel } from "@/components/evidence/evidence-panel";
import { useConversation, type ConversationState, type TurnViewModel } from "@/lib/use-conversation";
import { useDocuments, type DocumentsState } from "@/lib/use-documents";
import { useSession, type SessionState } from "@/lib/use-session";

export default function AppPage(): ReactElement {
  const { limits, error: startError }: SessionState = useSession();
  const documents: DocumentsState = useDocuments(limits);
  const conversation: ConversationState = useConversation(limits);
  const documentList: RefObject<HTMLUListElement | null> = useRef<HTMLUListElement | null>(null);

  const { activeTurnKey, activate }: ConversationState = conversation;
  const activeTurn: TurnViewModel | null =
    conversation.turns.find((turn: TurnViewModel) => turn.key === activeTurnKey) ?? null;
  const uploadsAllowed: boolean =
    limits !== null && documents.documents.length < limits.max_documents;

  function focusDocuments(): void {
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

  // Below the three-column width the evidence panel is not shown yet; this is where it opens.
  function showEvidence(): void {}

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
        <div className={`${styles.column} ${styles.documents}`}>
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
            onFiles={documents.addFiles}
            onToggle={documents.toggle}
            onSelectAll={documents.setAllSelected}
            onDismissUpload={documents.dismissUpload}
            listRef={documentList}
          />
        </div>
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
            onActivate={activate}
            onShowEvidence={showEvidence}
            onFiles={documents.addFiles}
            onScopeClick={focusDocuments}
          />
        </div>
        <div className={`${styles.column} ${styles.evidence}`}>
          <EvidencePanel
            turn={activeTurn}
            activeLabel={conversation.activeLabel}
            onActivate={activateEvidence}
          />
        </div>
      </main>
      <DropOverlay enabled={uploadsAllowed} limits={limits} onFiles={documents.addFiles} />
    </div>
  );
}
