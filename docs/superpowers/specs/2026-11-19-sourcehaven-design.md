# Sourcehaven — MVP design

- **Status:** approved by the owner on 2026-11-19
- **Date:** 2026-11-19
- **Scope:** public anonymous MVP: PDF upload, grounded streamed QA with citations, whole-document and collection summaries
- **Research notes (verified 2026-11-19):** [`docs/superpowers/research/`](../research/)

## How to read this document

Every decision is tagged with where it came from:

- **[R] Requirement** supplied in the project brief or standing instructions.
- **[A] Agreed** explicitly during the design conversation.
- **[P] Proposed default.** The designer's call; it can be changed without reopening the agreed decisions.
- **[D] Deferred.** Out of MVP scope, with a seam and the conditions that would bring it in.

Facts about third-party libraries and services are marked **[V]** when verified against the sources in §17, and **[U]** when they still need verifying during implementation.

---

## 1. Intent

Sourcehaven is a standalone, deployable web application where people bring their own documents, ask questions about them, and request summaries [R]. It is meant to be a real public product that grows into a maintained service, not a private demo [R].

The first visitors come through links the owner shares personally. Later, people should find it through search, so the public pages must be indexable [A]. Visitors try it without registering, on an open anonymous site with private, isolated sessions; it is not an invite-only pilot [A]. Traffic is expected to be modest [A].

**Success for the MVP:**
- A visitor uploads a few PDFs in English.
- They watch ingestion progress.
- They ask questions and get streamed, cited answers grounded only in their own selected documents.
- They can request a summary that genuinely covers a whole document or a set of documents.
- All of this stays inside a small monthly budget, and no visitor can ever see another visitor's material.

### 1.1 Goals

- **G1. Upload and reuse:** upload multiple PDFs, ingest them once, and reuse the prepared index for every later question [R].
- **G2. Grounded answers:** answers are grounded in the visitor's selected documents. They come with page-level citations, or an explicit note when page locations are unavailable [R].
- **G3. Follow-ups:** conversational follow-ups use bounded context [R].
- **G4. Coverage-aware summaries:** summaries of one document or a selected collection cover the whole source, not just the top retrieved passages [R].
- **G5. Streaming:** answers and summaries stream as they are generated. The visitor can stop them, and the UI shows clearly whether a result is complete, interrupted or failed [R].
- **G6. Understandable errors:** errors for bad uploads say what went wrong and, where possible, how to fix it [R].
- **G7. Isolation:** strict per-visitor isolation, enforced on the server and in the database [R].
- **G8. Limits and retention:** explicit limits, a spending cap, retention, cleanup and health checks suitable for a public launch [R].
- **G9. Reproducibility:** setup, tests and deployment run through Docker Compose [R].

### 1.2 Non-goals for the MVP

- User accounts, social or email login, premium libraries, durable history, billing [R].
- Formats other than PDF; OCR; images, audio or video; YouTube or URL ingestion [R].
- Documents, questions or answers in languages other than English, and translation workflows. The product supports English only [A].
- A shared public corpus or any sharing of documents between visitors [R].
- UI localisation; the interface is English [A].
- Advanced observability: metrics, tracing, dashboards, alerting [R].
- Downloading or previewing original uploaded files [P]. Citations show quoted snippets instead. This removes a whole file-serving surface.
- Horizontal scaling and Kubernetes [R].

### 1.3 Anti-goals: failures even if everything "works"

- One visitor sees any trace of another visitor's data, including filenames, snippets, counts, or timing that confirms a document exists.
- A summary that silently covers only part of a document while presenting itself as complete.
- Streamed text presented as a verified final answer when generation was interrupted or failed.
- Spending running past the cap because limits are enforced on the client, or can be reset by opening a new session.
- Private content leaking into search indexes, shared caches, logs or social previews.
- Promising language, format or privacy properties the system has not been evaluated for.

---

## 2. Decision register

### 2.1 Requirements supplied

| Area | Requirement |
|---|---|
| Runtime | CPython 3.14; uv with committed `uv.lock`; one installable package in `src/sourcehaven/`; pytest, Ruff, mypy (strict), pre-commit |
| Storage | Persistent database service in Docker Compose with named volumes; no embedded or in-memory store for the default deployment |
| Isolation | Owner-only access to all data and derived artefacts, enforced in the retrieval/database layer; client IDs are never credentials |
| Streaming | Incremental answers and summaries; Stop control; final citation validation; interrupted vs complete states |
| Summaries | Coverage-aware for whole documents and collections; not top-k retrieval |
| Embeddings | Prefer a local or self-hosted model if measured quality is satisfactory |
| Frontend | Preference for React with Next.js; public pages indexable, private content never indexed |
| Tests | Offline deterministic unit tests; separate container-backed integration suite; committed synthetic fixtures; opt-in live-provider checks; versioned evaluation corpus |
| Git | Atomic commits with pre-commit hooks; no AI attribution |

### 2.2 Decisions agreed in the conversation

| # | Decision |
|---|---|
| A1 | Open anonymous public site with private isolated sessions; no registration in the MVP |
| A2 | Early traffic comes from shared links; SEO for public pages matters later |
| A3 | Per-session upload, storage, request and processing limits, plus per-IP limits and a global spending cap. At capacity, wait in a bounded queue or return a clear "busy" response |
| A4 | English documents, questions and answers; evaluation covers English only. Quotations are preserved verbatim. UI in English |
| A5 | Budget ceiling about USD 100/month: up to $50 hosting, $30 model API, $20 backups/domain/contingency. Spending less is better |
| A6 | Develop and validate locally with Docker Compose first. Propose (but do not provision) a small hosted deployment |
| A7 | CPU-based self-hosted embeddings, if measurements are satisfactory. Generation through an API |
| A8 | Generation provider: OpenAI API (the owner has an API key) |
| A9 | Architecture: **FastAPI backend + Next.js frontend** |
| A10 | **LangChain** for generation (chat model, streaming, prompts) and text splitting. **LangGraph and LlamaIndex excluded from the MVP** |
| A11 | Retention: data deleted 24 h after a session's last activity, and at most 7 days after the session was created. "End session" deletes immediately. Limits as listed in §9 |
| A12 | Summary types: document summary, collection summary, and focused summary (handled as a question). Sectioned summarisation for long documents. Brief and detailed lengths. Summaries are in English |
| A13 | Documents can be any kind (contracts, papers, manuals, reports, books). No user-specified document kind; one automatic, layout-aware pipeline. Scanned PDFs are detected and explained; OCR is deferred |
| A14 | Abuse protection: **Cloudflare Turnstile** verification when a session is created, plus a share of the daily budget reserved for established sessions (§9). The privacy page discloses Cloudflare's processing |
| A15 | Deleting a document removes its file, chunks and every quote taken from it, and keeps the conversation: questions and answers stay, and their sources from that document are shown as deleted. Removal is refused (`409`) while an answer using the document is generating. Replaces the original decision to delete every turn that used it; see `2026-11-20-document-removal-design.md` (§7.5, §10) |
| A17 | The frontend lives in the same Git repository as a separate Node project under `frontend/` (§11.3) |

**Changes after approval:**

- 2026-11-20: language scope narrowed to English only (owner decision); earlier multi-language scope withdrawn.
- 2026-11-20: A15 changed (owner decision): deleting a document keeps the conversation and blanks the quotes taken from it, instead of deleting the turns that used it.

### 2.3 Proposed defaults

These are the main proposals; others are marked [P] where they appear.

- PostgreSQL 18 + pgvector 0.8.7 is the single store. Uploaded files live on a disk volume.
- Hugging Face Text Embeddings Inference (TEI) runs as a CPU sidecar container.
- Provisional embedding model: `Snowflake/snowflake-arctic-embed-m-v2.0`, confirmed or replaced by the experiment in §8.
- Provisional generation model: OpenAI `gpt-6-luna`.
- Ingestion runs in a worker process driven by a Postgres job table, with no Redis or broker.
- Caddy is the reverse proxy and handles TLS.
- Hosting target: a Hetzner Cloud server in an EU location.
- Build backend: `uv_build`. A single `sourcehaven` console script.

### 2.4 Deferred

Accounts, LangGraph, LlamaIndex, more formats, OCR, layout-model parsing, hybrid lexical search, reranking, multimodal retrieval, graph sources, public shared sources, horizontal scaling, advanced observability. See §16 for each one's seam and the condition that would bring it in.

---

## 3. Approaches considered

### 3.1 Complete architectures

| | A. FastAPI + Next.js (**chosen**) | B. Django full stack (templates + htmx) | C. Django API + Next.js | Gradio UI | Flask |
|---|---|---|---|---|---|
| Public-page SEO | Next.js renders on the server or ahead of time; metadata, sitemap and robots built in [V] | Server-rendered templates; good | Same as A | Poor fit | Manual |
| Streaming | FastAPI has native SSE (since 0.135.0) with keep-alive and no-buffering headers [V] | Async `StreamingHttpResponse` under ASGI [V] | Same as B | Built in, demo-grade | Manual |
| Typed boundaries | Pydantic end to end | Django forms/ORM; weaker strict typing | Mixed | Weak | Manual |
| Accounts later | Assembled: OIDC library + own magic links + server sessions | django-allauth and the Django admin are mature | Same as B | Weak | Manual |
| Runtimes | Python + Node | Python only | Python + Node | Python | Python |
| Matches the React/Next.js preference | Yes | No | Yes | No | No |

**Why A:**
- It meets the frontend preference.
- It streams natively.
- Its Pydantic contracts fit the strict-typing rules.
- It keeps the core services (ingestion, retrieval, generation) free of framework weight.

**What A gives up:** the admin and account ecosystem has to be assembled later (§16). C was the close alternative if accounts and admin were needed soon after launch. An Astro + React static frontend was also discussed; it would remove the Node server from production, but Next.js was chosen [A].

### 3.2 Storage

pgvector, Qdrant, Chroma (server) and MongoDB Community + mongot were compared. Details are in [research/2026-11-19-storage.md](../research/2026-11-19-storage.md).

