import { useId, useLayoutEffect, useRef, type ReactElement, type RefObject } from "react";

import { Composer } from "@/components/conversation/composer";
import styles from "@/components/conversation/conversation-panel.module.css";
import { EmptyState } from "@/components/conversation/empty-state";
import { TurnView } from "@/components/conversation/turn-view";
import type { DocumentInfo, SessionLimits } from "@/lib/api";
import { readySelectedIds } from "@/lib/selection";
import type { TurnViewModel } from "@/lib/use-conversation";

const DEFAULT_MAX_QUESTION_CHARS = 2000;
// How close to the bottom (in pixels) the reader must be for the list to keep following new text.
const FOLLOW_DISTANCE_PX = 48;

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
  const turnsList: RefObject<HTMLDivElement | null> = useRef<HTMLDivElement | null>(null);
  const followLatest: RefObject<boolean> = useRef<boolean>(true);
  const shownTurns: RefObject<number> = useRef<number>(0);

  useLayoutEffect(() => {
    const list: HTMLDivElement | null = turnsList.current;
    if (list === null) {
      return;
    }
    // A new question is always brought into view; a growing answer only while the reader is at
    // the bottom, so scrolling up to reread is not undone by the next streamed token.
    if (turns.length > shownTurns.current) {
      followLatest.current = true;
    }
    shownTurns.current = turns.length;
    if (followLatest.current) {
      list.scrollTop = list.scrollHeight;
    }
  }, [turns]);

  function handleTurnsScroll(): void {
    const list: HTMLDivElement | null = turnsList.current;
    if (list !== null) {
      const distance: number = list.scrollHeight - list.scrollTop - list.clientHeight;
      followLatest.current = distance <= FOLLOW_DISTANCE_PX;
    }
  }

  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <h2 id={headingId} className="visually-hidden">
        Conversation
      </h2>
      {turns.length > 0 ? (
        <div
          ref={turnsList}
          className={styles.turns}
          aria-live="polite"
          onScroll={handleTurnsScroll}
        >
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
