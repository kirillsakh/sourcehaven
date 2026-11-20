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

**When it runs.** Only for a **complete** answer, after `validate_citations` and before the turn is
stored and `sources` is sent, so the stored and streamed quotes are the same [P]. Failed,
interrupted and cut-off turns keep the passage-start quote: they have no finished answer to support
and must not wait on another TEI call.

**Inputs.**

- **Passage sentences:** each supplied passage split on line breaks and on sentence-ending
  punctuation (`. ! ? …` followed by whitespace). Line breaks count because CV bullets and list items
  have no full stop. Each sentence is an exact substring of the passage, with its offsets kept.
  Blank and punctuation-only pieces are dropped.
- **Citing sentences:** the answer sentences that contain a source's `[S#]` label, with all `[S#]`
  markers and Markdown emphasis/list/heading syntax removed. A sentence citing several sources is a
  citing sentence for each.
- **The question vector:** the one already computed for retrieval is reused.

**Embedding.** Passage sentences go through `embed_documents` (document prefix) and citing sentences
through query embedding (query prefix), in batches as ingestion does. The embedder gains a batch
query method (`embed_queries`) so citing sentences do not cost one request each [P].

**Choosing sentences, per source.**

1. **Cited source:** each of its citing sentences picks the passage sentence with the highest cosine
   similarity to it. The distinct picks are ranked by their best similarity.
2. **Uncited source:** the single passage sentence most similar to the question.
3. **Assembly:** take picks in rank order while the total, including separators, fits in 300
   characters; then arrange the kept sentences in passage order. Adjacent sentences are joined by the
   source text between them; non-adjacent ones by ` … `. A leading `…` is added when the first kept
   sentence does not start the passage, and a trailing `…` when the last does not end it.
4. **Overlong sentence:** if the top pick alone exceeds 300 characters, it is cut at the last word
   boundary that fits, followed by `…`.

**Fallback.** Any embedder error, or exceeding a total time limit of **2 s** [P, revisit after the
latency measurement], gives every source of that turn the passage-start quote, exactly as today. A
warning with the turn id and exception class is logged, never text. The answer still completes.

**Latency.** Up to 8 passages of about 400 tokens give roughly 100–200 short sentences, plus the
citing sentences. The cost on the development host's CPU TEI is unmeasured; the first
implementation task measures it with the real TEI on the demo documents and records p50/p95 here.
If it is well above a second, uncited sources fall back to the passage start (they are collapsed in
the UI) before anything else is changed.

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
