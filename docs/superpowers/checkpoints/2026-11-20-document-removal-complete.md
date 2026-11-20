# Checkpoint: document removal complete (2026-11-20)

Branch `feature/document-removal` (from `main` at 8909ddd). Spec
`docs/superpowers/specs/2026-11-20-document-removal-design.md`, plan
`docs/superpowers/plans/2026-11-20-document-removal.md`. All five plan tasks are complete, each
reviewed; a whole-branch review followed, its findings were fixed in one wave and re-reviewed.

## What was delivered

| Task | Delivered | Commits |
|---|---|---|
| 1 | `DELETE /api/documents/{id}` (204/404/409): one owner-scoped transaction, quotes blanked, answers kept, files removed after commit; integration and isolation tests; regenerated API types; parent spec A15/§7/§10/§11.1/§13.2 updated | c688982 |
| 2 | `FOR SHARE` lock in the question path's scope check, so questions and removals serialise | 98fb62f, e13d1d5 |
| 3 | Frontend state: `deleteDocument`, `useDocuments.remove` (ignores stale polls), `useConversation.markDocumentDeleted` | ee7d608 |
| 4 | Remove on each document row with in-row confirmation; full-session tray points to Remove | 492c4cf |
| 5 | Deleted citations and evidence rendering; README manual check | baf12e5 |
| Final review fixes | README limitation, confirm disabled while answering, focus after removal, publish locks the document before the job (deadlock fix), deleted evidence label, stale refusal text, M5 wording | eaac58b, a341d24, 48ba088 |

Checks on the final commit: Python unit 200, integration 132, frontend 244 tests; lint, typecheck,
`next build`, pre-commit all pass.

## Owner decisions

- Answers stay after removal; quotes are removed and citations show "document deleted" (A15 changed).
- Remove on each row with in-row confirmation; no bulk edit mode, no Undo for now.
- Immediate deletion in one transaction (no soft delete, no worker job).

## Rulings made during execution

- R1: a `404` from `DELETE` means the document is already gone (e.g. removed in another tab) and
  is treated as removed.
- R2: the publish/removal lock-order deadlock was fixed (publish locks the document first) rather
  than only documented.
- Builder-check calls (in the design): a generating turn older than 10 minutes no longer blocks
  removal; the question path takes a share lock on its documents.

## Open items

- **Remaining lock-order window:** the worker's `_begin` and `_record_failure` lock the job and then
  update the version, while removal's cascade goes document → version → job. A removal landing in
  the few milliseconds when indexing starts (or fails) can deadlock; PostgreSQL aborts one side
  (the visitor sees an error and Remove works on retry, or the worker retries the job). Fix: lock the
  document first in both, as `_publish` now does (~15 lines plus two concurrency tests).
- Deferred minors (accepted by the final review): `LocalFileStore.delete_prefix` ignores errors so
  directory-removal failures are not logged (M5 orphan sweep); no live region for "Removing…"/errors;
  a refusal caused by another tab's answer stays until this tab's next answer; cosmetic test items.
- Follow-up history (M5) must exclude answers with deleted sources (rule recorded in the parent spec).
