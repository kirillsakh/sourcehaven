# Evaluation Corpus and Retrieval Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fixed corpus of six real PDFs, about 40 questions with gold page-and-text spans, and an
offline benchmark command that scores the app's retrieval against them and records a baseline.

**Architecture:** A top-level `evals/` package (never in the wheel) imports the installed
`sourcehaven` package and calls its own parsing (`PdfAdapter`), splitting (`chunk_pages`),
embedding (`TeiEmbedder`), evidence selection (`select_evidence`) and quote selection
(`embed_passage_sentences`, `select_quotes`). Only the database's exact cosine ranking is
reimplemented in memory. Pure scoring functions sit apart from the async pipeline, and a command
module wires `fetch`, `check` and `run`.

**Tech Stack:** Python 3.14, stdlib `tomllib`/`sqlite3`/`argparse`/`hashlib`, httpx, pypdf, tokenizers,
pytest; TEI CPU 1.9 for the real run.

**Spec:** `docs/superpowers/specs/2026-11-20-corpus-and-harness-design.md` (approved 2026-11-21).
Read it before any task; §-references below point into it.

## Global Constraints

- Python 3.14 through `uv run`; no new runtime or dev dependency (spec §5).
- Absolute imports only (`from evals.scoring import Passage`), Ruff `TID252` applies to `evals/` and
  its tests; no `sys.path` edits.
- Every parameter, return, attribute, module constant and first local assignment annotated; mypy
  strict passes over `src`, `tests`, `scripts`, `evals`.
- Google-style docstrings only where a caller needs a contract; no boilerplate docstrings.
- Tests are pytest functions with plain asserts; offline; no TEI, network or paid calls.
- `evals/` is not packaged: the wheel built by `uv_build` contains only `src/sourcehaven`.
- PDFs, caches and reports are never committed: `/evals/corpus/files/`, `/evals/.cache/`,
  `/evals/reports/` are ignored.
- Before every commit: `uv run pre-commit run --all-files` passes (needs the sandbox disabled);
  commit with the hook active; no `--no-verify`; no AI attribution in messages; messages are short
  imperative sentences like the existing history ("Add batch query embedding").
- Work on branch `m2/corpus-harness`. Ask the owner before any push.
- Normalisation, metric definitions and thresholds are exactly spec §4.3: quote precision counts a
  quote at ≥ 80 % word coverage; candidates are the top `CANDIDATE_LIMIT` (20) from
  `sourcehaven.retrieval.search`; the threshold table runs 0.00–1.00 in steps of 0.01.

## Review Focus

1. **The same sentence in two documents** (`report` and `report-2024` share most text): a passage
   from another document must never count as containing a span. Pinned in Task 4.
2. **A stale, partial or changed corpus file:** `fetch` re-downloads a file that fails verification
   and refuses a download whose hash or size differs, leaving no `<id>.pdf` behind. Pinned in Task 2.
3. **A question whose selection cannot find its gold** (gold document not selected, conflict
   question without an explicit selection, gold page outside an excerpt): rejected when the file is
   loaded, naming the question id. Pinned in Task 3.
4. **TEI down or serving another model:** `run` exits non-zero with the readiness message before
   extracting or embedding anything. Pinned in Task 7.
5. **A question with no candidate above zero similarity** (empty selection, negative cosine):
   scored as a miss or a refusal without crashing; `top_similarity` may be negative. Pinned in
   Task 4.

---

## File structure

| File | Responsibility |
|---|---|
| `evals/__init__.py` | Empty package marker |
| `evals/normalize.py` | Text normalisation for matching; quote word coverage |
| `evals/corpus.py` | Manifest model and loading, fetch and verify, excerpt-aware extraction |
| `evals/questions.py` | Question-file model, loading and validation |
| `evals/scoring.py` | Passages, ranking records, span location, metric aggregation, threshold table |
| `evals/embedding.py` | Benchmark embedding config, tokenizer download, vector cache, cached embedder |
| `evals/pipeline.py` | Async benchmark run producing per-question outcomes and speed figures |
| `evals/report.py` | `report.json`, `summary.md` and review-sheet rendering |
| `evals/benchmark.py` | Command line: `fetch`, `check`, `run` |
| `evals/corpus/manifest.toml`, `evals/corpus/README.md`, `evals/questions.toml` | Committed data |
| `tests/unit/evals/` | One test module per `evals` module |

---

### Task 1: Package scaffold and text normalisation

**Files:**
- Create: `evals/__init__.py`, `evals/normalize.py`, `tests/unit/evals/__init__.py`,
  `tests/unit/evals/test_normalize.py`
- Modify: `pyproject.toml` (`[tool.mypy] files` add `"evals"`; `[tool.ruff.lint.isort]
  known-first-party = ["sourcehaven", "evals"]`), `.gitignore` (add `/evals/corpus/files/`,
  `/evals/.cache/`, `/evals/reports/` under a "Benchmark data" comment)

