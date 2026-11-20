import { useId, type ReactElement } from "react";

import { EvidenceItem } from "@/components/evidence/evidence-item";
import styles from "@/components/evidence/evidence-panel.module.css";
import type { TurnSource } from "@/lib/api";
import type { TurnViewModel } from "@/lib/use-conversation";

const NO_TURN_TEXT = "Evidence for each answer appears here.";
const GENERATING_TEXT = "Sources appear when the answer is finished.";
const INCOMPLETE_TEXT = "No evidence for an incomplete answer.";
const NO_SOURCES_TEXT = "No sources were cited. Treat this answer with caution.";

function labelNumber(source: TurnSource): number {
  return Number.parseInt(source.label.replace(/^S/, ""), 10);
}

function byLabel(sources: readonly TurnSource[]): TurnSource[] {
  return [...sources].sort((a: TurnSource, b: TurnSource) => labelNumber(a) - labelNumber(b));
}

function describeUncited(count: number): string {
  return count === 1
    ? "1 more passage was read but not cited"
    : `${count} more passages were read but not cited`;
}

function stateText(turn: TurnViewModel | null): string | null {
  if (turn === null) {
    return NO_TURN_TEXT;
  }
  if (turn.status === "generating") {
    return GENERATING_TEXT;
  }
  return turn.status === "complete" ? null : INCOMPLETE_TEXT;
}

function Sources({
  turn,
  activeLabel,
  activationCount,
  onActivate,
}: {
  turn: TurnViewModel;
  activeLabel: string | null;
  activationCount: number;
  onActivate: (label: string) => void;
}): ReactElement {
  const cited: TurnSource[] = byLabel(turn.sources.filter((source: TurnSource) => source.cited));
  const uncited: TurnSource[] = byLabel(
    turn.sources.filter((source: TurnSource) => !source.cited),
  );
  const highlighted: string | null = activeLabel ?? cited[0]?.label ?? null;

  function renderItem(source: TurnSource): ReactElement {
    return (
      <EvidenceItem
        key={source.label}
        source={source}
        active={source.label === highlighted}
        activation={activationCount}
        onActivate={onActivate}
      />
    );
  }

  return (
    <>
      {cited.length > 0 ? (
        <ul className={styles.list} aria-label="Cited passages">
          {cited.map(renderItem)}
        </ul>
      ) : (
        <p className={styles.state}>{NO_SOURCES_TEXT}</p>
      )}
      {uncited.length > 0 && (
        <details className={styles.uncited}>
          <summary className={styles.summary}>{describeUncited(uncited.length)}</summary>
          <ul className={styles.list} aria-label="Passages read but not cited">
            {uncited.map(renderItem)}
          </ul>
        </details>
      )}
    </>
  );
}

/**
 * Show the passages behind the active turn's answer.
 *
 * The quote of `activeLabel` is highlighted and scrolled into view; without a chosen citation the
 * first cited source is. A new `activationCount` replays the highlight and the scroll.
 */
export function EvidencePanel({
  turn,
  activeLabel,
  activationCount,
  onActivate,
}: {
  turn: TurnViewModel | null;
  activeLabel: string | null;
  activationCount: number;
  onActivate: (label: string) => void;
}): ReactElement {
  const headingId: string = useId();
  const state: string | null = stateText(turn);

  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <h2 id={headingId} className={styles.heading}>
        Evidence
      </h2>
      {turn !== null && turn.question !== "" && (
        <p className={styles.for} title={turn.question}>
          For &ldquo;{turn.question}&rdquo;
        </p>
      )}
      {turn === null || state !== null ? (
        <p className={styles.state}>{state}</p>
      ) : (
        // Keyed by turn so switching turns scrolls to the new highlight instead of keeping the old
        // turn's items, which share labels such as S1.
        <Sources
          key={turn.key}
          turn={turn}
          activeLabel={activeLabel}
          activationCount={activationCount}
          onActivate={onActivate}
        />
      )}
    </section>
  );
}