| Criterion | PG + pgvector | Qdrant (+PG) | Chroma (+PG) | MongoDB CE + mongot |
|---|---|---|---|---|
| Compose / operations | 1 service | 2 stores | 2 stores; open Python 3.14 bugs [V] | Replica set + keyfile + extra process |
| Metadata and transactions | Native ACID, same store as vectors | Needs PG; no cross-store transaction | Needs PG | Document transactions |
| Isolation | SQL `WHERE` + row-level security, inside one transaction | Payload filter (`is_tenant`) | Weak | Filter fields |
| Filtered retrieval at our scale | Exact B-tree-scoped scan, perfect recall | Strongest filtered HNSW | Basic | Pre-filter |
| Licence | PostgreSQL licence | Apache-2.0 | Apache-2.0 | SSPL (mongot) [V] |

**Choice:** PostgreSQL 18 + pgvector 0.8.7, image `pgvector/pgvector:0.8.7-pg18` [V].

**Conditions that would change it:**
- Durable libraries with millions of vectors that need heavily filtered approximate search, native multivector/ColBERT, or server-side sparse hybrid search → add Qdrant as the retrieval store, with Postgres staying the source of truth.
- Production-grade BM25 ranking where AGPL is acceptable → ParadeDB.

### 3.3 Orchestration libraries

| Library | MVP role | Reason |
|---|---|---|
| LangChain (`langchain-core`, `langchain-openai`, `langchain-text-splitters`) | **Used.** Chat-model integration, streaming with cancellation, prompt templates, and the text splitter, which counts tokens with the embedding model's tokenizer | Mature integrations; all have Python 3.14 classifiers [V] |
| LangGraph | **Excluded** [A] | The QA flow is a linear pipeline. Conversations live in our own owner-scoped tables, and a checkpointer would add a second memory system whose thread IDs still need separate authorisation |
| LlamaIndex | **Excluded** [A] | Would overlap LangChain for splitting and want to own index/storage. Heavy dependency set [V]. Its file reader pins `pypdf<7` and pulls in pandas [V] |
| `langchain-postgres` | **Not used** [P] | We own the SQL schema so ownership and versioning stay explicit. It also pins `pgvector<0.4` [V] |

### 3.4 Embedding deployment

| Mode | Assessment |
|---|---|
| **TEI CPU sidecar (chosen)** [P] | A Rust server, so the Python 3.14 runtime is irrelevant to it. Keeps torch out of the app image. Supports all shortlisted models without `trust_remote_code` [V]. Batches requests. Memory is capped through Compose. Switching models is a configuration change |
| In-process ONNX Runtime / FastEmbed | Fewest containers, but competes with the API and worker for CPU and RAM, and each model's pooling and prefixes are wired up by hand |
| In-process sentence-transformers + torch | Large image; the Linux torch wheel on PyPI pulls CUDA libraries unless the CPU index is used [V] |
| Hosted embedding API | Sends every document to a third party and adds per-call cost; contradicts A7 unless self-hosting fails the evaluation |

### 3.5 PDF parsing

| Parser | Licence | Notes |
|---|---|---|
| pypdf 7.x | BSD-3 | Pure Python; detects encryption; basic layout mode |
| pdfplumber / pdfminer.six | MIT | Layout analysis (word positions, column grouping); slower, pure Python |
| pypdfium2 (PDFium) | BSD-3 / Apache-2.0 | Fast and robust on damaged files; platform wheels [V] |
| PyMuPDF | **AGPL-3.0** or commercial | **Rejected:** serving it publicly would require releasing the app's source under AGPL [V] |
| Docling and other layout-model parsers | MIT (Docling) | Deferred: heavy ML stack, slow on CPU. A later adapter if the evaluation shows text extraction failing |

**Decision:** [P] The extraction parser is chosen in the §8 experiment from pypdf, pdfplumber and pypdfium2. The basis is reading-order quality on two-column and table fixtures, speed, and robustness. pypdf is the provisional default, and encryption checks use pypdf regardless.

---

## 4. Architecture

### 4.1 Deployment topology

```mermaid
flowchart LR
    Browser -- HTTPS --> Caddy
    subgraph host["Docker Compose host"]
        Caddy -- "/ (pages, assets)" --> Web["web: Next.js standalone"]
        Caddy -- "/api/* (JSON, SSE)" --> API["api: FastAPI (uvicorn)"]
        API --> DB[("db: Postgres 18 + pgvector")]
        API --> TEI["embeddings: TEI CPU"]
        Worker["worker: ingestion + cleanup"] --> DB
        Worker --> TEI
        API --- Uploads[("volume: uploads")]
        Worker --- Uploads
    end
    API -- "HTTPS (generation, summary sections)" --> OpenAI[(OpenAI API)]
```

- **Caddy** is the only container that publishes ports (80/443). It provides automatic TLS. It passes `text/event-stream` through without buffering [V], and streaming routes are excluded from its `encode` (compression) directive [V].
- **`/api/*` goes from Caddy straight to FastAPI** and never through Next.js. Community reports describe SSE being buffered through Next.js rewrites [U]. This routing also means the Next.js server never handles private data.
- **The `web` container** runs Next.js 16 with `output: "standalone"` [V]. It serves the public pages, which are generated ahead of time, and the app shell.
- **The `api` and `worker` containers** use one image built from the `sourcehaven` package (non-editable install, runtime dependencies only), with different commands.
- **`db` and `embeddings`** sit only on the internal Docker network.

**Named volumes:** `pgdata`, `uploads`, `tei-models` (model cache, pinned revision) and `caddy-data`.

**Compose health checks gate startup:** `db` (`pg_isready`) and `embeddings` (TEI `/health`) must be healthy before the `api` and `worker` containers start. A one-shot `migrate` service runs `sourcehaven migrate` before them.

### 4.2 Responsibilities

```mermaid
flowchart TB
    subgraph ingestion["Ingestion (worker)"]
        V[validate] --> P[parse PDF pages] --> C[chunk] --> E[embed] --> S[store + publish]
    end
    subgraph qa["Question answering (api)"]
        Q[question + selected docs] --> R[scoped retrieval] --> X[context assembly] --> G[stream generation] --> CV[citation validation]
    end
    subgraph sum["Summarisation (api, within the request)"]
        SS[sections by page range] --> M[section summaries] --> F[final streamed summary]
    end
    S --> PG[(Postgres)]
    R --> PG
    SS --> PG
```

### 4.3 Package layout

The modules inside `src/sourcehaven/` are a modular monolith [R]:

```
src/sourcehaven/
  __init__.py
  cli.py                 # `sourcehaven serve | worker | migrate`
  config.py              # pydantic-settings Settings
  composition.py         # composition root: builds clients/services, owns lifecycle
  domain/                # frozen dataclasses: ids, OwnerScope, PageSpan, ExtractedPage, ChunkDraft, Evidence, Citation
  sessions/              # anonymous sessions, cookie handling, owner resolution
  ingestion/             # validation, pdf adapter, page checks, chunking, pipeline, job runner
  embeddings/            # EmbeddingConfig, Embedder protocol, TEI client
  storage/               # SQLAlchemy models, repositories, owner-scoped transactions, FileStore
  retrieval/             # scoped vector search, evidence thresholds
  generation/            # chat-model factory (LangChain), prompt templates, usage accounting
  qa/                    # QA service: follow-up handling, context budget, citations
  summaries/             # direct / sectioned / collection summarisation, cache
  limits/                # rate limits, admission control, spending ledger
  api/                   # FastAPI app, routers, SSE encoding, request/response schemas
  worker/                # job loop, cleanup sweeper
  migrations/            # Alembic environment + versions (packaged so production can migrate)
  prompts/               # *.txt prompt templates, read via importlib.resources
frontend/                # Next.js app (separate Node project, own Dockerfile)
deploy/                  # Caddyfile, compose overrides for production, backup scripts
evals/                   # evaluation corpus, questions, benchmark harness (dev-only, not packaged)
tests/
  unit/  integration/  e2e/  fixtures/documents/
docs/
```

- **Packaging:** the build backend is `uv_build` [P]. It supports the `src` layout and ships non-Python files inside the package directory. The packaged resources are `prompts/` and `migrations/`.
- **Contents check:** distribution contents are checked in CI (§13.4).
- **Fallback:** if `uv_build` cannot express a needed include/exclude rule, switch to `hatchling` [V both support 3.14].

### 4.4 Composition root and interfaces

`composition.py` builds one `AppContainer` per process:
- Settings.
- SQLAlchemy async engine: psycopg 3 driver [V cp314 wheels].
- `httpx.AsyncClient` for TEI.
- The LangChain chat model.
- The `FileStore`.
- The services.

FastAPI's lifespan opens and closes the container. The worker does the same in its main loop. There are no module-level clients and no DI framework [R].

**Interfaces, kept deliberately few:**

| Boundary | Form | Production | Test substitute |
|---|---|---|---|
| Source parsing | `SourceAdapter` Protocol: `extract(path, limits) -> ExtractedSource` | `PdfAdapter` | real adapter on fixtures |
| Embeddings | `Embedder` Protocol: `embed_documents`, `embed_query`, `config` | `TeiEmbedder` | `HashEmbedder` (deterministic, offline) |
| Generation | LangChain `BaseChatModel` (an existing abstraction; no custom protocol) | `ChatOpenAI` | `GenericFakeChatModel` / scripted streaming fake |
| File storage | `FileStore` Protocol: `put`, `open`, `delete_prefix` | local-disk volume | temp-dir implementation |
| Clock | `Callable[[], datetime]` | `datetime.now(UTC)` | fixed/advancing clock |
| Human verification | `HumanVerifier` Protocol: `verify(token, remote_ip) -> bool` | `TurnstileVerifier` (httpx) | pass/fail/outage fake |

**Intentionally concrete, with no interface:**
- Repositories (SQLAlchemy; tested against real Postgres).
- QA, summary and ingestion services.
- Limits.
- The SSE encoder.

A second implementation of any of these would be speculative.

**Type conventions:**
- Domain types are frozen dataclasses.
- Pydantic is used for settings, API request/response schemas, and validating TEI/OpenAI boundary payloads [P].
- LangChain message objects stay inside `generation/` and `qa/`. They are not the domain model.