**Interfaces:**
- Produces: `normalize(text: str) -> str`; `word_coverage(span: str, quote: str) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ligatures_case_and_whitespace() -> None:
    assert normalize("The  ﬁrst\nRule") == "the first rule"

def test_line_end_hyphen_joins_and_other_hyphens_vanish() -> None:
    assert normalize("represen-\ntation") == normalize("representation")
    assert normalize("well-\nknown") == normalize("well-known") == "wellknown"

def test_soft_hyphen_dashes_and_quotes() -> None:
    assert normalize("co­operate") == "cooperate"
    assert normalize("“A” – ‘b’") == normalize('"A" - \'b\'')

def test_word_coverage_counts_words_as_a_multiset() -> None:
    assert word_coverage("the cat and the dog", "The cat … the dog") == 0.8
    assert word_coverage("24 months", "warranty of 24 months") == 1.0

def test_word_coverage_rejects_a_span_without_words() -> None:
    with pytest.raises(ValueError):
        word_coverage(" … ", "anything")
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_normalize.py -q` — expect import errors.

- [ ] **Step 3: Implement `evals/normalize.py`.** `normalize` applies, in order: NFKC; delete
  U+00AD; map U+2010–U+2015 and U+2212 to `-`; delete `-\s*\n\s*`; delete remaining `-`; map
  `‘’‚‛` to `'` and `“”„‟` to `"`; collapse whitespace to one space; `casefold()`; strip.
  `word_coverage` compares `Counter(re.findall(r"\w+", normalize(...)))` of span and quote and
  returns matched words / span words; `ValueError` when the span has no words.

- [ ] **Step 4: Run** the tests — PASS. Run `uv run mypy` and `uv run ruff check evals tests` — clean.

- [ ] **Step 5: Commit** — "Add the benchmark package and text normalisation".

---

### Task 2: Corpus manifest, fetching and excerpt-aware extraction

**Files:**
- Create: `evals/corpus.py`, `tests/unit/evals/test_corpus.py`

**Interfaces:**
- Consumes: `sourcehaven.ingestion.pdf.SourceAdapter`, `sourcehaven.domain.models.ExtractedSource`, `PageSpan`.
- Produces:
  - `class CorpusError(Exception)`.
  - `@dataclass(frozen=True) class CorpusDocument`: `id: str`, `title: str`, `author: str`,
    `url: str`, `sha256: str`, `size_bytes: int`, `page_count: int`, `licence: str`,
    `licence_url: str`, `layout: str`, `page_range: PageSpan | None`, `selected_by_default: bool`.
  - `@dataclass(frozen=True) class Manifest`: `version: int`, `documents: tuple[CorpusDocument, ...]`;
    method `document(self, document_id: str) -> CorpusDocument` (raises `KeyError`).
  - `load_manifest(path: Path) -> Manifest` (raises `CorpusError` listing every problem).
  - `document_path(files_dir: Path, document: CorpusDocument) -> Path` → `files_dir / f"{id}.pdf"`.
  - `verify_file(path: Path, document: CorpusDocument) -> bool`.
  - `async fetch_corpus(manifest: Manifest, files_dir: Path, client: httpx.AsyncClient) -> list[Path]`.
  - `extract_document(document: CorpusDocument, path: Path, adapter: SourceAdapter, *, max_pages: int) -> ExtractedSource`.

Manifest TOML shape (top-level `version`, then `[[document]]` tables with the field names above;
`pages = [first, last]` maps to `page_range`, inclusive, physical; `selected_by_default` defaults to
`true`).

- [ ] **Step 1: Write the failing tests**

```python
def test_loads_documents_with_optional_range(tmp_path: Path) -> None:
    manifest = load_manifest(write_manifest(tmp_path, pages=[17, 100], selected_by_default=False))
    doc = manifest.document("book")
    assert doc.page_range == PageSpan(start=17, end=100) and not doc.selected_by_default

@pytest.mark.parametrize("bad", [{"sha256": "abc"}, {"pages": [5, 2]}, {"pages": [1, 999]},
                                 {"id": "contract"}])  # last one duplicates an id
def test_rejects_invalid_manifests(tmp_path: Path, bad: dict[str, object]) -> None:
    with pytest.raises(CorpusError):
        load_manifest(write_manifest(tmp_path, **bad))

async def test_fetch_downloads_verifies_and_skips_verified_files(tmp_path: Path) -> None:
    # httpx.MockTransport serving fixture bytes; counts requests
    ...
    assert verify_file(paths[0], doc) and requests == 1
    await fetch_corpus(manifest, tmp_path, client)
    assert requests == 1  # verified file not downloaded again

async def test_fetch_replaces_a_partial_file(tmp_path: Path) -> None:
    document_path(tmp_path, doc).write_bytes(b"%PDF-1.7 trunc")
    await fetch_corpus(manifest, tmp_path, client)
    assert verify_file(document_path(tmp_path, doc), doc)

async def test_fetch_refuses_a_changed_upstream_file(tmp_path: Path) -> None:
    # transport serves different bytes than the manifest hash
    with pytest.raises(CorpusError, match="contract"):
        await fetch_corpus(manifest, tmp_path, client)
    assert not document_path(tmp_path, doc).exists()

def test_extract_keeps_only_the_excerpt_with_physical_numbers() -> None:
    source = extract_document(doc_with_range(3, 5), fixture("multipage_en.pdf"), PdfAdapter(), max_pages=300)
    assert [page.page for page in source.pages] == [3, 4, 5]
```

