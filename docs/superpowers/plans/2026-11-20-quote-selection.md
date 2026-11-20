# Quote Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A citation's quote shows the passage sentences that best support the answer sentences
citing it, instead of the passage's first 300 characters.

**Architecture:** Every `Citation` carries its own `quote`, defaulting to the passage start. For a
complete answer, a new `qa/quotes.py` splits each supplied passage into sentences, embeds them with
the citing answer sentences through TEI, picks the closest sentences per source and assembles a
≤ 300-character quote with ellipses. `QAService` runs it after citation validation, under a 2 s
limit, and keeps the passage-start quotes on any failure. The SSE encoder and the turn repository
use `citation.quote`, so streamed and stored quotes are identical.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, httpx, TEI, pytest + pytest-asyncio
(`asyncio_mode = "auto"`), integration suite on the Compose Postgres.

**Spec:** `docs/superpowers/specs/2026-11-20-quote-selection-design.md` (binding).

## Global Constraints

- Quote limit: **300 characters**, the existing `QUOTE_SNAPSHOT_CHARACTERS` in
  `src/sourcehaven/qa/citations.py`; every quote, selected or fallback, is ≤ 300.
- Ellipsis is the single character `…` (U+2026). Leading: `"…" + text`; between non-adjacent
  sentences: `" … "`; trailing: `text + " …"`; overlong cut: `cut + "…"`.
- Apart from inserted ellipses, every quote is verbatim passage text (A4).
- Selection runs only for **complete** answers. Failed, interrupted and length-limited turns keep
  passage-start quotes and make no embedder call beyond retrieval.
- Time limit: `QUOTE_SELECTION_TIMEOUT_SECONDS: float = 2.0` in `qa/quotes.py`.
- Any error or timeout in selection: all sources of the turn keep passage-start quotes, the answer
  completes, and one warning is logged with the turn id and exception class only — never text.
- No API, database, migration or frontend change. Stored quotes are not rewritten.
- Python rules (CLAUDE.md): strict mypy, annotated locals, absolute imports, Google docstrings where
  a contract needs explaining, pytest only.
- Checks before every commit (repo root): `uv run pytest`, `uv run pytest -m integration` (Compose
  `db` running), then `uv run pre-commit run --all-files` (sandbox disabled for uv and Docker).
  Imperative commit messages, no AI attribution, stage paths explicitly.

## Review Focus

1. **Label after the full stop or on its own line** (`…3 business days. [S1]`, or `[S1]` alone on
   the next line): the label belongs to the preceding sentence, not to an empty one. Test in Task 3.
2. **Markdown answers** (`- **Python:** 7 years of experience [S2]`, headings, `` `code` ``): the
   citing sentence is the plain words, so emphasis markers don't skew similarity. Test in Task 3.
3. **A passage that is one long run without sentence punctuation** (a table row, a run-on list
   over 300 characters): the quote is cut at a word boundary, ends with `…`, and is ≤ 300. Test in
   Task 4.
4. **A cited source whose citing sentences are nothing but labels** (`[S1][S2]`): it falls back to
   question similarity instead of picking an arbitrary sentence. Test in Task 5.
5. **The Unicode ellipsis and closing quotes as sentence ends** (`Wait… then`, `He said "yes." Then`):
   split there, with offsets that still slice the passage exactly. Test in Task 3.

---

### Task 1: Batch query embedding

**Files:**
- Modify: `src/sourcehaven/embeddings/protocol.py`, `src/sourcehaven/embeddings/tei.py`,
  `src/sourcehaven/embeddings/hashing.py`
- Modify (fakes must keep satisfying the protocol): `tests/support/embeddings.py`
  (`NotReadyEmbedder`, `FailingEmbedder`, `QueryFailingEmbedder`), `tests/integration/test_ingestion.py`
  (`ReclaimingEmbedder`)
- Test: `tests/unit/test_embeddings.py`