---

## 5. Data model and ownership

### 5.1 Ownership model

- **Owners:** an `owners` row is the unit of data ownership. Its `kind` is `anonymous_session` in the MVP, and `account` later.
- **Sessions:** every anonymous session has exactly one owner.
- **Owner on every row:** every table holding visitor data carries `owner_id`.
- **Where the owner comes from:** the server resolves the owner only from the validated session cookie. The client never sends an owner ID [R].

**Session cookie** [P]:
- **Name:** `sh_session`.
- **Value:** 32 random bytes, base64url.
- **Attributes:** `HttpOnly; Secure; SameSite=Lax; Path=/`. No `Domain` attribute, so it stays host-only.
- **Storage:** the database stores only the token's SHA-256 hash. A session is valid only if it is not ended and both its expiry times are in the future (§10).

**Defence in depth** [P]:
1. **Owner-scoped repositories.** Every query function takes an `OwnerScope` and adds `owner_id = :owner` to the SQL. Retrieval applies the owner and the selected documents inside the vector query itself [R].
2. **Row-level security.**
   - The app connects as the role `sourcehaven_app`, which is not the table owner. Every owner-scoped table has `ENABLE` and `FORCE ROW LEVEL SECURITY` with the policy `owner_id = current_setting('app.owner_id')::uuid`.
   - Each request transaction runs `SET LOCAL app.owner_id = …` [U: re-verify the RLS + `SET LOCAL` pattern with the async driver and connection pool].
   - The cleanup sweeper and migrations use a separate `sourcehaven_maintenance` role with `BYPASSRLS`. That role is never used for request handling.
   - **Cross-owner operations** [P]: a few operations must read across owners. Each is a narrowly scoped `SECURITY DEFINER` SQL function owned by the maintenance role, granted to the app role, and returning only what the caller needs:
     - session lookup by token hash, which returns the owner id;
     - claiming the next ingestion job, which returns the job's id and `owner_id`; the worker then sets `app.owner_id` to that owner for all further work on the job;
     - global spending totals and global queue depth, which return aggregates only.
3. **Identifiers are not credentials.** IDs are random UUIDv7s or v4s, but access always checks ownership. A foreign ID returns **404, the same response as a missing ID**, so existence is never revealed.

### 5.2 Tables

Columns are abbreviated; every visitor table also has `owner_id uuid not null` with a B-tree index.

| Table | Purpose and key columns |
|---|---|
| `owners` | `id`, `kind`, `created_at` |
| `anonymous_sessions` | `id`, `owner_id`, `token_hash` (unique), `created_at`, `last_active_at`, `idle_expires_at`, `absolute_expires_at`, `ended_at` |
| `documents` | `id`, `display_name` (sanitised original filename; display only), `current_version_id` (nullable), `created_at` |
| `document_versions` | `id`, `document_id`, `version_no`, `content_sha256`, `byte_size`, `page_count`, `file_key`, `token_count`, `parser_name`, `parser_version`, `chunker_fingerprint`, `embedding_config_id`, `ingestion_fingerprint`, `state` (`queued`/`processing`/`ready`/`failed`/`superseded`), `error_code`, `skipped_pages` (int[]), `created_at`, `ready_at` |
| `ingestion_jobs` | `id`, `version_id` (unique), `status`, `stage`, `progress_done`, `progress_total`, `attempts`, `lease_expires_at`, `next_attempt_at`, `last_error_code` |
| `chunks` | `id`, `document_id`, `version_id`, `embedding_config_id`, `ordinal`, `text`, `token_count`, `page_start`, `page_end`, `char_start`, `char_end` (offsets in the concatenated version text, used to rebuild sections without overlap), `heading` (nullable), `embedding vector` |
| `embedding_configs` | `id`, `fingerprint` (unique), `provider`, `model_id`, `model_revision`, `dimensions`, `query_prefix`, `document_prefix`, `normalize`, `max_input_tokens`, `distance`, `chunk_tokens`, `chunk_overlap`, `created_at`. Not owner-scoped |
| `conversations` | `id`, `created_at` |
| `turns` | `id`, `conversation_id`, `client_request_id`, `kind` (`question`/`summary`), `question`, `selected_document_ids` (uuid[]), `status` (`generating`/`complete`/`interrupted`/`failed`), `text`, `error_code`, `model`, `input_tokens`, `output_tokens`, `cost_micro_usd`, `created_at`, `completed_at`. Unique `(conversation_id, client_request_id)`. Partial unique index on `conversation_id WHERE status = 'generating'` |
| `turn_sources` | `turn_id`, `label` (`S1`…), `cited` (bool), `document_id` (nullable, `ON DELETE SET NULL`), `version_id`, `document_name_snapshot`, `page_start`, `page_end`, `quote_snapshot` |
| `summaries` | Cache: `id`, `kind`, `version_ids` (sorted uuid[]), `length`, `prompt_version`, `model`, `status`, `text`, `created_at`. Unique on the cache key within the owner |
| `summary_sections` | `version_id`, `section_index`, `page_start`, `page_end`, `length`, `prompt_version`, `text`. Reused across retries and summaries |
| `spend_ledger` | `id`, `owner_id` (nullable for system work), `day`, `reserved_micro_usd`, `actual_micro_usd`, `status` (`reserved`/`settled`/`released`), `turn_id` |
| `rate_limit_counters` | `key` (HMAC of IP or session id), `bucket`, `window_start`, `count`. No raw IPs stored |

**Where each kind of data lives** [R]:

| Data | Location | Deleted by |
|---|---|---|
| Original PDF | `uploads` volume: `{owner_id}/{document_id}/{version_id}.pdf`, server-generated names only | document delete, session expiry, orphan sweep |
| Extracted text and chunks | `chunks.text` | cascade from `document_versions` |
| Vectors | `chunks.embedding` | same row |
| Metadata and jobs | Postgres tables above | cascade from `owners` |
| Conversations and citations | `conversations`, `turns`, `turn_sources` | cascade from `owners` |
| Summaries | `summaries`, `summary_sections` | cascade from `owners`/`document_versions` |
| Spending and rate counters | `spend_ledger` (kept 90 days, without content), `rate_limit_counters` (kept for the window length) | scheduled pruning |

Every foreign key from owner data cascades from `owners`. Deleting an owner removes everything in one transaction; the files are removed afterwards (§10).

### 5.3 Provenance contract

```python
@dataclass(frozen=True)
class PageSpan:
    kind: Literal["page_span"]
    start: int  # 1-based physical page index
    end: int


Location = PageSpan  # later: PageSpan | TimeSpan | Section | ...


@dataclass(frozen=True)
class ExtractedPage:
    page: int
    text: str
    has_text_layer: bool


@dataclass(frozen=True)
class ExtractedSource:
    pages: tuple[ExtractedPage, ...]
    page_count: int
    parser_name: str
    parser_version: str
```

- **Physical page numbers:** citations use 1-based physical page numbers, shown as "p. 12".
- **Printed page labels:** a PDF's printed labels (e.g. "iv") are recorded when the parser provides them reliably [U]; otherwise they are not shown.
- **Cross-page chunks:** a chunk spanning a page break is cited as a range.
- **Future source types:** they add new `Location` variants. Chunks then store `location jsonb` alongside the indexed `page_start`/`page_end` columns, or in place of them. That migration is deliberately postponed until a second location type exists.

---

## 6. Ingestion

### 6.1 Flow

1. **Upload:** `POST /api/documents` (multipart, one file per request; the UI uploads several in parallel, at most 3 at a time).
   - **Admission:** the session is resolved or created, then rate limits and session quotas are checked: document count and remaining page budget, the latter checked after parsing.
   - **Size:** the body is streamed to a temporary file with a byte counter and aborted at 20 MB. Caddy also enforces `request_body max_size 21MB`.
   - **Type check:** the content must start with `%PDF-`. The declared MIME type and extension alone are not trusted.
   - **Hash:** SHA-256 of the content.
   - **Duplicates within the session:** if the same owner already has a `ready` or in-progress version with the same hash, the existing document is returned and no new ingestion starts. Duplicates are never matched across owners [R], so the response cannot reveal another visitor's upload.
   - **Write:** one transaction creates `documents`, `document_versions(state=queued)` and `ingestion_jobs`. The file is moved to its final key.
   - **Response:** `202` with the document representation.
2. **Worker claims the job:** `SELECT … FOR UPDATE SKIP LOCKED` on due jobs. It sets a lease of 5 minutes, renewed during work, and increments `attempts`.
3. **Parse:** in a **child process** with CPU time and memory limits (`resource.setrlimit`; 512 MB address space and a 90 s wall-clock timeout) [P].
   - It opens the PDF and rejects encrypted files.
   - It extracts text page by page and checks the page count (300 maximum).
   - A crash, timeout or memory limit is classified as a damaged or too-complex file.
4. **Page checks:** a page "has text" if it yields at least 20 non-whitespace characters [P, tune with fixtures].
   - **Scanned:** if 50% or more of the pages lack text, the job fails as `scanned_no_text`.
   - **Partly scanned:** otherwise, the image-only page numbers are recorded in `skipped_pages` and shown to the visitor.
   - **Empty:** a document with no extractable text at all fails as `empty`.
5. **Session page budget:** fail with `session_page_limit` if the session's ready plus in-progress pages would exceed 600.
6. **Chunk:**
   - **Splitter:** LangChain `RecursiveCharacterTextSplitter` with a length function that counts **tokens with the embedding model's tokenizer**. That is the `tokenizers` library loading the pinned `tokenizer.json` from the model cache; tests use a deterministic tokenizer.
   - **Size:** 400 tokens with 60 overlap [P]. The separator order is paragraph, line, sentence punctuation (`. ! ? …`), then space.
   - **Page tracking:** chunks are built over the concatenated page texts while page boundaries are tracked, so each chunk gets `page_start`/`page_end`.
   - **Headings:** the nearest preceding heading-like line, if any, is stored in `heading` [P, best effort].