`write_manifest` is a local test helper writing a two-document manifest (`contract`, `book`) with
overrides applied to `book` (or adding a duplicate for the `id` case).

- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_corpus.py -q` — FAIL.

- [ ] **Step 3: Implement `evals/corpus.py`.** Validation: `version` positive int; ids unique and
  matching `[a-z0-9-]+`; `sha256` 64 lowercase hex; sizes and page counts positive; a range within
  `1..page_count` with first ≤ last. Fetch streams into `files_dir / f".{id}.part"` with
  `follow_redirects=True`, checks size and SHA-256, then renames; on mismatch deletes the part
  file and raises `CorpusError` naming the id, the expected and actual hash, and the fix ("update
  the manifest deliberately and bump its version"). Extraction calls the adapter on the original
  file, then returns an `ExtractedSource` with only the pages inside `page_range` (all pages when
  `None`) and the same `page_count`, parser name and version.

- [ ] **Step 4: Run** the tests — PASS; mypy and Ruff clean.

- [ ] **Step 5: Commit** — "Add the benchmark corpus manifest and fetching".

---

### Task 3: Question file and validation

**Files:**
- Create: `evals/questions.py`, `tests/unit/evals/test_questions.py`

**Interfaces:**
- Consumes: `Manifest`, `CorpusDocument` (Task 2).
- Produces:
  - `type QuestionKind = Literal["answerable", "unanswerable", "conflict"]`.
  - `@dataclass(frozen=True) class GoldSpan`: `document: str`, `page: int`, `text: str`.
  - `@dataclass(frozen=True) class Question`: `id: str`, `kind: QuestionKind`, `text: str`,
    `documents: tuple[str, ...]` (resolved selection, never empty), `reference_answer: str | None`,
    `gold: tuple[GoldSpan, ...]`.
  - `class QuestionFileError(Exception)`.
  - `MAX_SPAN_CHARACTERS: Final[int] = 250`.
  - `load_questions(path: Path, manifest: Manifest) -> tuple[Question, ...]`.
  - `file_sha256(path: Path) -> str`.

TOML shape is spec §3.3 (`[[question]]` with `id`, `kind`, `text`, `documents`,
`reference_answer`, nested `[[question.gold]]` with `document`, `page`, `text`).

- [ ] **Step 1: Write the failing tests**

```python
def test_empty_selection_means_documents_selected_by_default(tmp_path: Path) -> None:
    (question,) = load_questions(write_questions(tmp_path, ANSWERABLE), MANIFEST)
    assert question.documents == ("contract", "report")  # report-2024 has selected_by_default = false

@pytest.mark.parametrize(("case", "message"), [
    (ANSWERABLE | {"gold": []}, "q-1"),                       # answerable without gold
    (ANSWERABLE | {"reference_answer": None}, "q-1"),
    (UNANSWERABLE | {"gold": [GOLD]}, "q-2"),                  # unanswerable with gold
    (CONFLICT | {"documents": []}, "q-3"),                     # conflict must list documents
    (CONFLICT | {"gold": [GOLD]}, "q-3"),                      # conflict needs spans in two documents
    (ANSWERABLE | {"documents": ["report"]}, "q-1"),           # gold document not selected
    (ANSWERABLE | {"gold": [GOLD | {"document": "nope"}]}, "q-1"),
    (ANSWERABLE | {"gold": [GOLD | {"page": 999}]}, "q-1"),    # outside the page range / excerpt
    (ANSWERABLE | {"gold": [GOLD | {"text": "x" * 251}]}, "q-1"),
])
def test_rejects_invalid_questions(tmp_path: Path, case: dict[str, object], message: str) -> None:
    with pytest.raises(QuestionFileError, match=message):
        load_questions(write_questions(tmp_path, case), MANIFEST)

def test_rejects_duplicate_ids(tmp_path: Path) -> None: ...
def test_reports_every_problem_at_once(tmp_path: Path) -> None:
    # two broken questions → one error whose message names both ids
```

`MANIFEST` is built in the test module from `CorpusDocument` values (`contract`, `report`, and
`report-2024` with `selected_by_default=False`); `ANSWERABLE`, `UNANSWERABLE`, `CONFLICT`, `GOLD`
are dict literals the helper serialises to TOML.

- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_questions.py -q` — FAIL.

- [ ] **Step 3: Implement `evals/questions.py`.** Collect every problem as `"<id>: <reason>"`
  and raise one `QuestionFileError` joined by newlines. Pages are valid inside the document's
  `page_range` when set, else `1..page_count`.

- [ ] **Step 4: Run** the tests — PASS; mypy and Ruff clean.

- [ ] **Step 5: Commit** — "Add the benchmark question file".

---

### Task 4: Scoring

**Files:**
- Create: `evals/scoring.py`, `tests/unit/evals/test_scoring.py`

**Interfaces:**
- Consumes: `normalize`, `word_coverage` (Task 1); `GoldSpan`, `Question` (Task 3);
  `sourcehaven.retrieval.search.select_evidence`; `Evidence`, `ExtractedPage`, `PageSpan`.
