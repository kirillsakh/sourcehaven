# Checkpoint: evaluation corpus and retrieval benchmark (2026-11-21)

M2 piece 2 of 5. Branch `m2/corpus-harness` (not merged, not pushed). Design
`docs/superpowers/specs/2026-11-20-corpus-and-harness-design.md` (approved 2026-11-21), plan
`docs/superpowers/plans/2026-11-21-corpus-and-harness.md`. Executed subagent-driven (owner's choice):
a fresh implementer and a reviewer per task.

## What was delivered

- A top-level `evals/` package, which is not in the wheel. It calls the app's own `PdfAdapter`,
  `chunk_pages`, `TeiEmbedder`, `select_evidence` and quote selection, and ranks passages in memory.
- `uv run python -m evals.benchmark fetch | check | run`.
  - `fetch` downloads the corpus and verifies each file's size and SHA-256.
  - `check` runs offline, validates every gold span against pypdf's extraction and writes
    `evals/reports/review-sheet.md`.
  - `run` writes `report.json` and `summary.md` under `evals/reports/<timestamp>-<label>/`. Vectors
    are cached in `evals/.cache/`.
- The corpus is six openly licensed PDFs, fetched by URL and never committed (`evals/corpus/`). They
  are a contract, the BERT paper, NIST SP 811, UK Energy in Brief 2025, an OpenStax book (pages
  17–100), and Energy in Brief 2024 for conflicts.
- `evals/questions.toml` holds 43 questions, approved by the owner on 2026-11-21:
  - 30 answerable, 6 per document; 7 are answered by a table row and 5 from the paper's right-hand
    column.
  - 3 conflict questions comparing the 2025 and 2024 editions.
  - 10 unanswerable, 7 of them on-topic near-misses.
- The dev Compose overlay publishes TEI on `127.0.0.1:8081`.

## Baseline

- **Configuration:** commit 0a4ec73. The report shows `-dirty` only because of two stray formatting
  edits in plan files, see Open items. Corpus version 1; question file SHA-256 `23c6d700…cedf6`;
  pypdf 7.1.1; `snowflake-arctic-embed-m-v2.0` at revision `95c2741…f017f`; passages of 400 tokens
  with 60 overlap; query prefix `query: `.
- **Repeatability:** a second run with an empty vector cache gave identical metrics, ranks, quotes
  and similarities (largest difference 0.0).

| Metric | Value |
|---|---|
| Recall@8 (33 answered questions) | 87.9 % |
| MRR@10 | 0.684 |
| Extraction coverage | 94.4 % (34 of 36 spans) |
| Split spans | 0 |
| Page accuracy | 100 % |
| Quote precision (coverage ≥ 80 %) | 62.5 %, mean coverage 67.7 % |

**Top-1 similarity:**

| Questions | Min | P10 | Median | P90 | Max |
|---|---|---|---|---|---|
| Answerable (33) | 0.398 | 0.444 | 0.639 | 0.693 | 0.784 |
| Unanswerable (10) | 0.156 | 0.159 | 0.474 | 0.578 | 0.688 |

**Evidence threshold:**

| Threshold | 0.00–0.15 | 0.20 | 0.25–0.35 | 0.40 | 0.45 | 0.50 | 0.55 | 0.60 | 0.65 | 0.70 |
|---|---|---|---|---|---|---|---|---|---|---|
| Recall@8 | 87.9 % | 87.9 % | 87.9 % | 78.8 % | 78.8 % | 72.7 % | 69.7 % | 48.5 % | 33.3 % | 9.1 % |
| Unanswerable refused | 0 % | 20 % | 30 % | 30 % | 40 % | 60 % | 80 % | 90 % | 90 % | 100 % |

**Speed** (development host, x86_64 Mac with the Compose TEI limits; informative only, not for
acceptance): extraction 0.026 s per page (12.7 s over the 499 pages pypdf parsed, which is the
whole file of every document; the second run gives 0.025); 2.08 passages per excerpt page; 793
passages embedded at 2.4–2.6 passages per second; query embedding p50 39–42 ms, p95 52–84 ms.

## Findings for pieces 3–5

- **Parser (piece 3):**
  - Both extraction failures are pypdf's. `manual-01` fails on "fo r" split mid-word on p35, and
    `manual-06` because Table 6 on p20 is read column by column.
  - Both questions are therefore misses whatever the passage size or model.
  - Gold has one location per span, but a few facts appear twice: `manual-06` is also answered on
    p62 and p79, and `report-01` on p29 and p30. Recall counts only the annotated location, so it
    can understate what a model could answer.
- **Passage size and model (pieces 4–5):**
  - `paper-04` and `paper-06` are found but ranked 15 and 18, outside the top 8. Both answers are
    short facts inside long two-column paper passages; smaller passages may help.
  - No span was split across passages at 400/60.
- **Threshold (piece 5):**
  - The distributions overlap. An unanswerable near-miss reaches 0.688, above the answerable median
    of 0.639, so no threshold separates the two cleanly.
  - 0.20–0.35 refuses 20–30 % of the unanswerable questions without losing recall. Anything higher
    costs recall quickly.
  - The model's instruction to say when the passages do not contain the answer stays necessary.
- **Quote precision is low for numbers and tables:** 12 spans score under 80 % coverage. The
  baseline quotes (`report.json`) show three causes.
  - Numbers are replaced by "…" (quote-selection ruling 3) and selection works on sentences, so a
    table row or figure is quoted as a caption or a neighbouring sentence. Examples: report-04
    (27 %) and report-05 (7 %) quote the surrounding prose, paper-03 (9 %) quotes the note under
    the results table, contract-05 (22 %) keeps "…Email 9.00am on the first …", and the conflict
    questions (0–19 %) quote chart titles or a bullet fragment instead of the figures.
  - A long run-on sentence is cut at the 300-character limit: contract-02 (38 %) loses the "60
    Working Days' notice" that the span states.
  - A wrong clause in repetitive legal text: contract-06 quotes clause 23.4.2 (liability for
    Government Data), not the Defaults clause in the gold span, yet scores 73 % because the clauses
    share most of their wording.
- **Quote precision is a proxy and close to an upper bound.** The reference answer stands in for
  the sentence a model would cite, and it often repeats the span's wording, which flatters the
  match. Coverage near 80 % in repetitive text (contract-06) therefore needs a look at the quote
  itself, not only at the number.
- Revisit quote selection for numbers and tables in piece 4, or as its own quote fix.
- **Embedding throughput** on the development host (2.5 passages/s) is below the parent §8.3
  criterion of 5 per second. Acceptance is measured on the target VM in piece 5.

## Owner decisions

- About 40 questions with about 10 unanswerable (option B). The benchmark calls the app's functions
  without a database (approach A); parent §8.2 was amended.
- Research notes and anything sensitive go in the ignored `/.superpowers/`. Designs, plans and
  checkpoints stay tracked.
- The design was approved; subagent-driven execution; the question set was approved.
- Observability was raised as the next topic, to show employers production-style operation. It was
  paused until this piece is finished; brainstorm it next.

## Rulings made during execution (cost if wrong)

1. **R1:** a question file with zero questions is valid. Cost: trivial.
2. **R2:** speed counts only the passage-embedding call. Cost: misreported informative speed.
3. **R3:** latency with fewer than 2 samples uses the single value. Cost: none.
4. **R4:** normalisation deletes every hyphen or dash together with the whitespace around it, so
   "a — b" matches "a—b". Cost: words joined across a dash are slightly less distinctive, on both
   sides alike.
5. **R5:** the question loader stays generic; a conflict question needs spans in at least two
   selected documents. Which documents conflict is checked at authoring and in the review sheet.
   Cost: a mistyped conflict document id passes validation.
6. **R6:** conflict questions need a reference answer. Cost: none.
7. **R7:** `hit` is false for unanswerable questions. Cost: none.
8. **R8:** the 300-page limit applies to the whole file, not to the excerpt range. Every corpus
   file is at most 201 pages. Cost: a future source longer than 300 pages would need a larger
   limit.
9. **R9:** `check` builds settings with the hash provider, so it needs no model revision. Cost: none.
10. **R10:** the questions were drafted by a subagent reading the rendered pages, not in the main
    session, to protect the controller's context. They were reviewed (26 spans compared with the
    pages, all 10 unanswerable questions searched) and approved by the owner. Cost: none seen.