**Interfaces:**
- Produces: `Embedder.embed_queries(self, texts: Sequence[str]) -> list[list[float]]` — query
  prefix, batched like `embed_documents`, `[]` for no texts, raises like `embed_query`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_tei_embedder_batches_queries_with_the_query_prefix() -> None:
    seen: list[TeiRequest] = []
    embedder: TeiEmbedder = TeiEmbedder(
        httpx.AsyncClient(transport=tei_mock(seen, dimensions=3), base_url="http://tei"),
        make_config(dimensions=3),
        batch_size=2,
    )
    vectors: list[list[float]] = await embedder.embed_queries(["a", "b", "c"])
    assert len(vectors) == 3
    assert [r["inputs"] for r in seen] == [["query: a", "query: b"], ["query: c"]]
    assert await embedder.embed_queries([]) == [] and len(seen) == 2


async def test_hash_embedder_embeds_queries_like_single_queries() -> None:
    embedder: HashEmbedder = HashEmbedder()
    assert await embedder.embed_queries(["warranty period", "support"]) == [
        await embedder.embed_query("warranty period"),
        await embedder.embed_query("support"),
    ]
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_embeddings.py -v` — Expected: FAIL
  (`AttributeError: ... has no attribute 'embed_queries'`).

- [ ] **Step 3: Implement `embed_queries`** on the protocol, `TeiEmbedder` (`self._embed(texts,
  self._config.query_prefix)`; make `embed_query` delegate to it), `HashEmbedder`, and each test
  fake: `NotReadyEmbedder` raises `EmbedderNotReady`, `FailingEmbedder` raises its
  `IngestionError`, `QueryFailingEmbedder` raises `EmbedderUnavailable`, `ReclaimingEmbedder`
  delegates to its inner embedder.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_embeddings.py -v` and `uv run mypy` — Expected:
  PASS, no mypy errors.

- [ ] **Step 5: Commit** — `git commit -m "Add batch query embedding"`

---

### Task 2: Citations carry their quote

Behaviour stays the same: every quote is still the passage start. This moves the decision into one
place so Task 6 can change it for both the stream and storage.

**Files:**
- Modify: `src/sourcehaven/domain/models.py` (`Citation`), `src/sourcehaven/qa/citations.py`
  (`validate_citations`), `src/sourcehaven/qa/service.py` (`_unvalidated`),
  `src/sourcehaven/api/sse.py` (`_source`), `src/sourcehaven/storage/repositories/conversations.py`
  (turn source insert)
- Test: `tests/unit/test_citations.py`, `tests/unit/test_sse.py`

**Interfaces:**
- Produces: `Citation.quote: str` — a required field (no default), documented as "the excerpt
  stored and shown with the citation". `validate_citations` and `_unvalidated` set it to
  `quote_snapshot(evidence.text)`.

- [ ] **Step 1: Write the failing tests**

In `test_citations.py`:

```python
def test_sources_quote_the_passage_start() -> None:
    item: LabelledEvidence = labelled("S1")
    long: LabelledEvidence = replace(item, evidence=replace(item.evidence, text="x" * 301))
    result: CitationResult = validate_citations("[S1]", [long])
    assert result.sources[0].quote == "x" * 300
```

