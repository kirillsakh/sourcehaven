# Quote selection for citations — design

- **Status:** approved by the owner on 2026-11-20
- **Date:** 2026-11-20
- **Parent:** [`2026-11-19-sourcehaven-design.md`](2026-11-19-sourcehaven-design.md) §7.5, §8.5, §15 (M2)
- **Size:** a small change: no API, database or UI change

Tags as in the parent design: **[A]** agreed with the owner, **[P]** the designer's call.

## M2 context

M2 is split into pieces, each with its own short design, in this order [A, 2026-11-20]:

1. Quote selection (this document).
2. Evaluation corpus with gold text spans, and the benchmark harness.
3. Parser comparison.
4. Splitting comparison.
5. Embedding-model comparison and evidence-threshold calibration.

Gold answers are marked as a page and the exact supporting text, not as passages, so every parser
and splitter can be scored against them and quote precision can be measured [P].

The splitting comparison tests three candidates, all settings changes: the current 400 tokens with
60 overlap, about 250 tokens, and about 150 tokens [A]. Structure-aware splitting is dropped because
pypdf yields no headings; sentence-window retrieval and semantic splitting are dropped because both
multiply embedding work and change how passages are stored, which is not worth it before smaller
passages are shown to fall short [P].

## Intent

A citation's quote is the first 300 characters of its passage (`quote_snapshot` in
`qa/citations.py`). On a short document the passage is the whole document, so the quote is usually
its opening (on the demo CV, the name and contact block) and not the text that supports the claim.
A visitor who checks a citation should see the sentences that back it.

- **Goal:** each quote shows the passage sentences that best support the answer sentences citing
  that source.
- **Non-goals:** highlighting inside a wider window; one quote per claim; changing what the model is
  given or how passages are retrieved; re-selecting quotes of answers already stored.
- **Anti-goals:** a quote that is not verbatim source text (apart from the ellipses marking omitted
  text); an answer that fails or stalls because quote selection failed; logging passage or answer
  text.

## What the visitor sees [A, option A]

Only the supporting sentences, up to 300 characters, with "…" where text is skipped:

```
"…Led the migration of a payments service to Python 3.12 and FastAPI, cutting p95 latency
 by 40%. … Mentored four engineers."
```

The evidence panel, drawer and highlighter are unchanged; they already show and mark the whole
quote.

## Approaches considered

| Approach | Tradeoff | Decision |
|---|---|---|
| **Embedding similarity** through TEI when the answer finishes | Matches paraphrase, which is the normal case since the model rewrites the source; adds one TEI round trip before sources are sent | **Chosen [A]** |
| Word overlap between sentences and the question/citing sentence | Free, instant and deterministic; misses paraphrase | Not chosen; the M2 harness may compare it against the chosen approach on quote precision |
| The model writes a verbatim quote per citation | Spends output tokens from the 2,000-token budget, complicates the streamed format, still needs a fallback for misquotes | Dropped |

## Design

**When it runs.** Quotes are chosen only for a **complete** answer, after `validate_citations` and
before the turn is stored and `sources` is sent, so the stored and streamed quotes are the same [P].
Failed, interrupted and cut-off turns keep the passage-start quote: they have no finished answer to
support and must not wait on another TEI call.

**Embedding while the answer streams** [A, changed 2026-11-20 after measuring]: the passages are
known before generation starts, so their sentences are embedded in a background task started with
generation. After the answer completes, only the citing sentences remain to embed. The task is
cancelled when the turn ends in any other way, so a failed or stopped answer never waits on it; the
TEI work it already did is the cost.

**Inputs.**

- **Passage sentences:** each supplied passage split on line breaks and on sentence-ending
  punctuation (`. ! ? …` followed by whitespace). Line breaks count because CV bullets and list items
  have no full stop. Each sentence is an exact substring of the passage, with its offsets kept.
  Pieces without a letter (blank lines, bullet glyphs, list numbers) are dropped.
- **Wrapped lines** [A, changed 2026-11-20 after measuring the demo documents]: extracted PDF text
  has a line break at every printed line, so splitting at every line break produced fragments such
  as "Recently" or "40%.". A line break is therefore not a boundary when the line does not end with
  sentence punctuation and the next line starts with a lowercase letter, or starts with a letter or
  digit after a line at least 70% as long as the passage's longest line, unless that next line
  looks like a heading (shorter than that, without sentence punctuation at its end). Answer text
  keeps every
  line break as a boundary, since the model does not wrap lines. A joined sentence keeps its line
  breaks (the evidence panel renders them as spaces).
