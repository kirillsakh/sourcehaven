# Evaluation corpus and retrieval benchmark — design

- **Status:** approved by the owner on 2026-11-21
- **Date:** 2026-11-20
- **Parent:** [`2026-11-19-sourcehaven-design.md`](2026-11-19-sourcehaven-design.md) §8.2, §8.3, §8.5,
  §15 (M2); M2 piece 2 of 5 (the order is in
  [`2026-11-20-quote-selection-design.md`](2026-11-20-quote-selection-design.md))
- **Branch:** `m2/corpus-harness`
- **Size:** a project-sized piece: new top-level `evals/` package, committed question set, one
  dev-only Compose port; no change to the application's behaviour, API, database or UI

Tags as in the parent design: **[A]** agreed with the owner, **[P]** the designer's call, open to
correction, **[B]** left to the builder within the stated constraints.

## 1. Intent

Pieces 3–5 of M2 choose the PDF parser, the passage size and the embedding model, and calibrate the
evidence threshold, which is 0.0 today. Each of those choices should rest on numbers rather than on
impressions from a few demo questions. This piece builds what produces the numbers: a fixed corpus
of real, openly licensed PDFs, a question set whose gold answers are a page and the exact supporting
text, and a benchmark script that scores retrieval against them. It ends with a baseline for today's
configuration (pypdf, 400-token passages with 60 overlap, `snowflake-arctic-embed-m-v2.0`).

What is measured is everything before the language model: whether the passage that holds the answer
is among the passages the model would receive. If it is not, no model can answer correctly. The
benchmark makes no OpenAI calls and costs nothing to run [A].

### 1.1 Goals

- A corpus of six real PDFs covering the layouts in parent §8.2, two of which conflict (§3.4).
- About 40 questions, of which about 10 are unanswerable; several unanswerable questions are
  on-topic near-misses (the corpus discusses the subject but does not state the answer) [A].
- Every answerable question has gold spans (document, physical page, exact supporting text) and a
  one-sentence reference answer.
- A benchmark command that reports, per configuration: Recall@8, MRR@10, gold-span extraction
  coverage, spans split across passages, page accuracy, quote precision, the similarity
  distributions of answerable vs unanswerable questions, and speed figures.
- A baseline report for today's configuration, recorded in this piece's checkpoint.
- Switches that pieces 3–5 reuse: passage size and overlap now; parser and model are added by those
  pieces through the same seams.

### 1.2 Non-goals