7. **Embed:** batches of 32 go to TEI with the document prefix, a 30 s timeout per batch, and up to 3 retries with exponential backoff for transient errors. Progress (`chunks embedded / total`) is written to the job row every batch.
8. **Store and publish:** one transaction:
   - delete any chunks already present for this version (makes retries idempotent);
   - insert all chunks with their vectors;
   - set the version to `ready`;
   - set `documents.current_version_id`;
   - mark the previous current version, if any, `superseded` and delete its chunks;
   - complete the job.

   About 2,000 chunks × 768 floats is small enough to hold in memory and insert in one transaction.

**Queryable only when published:** retrieval joins on `documents.current_version_id` and `document_versions.state = 'ready'`. Partial ingestion is never visible, because nothing becomes current until that transaction commits.

### 6.2 Fingerprints, idempotency and re-ingestion

- **`content_sha256`:** identifies the file content.
- **`chunker_fingerprint`:** a hash of the splitter settings and tokenizer revision.
- **`ingestion_fingerprint`:** a hash of `content_sha256`, `parser_name@version`, `chunker_fingerprint` and `embedding_config.fingerprint`.
- **Re-ingestion:** a version is re-ingested only when its fingerprint differs from what the active configuration would produce, for example after a parser upgrade or embedding-model change. It creates a new `document_versions` row and job from the stored original file, then publishes atomically as in step 8.
- **No user-facing replace in the MVP:** a visitor deletes a document and uploads the new file instead [P]. The version model exists for re-ingestion and for a future replace feature.
- **Retry safety:** step 8 is idempotent, and a job whose lease expires after a worker crash is simply re-run.

### 6.3 Failures

| Code | Cause | Message to the visitor (abridged) | Retry? |
|---|---|---|---|
| `unsupported_type` | not `%PDF-` | "Only PDF files are supported right now." | no |
| `empty_file` | 0 bytes | "This file is empty." | no |
| `too_large` | over 20 MB | "Files can be up to 20 MB. Try splitting or compressing the PDF." | no |
| `too_many_pages` | over 300 pages | "PDFs can have up to 300 pages. Try splitting it." | no |
| `session_page_limit` / `session_document_limit` | session quotas | "This session can hold up to 10 documents / 600 pages. Remove a document to add another." | no |
| `encrypted` | password-protected | "This PDF is password-protected. Remove the password and upload it again." | no |
| `damaged` | parse error, crash or memory limit | "We couldn't read this PDF; it may be damaged. Re-export or re-save it and try again." | no |
| `parse_timeout` | wall-clock limit | "This PDF took too long to process. Try a smaller or simpler file." | no |
| `scanned_no_text` | mostly image-only | "This looks like a scanned PDF. Text recognition (OCR) isn't supported yet." | no |
| `empty` | no extractable text | "We couldn't find any text in this PDF." | no |
| `embedding_unavailable` | TEI down or timing out | "Processing is temporarily unavailable. We'll retry automatically." | yes, 3 attempts, backoff 30 s / 2 min / 10 min |
| `internal` | anything else | "Something went wrong while processing this file." | yes, as above |

- **Retries:** transient failures retry up to 3 attempts, then end as `failed`.
- **What gets logged:** job id, document id, error code and exception class. Never text, filenames or file contents.
- **Orphans:** files without a version row are deleted by the sweeper (§10).

### 6.4 Embedding configuration and compatibility

- **Startup check:** the active `EmbeddingConfig` comes from settings: model id, pinned revision, dimensions, prefixes, normalisation, maximum tokens, distance (cosine) and chunk settings. At startup the API and worker:
  1. compute its fingerprint and upsert the `embedding_configs` row;
  2. call TEI `/info` and **refuse to become ready** if TEI's model id or revision differs from the config [U: confirm the `/info` fields].
- **Query compatibility:** queries only consider chunks whose `embedding_config_id` equals the active config. The query encoder uses the same model with the config's query prefix.
- **Reindexing path:** change the config and deploy. The worker enqueues re-ingestion jobs for every ready version with a stale `embedding_config_id`. Until each document is re-published, it shows "Updating index…" and is excluded from retrieval. Anonymous data lives at most 7 days, so reindexing is cheap.
- **Vector column:** an untyped `vector` column (no fixed dimension) is acceptable in the MVP because retrieval uses exact scans (§7.2). When an approximate index is needed, create a per-config partial expression index, e.g. `USING hnsw ((embedding::vector(768)) vector_cosine_ops) WHERE embedding_config_id = N` [U: verify expression-index syntax with pgvector 0.8.7]. Indexes are limited to 2,000 dimensions for `vector` and 4,000 for `halfvec` [V].

---

## 7. Question answering

### 7.1 Flow

```
question + selected document ids + conversation
  → admission: session/IP limits, spending reservation, generation slot
  → resolve scope: selected ids ∩ owner's documents with a ready current version (others → 404/validation error)
  → retrieval query = current question (+ previous user question in this conversation, if any)
  → embed query (TEI, query prefix)
  → scoped exact vector search → candidates with similarity
  → evidence check: none above threshold → "insufficient evidence" response, no LLM call
  → context assembly within budget (§7.4), labels S1..Sn
  → stream generation (OpenAI via LangChain)
  → final citation validation → persist turn + sources → `done` event
```

**Follow-ups** [P]: there is no extra rewriting LLM call [R]. The retrieval query concatenates the current question with the previous user question in the conversation, which handles most pronoun and ellipsis follow-ups cheaply. The generator also receives the last turns as history (§7.4). An LLM query-rewriting step is added only if the evaluation shows follow-up retrieval failing. Turns with any source whose `document_id` is null (its document was deleted, §7.5) are excluded from the history the generator receives and from the previous question used for retrieval [A15].

**Fresh evidence:** every answer retrieves its own evidence [R]. Earlier answers appear only as conversation history, labelled as prior assistant turns, never as sources.

### 7.2 Retrieval

```sql
SELECT c.id, c.document_id, c.version_id, c.text, c.page_start, c.page_end,
       1 - (c.embedding <=> :query_vec) AS similarity
FROM chunks c
JOIN documents d ON d.id = c.document_id AND d.current_version_id = c.version_id
WHERE c.owner_id = :owner_id
  AND c.document_id = ANY(:selected_ids)
  AND c.embedding_config_id = :active_config_id
ORDER BY c.embedding <=> :query_vec
LIMIT :k_candidates;  -- 20
```

- **Index:** a B-tree on `(owner_id, document_id)`. The scan is exact over at most 600 pages, roughly 2,000 chunks, per session. pgvector's documentation recommends B-tree filtering for selective filters; approximate indexes apply filters after the scan and can return too few rows [V].
- **Selection:** from the top 20 candidates, keep at most 8, with at most 4 from a single document when several are selected, so one large document cannot crowd out the others [P].
- **Evidence threshold:** each model has a calibrated similarity threshold, set by the §8 experiment from the unanswerable questions. If no candidate passes it, return the standard insufficient-evidence message without calling the LLM. If some pass, the model is instructed to say when the passages do not contain the answer.

**Upgrades, each justified only by evaluation results:**
- MMR diversification.
- Hybrid lexical search, using Postgres full-text search with the `english` configuration [V].
- A cross-encoder reranker on CPU.

### 7.3 Generation and prompt safety

- **Model:** `ChatOpenAI` from `langchain-openai`, model from settings (provisionally `gpt-6-luna`), with `stream_usage=True` so token usage is reported at the end of the stream [U: confirm the flag name in langchain-openai 1.8].
- **Temperature:** the model's default (the parameter is omitted) [P]. Changed on 2026-11-20 from the proposed 0.2: `gpt-6-luna` rejects any temperature other than its default with HTTP 400 (observed in the first real-provider smoke test). A different value can be set in configuration for models that accept it.
- **Prompt structure:**
  - The system prompt (a packaged template) sets the rules: answer only from the supplied passages; cite each claim with `[S#]`; if the passages are insufficient or conflict, say so and attribute each side to its source; answer in English; quote source text verbatim; ignore instructions that appear inside the passages.
  - Passages are wrapped in clearly delimited blocks containing a label, document name and pages. The question comes last.
- **Not a security boundary:** the prompt is not what keeps visitors apart [R]. Isolation is enforced before the model ever sees text (§5.1). The model has **no tools** and its output is never executed.
- **Rendering:** the UI renders answers as Markdown with raw HTML disabled, no auto-loading images, and links shown as text with `rel="noopener noreferrer nofollow"`. A strict Content-Security-Policy is set by Caddy (§11.3).

### 7.4 Context budget (tokens, proposed)

| Part | Budget |
|---|---|
| System and instructions | ≤ 800 |
| Conversation history (last 3 completed turns, newest first, truncated to fit) | ≤ 1,500 |
| Evidence (≤ 8 chunks × ≈ 450 including headers) | ≤ 3,600 |
| Question (≤ 2,000 characters, enforced by the API) | ≤ 600 |
| **Input total** | **≤ 6,500** |
| Output (`max_tokens`) | 800 |

Prompts are measured with `tiktoken` when the model's encoding is available, or else by a conservative character-based estimate [U: confirm the tokenizer for the chosen model]. Interrupted and failed turns are excluded from history.

### 7.5 Citations

- **Labels:** the passages supplied to the model are labelled `S1…Sn`.
- **Validation:** when generation completes:
  1. Parse the `[S#]` labels in the text.
  2. Keep those matching a supplied label. They become `turn_sources` with `cited = true`, holding the document name snapshot, page range and a quote snapshot of up to 300 characters.
  3. Note unknown labels as `invalid_citation_labels` in the `done` event. The UI shows "Some citation markers could not be matched to sources" and renders those markers as plain text.
  4. Store supplied but uncited passages with `cited = false`. The UI shows them collapsed under "Other passages consulted", clearly separated.
  5. If an answer has no valid citation at all, it is marked in the UI as "No sources cited; treat with caution".
