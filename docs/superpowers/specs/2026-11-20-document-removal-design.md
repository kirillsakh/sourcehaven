# Document removal — design

- **Date:** 2026-11-20
- **Status:** approved by the owner (2026-11-20)
- **Branch / delivery:** `feature/document-removal`, one pull request into `main`
- **Parent spec:** `docs/superpowers/specs/2026-11-19-sourcehaven-design.md` (§5.2, §7.5, §10, §11.1,
  §13.2, decision A15); UI: `docs/superpowers/specs/2026-11-20-app-ui-foundation-design.md`

Markers: **[O]** owner decision in the design conversation, **[C]** my call, open to correction,
**[B]** left to the builder within the stated constraints.

## 1. Intent

A visitor can remove documents they uploaded. The motivating case: the session is full (10 of 10)
and they want to make room for new files, or swap a file for a newer version ("replace" is remove,
then upload). The owner wants it for local demos before M2 [O]. It pulls the "delete document" part
of M5 forward; ending the session, the expiry sweeper and orphan cleanup stay in M5.

### 1.1 Goals

- **G1.** Remove any of the visitor's documents (ready, queued, processing or failed) from the
  documents column.
- **G2.** Removal frees the slot immediately; the full-session tray points to it.
- **G3.** Earlier answers stay readable; their citations of a removed document say clearly that the
  source was deleted [O].
- **G4.** "Remove" keeps its promise: the document, its file, its chunks and every quote taken from it
  are gone when the request succeeds [O].

### 1.2 Non-goals

- Bulk removal / an edit mode, and Undo [O: deferred].
- Ending the session, the expiry sweeper, orphan-file sweeping (M5).
- Cancelling a generating answer (M3); removal waits instead (§4.3).
- Follow-up conversation history (M5); this design only adds the rule M5 must follow (§3.3).

### 1.3 Anti-goals

- The checkboxes ("use in answers") ever deleting anything.
- A removed document's text surviving anywhere the visitor or the model can reach (quotes, chunks,
  file), except in answer text the visitor already received.
- Revealing whether another visitor's document id exists.

## 2. Change to an agreed decision (A15)

**Before (A15):** deleting a document also deletes every turn that used it as evidence, and the
conversation shows "N turns removed with a deleted document".

**Now [O]:** questions and answers are kept. Every source row taken from the document (cited or not)
loses its quote and its link to the document, and is marked deleted in the API. The UI shows those
citations as deleted. Answers with a deleted source are excluded from follow-up history (§3.3).

Why: deleting a file should not destroy the conversation the visitor did not ask to destroy, and it
keeps a demo readable [O]. The privacy promise stays honest because the document's own text — file,
chunks, quotes — is removed; only answers already shown remain, until the session expires.

The parent spec is updated in the same branch: decision register (A15), §7.5 "Deleting a document",
§10 "Delete document", §11.1 (status codes), §13.2 (deletion scenario), and the privacy-page wording
note in §10 ("answers you already received stay until your session ends").

## 3. Approaches considered

| | **1. Immediate delete in one transaction (chosen)** | 2. Soft delete + later purge | 3. Delete via the worker |
|---|---|---|---|
| How | API deletes rows, then the file | `deleted_at` flag; worker purges | API enqueues; worker deletes |
| Undo | no | possible | no |
| Risk | smallest | every query must skip flagged rows; text lingers until purge | "Removing…" states and polling for a fast operation |

The owner chose 1 [O]. It matches parent spec §10 and needs no migration.

## 4. Backend

### 4.1 Endpoint

`DELETE /api/documents/{id}` (session required).

| Outcome | Status | Body |
|---|---|---|
| Removed | `204` | none |
| Unknown id or another owner's id | `404` | `{"code": "not_found"}`, byte-identical for both |
| An answer using it is generating | `409` | `{"code": "document_in_use"}` |
| No session | `401` | `session_required` (existing dependency) |

Repeating the request after success gives `404` [C]. No request body; the parent spec's CSRF rule
(§11.1) is not implemented yet and remains M3/M6 work.

### 4.2 What one transaction does

Within `owner_session` (RLS owner set), in this order:

1. Lock the document row (`SELECT … FOR UPDATE` with the owner predicate). Missing → `404`.
2. If any turn of this owner has `status = 'generating'`, the document id in
   `selected_document_ids`, and `created_at` within the last 10 minutes → `409 document_in_use`.
   Older `generating` turns are treated as abandoned (an API restart can leave one behind; nothing
   recovers them before M3/M5), so they never make a document undeletable [C]. The bound is a module
   constant: answers are capped at 800 output tokens and finish in well under a minute.
3. Update `turn_sources` where `document_id = :id` (owner predicate): `quote_snapshot = ''`. Keep
   `document_name_snapshot`, `label`, `cited`, `page_start/page_end`.
4. Delete the document. Existing cascades remove versions, ingestion jobs and chunks; existing
   `ON DELETE SET NULL` clears `turn_sources.document_id` / `version_id` and
   `documents.current_version_id`.