In `test_sse.py`, replace `test_sse_mapping_of_sources_truncates_quotes` with
`test_sse_mapping_of_sources_sends_each_citation_quote`: build the two citations with explicit
`quote="The warranty is 24 months."` and `quote="…chosen sentence."` (S2's evidence text stays
`"x" * 301`), and assert the payload's quotes are exactly those two strings. Add `quote=` to the
other `Citation(...)` in that file.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_citations.py tests/unit/test_sse.py -v` —
  Expected: FAIL (`Citation` has no `quote`).

- [ ] **Step 3: Implement** the field and its producers; `_source` uses `quote=citation.quote` and
  the repository uses `quote_snapshot=citation.quote`. Remove the now-unused `quote_snapshot`
  imports from `sse.py` and `conversations.py`.

- [ ] **Step 4: Run** `uv run pytest` and `uv run pytest -m integration` — Expected: PASS (quotes
  unchanged end to end).

- [ ] **Step 5: Commit** — `git commit -m "Carry each citation's quote on the citation"`

---

### Task 3: Passage sentences and citing sentences

**Files:**
- Create: `src/sourcehaven/qa/quotes.py`
- Test: `tests/unit/test_quotes.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Sentence: start: int; end: int; text: str` — invariant
    `text == source[start:end]`.
  - `split_sentences(text: str) -> list[Sentence]` — boundaries at line breaks and after `.`, `!`,
    `?` or `…` (optionally followed by closing `"`, `'`, `”`, `’`, `)` or `]`) followed by
    whitespace; each piece stripped of surrounding whitespace with offsets adjusted; pieces with no
    word character (`\w`) dropped. No abbreviation handling.
  - `citing_sentences(answer: str) -> dict[str, list[str]]` — label (`"S1"`) → its cleaned citing
    sentences in answer order, without duplicates. Uses `split_sentences` on the answer; a piece
    consisting only of `[S#]` labels (and whitespace/punctuation) merges its labels into the
    preceding piece. Cleaning removes every `[S#]`, leading Markdown markers (`#…`, `-`, `*`, `+`,
    `>`, `1.`), and `**`, `__`, `*`, `_` emphasis and backticks, then collapses whitespace runs to
    one space, removes spaces before `. , ; : ! ?` and strips. A label whose only citing sentences
    clean to `""` maps to `[]`.
  - Reuse `_CITATION` from `qa/citations.py` (make it public as `CITATION_LABEL` if needed).

- [ ] **Step 1: Write the failing tests**

```python
def test_sentences_slice_the_passage_exactly() -> None:
    text: str = 'Senior Engineer.\n• Led the migration! Wait… then "yes." Then (done.) end'
    sentences: list[Sentence] = split_sentences(text)
    assert [s.text for s in sentences] == [
        "Senior Engineer.", "• Led the migration!", "Wait…", 'then "yes."', "Then (done.)", "end",
    ]
    assert all(text[s.start : s.end] == s.text for s in sentences)


def test_lines_without_full_stops_are_sentences_and_blank_pieces_are_dropped() -> None:
    assert [s.text for s in split_sentences("Skills\n\n  •  \nPython, FastAPI\n")] == [
        "Skills", "Python, FastAPI",
    ]


def test_label_after_the_full_stop_or_on_its_own_line_cites_the_preceding_sentence() -> None:
    answer: str = "Support answers in 3 days. [S1]\nThe warranty is 24 months.\n[S2]"
    assert citing_sentences(answer) == {
        "S1": ["Support answers in 3 days."], "S2": ["The warranty is 24 months."],
    }


def test_markdown_and_labels_are_removed_and_shared_sentences_count_for_each_label() -> None:
    answer: str = "## Fit\n- **Python:** 7 years of `FastAPI` work [S2][S3].\n- Mentoring [S2]."
    assert citing_sentences(answer) == {
        "S2": ["Python: 7 years of FastAPI work.", "Mentoring."],
        "S3": ["Python: 7 years of FastAPI work."],
    }


def test_label_without_words_has_no_citing_sentence() -> None:
    assert citing_sentences("Intro.\n[S1][S2]") == {"S1": ["Intro."], "S2": ["Intro."]}
    assert citing_sentences("[S1]") == {"S1": []}
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_quotes.py -v` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `Sentence`, `split_sentences` and `citing_sentences` in
  `src/sourcehaven/qa/quotes.py`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_quotes.py -v` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "Split passages and answers into sentences for quotes"`

---

### Task 4: Quote assembly

**Files:**
- Modify: `src/sourcehaven/qa/quotes.py`
- Test: `tests/unit/test_quotes.py`

**Interfaces:**
- Consumes: `Sentence`, `split_sentences` (Task 3).
- Produces: `assemble_quote(passage: str, sentences: Sequence[Sentence], ranked: Sequence[int], *,
  limit: int = QUOTE_SNAPSHOT_CHARACTERS) -> str` — `ranked` holds distinct indices into
  `sentences`, best first, non-empty.