- **Limits of label validation:** it does not prove a claim is supported [R]. Support is measured in the evaluation (§8.3).
- **Intelligible over time:** snapshots keep old citations readable after re-ingestion.
- **Deleting a document** [A15]:
  - **What's removed:** the document's file, chunks and versions, and the quote of every source taken from it (cited or not, since uncited passages were still sent to the model), as well as any summary cache that included it. The source row stays with its label, document name snapshot, page range and `cited` flag, but its `document_id` becomes null and its quote becomes empty. The API reports such a source as `document_id: null`, `quote: ""`.
  - **What's kept:** every question and answer, including their text. The UI shows the deleted sources as deleted and the quote as no longer available. The privacy page says that answers already received stay until the session ends.
  - **History [M5]:** turns with any source whose `document_id` is null are excluded from the conversation history used for follow-ups (§7.1), so later prompts carry no answer that quoted the removed document.
  - To support this, `turn_sources` rows exist for every supplied passage, which they already do (`cited = false` for uncited ones).

---

## 8. Embedding and parser selection experiment

This is an agreed early implementation step. Nothing is downloaded during design [R].

### 8.1 Candidates

| Model | Params | Dim | Max tokens | Licence | Role |
|---|---|---|---|---|---|
| `Snowflake/snowflake-arctic-embed-m-v2.0` | 305M | 768 (Matryoshka 256) | 8192 | Apache-2.0 | Provisional default |
| `intfloat/multilingual-e5-base` | 278M | 768 | 512 | MIT | Proven baseline (needs `query: `/`passage: ` prefixes) |
| `Qwen/Qwen3-Embedding-0.6B` | 596M | 1024 | 32K | Apache-2.0 | Quality ceiling, about 2–4× slower (estimate) |

All three are supported by TEI CPU (`ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`) [V]. Published benchmarks only produced the shortlist [R]. The shortlist was chosen when the scope covered several languages; M2 also benchmarks smaller English-only embedding models against it.

**Excluded, with reasons:**
- `jina-embeddings-v3`: non-commercial licence.
- EmbeddingGemma: Gemma terms, gated access.
- Paraphrase-multilingual models: built for paraphrase, not retrieval; 128-token limit.

### 8.2 Procedure

- **Corpus:** `evals/corpus/`, versioned. About 5 openly licensed English documents, each with its licence and source recorded.
  - **Layouts covered:** a contract-like legal text, a two-column paper, a manual with tables, a report and a long book excerpt.
  - **Candidate sources:** Wikipedia (CC BY-SA), public-domain books, openly licensed papers and official publications whose licence allows redistribution.
- **Questions:** about 20 English questions, each with its gold page range or passage. They include unanswerable questions (at least 3) and two documents that conflict.
- **Harness:** `evals/embedding_benchmark.py`, run with `uv run`. It ingests the corpus with each model through the real pipeline into a scratch database and measures:
  - Recall@8 and MRR@10;
  - p50/p95 query-embedding latency;
  - ingestion chunks per second;
  - peak memory of the TEI container;
  - the similarity distribution for answerable vs unanswerable questions, which sets the evidence threshold.
- **Hardware** [P, settled after builder review]:
  - **Local runs:** quality metrics (recall, MRR, thresholds) don't depend on hardware and are measured locally. The TEI container runs with Compose limits matching the target (`cpus: 4`, `mem_limit: 8g`) to compare speed between models.
  - **TEI on Apple Silicon:** if no native arm64 TEI CPU image exists [U], local speed numbers come from emulation and are not used for acceptance.
  - **Acceptance runs:** absolute latency, throughput and memory are confirmed on a **short-lived Hetzner x86 VM** matching the target size, created for the run and deleted afterwards. This costs a few euro cents an hour, and creating it requires the owner's go-ahead at that time.
- **Parser comparison:** the same harness runs pypdf, pdfplumber and pypdfium2 on the layout fixtures. It records reading-order errors on the two-column and table pages (judged against known expected sequences), extraction time per page, and failures on the damaged fixtures.

### 8.3 Acceptance criteria (proposed)

| Metric | Threshold |
|---|---|
| Recall@8 | ≥ 0.85 |
| Query embedding p95 on a 4-vCPU target | ≤ 150 ms |
| TEI resident memory | ≤ 3 GB |
| Ingestion throughput | ≥ 5 chunks/s (a 300-page PDF in about 3 minutes or less) |

- **Selection rule:** choose the smallest, fastest model that passes all four metrics.
- **If none passes:** report the specific gap to the owner and discuss options before considering a hosted embedding API [R].
- **Output:** record the chosen model, its pinned revision, measured numbers and threshold in `docs/decisions/embedding-model.md` (and the parser in `docs/decisions/pdf-parser.md`).

### 8.4 Answer-quality evaluation

A separate set of opt-in runs that call the real API and cost money:
- **Answer support:** claims are checked against the cited passages, by a human for a sample and by an LLM judge for the rest.
- **Citation accuracy and refusals:** the correct-source rate, and the share of unanswerable questions correctly refused.
- **Conflicting sources:** the share of conflict questions that attribute each side to its document.
- **Prompt injection:** a corpus document containing instructions such as "ignore previous instructions…" must not change behaviour.
- **Summary coverage:** whether the summary mentions each section marker of the multi-section document.
- **Latency and cost:** time to first token and cost per question and per summary.

An LLM judge alone is not accepted as proof of quality [R]. Each run's estimated cost (well under $1 at current prices) is printed before it starts, and it requires `--live`.

---

## 9. Limits, admission and spending (agreed values)

| Limit | Value |
|---|---|
| File size | 20 MB |
| Pages per PDF | 300 |
| Documents per session | 10 |
| Total pages per session (ready + in progress) | 600 |
| Questions per session | 30 / hour |
| Summaries per session | 10 / day |
| New sessions per IP | 5 / hour |
| Questions per IP | 60 / hour |
| Uploads per IP | 30 / hour [P] |
| Concurrent generations (answers + final summary streams) | 4 |
| Generation wait queue | 8 waiting, up to 30 s each; beyond → `busy` |
| Concurrent ingestion jobs | 2 [P]; up to 20 queued globally; beyond → `busy` on upload |
| Global spending cap | ≈ $1.00 / day [P] (≈ $30 / month) |
| Per-session spending cap | $0.20 / day [P] |
| Question length | 2,000 characters |

**Mechanics** [P]:
- **Rate limits:** fixed-window counters in `rate_limit_counters`, keyed by an HMAC of the client IP or session id with a server secret.
  - **Client IP:** taken from `X-Forwarded-For` as set by Caddy. The trusted proxy is configured explicitly; client-supplied values are not trusted.
  - **Over the limit:** `429` with `Retry-After` and a human-readable message.
- **Generation admission:**
  - **MVP:** an in-process `asyncio.Semaphore(4)` with a bounded waiter count, because the MVP runs **one API process**.
  - **More API processes:** the same contract moves to a Postgres-backed slot table or advisory locks. Recorded as a scaling item in §16.
- **Spending ledger:**
  - **Reserve:** before each LLM call, reserve its worst-case cost, priced from the configured per-model token prices: `input_tokens × in_price + max_tokens × out_price`.
  - **Settle:** when usage is reported, settle to the actual cost.
  - **Release:** if the call fails before any usage is reported, release the reservation.
  - **Cap checks:** a call is refused when the global or session reservations plus settled cost would exceed the cap.
  - **Prices:** kept in settings and updated by configuration, never hard-coded in logic.