- Choosing a parser, passage size, model or threshold (pieces 3–5).
- Adding pdfplumber or pypdfium2 adapters (piece 3).
- Answer-quality evaluation with a real model (parent §8.4): answer support, refusals, conflicting
  sources, prompt injection, cost. It stays opt-in and later (M7's live evaluation run). The
  prompt-injection document is added to the corpus then, not now [P].
- Absolute speed and TEI memory acceptance numbers; those need the target-sized VM (parent §8.2)
  and belong to piece 5.
- Running the benchmark in CI. It needs network access to fetch the corpus and a running TEI.

### 1.3 Anti-goals

- **A benchmark that flatters.** Questions must not copy the documents' wording, and gold spans must
  come from reading the PDF, not from pypdf's output, otherwise the parser comparison measures
  nothing. Generated synthetic PDFs are excluded for the same reason: every parser reads them
  perfectly [A].
- **A benchmark that drifts from production.** The script calls the same parsing, splitting,
  embedding, evidence-selection and quote-selection code the app runs; it reimplements only the
  database's cosine ranking.
- **Committing third-party PDFs or anything sensitive.** The PDFs are fetched by URL and verified by
  hash, never committed [A]; nothing from visitors or real people's documents is used.

## 2. Approaches

How the benchmark runs the pipeline [A: the owner chose A on 2026-11-20]:

- **A. Call the app's functions directly, without a database (chosen).** The script runs
  `PdfAdapter.extract`, `chunk_pages`, `TeiEmbedder` and `select_evidence` itself and ranks passages
  by cosine similarity in memory. Production retrieval is also an exact cosine scan (parent §7.2),
  so the ranking is the same apart from float rounding that could swap near-ties. Needs only TEI;
  the first run embeds about 1,200 passages in a few minutes, and repeated runs reuse cached
  vectors; parser, passage size and model
  become command-line switches without touching app settings or triggering re-ingestion. It skips
  the database and worker, which the integration tests already cover and which do not decide which
  passages are found.
- **B. The real ingestion into a scratch database** (what parent §8.2 said): most faithful, but
  needs Docker and a database per run and a full re-ingestion per variant, and measures nothing A
  does not.
- **C. Through the HTTP API with a fake model:** B plus sessions and streaming, still no extra
  information. Dropped.

This changes parent §8.2's "ingests the corpus … through the real pipeline into a scratch database";
the parent is amended to point here.

## 3. Corpus

### 3.1 Documents

One document per layout from parent §8.2, plus a conflicting pair [A]:

| Id | Layout | Why it is in the corpus |
|---|---|---|
| `contract` | Contract-like legal text | Numbered clauses, definitions, cross-references |
| `paper` | Two-column academic paper | Reading order across columns |
| `manual` | Manual or technical guide with tables | Facts that live in table cells |
| `report` | Report with sections, figures and some tables | Long structured prose |
| `book` | Long book excerpt | Many similar passages; narrative prose |
| `report-2024` | The previous edition of `report` | The same facts with different values |

Requirements for every document [P]: English, born-digital with a real text layer, openly licensed
so redistribution is allowed (CC BY, CC BY-SA, CC0, public domain, US federal work, UK OGL or
similar) with the licence verified on the publisher's own page, a stable direct-download URL, no
personal data about private individuals, no text aimed at AI systems, at most 300 benchmarked pages
(the app's page limit; a longer book is cut to a page range, below). The 20 MiB upload limit does not
apply: the benchmark never goes through upload, and file size does not affect retrieval, so the
corpus may include a larger file [P]. The selected documents are listed in §3.4.

### 3.2 Manifest and fetching

- `evals/corpus/manifest.toml` (committed) lists each document: `id`, title, publisher or author,
  `url`, `sha256`, byte size, page count, licence name, licence-evidence URL, layout, and an optional
  `pages` range for excerpts [P]. TOML because the standard library reads it (`tomllib`), so no new
  dependency [P].
- `uv run python -m evals.benchmark fetch` downloads every document into `evals/corpus/files/`
  (ignored by Git), verifies the SHA-256 and byte size, and refuses a mismatch instead of using the
  file. Already verified files are not downloaded again [P].
- **Excerpts:** a document with a `pages` range is benchmarked on those physical pages only; page
  numbers in gold spans and reports stay the original physical page numbers. The harness passes only
  those pages to the splitter, so the excerpt behaves as if it were the whole document [P]. How the
  excerpt reaches the adapter (slicing a copy with pypdf, or filtering extracted pages) is [B],
  provided the parser under test still opens the original file.
- `evals/corpus/README.md` gives each document's attribution (title, author, source, licence), as
  CC BY requires; the committed question file quotes short excerpts from the documents [P].
- The manifest has a `version`; changing a document or its range bumps it, and reports record it.

### 3.3 Questions and gold answers

`evals/questions.toml` (committed), one entry per question [P]:

```toml
[[question]]
id = "manual-03"
kind = "answerable"          # answerable | unanswerable | conflict
text = "What is the maximum operating temperature of the unit?"
documents = []               # empty: all corpus documents are selected
reference_answer = "The unit operates at up to 45 °C."

[[question.gold]]
document = "manual"
page = 17                    # physical, 1-based
text = "Operating temperature 0 °C to 45 °C"
```

- **Kinds:** about 28 answerable, about 10 unanswerable (no gold, no reference answer), and 2–4
  conflict questions whose gold has one span in each of `report` and `report-2024` [A for the
  counts, P for the split].
- **Selection:** by default a question runs with every corpus document selected except
  `report-2024`, as a visitor who uploaded them all would. `report-2024` repeats most of `report`
  word for word, so selecting both by default would score the right fact found in the other edition
  as a miss and let the two editions fill each other's per-document slots. Conflict questions list
  all six documents; a question may list documents to narrow it [P].
- **Spread:** about 4–7 questions per document; at least 3 whose answer is in a table cell and at
  least 3 whose answer is in the paper's second column; questions phrased the way a reader would ask,
  not copied from the text [P].
- **Gold spans** are copied from the PDF as a person reads it, not from any parser's output: the
  builder reads the rendered page (an assistant that can view PDF pages, or a PDF viewer) and types
  the span, then `check` compares it with the extraction. Each span is one sentence, clause or table
  row, at most about 250 characters, so it fits in one 150-token passage and in a 300-character
  quote. Spans avoid superscripts, subscripts and formulas: their "correct" plain-text form is
  ambiguous, and NFKC normalisation would fold "10²⁴" into "1024" and hide exactly the flattening
  pypdf shows on `manual`. The parser comparison judges reading order and tables, not mathematical
  typesetting [P].
- **Unanswerable near-misses:** at least 5 of the unanswerable questions concern a subject the
  corpus discusses (for example a figure for a year the report does not cover). A near-miss about
  the energy report must be unanswerable from both editions [P].
- **Authoring:** the builder drafts the questions, spans and reference answers; the owner reviews a
  generated review sheet (below) before the baseline is recorded [A].

### 3.4 Selected documents

Researched on 2026-11-20 [P, for the owner to confirm]. Each file was downloaded, hashed and
extracted with the pinned pypdf 7.1.1. Each licence was read on the publisher's own page. Page
numbers are physical.

| Id | Document | Licence | Pages | Size | Why this one |
|---|---|---|---|---|---|
| `contract` | UK Government *Model Services Contract — Terms and Conditions* (MHCLG edition, TCMSC 11.25) | OGL v3.0 (stated in the PDF, p5) | 84 | 0.6 MB | Numbered clauses and inline defined terms. Clean text with a three-line header on every page. Drafting placeholders such as "[£10 million]" |
| `paper` | Devlin et al., *BERT* (NAACL 2019), ACL Anthology N19-1423 | CC BY 4.0 (ACL Anthology, 2016 onwards) | 16 | 0.8 MB | Two columns and results tables. pypdf keeps the ﬁ/ﬂ ligature characters and splits hyphenated words at line ends. Page labels restart in the appendix |
| `manual` | NIST SP 811 (2008), *Guide for the Use of the International System of Units* | US government work | 90 | 2.0 MB | Many tables. pypdf flattens exponents ("10^24" becomes "1024") and breaks the dot-leader conversion tables. Printed page = physical − 12 |
| `report` | DESNZ, *UK Energy in Brief 2025* | OGL v3.0 (gov.uk publication page) | 54 | 2.0 MB | Short sections, each with a small table and a chart. pypdf splits some words ("Perc entage") |
| `book` | OpenStax, *Introduction to Intellectual Property*, physical pages 17–100 (chapters 1–2) | CC BY 4.0 (stated in the PDF) | 84 of 201 | 24.6 MB | Long textbook prose with many similar passages. The footer "Access for free at openstax.org" repeats on every page |
| `report-2024` | DESNZ, *UK Energy in Brief 2024* | OGL v3.0 (gov.uk publication page) | 54 | 12.8 MB | The earlier edition of `report`. Revised figures for 2023 give natural conflicts |

The corpus has six files, about 380 pages in all. Examples of
conflicting 2023 figures in the two editions:
- import dependency: 41 % in the 2024 edition, 40 % in the 2025 edition, p13 of each;
- total natural gas demand: 696.3 TWh vs 700.0 TWh, p27;
- domestic gas demand: 237.1 TWh vs 242.9 TWh, p27.

**Sources** (checked 2026-11-20; SHA-256 of the whole file):

| Id | URL | Bytes | SHA-256 |
|---|---|---|---|
| `contract` | <https://assets.publishing.service.gov.uk/media/6953ae6897f1c5e3c92a8322/MHCLG__Model_Services_Contract_Terms_and_Conditions.pdf> | 649,932 | `00f37dbba296eb4f3db214f24cc7f8a478ebe48ab494669e0c494e98424c1f3d` |
| `paper` | <https://aclanthology.org/N19-1423.pdf> | 786,279 | `987545ffb087f1ece898142c403a516baeabeb70ce19089397fac6f7db12c3d4` |
| `manual` | <https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication811e2008.pdf> | 2,027,518 | `788dd8f0bcb0ec06e40c300690266742532a7e760a93be57764b77ed0ef3482f` |
| `report` | <https://assets.publishing.service.gov.uk/media/688890c3a11f859994409132/UK_Energy_in_Brief_2025.pdf> | 2,033,286 | `83fb8966db7a5e4e8e4e54fbe035e8bd03aebf64ec3166658e7ddaa69cd6ebe5` |
| `book` | <https://assets.openstax.org/oscms-prodcms/media/documents/introduction-intellectual-property_-_WEB.pdf> | 24.6 MB | `1498509864d37cb63a6ccc11bab7c783f3d30b2ed37d808ef80c56fdb676378a` |
| `report-2024` | <https://assets.publishing.service.gov.uk/media/687f4cf592957f2ec567c64f/UK_Energy_in_Brief_2024.pdf> | 12.8 MB | `bed33e10c664152c09327e28d68d4c58bdf55e299089f4630d75ae89fde3871d` |

Licence evidence: OGL on the gov.uk publication pages
(<https://www.gov.uk/government/publications/model-services-contract-terms>,
<https://www.gov.uk/government/statistics/uk-energy-in-brief-2025>,
<https://www.gov.uk/government/statistics/uk-energy-in-brief-2024>); ACL Anthology
<https://aclanthology.org/faq/copyright/>; NIST
<https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications>;
OpenStax in the PDF (p4). The manifest records the exact byte sizes of the two larger files when
it is written.

**Stability.** Most URLs are stable government or ACL
Anthology URLs. The OpenStax URL is not versioned, and the file last changed in April 2026. If its
hash stops matching, `fetch` fails with a clear message. The fix is to update the manifest
deliberately, bumping the corpus version, or to point it at an archived copy [P].

**Caveats.**
- BERT is famous, so a language model may answer questions about it from memory. That does not
  affect this retrieval benchmark, but it matters for the later answer-quality run, which should
  weigh BERT questions accordingly.
- The OGL statement for the two Energy in Brief PDFs comes from the gov.uk publication page ("except
  where otherwise stated"); the PDFs themselves say nothing.
- OpenStax figures carry their own CC BY credits. Figures are not used.

**Backups**, also downloaded and verified:
- `contract`: MHCLG *Mid-Tier Terms and Conditions*, 39 pages, OGL.
- `paper`: *Sentence-BERT*, ACL Anthology D19-1410, 11 pages, CC BY 4.0.
- `manual`: NIST FIPS 197-upd1 (AES), 46 pages; its tables come out column by column and the "fi"
  ligature is dropped.
- `report`: USGS *Mineral Commodity Summaries 2025*, 216 pages, 10.4 MB, public domain.
- `book`: OpenStax *Statistics*, chapter excerpt, CC BY 4.0.
- Conflicting pair: IRS Publication 15, 2024 vs 2025 (two columns, public domain); for example, the
  social security wage base is $168,600 vs $176,100.

## 4. Benchmark

### 4.1 Commands

The code is a top-level `evals/` package (with `__init__.py`), not part of `src/sourcehaven`, so it
never ships in the wheel; it imports the app through the installed package with absolute imports.
It is run as a module from the repository root [P]:

- `uv run python -m evals.benchmark fetch` — download and verify the corpus.
- `uv run python -m evals.benchmark check` — offline (no TEI): validate the manifest and questions,
  extract every document with the parser, and report whether each gold span is found in its
  document's text and on its page. Writes the **review sheet**: a Markdown file listing each
  question with its kind, gold page and span, reference answer and extraction status.
- `uv run python -m evals.benchmark run [--chunk-tokens N --chunk-overlap N] [--label NAME]` —
  the full benchmark against TEI.

Reports go to `evals/reports/<UTC timestamp>-<label>/` (ignored by Git): `report.json` with every
per-question result and `summary.md` for reading. A report records the corpus version, the
question-file hash, the Git commit, and the parser, splitter and embedding configuration [P].

### 4.2 Pipeline per run

1. For every corpus document: extract with `PdfAdapter` (its page limit applies to the benchmarked
   range), keep the excerpt pages, split with `chunk_pages` using the model's tokenizer.
2. Embed every passage with `TeiEmbedder.embed_documents` (document prefix as in production) and
   every question with `embed_queries` (query prefix).
3. For each question: rank all passages of its selected documents by cosine similarity, take the
   top 20 candidates as `search_evidence` does, and pass them to `select_evidence` with threshold 0
   to get the 8 passages the model would receive.
4. For each answerable question with a hit, run the app's quote selection on the passage that
   holds the gold span, with the reference answer standing in for the model's citing sentence
   (below).

**TEI and tokenizer.** The dev overlay publishes the `embeddings` service on `127.0.0.1:8081` so the
script can reach it from the host [P]. Before a run the script calls `check_ready`, which verifies
that TEI serves the configured model and revision. The splitter needs the model's `tokenizer.json`
at the pinned revision; the script downloads it from the Hugging Face Hub into the ignored cache
(`evals/.cache/`) unless `--tokenizer-file` is given [P].

**Configuration.** The embedding settings (model id, revision, dimensions, prefixes, input limit,
passage size) come from the same `SOURCEHAVEN_*` variables and defaults as the app, read through
`Settings` or an equivalent that does not require database or OpenAI settings [B]; the command-line
switches override passage size and overlap.

**Vector cache.** Passage and question vectors are cached under `evals/.cache/` keyed by the
embedding configuration's fingerprint and the text's SHA-256, so a rerun with unchanged passages
embeds nothing [P]. Storage format is [B] (the standard library's `sqlite3` is enough).

### 4.3 Metrics

Matching is done on normalised text: Unicode NFKC (which also splits ligatures), soft hyphens
removed, a hyphen at a line end joined with the next word, typographic quotes and dashes mapped to
ASCII, all whitespace collapsed to one space, case folded [P]. A passage **contains** a gold span
when it belongs to the span's document and its normalised text contains the normalised span.

| Metric | Definition |
|---|---|
| **Recall@8** | Share of answerable and conflict questions for which every gold span is contained in one of the 8 passages `select_evidence` chooses |
| **MRR@10** | Mean of 1 / r, where r is the smallest rank in the raw similarity ranking at which every gold span is contained in a passage ranked at or above it; 0 if r > 10 |
| **Extraction coverage** | Share of gold spans whose normalised text occurs in the document's extracted text at all: a parser measure, independent of splitting and model |
| **Split spans** | Gold spans found in the document's text but in no single passage: a splitter measure |
| **Page accuracy** | Among hits, share whose containing passage's pages include the gold page |
| **Quote precision** | Among answerable hits, share whose selected quote contains at least 80 % of the gold span's normalised words (as a multiset); the mean word coverage is reported too. The threshold allows for dates and amounts that quote selection replaces with `…` [P] |
| **Similarity distributions** | For each question the top-1 similarity; min, p10, median, p90 and max for answerable and for unanswerable questions |
| **Threshold table** | For thresholds from 0.00 to 1.00 in steps of 0.01: Recall@8 when `select_evidence` uses that threshold, and the share of unanswerable questions refused (no passage reaches it). Piece 5 chooses from it |
| **Speed (informative)** | Extraction seconds per page, passages per page, embedding passages per second, query-embedding p50/p95; measured on the development host, not for acceptance |

**Quote selection in the benchmark.** The app chooses a quote by comparing passage sentences with
the answer sentences that cite the passage. The benchmark uses the question's reference answer with
a citation label appended as that answer, and the hit passage as the single cited source, then calls
the app's `embed_passage_sentences` and `select_quotes`. This measures quote selection without a
paid model call [A]. Conflict questions are scored per span.

The summary also lists every miss: questions whose spans were not found, with the rank of the best
passage from the right document and whether the span was missing from the extracted text, split,
or ranked too low.

### 4.4 Reproducibility

- TEI's CPU inference is expected to give the same vectors for the same input; the builder
  confirms this by running the benchmark twice and comparing the reports. Ties in similarity are
  broken by document id and passage ordinal [P].
- A report is reproducible from its recorded commit, corpus version, question-file hash and
  configuration.

## 5. Repository changes

- `evals/` package: `benchmark.py` (command entry point), plus modules for the corpus, the questions,
  text normalisation and metrics, as the builder sees fit [B].
- `evals/corpus/manifest.toml`, `evals/corpus/README.md`, `evals/questions.toml` (committed).
- `.gitignore`: `/evals/corpus/files/`, `/evals/.cache/`, `/evals/reports/`.
- `compose.dev.yaml`: publish `embeddings` on `127.0.0.1:8081` (dev only).
- `pyproject.toml`: add `evals` to mypy's `files` and to Ruff's `known-first-party`. No new runtime
  dependency; pypdf, tokenizers and httpx are already dependencies [P].
- Parent spec §8.2 amended: harness location and approach, about 40 questions with about 10
  unanswerable, pointer to this design.

The packaging check is unaffected: the build backend packages only `src/sourcehaven`.

## 6. Testing

- Unit tests (offline, in `tests/unit/evals/`): normalisation (ligatures, hyphenation, whitespace),
  span containment, Recall@8 and MRR@10 on hand-made rankings, multi-span (conflict) scoring, the
  threshold table, quote-coverage scoring, manifest and question-file validation (unknown document,
  page out of range, answerable question without gold, duplicate ids).
- One offline end-to-end test runs the whole `run` path on the committed synthetic fixtures
  (`tests/fixtures/documents/`) with the hash embedder and a whitespace token counter, so the
  command is exercised in CI without TEI or network.
- The benchmark itself is not a test and is not run in CI.

## 7. Delivery and acceptance

Piece 2 is done when:

1. `fetch` downloads and verifies every corpus document.
2. `check` reports every gold span as found by pypdf, or the miss is explained in the review sheet
   (a pypdf reading-order or table failure is a finding for piece 3, not an annotation error).
3. The owner has reviewed the review sheet.
4. `run` completes on the development host, and the baseline numbers, with the commit and
   configuration, are recorded in this piece's checkpoint.
5. Unit tests, mypy, Ruff and pre-commit pass.

No recall threshold applies in this piece; the parent §8.3 criteria are applied in piece 5.

## 8. Left to the builder

- Module layout inside `evals/`, the cache format, report layout beyond the fields named above.
- How excerpts reach the adapter (§3.2).
- How the embedding configuration is read without database or OpenAI settings (§4.2).
- The exact wording of the questions within §3.3's rules.
