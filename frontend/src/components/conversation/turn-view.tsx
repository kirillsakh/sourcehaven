import { useRef, type ReactElement, type RefObject } from "react";

import { AnswerMarkdown } from "@/components/conversation/answer-markdown";
import styles from "@/components/conversation/turn-view.module.css";
import type { TurnSource } from "@/lib/api";
import type { TurnViewModel } from "@/lib/use-conversation";

const SEARCHING_TEXT = "Searching your documents…";
const NO_SOURCES_TEXT = "No sources were cited. Treat this answer with caution.";
const UNMATCHED_TEXT = "Some citation markers could not be matched to sources.";
// Turns restored after a reload carry a status but no message.
const INCOMPLETE_TEXT = "This answer is incomplete.";
const SOURCE_DELETED_TEXT = "A source of this answer was deleted.";
const SOURCES_DELETED_TEXT = "Some sources of this answer were deleted.";
const FAILED_TEXT = "This answer could not be completed.";

function problemText(turn: TurnViewModel): string | null {
  if (turn.errorMessage !== null) {
    return turn.errorMessage;
  }
  if (turn.status === "interrupted") {
    return INCOMPLETE_TEXT;
  }
  return turn.status === "failed" ? FAILED_TEXT : null;
}

function describeSources(cited: readonly TurnSource[]): string {
  const documents: number = new Set(cited.map((source: TurnSource) => source.document_name)).size;
  return `Sources from ${documents} ${documents === 1 ? "document" : "documents"}`;
}

/**
 * Show one question and its answer.
 *
 * `generating` reports whether any answer in the conversation is being generated; Try again is
 * hidden meanwhile, because a second question cannot start until the first ends.
 */
export function TurnView({
  turn,
  active,
  activeLabel,
  generating,
  onActivate,
  onRetry,
  onShowEvidence,
}: {
  turn: TurnViewModel;
  active: boolean;
  activeLabel: string | null;
  generating: boolean;
  onActivate: (turnKey: string, label?: string) => void;
  onRetry: (question: string) => void;
  onShowEvidence: () => void;
}): ReactElement {
  // A citation click bubbles to the turn; this tells the turn-level handler it was already served.
  const citationHandled: RefObject<boolean> = useRef<boolean>(false);
  const cited: TurnSource[] = turn.sources.filter((source: TurnSource) => source.cited);
  const knownLabels: ReadonlySet<string> = new Set(cited.map((source: TurnSource) => source.label));
  const deletedLabels: ReadonlySet<string> = new Set(
    cited
      .filter((source: TurnSource) => source.document_id === null)
      .map((source: TurnSource) => source.label),
  );
  const streaming: boolean = turn.status === "generating";
  const problem: string | null = problemText(turn);

  function handleTurnClick(): void {
    const alreadyHandled: boolean = citationHandled.current;
    citationHandled.current = false;
    // A drag that selects text to copy it ends with a click; it should not switch the evidence.
    const selectingText: boolean = window.getSelection()?.isCollapsed === false;
    if (!active && !alreadyHandled && !selectingText) {
      onActivate(turn.key);
    }
  }

  function handleCitation(label: string): void {
    citationHandled.current = true;
    onActivate(turn.key, label);
  }

  return (
    <article
      className={active ? `${styles.turn} ${styles.active}` : `${styles.turn} ${styles.past}`}
      aria-busy={streaming}
      aria-current={active ? "true" : undefined}
      onClick={handleTurnClick}
    >
      {turn.question !== "" && <p className={styles.question}>{turn.question}</p>}
      {streaming && turn.text === "" ? (
        <p className={styles.status}>{SEARCHING_TEXT}</p>
      ) : (
        <AnswerMarkdown
          text={turn.text}
          knownLabels={knownLabels}
          deletedLabels={deletedLabels}
          activeLabel={active ? activeLabel : null}
          onCitation={handleCitation}
          streaming={streaming}
        />
      )}
      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem}
          {turn.retryable && turn.question !== "" && !generating && (
            <>
              {" "}
              <button
                type="button"
                className={styles.retry}
                onClick={(): void => onRetry(turn.question)}
              >
                Try again
              </button>
            </>
          )}
        </p>
      )}
      {turn.invalidCitationLabels.length > 0 && <p className={styles.note}>{UNMATCHED_TEXT}</p>}
      {turn.status === "complete" && cited.length === 0 && (
        <p className={styles.note}>{NO_SOURCES_TEXT}</p>
      )}
      {turn.status === "complete" && cited.length > 0 && (
        <p className={styles.note}>
          {describeSources(cited)}
          <button type="button" className={styles.showEvidence} onClick={onShowEvidence}>
            Show evidence
          </button>
        </p>
      )}
      {deletedLabels.size > 0 && (
        <p className={styles.note}>
          {deletedLabels.size === 1 ? SOURCE_DELETED_TEXT : SOURCES_DELETED_TEXT}
        </p>
      )}
    </article>
  );
}