Rules (spec "Choosing sentences", steps 3–4):
1. Walk `ranked`; keep adding an index while the rendered quote stays ≤ `limit`; stop at the first
   that does not fit.
2. Render the kept indices in passage order: adjacent indices are joined by
   `passage[previous.end:next.start]`; non-adjacent by `" … "`; prefix `"…"` unless the first kept
   index is 0; suffix `" …"` unless the last kept index is `len(sentences) - 1`.
3. If even the top pick alone does not fit: take its text, cut at the last space so that
   prefix (`"…"` unless index 0) + cut + `"…"` is ≤ `limit` (hard cut at `limit` when there is no
   space), strip trailing whitespace before `"…"`.

- [ ] **Step 1: Write the failing tests**

```python
PASSAGE: str = "Alex Novák. Prague.\nLed the migration to FastAPI. Cut p95 by 40%.\nMentored four engineers."


def test_quote_keeps_picks_in_passage_order_with_ellipses() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    assert assemble_quote(PASSAGE, sentences, [4, 2]) == (
        "…Led the migration to FastAPI. … Mentored four engineers."
    )


def test_adjacent_picks_keep_the_source_text_between_them() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    assert assemble_quote(PASSAGE, sentences, [3, 2]) == (
        "…Led the migration to FastAPI. Cut p95 by 40%. …"
    )


def test_picks_stop_at_the_first_that_does_not_fit() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    assert assemble_quote(PASSAGE, sentences, [2, 4, 0], limit=60) == (
        "…Led the migration to FastAPI. … Mentored four engineers."
    )


def test_overlong_sentence_is_cut_at_a_word_boundary() -> None:
    run: str = " ".join(["Python"] * 80)  # one sentence, 559 characters
    quote: str = assemble_quote(run, split_sentences(run), [0])
    assert len(quote) <= 300 and quote.endswith("Python…") and run.startswith(quote[:-1])


def test_quotes_are_verbatim_apart_from_ellipses() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    for ranked in ([0], [1, 3], [4, 0, 2]):
        quote: str = assemble_quote(PASSAGE, sentences, ranked)
        assert all(part.strip() in PASSAGE for part in quote.split("…") if part.strip())
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_quotes.py -v` — Expected: the new tests FAIL.

- [ ] **Step 3: Implement** `assemble_quote` in `qa/quotes.py`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_quotes.py -v` — Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "Assemble citation quotes from chosen sentences"`

---

### Task 5: Choose quotes by embedding similarity

**Files:**
- Modify: `src/sourcehaven/qa/quotes.py`
- Test: `tests/unit/test_quotes.py`

**Interfaces:**
- Consumes: `Embedder.embed_queries` (Task 1), `Citation.quote` (Task 2), `split_sentences`,
  `citing_sentences` (Task 3), `assemble_quote` (Task 4).
- Produces:
  - `QUOTE_SELECTION_TIMEOUT_SECONDS: float = 2.0`
  - `async def select_quotes(answer: str, sources: Sequence[Citation], *, question_vector:
    Sequence[float], embedder: Embedder, timeout_seconds: float = QUOTE_SELECTION_TIMEOUT_SECONDS)
    -> list[Citation]` — same order and fields as `sources`, with `quote` replaced
    (`dataclasses.replace`). A source whose passage yields no sentences keeps its quote.
  - Raises whatever the embedder raises, and `TimeoutError` when the whole call exceeds
    `timeout_seconds` (`asyncio.timeout`). The caller owns the fallback.

Algorithm: one `embed_documents` call with every passage sentence of every source, one
`embed_queries` call with every distinct citing sentence (skipped when there are none). Similarity
is cosine. Cited source with ≥ 1 citing sentence: each citing sentence picks its most similar
passage sentence (ties → earlier sentence); rank the distinct picks by their best similarity,
descending. Otherwise (uncited, or citing sentences all empty): the single sentence most similar to
`question_vector`. Then `assemble_quote`.