- Produces:
  - `QUOTE_COVERAGE_THRESHOLD: Final[float] = 0.8`.
  - `@dataclass(frozen=True) class Passage`: `document: str`, `ordinal: int`, `text: str`,
    `normalized: str`, `pages: PageSpan`; `evidence(self, similarity: float) -> Evidence` builds an
    `Evidence` with `uuid5`-derived ids (document id → `document_id` and `version_id`,
    `f"{document}:{ordinal}"` → `chunk_id`) and `document_name=document`.
  - `@dataclass(frozen=True) class Ranked`: `passage: Passage`, `similarity: float`.
  - `contains(passage: Passage, span: GoldSpan) -> bool`.
  - `covering_rank(ranking: Sequence[Passage], spans: Sequence[GoldSpan]) -> int | None` (1-based).
  - `choose_passages(candidates: Sequence[Ranked], *, threshold: float) -> list[Ranked]` — maps to
    `Evidence`, calls `select_evidence(..., threshold=threshold)`, maps back.
  - `type SpanLocation = Literal["on_page", "other_page", "across_pages", "missing"]`;
    `locate_span(span: GoldSpan, pages: Sequence[ExtractedPage]) -> SpanLocation`.
  - `@dataclass(frozen=True) class SpanOutcome`: `span: GoldSpan`, `location: SpanLocation`,
    `split: bool`, `best_rank: int | None`, `selected: bool`, `page_correct: bool | None`,
    `quote: str | None`, `quote_coverage: float | None`.
  - `@dataclass(frozen=True) class QuestionOutcome`: `question: Question`,
    `top_similarity: float | None`, `covering_rank: int | None`, `hit: bool`,
    `spans: tuple[SpanOutcome, ...]`, `candidates: tuple[Ranked, ...]`.
  - `@dataclass(frozen=True) class Distribution`: `count: int`; `minimum`, `p10`, `median`, `p90`,
    `maximum`, each `float | None` (all `None` when empty); `distribution(values: Sequence[float]) -> Distribution`.
  - `@dataclass(frozen=True) class ThresholdRow`: `threshold: float`, `recall_at_8: float`,
    `refused: float`; `threshold_table(outcomes: Sequence[QuestionOutcome]) -> list[ThresholdRow]`.
  - `@dataclass(frozen=True) class Metrics`: `answered_questions: int`, `unanswerable_questions: int`,
    `recall_at_8: float`, `mrr_at_10: float`, `extraction_coverage: float`, `split_spans: int`,
    `page_accuracy: float | None`, `quote_precision: float | None`, `mean_quote_coverage: float | None`,
    `answerable_top: Distribution`, `unanswerable_top: Distribution`, `thresholds: list[ThresholdRow]`.
  - `summarize(outcomes: Sequence[QuestionOutcome]) -> Metrics`.

Definitions are spec §4.3. "Answered questions" means kinds `answerable` and `conflict`.
`distribution` uses `statistics.quantiles(values, n=10, method="inclusive")` for p10/p90 and
`statistics.median`; one value gives that value everywhere. `refused` is the share of unanswerable
questions for which `choose_passages(candidates, threshold=t)` is empty.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_passage_from_another_document_never_contains_the_span() -> None:
    span = GoldSpan(document="report", page=13, text="Import dependency was 40%.")
    assert contains(passage("report", "… Import dependency was 40%. …"), span)
    assert not contains(passage("report-2024", "… Import dependency was 40%. …"), span)

def test_covering_rank_needs_every_span() -> None:
    a, b = span_in("report", "alpha"), span_in("report-2024", "beta")
    ranking = [passage("report", "alpha"), passage("x", "noise"), passage("report-2024", "beta")]
    assert covering_rank(ranking, [a]) == 1 and covering_rank(ranking, [a, b]) == 3
    assert covering_rank(ranking[:2], [a, b]) is None

def test_choose_passages_applies_the_threshold_and_document_cap() -> None:
    ranked = [Ranked(passage("a", f"t{i}", ordinal=i), 0.9 - i / 100) for i in range(6)] + [
        Ranked(passage("b", "u"), 0.5)]
    chosen = choose_passages(ranked, threshold=0.0)
    assert sum(r.passage.document == "a" for r in chosen) == 4 and chosen[-1].passage.document == "b"
    assert choose_passages(ranked, threshold=0.95) == []

def test_locate_span() -> None:
    pages = [ExtractedPage(1, "Intro text.", True), ExtractedPage(2, "The answer is 42.", True),
             ExtractedPage(3, "Starts here and", True), ExtractedPage(4, "ends there.", True)]
    assert locate_span(GoldSpan("d", 2, "the answer is 42"), pages) == "on_page"
    assert locate_span(GoldSpan("d", 1, "the answer is 42"), pages) == "other_page"
    assert locate_span(GoldSpan("d", 3, "here and ends there"), pages) == "across_pages"
    assert locate_span(GoldSpan("d", 2, "not present"), pages) == "missing"