- **Backstop:** a monthly budget limit configured in the OpenAI project dashboard (manual, documented in the README).
- **Cloudflare Turnstile at session creation** [A14]:
  - **Browser:** the `/app` page renders the Turnstile widget, preferably in managed/invisible mode, so most visitors see no puzzle.
  - **Server check:** `POST /api/session` requires the Turnstile token. The API verifies it server-side against Cloudflare's `siteverify` endpoint with the secret key, the visitor IP and an expected hostname check, before creating the session.
  - **Tokens:** single-use and short-lived [U: verify the current validity period and response fields in Cloudflare's docs at implementation].
  - **Where it applies:** only at session creation, not on every request. The session's own rate limits apply after that.
  - **No traffic proxying:** the site doesn't have to be proxied through Cloudflare. Turnstile is used as a standalone widget plus API [U: confirm the current free-plan terms].
  - **Settings:** `TURNSTILE_SITE_KEY` (public, built into the frontend) and `TURNSTILE_SECRET_KEY` (server `.env` only).
  - **When Cloudflare is unreachable or verification fails:** new sessions are refused with "We couldn't verify your browser. Please try again." The policy is to fail closed for new sessions only; existing sessions are unaffected.
  - **Tests:** a `HumanVerifier` Protocol is injected at the composition root, with a fake in unit and integration tests, so no network calls are made. Cloudflare's documented always-pass/always-fail test keys are used in the e2e stack [U: verify the test key values].
- **Budget reserved for established sessions** [A14]: once today's global spending (reserved + settled) passes **70%** of the daily cap, new generations are admitted only for sessions that completed at least one turn more than 10 minutes ago [P]. Others get "Sourcehaven is busy today; please try again later." Visitors already working can carry on, while a burst of fresh sessions can't drain the remainder.

**Cost estimates** (list prices for `gpt-6-luna`, $0.10 per 1M input / $0.50 per 1M output [V]; usage is *estimated*):

| Workload | Tokens | Estimated cost |
|---|---|---|
| Question | ≈ 6k in, ≈ 500 out | ≈ $0.001 |
| Document summary, short (≤ 60k tokens) | ≈ 60k in, ≈ 800 out | ≈ $0.007 |
| Document summary, 300 pages (≈ 150k tokens, 9 sections) | ≈ 155k in, ≈ 6k section outputs + 1k final | ≈ $0.02 |
| Collection summary, 600 pages | ≈ 310k in, ≈ 13k out | ≈ $0.04 |

At $30/month that is on the order of 30,000 questions, or about 1,000 large summaries. Tokens are counted with the model's own tokenizer.

---

## 10. Sessions, retention and deletion (agreed)

- **Creating a session:** `POST /api/session` creates a session lazily, when the app first needs one, and is limited per IP. Each authenticated request updates `last_active_at`, at most once a minute, and extends `idle_expires_at = last_active_at + 24 h`. `absolute_expires_at = created_at + 7 days`, which is never extended.
- **Becoming inaccessible:** the session lookup rejects sessions that are expired or ended, so expired data becomes **inaccessible immediately**, before physical deletion.
- **Physical cleanup:** the worker's sweeper runs every 5 minutes, using the maintenance role.
  1. It finds expired or ended sessions and deletes their owners, which cascades through all rows in one transaction per owner.
  2. It then deletes `uploads/{owner_id}/`.
  3. It deletes files with no matching version row (orphans older than 1 hour) and prunes old rate counters.
  4. Deletions are logged by owner id and counts only.
- **End session:** `POST /api/session/end` deletes the owner synchronously, then the files (or schedules file removal if it fails), and clears the cookie.
- **Delete document:** `DELETE /api/documents/{id}` deletes, in one transaction, the document's rows (chunks, versions, jobs, section and summary caches containing it) and blanks the quote of every source taken from it; turns are kept and those sources lose their `document_id` [A15]. Its files are removed after the commit; a failure there is logged (ids only) and does not fail the request, and the orphan sweep removes them later.
  - **In-progress ingestion:** deleting cascades the job row, and the worker discards its work when the job has disappeared.
  - **Answers being generated:** removal is refused with `409 document_in_use` while a turn that selected the document is `generating` and was created within the last 10 minutes. Older `generating` turns are treated as abandoned (an API restart can leave one behind) and do not block removal. Cancelling an answer is not part of removal.
- **Restarts:** data survives restarts and redeploys within the retention window [A].
- **Backups:**
  - **Database:** nightly `pg_dump`, kept 3 days [P]. Deleted data can therefore persist in backups for up to 3 days, and the privacy page says so.
  - **Uploads volume:** not backed up. Originals are only needed for re-ingestion and are ephemeral by design.
  - **After a restore:** sessions whose expiry has passed are swept on the next run.
- **What the privacy page tells visitors:**
  - **Sent to OpenAI:** question text and the retrieved passages, or whole-document text for summaries, plus the recent conversation.
  - **OpenAI's terms:** OpenAI states that API data is not used for training by default and may be retained for up to 30 days for abuse monitoring [V]. Zero data retention requires OpenAI's approval and is not assumed.
  - **What Sourcehaven keeps:** what is retained and for how long (above), and that logs contain no document content.
  - **Deleting a document:** removes the file, its text and the quotes taken from it. Answers already received stay until the session ends.
  - **Cloudflare Turnstile:** it processes browser and device signals and the visitor's IP to tell humans from bots when a session is created, under Cloudflare's own privacy terms. No document content is ever sent to Cloudflare [A14].

---

## 11. API, streaming and frontend

### 11.1 API surface (same-origin under `/api`)

| Method & path | Purpose |
|---|---|
| `POST /api/session` | Create a session (requires a valid Turnstile token, §9) or confirm an existing one; returns limits and expiry |
| `GET /api/session` | Session status: expiry times, usage against limits |
| `POST /api/session/end` | Delete everything and end the session |
| `POST /api/documents` | Upload one PDF (multipart) → `202` |
| `GET /api/documents` | List the owner's documents with state, progress, errors, skipped pages |
| `DELETE /api/documents/{id}` | Delete a document and its quotes, keep the answers → `204`; `404` unknown or foreign id; `409 document_in_use` while an answer using it is generating |
| `POST /api/conversations` | Start a conversation |
| `GET /api/conversations/{id}` | Turns with statuses, text and sources (used after reconnecting) |
| `POST /api/conversations/{id}/turns` | Ask a question or request a summary → **SSE stream** |
| `POST /api/turns/{id}/cancel` | Stop generation |
| `GET /api/health/live`, `GET /api/health/ready` | Health checks (§12) |

**Request rules:**
- **Unsafe methods** must carry a JSON body or multipart form, and an `Origin` header equal to the site origin. Anything else gets `403` (CSRF defence alongside `SameSite=Lax`) [P].
- **CORS** is disabled, because everything is same-origin.
- **Validation** uses Pydantic models: question length, at most 10 document ids, enumerations for summary options.

**Turn request body:**
```json
{
  "client_request_id": "uuid",
  "kind": "question",
  "question": "...",
  "document_ids": ["..."]
}
```
or
```json
{
  "client_request_id": "uuid",
  "kind": "summary",
  "document_ids": ["..."],
  "length": "brief|detailed"
}
```

### 11.2 Streaming protocol

FastAPI's native `EventSourceResponse` on a POST route [V]. The browser reads it with `fetch` and a small stream parser, since `EventSource` cannot send POST requests.

| Event | Data |
|---|---|
| `turn` | `{turn_id, status: "generating"}`, sent first |
| `progress` | `{stage: "waiting_for_capacity" \| "retrieving" \| "summarizing_sections", done?, total?}` |
| `delta` | `{text}`: incremental model output, provisional |
| `sources` | `{sources: [...], invalid_citation_labels: [...]}`: final, validated |
| `done` | `{status: "complete", usage}` |
| `error` | `{status: "failed" \| "interrupted", code, message, retryable}` |

Keep-alive comments every 15 s are built in [V].

**Semantics:**
- **Idempotency:** `(conversation_id, client_request_id)` is unique.
  - A repeated request for a **finished** turn returns its stored result as a short replay of `turn` + one `delta` with the full text + `sources` + `done`, and generates nothing new.
  - A repeated request while it is **still generating** returns `409` with the turn id; the client polls `GET /api/conversations/{id}`.
  - Only one turn per conversation can be generating at a time (enforced by the partial unique index).
- **Reconnect:** a dropped stream is not resumed mid-generation. The client fetches the conversation and shows the turn's stored state.
- **Stop:** the client aborts the fetch and calls `/cancel`. The server detects cancellation either way: an explicit cancel flag, or client disconnect noticed through the cancelled request task / `request.is_disconnected()` [U: verify behaviour with FastAPI 0.165 SSE]. It then cancels the generation task, which closes the upstream OpenAI stream. The turn is stored as `interrupted` with its partial text and no validated sources. The UI labels it "Stopped — incomplete answer".
- **Timeouts and retries:**
  - 20 s to the first token, 120 s total for answers, 300 s for a final summary stream.
  - Upstream errors **before the first token** retry up to 2 times with backoff.
  - **After tokens have streamed,** there is no retry. The turn ends `failed` (provider error) or `interrupted` (timeout), with its partial text kept and labelled incomplete.
- **Spending:** usage reported by the provider is always settled to the ledger, even for interrupted turns. If no usage is reported, the reservation is settled at its maximum [P].

**Proxy buffering:**
- Caddy flushes `text/event-stream` immediately [V], and `encode` is disabled on `/api/*` streaming routes.
- An integration test confirms through the real Caddy container that the first `delta` arrives before generation completes (§13.2).

### 11.3 Frontend (Next.js 16, App Router)

**Public pages, generated ahead of time, indexable:**

| Page | Purpose |
|---|---|
| `/` | Landing: what it is, how it works, limits |
| `/how-it-works` | Explanation; citation and summary behaviour; English-only support |
| `/privacy` | What is sent where, retention, deletion, backups |

Each has a title and description from the Metadata API, a canonical URL, and Open Graph/Twitter metadata. `sitemap.xml` lists **only** these pages. `robots.txt` disallows `/app` and `/api`.

**Private:** `/app`, a client-rendered React component. It is excluded from the sitemap, and Caddy adds `X-Robots-Tag: noindex, nofollow` for `/app*` and `/api*`. The Next.js server never fetches private data, so no private content can reach server-side caches or page metadata. Indexing directives supplement the access controls; they do not replace them [R].

**Security headers (set by Caddy):**
- A strict CSP: `default-src 'self'`, no inline scripts beyond what Next.js requires [U: Next.js nonce/hash approach], `frame-ancestors 'none'`. The only external origin allowed is `https://challenges.cloudflare.com`, for `script-src` and `frame-src` on `/app` (Turnstile) [U: confirm Cloudflare's documented CSP requirements].
- `X-Content-Type-Options: nosniff`.
- `Referrer-Policy: strict-origin-when-cross-origin`.
- HSTS.

**App screen (sketch):**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Sourcehaven         Session data is deleted 24 h after last activity.    │
│                     [End session & delete everything]                    │
├──────────────────────────┬──────────────────────────────────────────────┤
│ Your documents (3/10)    │ Q: How long does the contract run?           │
│ 412/600 pages            │                                              │
│ [ Drop PDFs or browse ]  │ A: The contract runs for 24 months [S1],     │
│                          │ with automatic renewal [S2]…  ▌              │
│ ☑ contract.pdf     Ready │                                  [ ■ Stop ]  │
│ ☑ annex.pdf        Ready │ Sources                                      │
│   p. 3, 7 skipped (scan) │  S1 contract.pdf · p. 4  "The term of…"      │
│ ☐ report.pdf  Processing │  S2 contract.pdf · p. 12 "…is renewed…"      │
│   ████████░░ 80%         │  ▸ Other passages consulted (3)              │
│ ✕ scan.pdf  Failed:      │                                              │
│   scanned PDF — OCR not  │ ──────────────────────────────────────────── │
│   supported yet [Remove] │ [ Ask about the selected documents…    ][Ask]│
│                          │ [Summarize selected ▾ brief | detailed]      │
└──────────────────────────┴──────────────────────────────────────────────┘
```

- **Selection:** checkboxes decide the scope. Only `Ready` documents can be selected.
- **Progress:** polled with `GET /api/documents` every 2 s while any document is processing.
- **Turn states:** generating (cursor + Stop), complete (sources), stopped/incomplete (badge, no validated sources), failed (message + "Try again", which sends a new `client_request_id`).
- **Limit and busy errors:** shown inline, with the server's message and retry timing.

**Repository layout** [P]:
- **Where it lives:** the frontend lives in the **same Git repository**, as a separate Node project under `frontend/` with its own `package.json`, lockfile and multi-stage Dockerfile (non-root runtime user). It is not part of the Python distribution.
- **Why one repository:** an API change and the UI change that depends on it land in one atomic commit. There is one CI, one Compose file and one set of docs.
- **API types:** TypeScript types for the API are generated from FastAPI's OpenAPI schema (e.g. `openapi-typescript`) and committed. CI fails if they are stale.
- **When to split it out:** a separate repository becomes worthwhile only with a separate team or an independent release cadence.

---

## 12. Operations

- **Logging:**
  - **Format:** standard-library `logging` with a JSON formatter, configured in `composition.py`.
  - **Fields:** timestamp, level, request id, route, status, duration, owner id (UUID only), document, job and turn ids, error codes, token usage and cost.
  - **Never logged:** document text, questions, answers, filenames, raw IPs, cookies or API keys.
  - **Uvicorn access logs:** replaced with this logger so query strings and headers aren't dumped.
- **Health:**
  - `GET /api/health/live` returns 200 while the process can serve.
  - `GET /api/health/ready` checks database connectivity, that migrations are at head, TEI readiness, and that TEI's model matches the active embedding config.
  - OpenAI reachability is **not** part of readiness, because generation errors are handled per request.
  - The worker runs a heartbeat query and exposes a file-based health check for Compose.
- **Graceful shutdown:**
  - **API:** stops accepting connections and lets in-flight streams finish for up to 30 s, then cancels them (turns stored as `interrupted`).
  - **Worker:** finishes or abandons the current job; leases make abandoned jobs retry.
- **Containers:**
  - **Images:** non-root users; `python:3.14-slim` (Debian trixie) for the app [V]; pinned image tags or digests for Postgres, TEI and Caddy.
  - **Restart policy:** `restart: unless-stopped`.
  - **Resource limits:** Compose CPU and memory limits per service.
- **Secrets:** `.env` on the host (git-ignored), with placeholders in `.env.example`. It holds `OPENAI_API_KEY`, `TURNSTILE_SECRET_KEY`, the database passwords for the app and maintenance roles, and the rate-limit HMAC key.
- **Migrations:** Alembic, packaged with the app and run by `sourcehaven migrate` in a one-shot Compose service before `api` and `worker` start.
- **Advanced observability:** metrics, tracing, dashboards and alerting are deferred [R]. The spending ledger and per-turn usage columns are the bookkeeping that the limits and evaluation need.

### 12.1 Hosting proposal (not provisioned) [A6]

| Item | Proposal | Monthly (excl. VAT) |
|---|---|---|
| Server | Hetzner Cloud CX33 (4 vCPU, 8 GB, 80 GB), EU location; upgrade to CX43 (8 vCPU, 16 GB) if the §8 measurements need it | €8.99 (CX43: €16.49) [V; plan availability shown as limited, check in the console] |
| Server backups | Hetzner automated backups (about 20% of the server price) | ≈ €1.80–3.30 |
| Off-server DB dumps | Hetzner Storage Box or similar object storage | ≈ €3–4 [U] |
| Domain | — | ≈ €1 |
| Generation API | OpenAI, capped | ≤ $30 |

That is about €15–25/month for infrastructure, well under the $50 hosting allocation. The same Compose topology runs on any Linux VM, including GCP and AWS; moving providers means restoring a database dump and pointing DNS at the new server. Managed Postgres with pgvector is possible later but costs a large share of the budget at useful sizes [V].

---

## 13. Testing and quality

### 13.1 Suites

| Suite | Marker / location | Uses | Runs in |
|---|---|---|---|
| Unit | `tests/unit` | pure logic with fakes: chunking with page spans, budget assembly, citation validation, ledger maths, SSE encoding, error classification | CI and local; offline, fast |
| Integration | `tests/integration`, `@pytest.mark.integration` | real Postgres + pgvector (Compose test project, isolated database per run), real PDF parser and ingestion path, `HashEmbedder`, scripted fake chat model | CI and local; **fails, never skips, if Postgres is unavailable while the suite is requested** [R] |
| End to end | `tests/e2e` | Full Compose stack with fakes behind configuration flags (fake embedder/LLM services) through Caddy: upload → ingest → ask → stream → stop → delete | CI (slower job) |
| Live | `@pytest.mark.live` | real OpenAI and TEI | opt-in only (`--live`), never in CI by default |
| Evaluation | `evals/` | §8 harness | manual, opt-in, cost printed first |

Pre-commit runs static checks only, never test suites [R]: Ruff, mypy, hygiene, and, for files under `frontend/` (`files: ^frontend/`), ESLint and `tsc --noEmit` through the lockfile-pinned local toolchain (`npm --prefix frontend run lint`/`typecheck`). Commits touching only Python files therefore don't need Node [P, settled after builder review].

Tests run in CI and locally, including Vitest unit tests for the SSE stream parser and turn-state reducer.

A Playwright browser test is deferred [P].

### 13.2 Required integration scenarios

- **Grounding:** known facts from the small PDF are retrieved, with the correct document and page in the stored sources.
- **Multi-page sections:** section markers on different pages are cited with the right pages. Sectioned summarisation includes every section marker in its section inputs.
- **Conflicting documents:** with only A selected, only A's fact is used. With both selected, both are attributed to their own sources.
- **Two-visitor isolation:**
  - **Setup:** sessions X and Y, each with unique-marker documents.
  - **ID substitution:** Y uses X's document, conversation and turn ids in list, delete, ask, summarise and cancel calls. Expect 404 everywhere, identical to unknown ids.
  - **No leakage:** Y's questions about X's markers never retrieve X's chunks. This is checked at the SQL level by asserting on the evidence ids, and by RLS with the application filter deliberately removed in a test-only repository variant.
  - **Duplicate uploads:** uploading X's exact file in Y creates a new document and reveals nothing about X.
  - **Summary cache:** caches are never shared across owners.
- **Failure inputs:** empty, malformed, encrypted and image-only fixtures each produce their documented error code. A half-scanned fixture reports its skipped pages.
- **Idempotency:** killing the worker mid-job means the re-run produces exactly one set of chunks. A repeated `client_request_id` triggers no second generation, which the fake LLM call counter confirms.
- **Publication:** chunks of a version in `processing` state are never returned by retrieval.
- **Re-ingestion and deletion:** after an embedding config change, stale documents are excluded, re-ingested and re-published. Deleting a document removes its rows and files and every summary cache that included it, and blanks the quote of every source taken from it (cited or not) while the turns stay, with those sources reported as `document_id: null`, `quote: ""`. Deletion is refused with `409` while an answer using the document is generating, and a `generating` turn older than 10 minutes does not block it. Later follow-up prompts contain no turn with a deleted source and none of the removed text, which the fake LLM's recorded prompts confirm (the prompt part lands with M5).
- **Incompatible embeddings:** TEI reporting a different model makes readiness fail.
- **Restarts and expiry:** data persists across an `api`/`db` container restart. An advanced clock expires the session, after which the API returns "session expired" and the sweeper physically removes the rows and files.
- **Limits:** each quota and rate limit returns its error. The spending cap blocks generation. The admission queue returns `busy` when full. Above 70% of the daily cap, only established sessions are admitted.
- **Human verification:** session creation rejects missing or failed verification and verifier outages (fake `HumanVerifier`), and never creates a session in those cases.
- **Streaming:**
  - **Incremental delivery:** the first `delta` arrives before the fake model is released to finish. A scripted fake blocks on an event, so the check is deterministic.
  - **Completion:** completion delivers `sources` and then `done`.
  - **Cancellation:** cancel produces `interrupted` and stops upstream; the fake records that it was cancelled.
  - **Mid-stream error:** an error mid-stream produces `failed` with the partial text kept.
  - **Through Caddy:** the same incremental-delivery assertion is repeated through the Caddy container.

### 13.3 Fixtures (`tests/fixtures/documents/`, committed)

They are generated by `tests/fixtures/generate_documents.py` (dev dependency: `reportlab`, or `fpdf2` if its licence fits better [P]). Text uses Helvetica, a standard PDF base font, so no font file is vendored or embedded. `tests/fixtures/documents/README.md` records each fixture's facts, pages and expected results.

| Fixture | Contents |
|---|---|
| `facts_small_en.pdf` | 2 pages, known facts |
| `sections_multipage_en.pdf` | 12 pages, section markers SECTION-A..D on pages 2, 5, 8, 11 |
| `conflict_a_en.pdf`, `conflict_b_en.pdf` | Same question, conflicting values |
| `visitor_x_en.pdf`, `visitor_y_en.pdf` | Unique markers per visitor |
| `two_column_en.pdf` | Two-column layout with known reading order |
| `empty.pdf` (0 bytes), `malformed.pdf` (truncated), `encrypted.pdf` (password), `scanned.pdf` (image-only), `half_scanned.pdf` | Error paths |
| `injection_en.pdf` | Contains "ignore previous instructions…" text |

### 13.4 Packaging check (CI)

1. `uv build` → wheel + sdist.
2. Inspect the wheel: it contains `sourcehaven/prompts/*.txt` and `sourcehaven/migrations/**`, and no `tests/`, `evals/`, `.claude/`, `.env*` or data.
3. In a fresh virtual environment outside the checkout, `uv pip install dist/*.whl`, then run:
   - `python -c "import sourcehaven, sourcehaven.api.app"`;
   - a resource-read smoke test via `importlib.resources`;
   - `sourcehaven --help`.
4. No network services or credentials are needed. Importing the package does not connect to anything.

### 13.5 CI

GitHub Actions is the proposed CI [P]. There is no remote yet, and the workflow is equally runnable locally.

| Job | What it runs |
|---|---|
| `checks` | `uv run pre-commit run --all-files` |
| `unit` | Unit tests |
| `integration` | Service container `pgvector/pgvector:0.8.7-pg18` |
| `packaging` | The §13.4 check |
| `frontend` | Lint, type check, Vitest, `next build` |
| `e2e` | Compose stack with fakes |

All Python jobs use Python 3.14 via `uv` with `--frozen`.

---

## 14. Python project configuration

- **`pyproject.toml`:**
  - `requires-python = ">=3.14,<3.15"`;
  - `[build-system]` uses `uv_build`;
  - `[project.scripts] sourcehaven = "sourcehaven.cli:main"`;
  - runtime dependencies: fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy[asyncio], psycopg[binary], pgvector, alembic, httpx, python-multipart, pypdf (plus the experiment's parser if different), tokenizers, tiktoken, langchain-core, langchain-openai, langchain-text-splitters;
  - dev groups: `dev` (ruff, mypy, pre-commit), `test` (pytest, pytest-asyncio or anyio, reportlab/fpdf2), `eval`.
  - All cp314 or pure-Python packages are listed in [research/2026-11-19-python-314-compat.md](../research/2026-11-19-python-314-compat.md) [V metadata; runtime confirmed by CI].
- **Ruff, mypy and pre-commit:** as already committed. Extend `known-first-party` and source roots when `src/` exists. Remove the mypy hook's no-source guard in the first milestone.
- **Typing gaps:** pgvector-python and pypdf typing gaps, if any, get narrow `[[tool.mypy.overrides]]` entries with a comment explaining why.

---

## 15. Milestones

Each milestone is a set of atomic commits with tests and documentation.

1. **M0 — Skeleton and packaging**
   - Build backend, `src/sourcehaven` with `cli`, `config` and `composition`.
   - Health endpoints.
   - Compose with `db`, `embeddings` (TEI with the provisional model), `migrate` and `api`.
   - Alembic baseline including the roles and RLS.
   - CI with the packaging check.
   - Remove the mypy guard.
2. **M1 — End-to-end slice**
   - Anonymous session.
   - PDF upload → worker ingestion (pypdf) → chunks in pgvector → question → SSE-streamed answer with validated citations (OpenAI).
   - Minimal `/app` page.
   - Two-visitor isolation tests from day one.
3. **M2 — Measurement**
   - English evaluation corpus and the embedding and parser benchmark.
   - Decision records; threshold calibration.
   - Switch the default model or parser if the results say so.
4. **M3 — Robustness and limits**
   - Full error taxonomy with the fixtures.
   - Child-process parsing limits, retries and leases.
   - Rate limits, admission queue, spending ledger.
   - Stop/cancel, idempotency, reconnect behaviour.
5. **M4 — Summaries**
   - Direct and sectioned document summaries, collection summaries.
   - Caching, progress events, page-range citations.
6. **M5 — Lifecycle**
   - Follow-ups with history budget; turns with a source whose `document_id` is null are excluded from the history (§7.1).
   - Deletion, end session, expiry sweeper, orphan cleanup.
   - Restart tests.
7. **M6 — Product UI and public pages**
   - Full app screen. Its foundation (visual system, layout, drag-and-drop upload, evidence panel)
     was pulled forward before M2: see `2026-11-20-app-ui-foundation-design.md`.
   - Landing, how-it-works and privacy pages with metadata, sitemap and robots.
   - Security headers.
8. **M7 — Deployment readiness**
   - Production Compose with Caddy.
   - Backup/restore scripts and a restore drill.
   - README and runbook.
   - Live evaluation run.
   - Pre-launch checklist (below).

**Conditions before public launch:**
- All integration suites pass, including isolation and streaming through Caddy.
- The embedding acceptance criteria are met, or a deviation is agreed with the owner.
- A live evaluation report exists with no isolation or injection failures.
- The spending caps are verified, including the OpenAI dashboard limit.
- The privacy page is accurate.
- A backup restore has been tested.
- TLS and security headers are verified.
- The OpenAI key is restricted to this project.

---

## 16. Roadmap and seams

| Future capability | Seam in the MVP | Trigger |
|---|---|---|
| More document formats (DOCX, EPUB, Markdown, HTML, TXT, RTF) | `SourceAdapter` returning `ExtractedSource`; adapter chosen by detected type. LlamaIndex readers may be wrapped here if one saves real work | Owner prioritises a format |
| Layout-model parsing (Docling), table structure | Another `SourceAdapter` implementation; parser recorded in `ingestion_fingerprint` drives re-ingestion | Evaluation shows reading-order or table failures |
| OCR, images, audio/video, YouTube transcripts | `Location` union (`TimeSpan` etc.); `FileStore` for originals; URL ingestion needs SSRF protection, outbound allow-lists, redirect/size limits, safe archive handling | Product decision; separate design |
| Accounts (Google OIDC, email magic link) | `owners.kind = account`; an anonymous owner's data can be re-parented to an account at sign-in; sessions table stays the server-side session store. Libraries such as Authlib + own magic-link flow; admin via SQLAdmin or similar [U: verify maintenance status then] | Retention/persistence demand |
| Premium durable libraries and history | Retention policy per owner kind; HNSW per-config partial indexes once per-owner corpora grow | Accounts exist |
| Higher concurrency | Move admission slots to Postgres; multiple API processes; more workers (jobs already use `SKIP LOCKED`); TEI scaled separately | Sustained busy responses |
| Hybrid lexical search, reranking, query rewriting | Retrieval service internals; Postgres full-text search (`english` configuration) or ParadeDB; CPU cross-encoder | Evaluation shows recall gaps |
| LangGraph | Multi-step agent/tool workflows; its checkpointer must be owner-scoped | Tools or branching workflows enter scope |
| Shared public sources (e.g. Wikidata graph mirror) | Separate read-only store behind the retrieval service with an explicit publication policy; never merged with private data | Separate design and publication decision |
| Qdrant or a dedicated vector store | Retrieval and chunk storage behind repositories; Postgres stays the source of truth | Millions of vectors, multivector or sparse needs |
| Advanced observability | JSON logs with ids already; add OpenTelemetry later | Operational need |

---

## 17. Sources (verified 2026-11-19 unless marked)

Detailed notes: `docs/superpowers/research/2026-11-19-*.md`.

- **pgvector:**
  - https://github.com/pgvector/pgvector
  - https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md
- **PostgreSQL text search dictionaries:** https://www.postgresql.org/docs/current/textsearch-dictionaries.html
- **Qdrant:**
  - https://qdrant.tech/documentation/guides/multiple-partitions/
  - https://qdrant.tech/documentation/concepts/hybrid-queries/
- **Chroma:**
  - https://docs.trychroma.com/guides/deploy/client-server-mode
  - https://cookbook.chromadb.dev/strategies/multi-tenancy/naive-multi-tenancy
  - Python 3.14 issues: chroma-core/chroma #5554, #6984, #5983
- **MongoDB Community search:** https://www.mongodb.com/products/updates/now-ga-mongodb-search-and-vector-search-for-community-edition/
- **FastAPI SSE:** https://fastapi.tiangolo.com/tutorial/server-sent-events/
- **Django:**
  - https://docs.djangoproject.com/en/6.1/ref/request-response/
  - https://docs.djangoproject.com/en/6.1/topics/tasks/
- **Next.js:**
  - https://nextjs.org/docs/app/api-reference/file-conventions/route
  - https://nextjs.org/docs/app/api-reference/config/next-config-js/output
  - https://nextjs.org/docs/app/guides/self-hosting
- **Caddy reverse proxy:** https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
- **TEI supported models:** https://huggingface.co/docs/text-embeddings-inference/supported_models
- **FastEmbed models:** https://qdrant.github.io/fastembed/examples/Supported_Models/
- **Model cards:** https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0, https://huggingface.co/intfloat/multilingual-e5-base, https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- **INT8 vs FP32 tradeoffs:** https://blog.vespa.ai/embedding-tradeoffs-quantified/
- **OpenAI:**
  - Pricing: https://developers.openai.com/api/docs/pricing
  - Data controls: https://developers.openai.com/api/docs/guides/your-data
- **Hosting:**
  - Hetzner: https://www.hetzner.com/cloud/cost-optimized/
  - DigitalOcean: https://www.digitalocean.com/pricing/droplets
  - Supabase: https://supabase.com/pricing
- **PyPI metadata:** `https://pypi.org/pypi/<package>/json` for every package version cited (llama-index-core 0.14.26, llama-index-readers-file 0.8.0 rechecked on 2026-11-19).

---

## 18. Left to the builder

- Exact module boundaries inside each package and the names of private helpers.
- Alembic revision layout, and SQLAlchemy Core vs ORM style per repository. ORM models with typed `Mapped[...]` are suggested.
- The SSE parser library or a hand-written parser on the frontend; styling and component library (keep it small).
- Concrete retry/backoff jitter values within the stated bounds.
- Fixture generation library (`reportlab` vs `fpdf2`), subject to a licence check.
- Prompt wording, within the rules in §7.3 and the summary rules below.

### Summary rules (agreed, A12)

- **Document summary:**
  - **Direct path:** if the document is ≤ 60k tokens [P], its full text goes to one call. The output streams, with page-range citations taken from the page markers included in the input.
  - **Sectioned path:** otherwise, the text is split into page-aligned sections of about 16k tokens [P].
    - **Where it runs** [P, settled after builder review]: the whole summary runs **inside the API request**, with no hand-off to the worker. Section calls wait on network I/O, so they run as async tasks, at most 2 in parallel per summary.
    - **Caching:** each completed section is cached immediately in `summary_sections`, keyed by version, section, length and prompt version. A retry or later request reuses it.
    - **Final stream:** the API streams the final summary, written from the section summaries, each labelled with its page range.
    - **Progress:** events show "Summarizing part i of n". Intermediate text is never shown as the answer.
    - **Capacity and time:** the summary holds one of the 4 generation slots for its whole duration. The section phase has a 240 s limit; the final stream keeps its 300 s.
    - **Stop or disconnect:** outstanding section calls are cancelled. Completed sections stay cached, and the turn becomes `interrupted`.
    - **Spending:** every section call reserves and settles against the visitor's session cap and the global cap, linked to the summary's `turn_id`.
    - **Page text:** sections are rebuilt from the version's chunks in ordinal order, de-duplicating overlaps by tracking offsets. Because of that, the chunker records `char_start`/`char_end` within the concatenated document text [P].
- **Collection summary:** a brief summary per document, reused from cache, then a streamed combination that notes agreement and differences, citing document and page ranges.
- **Lengths:** brief ≈ 150–250 words; detailed ≈ 600–900 words.
- **Language:** summaries are written in English.
- **Cache:** finished summaries are cached per owner by (kind, sorted version ids, length, prompt version, model). Re-requesting replays the cached summary with `done` and makes no call. Summaries are deleted with any of their versions.
- **Citations:** summaries cite page ranges, not passages, and the UI says so.
- **Focused summary** ("summarize what these say about X") is handled as a normal question (§7). The UI notes that it covers the relevant passages only.
