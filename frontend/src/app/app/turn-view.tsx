import type { ReactElement } from "react";

import type { TurnSource } from "@/lib/api";
import { formatPages, splitCitations } from "@/lib/format";

export interface TurnViewModel {
  key: string;
  status: string;
  question: string;
  text: string;
  sources: TurnSource[];
  invalidCitationLabels: string[];
  errorMessage: string | null;
  retryable: boolean;
}

const STATUS_LABELS: Record<string, string> = {
  generating: "Generating",
  complete: "Complete",
  failed: "Failed",
  interrupted: "Interrupted",
};

function SourceItem({ source }: { source: TurnSource }): ReactElement {
  return (
    <li>
      <span className="chip">{source.label}</span> {source.document_name} &middot;{" "}
      {formatPages(source.pages.start, source.pages.end)}
      <div className="quote">&ldquo;{source.quote}&rdquo;</div>
    </li>
  );
}

export function TurnView({
  turn,
  onRetry,
}: {
  turn: TurnViewModel;
  onRetry: (question: string) => void;
}): ReactElement {
  const cited = turn.sources.filter((source) => source.cited);
  const others = turn.sources.filter((source) => !source.cited);
  const knownLabels: ReadonlySet<string> = new Set(cited.map((source) => source.label));
  const generating = turn.status === "generating";

  return (
    <article className="turn" aria-busy={generating}>
      {turn.question !== "" && <div className="question">Q: {turn.question}</div>}
      <div>
        <span className={`badge ${turn.status}`}>{STATUS_LABELS[turn.status] ?? turn.status}</span>
      </div>
      <p className="answer">
        {splitCitations(turn.text, knownLabels).map((segment, index) =>
          segment.label === null ? (
            <span key={index}>{segment.text}</span>
          ) : (
            <span key={index} className="chip">
              {segment.text}
            </span>
          ),
        )}
        {generating && (
          <span className="cursor" aria-hidden="true">
            &#9611;
          </span>
        )}
      </p>
      {turn.errorMessage !== null && (
        <p className="error" role="alert">
          {turn.errorMessage}{" "}
          {turn.retryable && turn.question !== "" && (
            <button type="button" onClick={() => onRetry(turn.question)}>
              Try again
            </button>
          )}
        </p>
      )}
      {turn.invalidCitationLabels.length > 0 && (
        <p className="muted">Some citation markers could not be matched to sources.</p>
      )}
      {turn.status === "complete" && cited.length === 0 && (
        <p className="muted">No sources cited; treat with caution.</p>
      )}
      {cited.length > 0 && (
        <>
          <h3 className="muted">Sources</h3>
          <ul className="sources">
            {cited.map((source) => (
              <SourceItem key={source.label} source={source} />
            ))}
          </ul>
        </>
      )}
      {others.length > 0 && (
        <details className="other">
          <summary>Other passages consulted ({others.length})</summary>
          <ul className="sources">
            {others.map((source) => (
              <SourceItem key={source.label} source={source} />
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