def test_summarize_on_hand_made_outcomes() -> None:
    # 2 answered (one hit at covering rank 2, one miss with rank None) and 2 unanswerable
    metrics = summarize([...])
    assert metrics.recall_at_8 == 0.5 and metrics.mrr_at_10 == 0.25
    assert metrics.quote_precision == 1.0  # the hit's only span has coverage 0.85

def test_rank_beyond_ten_scores_zero_mrr() -> None: ...

def test_question_without_candidates_or_with_negative_similarity() -> None:
    outcome = unanswerable_outcome(candidates=(), top_similarity=None)
    negative = unanswerable_outcome(candidates=(Ranked(passage("a", "x"), -0.2),), top_similarity=-0.2)
    metrics = summarize([answered_hit(), outcome, negative])
    assert metrics.unanswerable_top.count == 1 and metrics.unanswerable_top.minimum == -0.2
    assert metrics.thresholds[0].refused == 1.0  # both refused at threshold 0.00

def test_threshold_table_rows() -> None:
    rows = threshold_table([...])
    assert len(rows) == 101 and rows[0].threshold == 0.0 and rows[-1].threshold == 1.0
    assert rows[50].recall_at_8 == ... and rows[50].refused == ...
```

`passage(...)`, `span_in(...)` and the outcome builders are local helpers.

- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_scoring.py -q` — FAIL.

- [ ] **Step 3: Implement `evals/scoring.py`.** `locate_span`: normalised search on the gold page
  first, then on each other page, then on all pages joined with `"\n\n"` (→ `across_pages`).
  Thresholds are `round(i / 100, 2)` for `i` in `0..100`.

- [ ] **Step 4: Run** the tests — PASS; mypy and Ruff clean.

- [ ] **Step 5: Commit** — "Add benchmark scoring".

---

### Task 5: Embedding configuration, tokenizer download and vector cache

**Files:**
- Create: `evals/embedding.py`, `tests/unit/evals/test_embedding.py`

**Interfaces:**
- Consumes: `Settings`, `EmbeddingConfig`, `Embedder` protocol.
- Produces:
  - `benchmark_config(settings: Settings, *, chunk_tokens: int, chunk_overlap: int) -> EmbeddingConfig`
    — `dataclasses.replace(EmbeddingConfig.from_settings(settings), ...)`; `ValueError` unless the
    provider is `tei`.
  - `async ensure_tokenizer(model_id: str, revision: str, cache_dir: Path, client: httpx.AsyncClient) -> Path`
    — downloads `https://huggingface.co/{model_id}/resolve/{revision}/tokenizer.json` once into
    `cache_dir / "tokenizers" / model_id.replace("/", "--") / revision / "tokenizer.json"`.
  - `class VectorCache` — `__init__(self, path: Path) -> None` (sqlite3, creates the table),
    `get(self, key: str) -> list[float] | None`, `put_many(self, items: Mapping[str, Sequence[float]]) -> None`,
    `close(self) -> None`.
  - `class CachedEmbedder` (satisfies `Embedder`) — `__init__(self, inner: Embedder, cache: VectorCache) -> None`;
    `config`, `embed_documents`, `embed_query`, `embed_queries`, `check_ready` delegate through the
    cache; attributes `embedded_texts: int` and `embed_seconds: float` count only texts sent to
    `inner` and the time spent in those calls. Cache key:
    `f"{config.fingerprint()}:{kind}:{sha256(text)}"` with `kind` `document` or `query`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_cached_embedder_embeds_each_text_once(tmp_path: Path) -> None:
    embedder = CachedEmbedder(HashEmbedder(), VectorCache(tmp_path / "v.sqlite3"))
    first = await embedder.embed_documents(["a", "b"])
    second = await embedder.embed_documents(["b", "a", "c"])
    assert second[:2] == [first[1], first[0]] and embedder.embedded_texts == 3

async def test_query_and_document_vectors_are_cached_separately(tmp_path: Path) -> None: ...
async def test_cache_survives_reopening(tmp_path: Path) -> None: ...

def test_benchmark_config_overrides_passage_size_and_requires_tei() -> None:
    settings = Settings(embedding_model_revision="abc", _env_file=None)
    config = benchmark_config(settings, chunk_tokens=150, chunk_overlap=20)
    assert (config.chunk_tokens, config.chunk_overlap, config.model_revision) == (150, 20, "abc")
    with pytest.raises(ValueError):
        benchmark_config(Settings(embedding_provider="hash", _env_file=None), chunk_tokens=400, chunk_overlap=60)

async def test_tokenizer_is_downloaded_once(tmp_path: Path) -> None:
    # MockTransport asserting the resolve URL; second call makes no request
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_embedding.py -q` — FAIL.

- [ ] **Step 3: Implement `evals/embedding.py`.** Store vectors as `array("d")` bytes. Misses in
  one call go to `inner` as a single batch call, in input order.

- [ ] **Step 4: Run** the tests — PASS; mypy and Ruff clean.

- [ ] **Step 5: Commit** — "Add the benchmark vector cache and tokenizer download".

---

### Task 6: Benchmark pipeline

**Files:**
- Create: `evals/pipeline.py`, `tests/unit/evals/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 2–5; `chunk_pages`, `SourceAdapter`, `TokenCounter`, `Embedder`,
  `CANDIDATE_LIMIT`, `embed_passage_sentences`, `select_quotes`, `Citation`, `LabelledEvidence`.