- [ ] **Step 1: Write the failing tests** (with `HashEmbedder`, whose similarity follows shared
  words; `_citation(label, text, cited)` builds a `Citation` with a passage-start quote)

```python
async def test_cited_source_quotes_the_sentences_its_citing_sentences_match() -> None:
    passage: str = "Alex Novák, Prague. Led the migration to FastAPI. Enjoys hiking."
    sources: list[Citation] = [_citation("S1", passage, cited=True)]
    chosen: list[Citation] = await select_quotes(
        "Alex migrated a service to FastAPI [S1].", sources,
        question_vector=await HashEmbedder().embed_query("hobbies"), embedder=HashEmbedder(),
    )
    assert chosen[0].quote == "…Led the migration to FastAPI. …"


async def test_uncited_and_label_only_sources_use_the_question() -> None:
    passage: str = "The warranty period is 24 months. Support answers within 3 business days."
    embedder: HashEmbedder = HashEmbedder()
    chosen: list[Citation] = await select_quotes(
        "[S1]",
        [_citation("S1", passage, cited=True), _citation("S2", passage, cited=False)],
        question_vector=await embedder.embed_query("How fast does support answer?"),
        embedder=embedder,
    )
    assert [c.quote for c in chosen] == ["…Support answers within 3 business days."] * 2


async def test_embedder_errors_propagate() -> None:
    with pytest.raises(EmbedderUnavailable):
        await select_quotes(
            "Fact [S1].", [_citation("S1", "Fact.", cited=True)],
            question_vector=[1.0], embedder=QueryFailingEmbedder(),
        )


async def test_slow_embedder_times_out() -> None:
    with pytest.raises(TimeoutError):
        await select_quotes(
            "Fact [S1].", [_citation("S1", "Fact.", cited=True)],
            question_vector=[1.0], embedder=SlowEmbedder(delay_seconds=1.0), timeout_seconds=0.05,
        )
```

Add `SlowEmbedder(HashEmbedder)` to `tests/support/embeddings.py`: it sleeps `delay_seconds` in
`embed_documents` before delegating.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_quotes.py -v` — Expected: the new tests FAIL.

- [ ] **Step 3: Implement** `select_quotes` and `QUOTE_SELECTION_TIMEOUT_SECONDS`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_quotes.py -v` and `uv run mypy` — Expected:
  PASS.

- [ ] **Step 5: Commit** — `git commit -m "Choose citation quotes by sentence similarity"`

---

### Task 6: Select quotes for complete answers

**Files:**
- Modify: `src/sourcehaven/qa/service.py` (`_events`, `_retrieve`, `_StartedTurn` if the vector is
  kept there)
- Modify: `docs/superpowers/specs/2026-11-19-sourcehaven-design.md` §7.5 step 2
- Test: `tests/integration/test_question_answering.py`; add `CountingEmbedder(HashEmbedder)` and
  `QuoteFailingEmbedder(HashEmbedder)` to `tests/support/embeddings.py`

**Interfaces:**
- Consumes: `select_quotes` (Task 5).
- Produces: `_retrieve` returns `tuple[list[float], list[Evidence]]` (the question vector is reused).

Behaviour: after `validate_citations`, replace `result.sources` with `await select_quotes(text,
result.sources, question_vector=..., embedder=self._container.embedder)`. On any `Exception`, keep
`result` as it is and log `logger.warning("turn %s kept passage-start quotes: %s", turn.turn_id,
type(error).__name__)`. Selection happens before `_finish`, so the stored and streamed quotes are
the same object. No other branch calls it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_quote_shows_the_supporting_sentence_not_the_passage_start(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(
        script=["Support requests are answered within 3 business days [S1]."]
    )
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    events: list[SseEvent] = await visitor.ask("How fast is support?", [doc])
    quote: str = events[-2].data["sources"][0]["quote"]
    assert quote.startswith("…") and "within 3 business days." in quote
    assert "warranty" not in quote
    assert (await visitor.last_turn())["sources"][0]["quote"] == quote


async def test_quote_selection_failure_keeps_the_passage_start_and_completes(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["The warranty is 24 months [S1]."])
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf",
        overrides=ContainerOverrides(chat_model=model, embedder=QuoteFailingEmbedder()),
    )
    events: list[SseEvent] = await visitor.ask("How long is the warranty period?", [doc])
    assert events[-1].name == "done" and events[-1].data["status"] == "complete"
    assert events[-2].data["sources"][0]["quote"].startswith("The Sourcehaven warranty")


