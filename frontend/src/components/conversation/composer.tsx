import { useId, type FormEvent, type KeyboardEvent, type ReactElement } from "react";

import styles from "@/components/conversation/composer.module.css";
import { scopeLine } from "@/lib/selection";

export function Composer({
  question,
  maxChars,
  generating,
  readySelected,
  readyTotal,
  indexing,
  error,
  onChange,
  onAsk,
  onStop,
  onScopeClick,
}: {
  question: string;
  maxChars: number;
  generating: boolean;
  readySelected: number;
  readyTotal: number;
  indexing: number;
  error: string | null;
  onChange: (text: string) => void;
  onAsk: () => void;
  onStop: () => void;
  onScopeClick: () => void;
}): ReactElement {
  const labelId: string = useId();
  const canAsk: boolean = question.trim() !== "" && readySelected > 0 && !generating;

  function submit(): void {
    if (canAsk) {
      onAsk();
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    // Enter confirms a candidate while an input method editor is composing text.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form className={styles.composer} onSubmit={handleSubmit}>
      <div className={styles.box}>
        <label htmlFor={labelId} className="visually-hidden">
          Question
        </label>
        <textarea
          id={labelId}
          className={styles.input}
          rows={2}
          maxLength={maxChars}
          placeholder="Ask a question about your selected documents"
          value={question}
          onChange={(event): void => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        {generating ? (
          <button type="button" className={styles.stop} onClick={onStop}>
            Stop
          </button>
        ) : (
          <button type="submit" className={styles.ask} disabled={!canAsk}>
            Ask
          </button>
        )}
      </div>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <button type="button" className={styles.scope} onClick={onScopeClick}>
        {scopeLine(readySelected, readyTotal, indexing)}
      </button>
    </form>
  );
}