- Produces:
  - `@dataclass(frozen=True) class DocumentPassages`: `document: CorpusDocument`,
    `source: ExtractedSource`, `passages: tuple[Passage, ...]`, `extract_seconds: float`.
  - `build_passages(document: CorpusDocument, path: Path, adapter: SourceAdapter, counter: TokenCounter, *, chunk_tokens: int, chunk_overlap: int, max_pages: int) -> DocumentPassages`.
  - `@dataclass(frozen=True) class SpeedFigures`: `extract_seconds_per_page: float`,
    `passages_per_page: float`, `embedded_passages: int`, `passages_per_second: float | None`
    (`None` when everything came from the cache), `query_p50_ms: float | None`, `query_p95_ms: float | None`.
  - `@dataclass(frozen=True) class BenchmarkResult`: `outcomes: tuple[QuestionOutcome, ...]`,
    `documents: tuple[DocumentPassages, ...]`, `speed: SpeedFigures`, `config: EmbeddingConfig`.
  - `async run_benchmark(manifest: Manifest, questions: Sequence[Question], files_dir: Path, *, adapter: SourceAdapter, counter: TokenCounter, embedder: CachedEmbedder, latency_embedder: Embedder | None, chunk_tokens: int, chunk_overlap: int, max_pages: int) -> BenchmarkResult`.
  - `QUOTE_TIMEOUT_SECONDS: Final[float] = 60.0` (the benchmark measures quality, not the app's 2 s limit).

Per question (spec §4.2): rank the passages of `question.documents` by cosine similarity, ties by
document id then ordinal; `candidates` = top `CANDIDATE_LIMIT`; selection =
`choose_passages(candidates, threshold=0.0)`; `covering_rank` over the full ranking; per span:
`location` from `locate_span` on that document's pages, `split` when located but contained in no
passage of its document, `best_rank` of the first passage containing it in the full ranking,
`selected` / `page_correct` from the first selected passage containing it. For each selected span of
an answered question, the quote comes from `select_quotes(f"{reference_answer} [S1]", [Citation("S1", evidence, cited=True, quote="")], passage_sentences=embed_passage_sentences([LabelledEvidence("S1", evidence)], embedder), question_vector=..., embedder=embedder, timeout_seconds=QUOTE_TIMEOUT_SECONDS)`.
Query latency: when `latency_embedder` is given, embed each question once more through it, one at
a time, and take p50/p95 with `statistics.quantiles(n=100, method="inclusive")`.

- [ ] **Step 1: Write the failing tests** (offline: committed fixtures, `HashEmbedder`,
  `WhitespaceTokenCounter`, a `CachedEmbedder` over a tmp cache)

```python
async def test_end_to_end_on_the_synthetic_fixtures(tmp_path: Path) -> None:
    result = await run_benchmark(MANIFEST, QUESTIONS, files_dir, ...)  # facts + multipage fixtures
    warranty = outcome(result, "warranty")
    assert warranty.hit and warranty.covering_rank == 1
    (span,) = warranty.spans
    assert span.location == "on_page" and span.page_correct and span.quote_coverage >= 0.8
    assert outcome(result, "bridge").spans[0].selected  # multipage p4 "completed in 1931"
    assert not outcome(result, "peru").hit and outcome(result, "peru").covering_rank is None

async def test_excerpt_passages_keep_physical_pages(tmp_path: Path) -> None:
    pages = build_passages(multipage_with_range(3, 5), ...)
    assert all(3 <= p.pages.start <= p.pages.end <= 5 for p in pages.passages)

async def test_second_run_embeds_nothing(tmp_path: Path) -> None:
    ...
    assert second.speed.embedded_passages == 0 and second.speed.passages_per_second is None

async def test_a_question_only_sees_its_selected_documents(tmp_path: Path) -> None:
    # question selects only "multipage": no candidate from "facts"
```

Fixture copies go to `tmp_path` as `<id>.pdf`; the test manifest's hashes are computed from them.

- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_pipeline.py -q` — FAIL.

- [ ] **Step 3: Implement `evals/pipeline.py`.** Embed all passages of all documents in one
  `embed_documents` call and all questions in one `embed_queries` call. Cosine in pure Python with
  precomputed norms.

- [ ] **Step 4: Run** the tests — PASS; mypy and Ruff clean.

- [ ] **Step 5: Commit** — "Add the benchmark pipeline".

---

### Task 7: Reports, review sheet and the command line

**Files:**
- Create: `evals/report.py`, `evals/benchmark.py`, `tests/unit/evals/test_report.py`,
  `tests/unit/evals/test_benchmark.py`
- Modify: `compose.dev.yaml` (publish `embeddings` on `"127.0.0.1:8081:80"`, comment: "for the
  benchmark, `uv run python -m evals.benchmark run`"); `scripts/check-package.sh` (add `evals` to
  `FORBIDDEN_PATTERN`'s directory list so neither artefact can carry it)

**Interfaces:**
- Consumes: Tasks 2–6; `PdfAdapter`, `TeiEmbedder`, `HfTokenCounter`, `Settings`, `EmbedderNotReady`.
- Produces:
  - `@dataclass(frozen=True) class RunContext`: `created_at: datetime`, `git_commit: str`,
    `corpus_version: int`, `questions_sha256: str`, `label: str`.
  - `write_report(result: BenchmarkResult, metrics: Metrics, context: RunContext, reports_dir: Path) -> Path`
    — creates `reports_dir / f"{created_at:%Y%m%dT%H%M%SZ}-{label}"` with `report.json` (context,
    parser name and version, `dataclasses.asdict(config)`, metrics, speed, every outcome without
    `candidates`) and `summary.md`; returns the directory.
  - `render_summary(result: BenchmarkResult, metrics: Metrics, context: RunContext) -> str` — header
    with context and configuration; metrics table; similarity distributions; the threshold table
    for every 0.05; speed; a "Misses" list per missed question with each span's location, `split`
    and `best_rank`.
  - `render_review_sheet(questions: Sequence[Question], locations: Mapping[tuple[str, int], SpanLocation]) -> str`
    — keyed by (question id, span index); one section per question: id, kind, question, selected
    documents, reference answer, each span with document, page, text and location; a top summary
    counting spans per location.
  - `main(argv: Sequence[str] | None = None) -> int` with subcommands `fetch`, `check`, `run`;
    shared options `--manifest`, `--questions`, `--files`, `--cache`, `--reports` defaulting to
    paths under `Path(__file__).resolve().parent` (`corpus/manifest.toml`, `questions.toml`,
    `corpus/files`, `.cache`, `reports`); `run` adds `--tei-url` (default
    `http://127.0.0.1:8081`), `--chunk-tokens`/`--chunk-overlap` (default from settings),
    `--label` (default `run`), `--tokenizer-file`.
  - `async run_command(options: RunOptions, *, embedder: Embedder, counter: TokenCounter, measure_latency: bool) -> Path`
    — calls `embedder.check_ready()` first, then loads the manifest and questions, wraps `embedder`
    in a `CachedEmbedder` over `options.cache / "vectors.sqlite3"`, runs with
    `latency_embedder=embedder if measure_latency else None`, summarises and writes; `main` builds
    the TEI pieces and maps `EmbedderNotReady`, `CorpusError` and `QuestionFileError` to a
    one-line message on stderr and exit code 2. `RunOptions` is a frozen dataclass of the parsed
    `run` options.
  - Module entry: `if __name__ == "__main__": raise SystemExit(main())`.

`git_commit` comes from `git rev-parse HEAD` (`"unknown"` if it fails), with `-dirty` appended when
`git status --porcelain` is non-empty.

- [ ] **Step 1: Write the failing tests**

```python
def test_review_sheet_lists_every_span_and_summary_counts() -> None:
    sheet = render_review_sheet(QUESTIONS, {("q-1", 0): "on_page", ("q-3", 0): "missing", ...})
    assert "q-1" in sheet and "missing: 1" in sheet

def test_summary_lists_misses_with_their_cause() -> None: ...

def test_report_json_round_trips_the_metrics(tmp_path: Path) -> None:
    directory = write_report(RESULT, METRICS, CONTEXT, tmp_path)
    data = json.loads((directory / "report.json").read_text())
    assert data["metrics"]["recall_at_8"] == METRICS.recall_at_8 and data["context"]["label"] == "test"

def test_check_writes_the_review_sheet_offline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--manifest", str(manifest), "--questions", str(questions),
                 "--files", str(files), "--reports", str(tmp_path / "reports")]) == 0
    assert (tmp_path / "reports" / "review-sheet.md").exists()

def test_check_fails_on_an_invalid_question_file(tmp_path: Path, capsys: ...) -> None:
    assert main([...broken questions...]) == 2 and "q-1" in capsys.readouterr().err

async def test_run_stops_before_any_work_when_tei_is_not_ready(tmp_path: Path) -> None:
    embedder = NotReadyEmbedder()  # check_ready raises EmbedderNotReady("TEI serves model 'x'")
    with pytest.raises(EmbedderNotReady):
        await run_command(options, embedder=embedder, counter=WhitespaceTokenCounter(), measure_latency=False)
    assert embedder.embed_calls == 0 and not (tmp_path / "reports").exists()

async def test_run_command_writes_a_report_on_the_fixtures(tmp_path: Path) -> None: ...
```

`check` writes `reports_dir / "review-sheet.md"` (overwriting) and prints the location counts.
`NotReadyEmbedder` already exists in `tests/support/embeddings.py`; add an embed-call counter to it
if it has none.

- [ ] **Step 2: Run** `uv run pytest tests/unit/evals -q` — new tests FAIL.

- [ ] **Step 3: Implement `evals/report.py` and `evals/benchmark.py`, and the Compose port.**

- [ ] **Step 4: Run** `uv run pytest tests/unit -q`, `uv run mypy`, Ruff — all pass. Run
  `uv run python -m evals.benchmark --help` from the repository root — prints usage. Run
  `scripts/check-package.sh` (sandbox disabled if needed) — passes, so neither the wheel nor the
  sdist contains `evals/`.

- [ ] **Step 5: Commit** — "Add the benchmark command and reports".

---

### Task 8: The corpus manifest and attributions

**Files:**
- Create: `evals/corpus/manifest.toml`, `evals/corpus/README.md`

- [ ] **Step 1: Write `manifest.toml`** (`version = 1`) from spec §3.4: the six documents with the
  URLs and SHA-256 values in the Sources table; `size_bytes` 649932, 786279, 2027518, 2033286,
  24582768 (`book`), 12796516 (`report-2024`); page counts 84, 16, 90, 54, 201, 54; `book` has
  `pages = [17, 100]`; `report-2024` has `selected_by_default = false`. Take `title`, `author` and
  `licence` from the PDF's title and copyright pages, `licence_url` from the spec's licence-evidence
  links (`book`: the book's OpenStax details page).

- [ ] **Step 2: Write `README.md`:** what the corpus is for (link to the design), how to fetch, and
  an attribution list (title, author, source URL, licence with link, "excerpt: physical pages
  17–100" for the book), stating that the PDFs are not redistributed here and that
  `questions.toml` quotes short excerpts under the same licences.

- [ ] **Step 3: Fetch** — `uv run python -m evals.benchmark fetch` (network; in the sandbox pass the
  hosts `assets.publishing.service.gov.uk`, `aclanthology.org`, `nvlpubs.nist.gov`,
  `assets.openstax.org` in `allowed_domains`). Expected: six verified files in
  `evals/corpus/files/`. If a hash no longer matches, stop and report it to the owner; do not
  change the manifest silently.

- [ ] **Step 4: Run** `uv run python -m evals.benchmark check` with an empty `questions.toml`
  (zero questions is valid) — exit 0. `git status` shows no PDF.

- [ ] **Step 5: Commit** — "Add the benchmark corpus manifest".

---

### Task 9: Questions and gold spans

Done in the main session (it needs to view rendered PDF pages). No code.

**Files:**
- Modify: `evals/questions.toml`

- [ ] **Step 1: Draft per document** by reading the rendered pages of `evals/corpus/files/<id>.pdf`
  (the Read tool, at most 20 pages per call; for `book` only pages 17–100). Rules (spec §3.3):
  about 40 questions — about 28 answerable spread 4–7 per document, 2–4 conflict questions
  selecting all six documents with one span in each energy edition, about 10 unanswerable with at
  least 5 on-topic near-misses (energy near-misses unanswerable from both editions); at least 3
  table-cell answers and at least 3 answers from the paper's second column; questions phrased as a
  reader would ask; spans typed from the rendered page, ≤ 250 characters, no superscripts,
  subscripts or formulas; one-sentence reference answers. Ids `<document>-NN`, `conflict-NN`,
  `none-NN`.

- [ ] **Step 2: Run** `uv run python -m evals.benchmark check`. For each span not `on_page`, look at
  the rendered page again: fix a typo or page number in the span; keep a genuine pypdf failure
  (split words, scrambled table, flattened exponent) and note it in a TOML comment above the span.

- [ ] **Step 3: Repeat Step 2** until every remaining non-`on_page` span carries a comment
  explaining the pypdf failure.

- [ ] **Step 4: Commit** — "Add the benchmark questions and gold spans".

- [ ] **Step 5: Owner gate.** Tell the owner where `evals/reports/review-sheet.md` is and what to
  look for (question wording, gold spans, unanswerable questions that are actually answerable).
  Stop until they reply; apply their corrections, rerun `check`, commit.

---

### Task 10: Baseline run and checkpoint

**Files:**
- Create: `docs/superpowers/checkpoints/2026-11-2X-corpus-and-harness-complete.md` (actual date)

- [ ] **Step 1: Start TEI** (sandbox disabled): check Docker disk space first, never prune; then
  `docker compose -f compose.yaml -f compose.dev.yaml up -d embeddings` and wait until healthy.
  If the owner's `api`/`worker` containers are running, leave them alone.

- [ ] **Step 2: Run** `uv run python -m evals.benchmark run --label baseline` — exit 0; note the
  report directory.

- [ ] **Step 3: Run it again** with `--label baseline-repeat` and compare the two `report.json`
  metrics and per-question ranks. Expected: identical (spec §4.4). Any difference goes into the
  checkpoint with its size.

- [ ] **Step 4: Write the checkpoint:** what was delivered; the baseline configuration (commit,
  corpus version, questions hash, parser, model and revision, 400/60); the metrics table;
  similarity distributions and the threshold table rows 0.00–1.00 every 0.05; speed figures marked
  "development host, informative"; the misses grouped by cause (not extracted, split, ranked low)
  as input for pieces 3–5; the owner decisions and the rulings made during execution with their
  cost if wrong; open items; "Next: piece 3, parser comparison". Run the full unit suite, mypy and
  pre-commit; report exactly what ran.

- [ ] **Step 5: Commit** — "Record the corpus and benchmark checkpoint". Update the project memory.
  Ask the owner before merging into `main` or pushing.
