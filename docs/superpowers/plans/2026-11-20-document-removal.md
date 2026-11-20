# Document Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a visitor remove any of their documents from `/app`, keeping earlier answers readable
with their citations of the removed document marked as deleted.

**Architecture:** `DELETE /api/documents/{id}` runs one owner-scoped transaction (lock the document,
refuse while a recent generating turn uses it, blank its quote snapshots, delete it — existing
cascades and `SET NULL` do the rest), then removes the file prefix. The question path's scope check
takes share locks so it serialises with removal. The frontend adds a per-row Remove with in-row
confirmation, drops the document from state, and marks its sources as deleted in the conversation.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, PostgreSQL 18 with RLS, pytest (integration
suite on the Compose Postgres); Next.js 16.4, React 19.3, TypeScript strict, CSS Modules, Vitest +
Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-20-document-removal-design.md` (binding; section numbers
below refer to it). UI conventions: `docs/superpowers/specs/2026-11-20-app-ui-foundation-design.md`.

## Global Constraints

- Endpoint: `DELETE /api/documents/{id}` → `204` (no body) | `404 {"code": "not_found"}` byte-identical
  for unknown and foreign ids | `409 {"code": "document_in_use"}` | `401 session_required`.
- Stale bound: a `generating` turn blocks removal only if `created_at` is within the last
  **10 minutes**; module constant `GENERATING_TURN_BLOCK_WINDOW: Final[timedelta] = timedelta(minutes=10)`.
- Deleted source representation: `document_id: null`, `quote: ""`; no API schema change except the new route.
- Every SQL query carries an explicit `owner_id` predicate in addition to RLS (parent spec §5.1).
- Logs contain ids only — never file names, questions or document text.
- Copy (verbatim):
  - confirm: `Remove {name}? Its quotes in earlier answers will no longer be shown.`
  - in progress: `Removing…`
  - `document_in_use`: `An answer is still being written from this document. Remove it when the answer is finished.`
  - full tray: `This session is full. Remove a document to add another.`
  - evidence: `This document was deleted, so its quote is no longer available.`
  - under answer: `A source of this answer was deleted.` / `Some sources of this answer were deleted.`
  - citation accessible name: `Source {n}, document deleted`
- Frontend rules from the UI foundation: tokens only (no hex outside `globals.css`), no inline
  `style`, no text below 12.5px, sentence case, explicit types on every function/component, `@/`
  imports; deleted things use `--graphite`, never `--highlighter`.
- Python rules (CLAUDE.md): strict mypy, Google docstrings where a contract needs explaining,
  annotated locals, absolute imports, pytest fixtures/assertions (no `unittest`).
- Checks before every commit (repo root): `uv run pytest`, `uv run pytest -m integration` (needs the
  Compose `db` service, already running locally), `npm --prefix frontend run lint && npm --prefix
  frontend run typecheck && npm --prefix frontend test && npm --prefix frontend run build`, then
  `uv run pre-commit run --all-files` (sandbox disabled for uv/Docker/`next build`; npm with
  `npm_config_cache="$TMPDIR/npm-cache"` if `~/.npm` is not writable). Imperative commit messages, no
  AI attribution, stage paths explicitly.

## Review Focus

1. **A poll in flight resurrects a removed document:** `useDocuments` merges list responses; a
   `GET /api/documents` started before the DELETE can return the document afterwards. Expected: it
   never reappears. → Task 3 test "a poll that started before removal does not bring it back".
2. **Removing the document whose quote is highlighted in the evidence panel:** the panel must switch
   that item to the deleted text immediately, without the highlighter. → Task 5 page test.
3. **Double activation of the confirm button:** exactly one DELETE request. → Task 4 test.
4. **Removing a selected document that was the only selection:** Ask becomes disabled and the scope
   line updates. → Task 3 test (selection) and Task 4 page test.
5. **Removal racing a question on the same document:** serialised; no source rows reference a
   deleted document. → Task 2 integration test.

---

## File structure

```
src/sourcehaven/storage/repositories/documents.py   # + delete_document, RemovalOutcome (Task 1)
src/sourcehaven/storage/repositories/conversations.py # document_readiness: optional share lock (Task 2)
src/sourcehaven/api/routes/documents.py             # + DELETE route (Task 1)
src/sourcehaven/qa/service.py                       # _check_scope uses the lock (Task 2)
tests/integration/test_document_removal.py          # new (Tasks 1, 2)
tests/integration/test_isolation.py                 # + foreign removal (Task 1)
frontend/openapi.json → frontend/src/lib/api-types.ts (regenerated, Task 1)
frontend/src/lib/api.ts, messages.ts, use-documents.ts, use-conversation.ts (+ tests) (Task 3)
frontend/src/components/documents/document-row.tsx, document-list.tsx, documents-panel.tsx, drop-tray.tsx (+ css, tests) (Task 4)
frontend/src/app/app/page.tsx (+ test) (Tasks 4, 5)
frontend/src/components/conversation/citation-button.tsx, answer-markdown.tsx, turn-view.tsx (+ css, tests) (Task 5)
frontend/src/components/evidence/evidence-item.tsx, evidence-panel.tsx (+ css, tests) (Task 5)
docs/superpowers/specs/2026-11-19-sourcehaven-design.md, README.md (Tasks 1, 5)
```

---

### Task 1: Removal endpoint

**Files:**
- Modify: `src/sourcehaven/storage/repositories/documents.py`, `src/sourcehaven/api/routes/documents.py`
- Create: `tests/integration/test_document_removal.py`; Modify: `tests/integration/test_isolation.py`
- Modify: `frontend/src/lib/api-types.ts` (regenerated); `docs/superpowers/specs/2026-11-19-sourcehaven-design.md`

**Interfaces:**
- Produces:
  - `class RemovalOutcome(StrEnum)`: `REMOVED = "removed"`, `NOT_FOUND = "not_found"`, `IN_USE = "document_in_use"`
  - `async def delete_document(session: AsyncSession, owner: OwnerScope, document_id: UUID, *, now: datetime) -> RemovalOutcome`
    — steps 1–4 of spec §4.2 in the caller's transaction: `select(Document.id).where(owner, id).with_for_update()`;
    in-use check `Turn.status == "generating"`, `Turn.created_at > now - GENERATING_TURN_BLOCK_WINDOW`,
    `Turn.selected_document_ids.any(document_id)` (or `.contains([document_id])`), owner predicate;
    `update(TurnSource).where(owner, TurnSource.document_id == document_id).values(quote_snapshot="")`;
    `delete(Document).where(owner, id)`.
  - Route `DELETE /api/documents/{document_id}` (`status_code=204`, documented 404/409 responses):
    calls `delete_document` inside `owner_session` with `now=container.clock()`; `NOT_FOUND` →
    `ApiError(404, "not_found")`; `IN_USE` → `ApiError(409, "document_in_use")`; after the session
    commits, `await container.file_store.delete_prefix(f"{owner.owner_id}/{document_id}/")` wrapped
    in `try/except OSError` that logs `logger.exception("could not remove files of document %s", document_id)`
    and still returns 204.

- [ ] **Step 1: Write failing integration tests** in `test_document_removal.py` (use `ready_visitor`,
  `visitor`, `make_visitor` fixtures and `Visitor.ask` like `test_question_answering.py`):
  - `test_removal_deletes_document_rows_and_file`: ready document → DELETE → 204, empty body; the
    `Document`, `DocumentVersion`, `IngestionJob` and `Chunk` rows for it are gone; no stored PDF
    under `{owner}/{document_id}/`; `GET /api/documents` no longer lists it.
  - `test_removal_keeps_turns_and_marks_sources_deleted`: ask a question that cites the document
    (fake chat model as in existing QA tests) → DELETE → `GET /api/conversations/{id}`: same turn
    count, same question and answer text; every source that came from the document has
    `document_id is None` and `quote == ""`, keeps `label`, `document_name`, `pages`; sources from
    another still-present document are unchanged.
  - `test_removal_is_refused_while_an_answer_is_generating`: insert/keep a `generating` turn whose
    `selected_document_ids` contains the document (use `Visitor.stream_question` and DELETE while the
    stream is open, or insert a turn row directly) → `409 {"code": "document_in_use"}`; document
    and quotes unchanged.
  - `test_stale_generating_turn_does_not_block_removal`: a `generating` turn with `created_at` 11
    minutes before the container clock (`FakeClock` override) → 204.
  - `test_removal_twice_is_404`, `test_unknown_id_is_404`.
  - `test_removal_during_ingestion_publishes_nothing`: upload (queued) → DELETE → 204 → `run_once`
    until idle → no `Chunk` rows for that document id and no document listed.
  - `test_same_file_can_be_uploaded_again_after_removal`: upload → ingest → DELETE → upload the same
    fixture → `202` with a new id.
  - `test_file_removal_failure_still_succeeds`: `ContainerOverrides(file_store=…)` whose
    `delete_prefix` raises `OSError` → 204 and rows gone (use `caplog` to assert one error record
    whose message contains the document id and not the file name).
  - In `test_isolation.py`: `test_removing_foreign_document_is_404_like_unknown` (Y deletes X's id →
    404 body identical to unknown id; X's document still ready, its chunks intact), and add
    `("DELETE", f"/api/documents/{x_docs[0]}")` to `test_without_cookie_everything_requires_session`.
- [ ] **Step 2: Run** `uv run pytest -m integration tests/integration/test_document_removal.py tests/integration/test_isolation.py` — Expected: FAIL (405/route missing).
- [ ] **Step 3: Implement** `RemovalOutcome`, `delete_document` and the route.
- [ ] **Step 4: Run** the same command — Expected: PASS; then the full Python suites.
- [ ] **Step 5: Regenerate API types:** `npm --prefix frontend run gen:api`; the diff adds only the
  DELETE route.
- [ ] **Step 6: Parent spec:** update `docs/superpowers/specs/2026-11-19-sourcehaven-design.md` —
  decision A15 row, §7.5 "Deleting a document", §10 "Delete document" (keep answers, blank quotes,
  409 while generating with the 10-minute bound, files after commit) and the privacy-page bullet
  ("answers you already received stay until your session ends"), §11.1 table (`204/404/409`),
  §13.2 deletion scenario; add the M5 rule "turns with a source whose `document_id` is null are
  excluded from follow-up history" to §7 follow-ups and §15 M5.
- [ ] **Step 7: Checks + commit** — "Add document removal endpoint".

---

### Task 2: Serialise questions with removal

**Files:**
- Modify: `src/sourcehaven/storage/repositories/conversations.py`, `src/sourcehaven/qa/service.py`
- Modify: `tests/integration/test_document_removal.py`

**Interfaces:**
- Consumes: Task 1 `delete_document`.
- Produces: `document_readiness(session, owner, document_ids, *, lock: bool = False) -> dict[UUID, bool]`
  — with `lock=True` the select adds `.with_for_update(read=True, of=Document)` (FOR SHARE OF
  documents; the outer-joined version table is not lockable). `QaService._check_scope` passes
  `lock=True`. No other caller changes.

- [ ] **Step 1: Failing test** `test_question_scope_check_serialises_with_removal`: open an
  `owner_session` A, call `document_readiness(..., lock=True)` for the document (do not commit);
  start the removal as a task with its own session; assert it has not finished after 0.3 s; insert a
  `generating` turn selecting the document in session A (repository `add_generating_turn`) and
  commit A; the removal task then returns `IN_USE`. Second case: removal holds its lock first → the
  question's scope check (after removal commits) raises `LookupError` (document gone).
- [ ] **Step 2: Run** — Expected: FAIL (removal is not blocked).
- [ ] **Step 3: Implement** the `lock` parameter and pass it from `_check_scope`.
- [ ] **Step 4: Run** the removal and QA integration tests — Expected: PASS, existing QA tests unchanged.
- [ ] **Step 5: Checks + commit** — "Lock selected documents while a question starts".

---

### Task 3: Frontend data layer

**Files:**
- Modify: `frontend/src/lib/api.ts`, `messages.ts`, `use-documents.ts`, `use-conversation.ts` and their tests

**Interfaces:**
- Produces:
  - `deleteDocument(documentId: string): Promise<void>` — `DELETE /api/documents/{id}`, same-origin
    credentials; non-2xx → `ApiError` via the shared parser.
  - `messages.ts`: `document_in_use` text from Global Constraints in `describeError`.
  - `useDocuments` additions: `removing: ReadonlySet<string>`, `removeErrors: ReadonlyMap<string, string>`,
    `remove: (id: string) => Promise<boolean>` (true on success). On success: drop the document, its
    selection and `knownReady` entry, and remember the id so later list merges skip it (Review Focus 1).
    On failure: keep the document, set `removeErrors[id]` to `describeError(error)`; a later `remove`
    of the same id clears it. Concurrent `remove(id)` calls for an id already in `removing` return
    `false` without a request.
  - `useConversation` addition: `markDocumentDeleted: (documentId: string) => void` — every source
    with that `document_id` in every turn becomes `{ ...source, document_id: null, quote: "" }`.
- [ ] **Step 1: Failing tests:** `api` test (fake fetch: 204 resolves; 409 rejects `ApiError` code
  `document_in_use`); `use-documents.test.tsx`: success removes row, id from `selected`; a poll
  started before removal and resolving after it does not bring the document back; 409 keeps the row
  and sets the error text; double `remove` sends one request; `use-conversation.test.tsx`:
  `markDocumentDeleted` nulls only that document's sources across turns.
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: Checks + commit** — "Add document removal to the frontend state".

---

### Task 4: Remove in the documents column

**Files:**
- Modify: `frontend/src/components/documents/document-row.tsx`, `document-list.tsx`,
  `documents-panel.tsx`, `drop-tray.tsx` (+ `.module.css`, tests); `frontend/src/app/app/page.tsx`, `page.test.tsx`

**Interfaces:**
- Consumes: Task 3 hook additions.
- Produces: `DocumentsPanel` gains `removing: ReadonlySet<string>`, `removeErrors: ReadonlyMap<string, string>`,
  `removeDisabledReason: string | null`, `onRemove: (id: string) => void`; rows render per spec §5.1.
  `page.tsx` wires `onRemove` to `documents.remove(id)` and, on `true`, `conversation.markDocumentDeleted(id)`;
  `removeDisabledReason` is the `document_in_use` text while `conversation.generating`, else `null`.
- Behaviour (spec §5.1): Remove button per server-document row (not upload rows), visible on
  `:hover`/`:focus-within`, always under `@media (hover: none)` and on failed rows; click → in-row
  confirm with the Global Constraints copy, **Remove** + **Cancel**, focus moves to Cancel, Escape
  cancels and returns focus to the row's Remove button; confirm → `onRemove`; `removing` → "Removing…"
  and buttons disabled; `removeErrors` text shown in `--bad` under the row; disabled Remove carries
  `aria-describedby` pointing at the reason text (visually hidden). Full tray text per Global
  Constraints.
- [ ] **Step 1: Failing tests:** row shows Remove; confirm text; Cancel focused; Escape cancels;
  confirm calls `onRemove(id)` once even when clicked twice; disabled with reason while
  `removeDisabledReason` set; failed row shows Remove; tray full text; page test: removing the only
  selected document disables Ask and the scope line reads the "Select at least one…" text.
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: Checks + commit** — "Add Remove to document rows".

---

### Task 5: Deleted sources in answers and evidence

**Files:**
- Modify: `frontend/src/components/conversation/citation-button.tsx`, `answer-markdown.tsx`,
  `turn-view.tsx`; `frontend/src/components/evidence/evidence-item.tsx`, `evidence-panel.tsx`
  (+ `.module.css`, tests); `frontend/src/app/app/page.test.tsx`; `README.md` (Manual browser check)

**Interfaces:**
- Consumes: `TurnSource.document_id === null` means deleted (Task 3 / API).
- Produces: `AnswerMarkdown` gains `deletedLabels: ReadonlySet<string>`; `CitationButton` gains
  `deleted: boolean` (graphite, underline on hover/active, accessible name per Global Constraints,
  still calls `onActivate`). `TurnView` computes `deletedLabels` from cited sources and shows the
  under-answer note. `EvidenceItem` renders the deleted text instead of the quote and never the
  highlighted/sweep class.
- [ ] **Step 1: Failing tests:** deleted citation's accessible name and class, still activates;
  note text singular/plural; evidence item deleted text and no highlight even when active; page
  test (Review Focus 2): answer with cited `[1]` highlighted in the panel → remove that document →
  the panel shows the deleted text, no highlighted mark, and the answer's `[1]` is named "Source 1,
  document deleted".
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: README:** add a removal step to "Manual browser check" (remove a cited document;
  its citation turns grey and the evidence says the document was deleted).
- [ ] **Step 6: Checks + commit** — "Show deleted sources in answers and evidence".

---

### After the tasks (controller)

Whole-branch review; checkpoint note in `docs/superpowers/checkpoints/`; rebuild the dev stack for
the owner's visual check; ask before pushing or opening the PR.