async def test_failed_answer_makes_no_quote_selection_call(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    embedder: CountingEmbedder = CountingEmbedder()
    model: ScriptedChatModel = ScriptedChatModel(script=["Partial [S1] ", "more"], fail_after=1)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model, embedder=embedder)
    )
    embedder.reset()
    await visitor.ask("warranty?", [doc])
    assert embedder.query_batches == 0 and embedder.document_batches == 0
```

`QuoteFailingEmbedder` raises `EmbedderUnavailable` from `embed_queries` only (retrieval still uses
`embed_query`). `CountingEmbedder` exposes `query_batches: int` and `document_batches: int`
(calls to `embed_queries` and `embed_documents`) and `reset() -> None`.

- [ ] **Step 2: Run** `uv run pytest -m integration tests/integration/test_question_answering.py -v`
  — Expected: the new tests FAIL (quote starts with "The Sourcehaven warranty").

- [ ] **Step 3: Implement** the service change and update §7.5 step 2 of the parent design: "a
  quote snapshot of up to 300 characters holding the passage sentences that best support the
  citing answer sentences (the question, for uncited passages), with the passage start as the
  fallback; see `2026-11-20-quote-selection-design.md`."

- [ ] **Step 4: Run** `uv run pytest`, `uv run pytest -m integration` — Expected: PASS, including
  the existing `test_completed_turn_is_stored_with_its_sources` (quote ≤ 300, streamed == stored).

- [ ] **Step 5: Commit** — `git commit -m "Quote the supporting sentences of complete answers"`

---

### Task 7: Measure latency and check the demo

The spec places the latency measurement first; it moves last so it times the real step rather than
a stand-in. The only decision it feeds (dropping uncited sources from selection) is a small change.

**Files:**
- Modify: `docs/superpowers/specs/2026-11-20-quote-selection-design.md` ("Latency": measured numbers)
- Throwaway (not committed): a script in the session scratchpad

- [ ] **Step 1: Measure.** Check Docker VM disk, `docker compose build api`, `docker compose up -d
  embeddings`, then run a scratchpad script inside the Compose network (`docker compose run --rm
  --no-deps -v <scratchpad>:/measure api python /measure/measure_quotes.py`). The script extracts
  the three `docs/demo/` PDFs with the package's PDF adapter, chunks them with the current settings,
  takes 8 passages and 6 citing sentences drawn from them, and times `select_quotes` with the real
  `TeiEmbedder` 30 times after one warm-up. Record p50/p95, the sentence count and the host
  (x86_64 Mac, native TEI) in the design's "Latency" paragraph.
- [ ] **Step 2: Decide.** If p95 > 1.0 s, ask the owner before changing anything: the spec's next
  step is to stop selecting quotes for uncited sources (they keep the passage start).
- [ ] **Step 3: Demo check.** With the owner's `.env` (OpenAI, `gpt-5-mini`, reasoning effort
  `low` — confirm before running; it is a paid call), upload the three demo PDFs and ask "Go
  through the must-have requirements in the Sourcehaven.ai job ad and check each one against
  Alex's CV." Confirm the CV quotes contain the supporting lines, not the contact block.
- [ ] **Step 4: Run** `uv run pre-commit run --all-files` — Expected: all hooks pass.
- [ ] **Step 5: Commit** — `git commit -m "Record quote selection latency"`
