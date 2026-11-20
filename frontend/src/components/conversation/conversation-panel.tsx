import { useId, type ReactElement } from "react";

import { Composer } from "@/components/conversation/composer";
import styles from "@/components/conversation/conversation-panel.module.css";
import { EmptyState } from "@/components/conversation/empty-state";
import { TurnView } from "@/components/conversation/turn-view";
import type { DocumentInfo, SessionLimits } from "@/lib/api";
import { readySelectedIds } from "@/lib/selection";
import type { TurnViewModel } from "@/lib/use-conversation";

const DEFAULT_MAX_QUESTION_CHARS = 2000;

function describeReadyDocuments(ready: readonly DocumentInfo[]): string {
  return ready.length === 1
    ? `Ask something about ${ready[0]?.display_name ?? "your document"}`
    : `Ask something about your ${ready.length} documents`;
}

export function ConversationPanel({
  limits,
  documents,
  selected,
  turns,
  activeTurnKey,
  activeLabel,
  generating,
  question,
  askError,
  onQuestionChange,
  onAsk,
  onStop,
  onActivate,
  onShowEvidence,
  onFiles,
  onScopeClick,
}: {
  limits: SessionLimits | null;
  documents: DocumentInfo[];
  selected: ReadonlySet<string>;
  turns: TurnViewModel[];
  activeTurnKey: string | null;
  activeLabel: string | null;
  generating: boolean;
  question: string;
  askError: string | null;
  onQuestionChange: (text: string) => void;
  onAsk: (text: string, documentIds: string[]) => void;
  onStop: () => void;
  onActivate: (turnKey: string, label?: string) => void;
  onShowEvidence: () => void;
  onFiles: (files: File[]) => void;
  onScopeClick: () => void;
}): ReactElement {
  const headingId: string = useId();
  const ready: DocumentInfo[] = documents.filter(
    (document: DocumentInfo) => document.state === "ready",
  );
  const readySelected: string[] = readySelectedIds(documents, selected);

  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <h2 id={headingId} className="visually-hidden">
        Conversation
      </h2>
      {turns.length > 0 ? (
        <div className={styles.turns} aria-live="polite">
          {turns.map((turn: TurnViewModel) => (
            <TurnView
              key={turn.key}
              turn={turn}
              active={turn.key === activeTurnKey}
              activeLabel={activeLabel}
              onActivate={onActivate}
              onRetry={(text: string): void => onAsk(text, readySelected)}
              onShowEvidence={onShowEvidence}
            />
          ))}
        </div>
      ) : documents.length === 0 ? (
        <EmptyState limits={limits} onFiles={onFiles} />
      ) : (
        <div className={styles.turns}>
          {ready.length > 0 && <p className={styles.hint}>{describeReadyDocuments(ready)}</p>}
        </div>
      )}
      <Composer
        question={question}
        maxChars={limits?.max_question_chars ?? DEFAULT_MAX_QUESTION_CHARS}
        generating={generating}
        readySelected={readySelected.length}
        readyTotal={ready.length}
        error={askError}
        onChange={onQuestionChange}
        onAsk={(): void => onAsk(question, readySelected)}
        onStop={onStop}
        onScopeClick={onScopeClick}
      />
    </section>
  );
}
