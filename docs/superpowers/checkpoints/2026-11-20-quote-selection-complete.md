# Checkpoint: quote selection complete (2026-11-20)

M2 piece 1 of 5. Merged into `main` (fast-forward) and pushed at 480bdd1; branch
`m2/quote-selection` deleted. Spec `docs/superpowers/specs/2026-11-20-quote-selection-design.md`
(amended during execution, authoritative), plan `docs/superpowers/plans/2026-11-20-quote-selection.md`.
Executed inline (owner's choice), one independent whole-branch review at the end.

## What was delivered

- A citation's quote is now the passage sentences that best support the answer sentences citing it
  (the question, for uncited passages), up to 300 characters with `…` for skipped text, instead of
  the passage's first 300 characters. Only complete answers; any error or the 2 s limit falls back to
  the passage start and the answer still completes.
- `qa/quotes.py`: sentence splitting that rejoins PDF-wrapped lines, citing-sentence extraction from
  Markdown answers, quote assembly (headings continue with the sentences under them; bare list numbers
  and bullet glyphs dropped; dates and amounts marked with `…`), embedding-similarity selection.
- Passage sentences are embedded in a background task started with generation; after the answer only
  the citing sentences are embedded. `Embedder.embed_queries` added. `Citation.quote` carries the
  quote, so streamed and stored quotes are identical. No API, database or frontend change.
- Measured on the development host with the real TEI and the demo documents: after-answer step p50
  120 ms, p95 175 ms; background embedding p50 1.4 s, p95 2.0 s (details in the spec's Latency).
- Paid demo check (`gpt-5-mini`): CV quotes contain the supporting lines; the job-ad quote that showed
  only "Must-haves" was fixed afterwards (verified with TEI, not re-run with OpenAI).

Checks on 480bdd1: unit 235, integration 143, mypy, Ruff, pre-commit all pass. GitHub CI not checked.

## Owner decisions

- M2 split into five pieces with their own short designs, in order: quote selection; corpus with gold
  text spans and the benchmark harness; parser; splitting; embedding model and threshold (spec §8.5).
- Splitting comparison narrowed to three candidates: current 400/60, about 250 and about 150 tokens.
- Quote shows only the supporting sentences (option A); embedding similarity chosen over word overlap.
- Embed passage sentences while the answer streams; rejoin wrapped lines; continue quoted headings.
- YouTube transcripts parked in the roadmap: `docs/superpowers/research/2026-11-20-youtube-transcripts.md`.

## Rulings made during execution (cost if wrong)

1. Pieces without a letter are dropped from answers too — a label on a letterless line cites nothing.
2. A long line does not join a heading-like next line — a short capitalised wrapped continuation
   without a full stop splits.
3. Skipped dates/numbers become ` … `; a date-only line is never quotable on its own.
4. Heading = at most 4 words, no sentence punctuation, no comma or colon — a short content line such
   as "Python developer" pulls in the lines after it when chosen.
5. Bare list numbers (`1`, `2.`, `3)`) between neighbours vanish unmarked like bullets.

## Open items

- Deferred minors from the review: a label right after a full stop (`days.[S1] Next`) merges two
  citing sentences; pure-Python cosine ranking can block the event loop ~100 ms on long answers;
  indented continuation lines are never joined.
- The heading/list-number change (480bdd1) came after the independent review.
- The owner's running dev `api`/`worker` were built before 480bdd1; rebuild before demos.
- Earlier open items are unchanged (see the document-removal and M1 checkpoints).

## Next: M2 piece 2 — evaluation corpus and benchmark harness

Brainstorm it with `superpowers:brainstorming` before planning. Starting points: spec §8.2 (corpus of
about 5 openly licensed English documents with layouts: contract, two-column paper, manual with
tables, report, book excerpt; about 20 questions incl. at least 3 unanswerable and two conflicting
documents), §8.5 (gold answers as a page plus the exact supporting text, so every parser and splitter
can be scored; quote precision metric), §8.3 acceptance criteria. The harness feeds pieces 3–5 and
the evidence-threshold calibration (the threshold is 0.0 today).