11. **Spec corrections:** the Energy in Brief PDFs do state OGL v3.0 (p54). The contract's own
    title is "Core Terms".

## Open items

- **Stray formatting edits:** a subagent ran `ruff format .` over the whole repository, which left
  formatting-only edits in `docs/superpowers/plans/2026-11-20-quote-selection.md` and
  `2026-11-21-corpus-and-harness.md` (uncommitted). Its `git checkout` revert was refused by the
  permission check, so the controller did not revert it on its behalf. The owner decides; until
  then, reports record the commit as `-dirty`.
- **TEI container recreated:** to publish port 8081, the TEI container was recreated. The first
  attempt hit a Docker "zombie" error and stopped it for about a minute, after which it was brought
  back with the port. The owner's `api` and `worker` were not restarted.
- **Deferred minors** (left open by the final review; fix opportunistically, the first two with
  piece 3's first commit):
  - `tests/unit/evals/test_pipeline.py:311`: `(span,) = scored.spans` lacks a type annotation.
  - This checkpoint calls the conflict quotes "chart titles or a bullet fragment". `conflict-02`
    actually quotes prose sentences, still without the figures.
  - `run` downloads the tokenizer and loads it before TEI's readiness check, and a bad
    `--tokenizer-file` ends in a traceback rather than a one-line error with exit 2.
  - The `VectorCache` instances in `test_embedding.py` are not closed (ResourceWarning under
    `-W default`).
  - Untested: `fetch` aborting a download that grows past the pinned size, and truncation of the
    ranking to `CANDIDATE_LIMIT`. The quote test's gold sentence starts its passage, so it cannot
    tell real selection from a passage-start quote.
  - The vector cache key includes passage size and overlap. Every size in piece 4's sweep therefore
    re-embeds the questions and quote sentences. That costs time, not correctness.
  - A report written twice in the same second with the same label overwrites the first.
  - Spec §4.3 still says soft hyphens are "removed"; they are now mapped to a hyphen and joined,
    which has the same effect.
- Earlier open items are unchanged (see the quote-selection checkpoint).

## Next

1. Final whole-branch review, then merge into `main` and push, with the owner's go-ahead.
2. Brainstorm observability (owner request).
3. M2 piece 3: parser comparison (pdfplumber and pypdfium2 adapters behind `--parser`).