- **Citing sentences:** the answer sentences that contain a source's `[S#]` label, with all `[S#]`
  markers and Markdown emphasis/list/heading syntax removed. A sentence citing several sources is a
  citing sentence for each.
- **The question vector:** the one already computed for retrieval is reused.

**Embedding.** Passage sentences go through `embed_documents` (document prefix, in the background
task) and citing sentences through query embedding (query prefix), in batches as ingestion does. The embedder gains a batch
query method (`embed_queries`) so citing sentences do not cost one request each [P].

**Choosing sentences, per source.**

1. **Cited source:** each of its citing sentences picks the passage sentence with the highest cosine
   similarity to it. The distinct picks are ranked by their best similarity.
2. **Uncited source:** the single passage sentence most similar to the question.
3. **Assembly:** take picks in rank order while the total, including separators, fits in 300
   characters; then arrange the kept sentences in passage order. Adjacent sentences are joined by the
   whitespace between them in the source (a dropped piece such as a bullet glyph is left out); non-adjacent ones by ` … `. A leading `…` is added when the first kept
   sentence does not start the passage, and a trailing `…` when the last does not end it.
4. **Overlong sentence:** if the top pick alone exceeds 300 characters, it is cut at the last word
   boundary that fits, followed by `…`.

**Fallback.** Any embedder error, or exceeding a time limit of **2 s** for the work after the answer
(waiting for the background task, then the citing sentences) [P], gives every source of that turn the passage-start quote, exactly as today. A
warning with the turn id and exception class is logged, never text. The answer still completes.

**Latency** (measured 2026-11-20, development host: x86_64 Mac, native TEI CPU image, provisional
`snowflake-arctic-embed-m-v2.0`). The three demo documents give 4 passages. With quotes chosen
entirely after the answer, 98 line-split sentences plus 6 citing sentences took p50 1.9 s and p95
2.3 s, past the time limit; embedding the passage sentences was about 1.6 s of that and the citing
sentences about 0.1 s. Dropping uncited sources would not have helped, since all four were cited.
This led to the two changes marked above: joining wrapped lines and embedding while the answer
streams. After both changes (same host and documents, 30 runs): 80 passage sentences and 6 citing
sentences; the background passage embedding takes p50 1.4 s and p95 2.0 s while the answer streams,
and the work left after the answer takes p50 120 ms and p95 175 ms (max 220 ms). A very short
answer can leave part of the background embedding to wait for; the 2 s limit still bounds it.

**Code seams.**

- `Citation` gains `quote: str`; `validate_citations` keeps its job, and a new quote-selection step
  in `qa/` fills `quote` for complete answers.
- `api/sse.py` and `storage/repositories/conversations.py` use `citation.quote` instead of calling
  `quote_snapshot` themselves. `quote_snapshot` remains as the fallback.
- No migration: `turn_sources.quote_snapshot` stays a text column; stored quotes are not rewritten.

## Tests

- **Unit (offline, hash embedder or a scripted fake):** sentence splitting keeps offsets and
  verbatim text, including bullets without full stops; citing-sentence extraction strips labels and
  Markdown and handles a sentence citing several sources; assembly respects 300 characters, passage
  order, adjacent joins, ellipses and the overlong-sentence cut; uncited sources use the question;
  embedder errors and the time limit fall back to passage-start quotes.
- **Service:** a complete answer streams and stores the same selected quotes; failed and interrupted
  turns store passage-start quotes and make no extra embedder call.
- **Integration:** the existing question-answering suite runs with the selected quotes; one scenario
  checks that a passage whose supporting sentence is not at its start gets a quote containing it.
- **Manual:** with the demo documents, "Go through the must-have requirements in the
  Sourcehaven.ai job ad and check each one against Alex's CV." shows CV quotes containing the
  supporting lines rather than the contact block.

## Documentation

- Parent design §7.5 step 2: the quote snapshot holds the selected supporting sentences (up to 300
  characters), with the passage start as the fallback.
- Parent design §8.5: record the agreed M2 order and the three splitting candidates, and note that
  quote selection shipped first; its precision is measured once the corpus exists.

## Left to the builder

- Sentence-splitting details for abbreviations ("e.g.", "Dr.") and numbered lists, within the rules
  above.
- Module and function names; whether the time limit wraps the embedding calls or the whole step.
- Batch sizes for sentence embedding, within TEI's configured limits.