5. Commit, then `file_store.delete_prefix(f"{owner_id}/{document_id}/")`. A failure there is logged
   (ids only) and does not fail the request; the M5 orphan sweep removes the file later.

Every query carries the explicit owner predicate (parent spec §5.1 layer 1) in addition to RLS.
A repository function holds steps 1–4 [B: name, e.g. `delete_document(session, owner, document_id)`
returning an outcome enum].

### 4.3 Concurrency

- **Ingestion in progress:** deleting cascades the job row; the pipeline already abandons work when
  the job disappears (`_LeaseLost`). If the worker's publish transaction holds the job row, the delete
  waits for it and then cascades the freshly published chunks.
- **Questions:** `QaService._start` checks scope and inserts the `generating` turn in one
  transaction. That scope check now takes `FOR SHARE` locks on the selected document rows [C], so it
  and a removal serialise: if the question locks first, the removal waits, then sees the turn and
  returns `409`; if the removal locks first, the question waits and then finds the document gone
  (`not_found`, as today). Without the lock, a turn committing between step 2 and the delete's commit
  could later fail inserting its sources against a deleted document.
- **Two removals of the same document:** the row lock serialises them; the second gets `404`.

### 4.4 API representation of deleted sources

No schema change: a source whose document was removed has `document_id: null` and `quote: ""` in both
the SSE `sources` event and `GET /api/conversations/{id}`. The frontend treats `document_id === null`
as "deleted". The source schema does not change [C]; the regenerated OpenAPI types only gain the new
route.

### 4.5 Follow-up history rule (for M5)

When M5 adds conversation history to prompts, turns with any source whose `document_id` is null are
excluded from that history, and the parent spec says so.

## 5. Frontend

### 5.1 Documents column

- Each document row gets a **Remove** button (text, sentence case), shown on row hover and on
  keyboard focus within the row, always shown on touch screens (`@media (hover: none)`) and on
  failed rows.
- Clicking it turns the row into an in-row confirmation: "Remove contract.pdf? Its quotes in earlier
  answers will no longer be shown." with **Remove** and **Cancel**. Focus moves to Cancel; Escape
  cancels [C].
- While the request runs the row shows "Removing…"; on success the row disappears, the id leaves the
  selection, and the slot count drops. On failure the row returns with the error text:
  `document_in_use` → "An answer is still being written from this document. Remove it when the answer
  is finished."; other errors via the existing `describeError`.
- While any answer is generating, Remove is disabled with the same explanation as its accessible
  description [C] (the server check stays authoritative).
- Uploading/rejected rows keep their existing Dismiss; they are not server documents.
- Full session tray text becomes "This session is full. Remove a document to add another."

### 5.2 Conversation and evidence

- After a successful removal the client marks every source with that `document_id` in its turns as
  deleted (`document_id: null`, `quote: ""`), so the view matches what a reload returns.
- **Citation in the answer:** a deleted source's `[n]` stays a button (it still opens the evidence),
  in `--graphite` instead of `--prussian`, accessible name "Source n, document deleted". Its
  hover/active state uses an underline, not the highlighter [C].
- **Under the answer:** "A source of this answer was deleted." (or "Some sources of this answer were
  deleted.") when at least one cited source is deleted.
- **Evidence panel:** a deleted item shows "[n] contract.pdf, page 4" and, instead of the quote,
  "This document was deleted, so its quote is no longer available." in `--graphite`. It never gets the
  highlighter. Deleted uncited passages are listed the same way inside "N more passages…".
- "Sources from N documents" counts distinct document names, deleted ones included.

## 6. Testing

- **Integration (Postgres, `tests/integration/`):**
  - removal deletes the document, versions, job and chunks, blanks quotes and nulls
    `turn_sources.document_id`/`version_id`, keeps turns and their text; the file prefix is gone;
  - `GET /api/conversations/{id}` afterwards returns those sources with `document_id: null`,
    `quote: ""`;
  - `409 document_in_use` while a turn selecting the document is `generating`; nothing changed;
  - a `generating` turn older than 10 minutes does not block removal;
  - a question's scope check and a removal of the same document serialise (the question's
    transaction holds its share lock while the removal waits, then the removal returns `409`);
  - removal during ingestion: the worker run afterwards does not resurrect chunks;
  - re-uploading the same file after removal creates a new document;
  - isolation: visitor Y removing X's id gets the same `404` body as an unknown id, and X's data is
    untouched (`tests/integration/test_isolation.py`);
  - `401` without a session.
- **Unit (pytest):** file-removal failure is logged and does not fail the request (fake file store).
- **Frontend (Vitest):** `deleteDocument` API helper; `useDocuments.remove` (success removes row and
  selection, 409 restores row with text); `useConversation.markDocumentDeleted`; row confirm flow
  (Cancel focus, Escape, disabled while generating); deleted citation and evidence rendering; tray
  copy.
- OpenAPI types regenerated (`npm run gen:api`) and committed; CI's stale-types check stays green.
- Owner's visual check of the flow before merge.

## 7. Left to the builder

Repository function and outcome names; exact row-confirm layout within the existing row styles;
whether "Removing…" uses the status line or the button label; log wording (ids only, never names or
content).
