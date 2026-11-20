# Checkpoint: `/app` UI foundation complete (2026-11-20)

Branch `ui/app-foundation` (from `main` at 7b23e70). Spec
`docs/superpowers/specs/2026-11-20-app-ui-foundation-design.md`, plan
`docs/superpowers/plans/2026-11-20-app-ui-foundation.md`. All nine plan tasks are complete. Each was
reviewed (spec compliance and quality); a whole-branch review followed, and its findings were fixed
in one wave and re-reviewed. No backend or API change.

## What was delivered

| Task | Delivered | Commits |
|---|---|---|
| 1 | Colour tokens, bundled fonts (Atkinson Hyperlegible Next, Source Serif 4), restyled `/` | 357683d |
| 2 | Message, ingestion-error, document-status, upload-check and selection helpers | 75ee92d |
| 3 | Safe Markdown answers with `[n]` citation buttons; jsdom + Testing Library setup | 5d28888 |
| 4 | Session and documents hooks: XHR upload progress, 3 parallel uploads, client pre-checks, polling | 3aa1496 |
| 5 | Conversation hook with an active turn and citation | 61030d0 |
| 6 | Documents column, "Use all ready documents", page-wide drag-and-drop overlay | 2b51c90, e8486e1 |
| 7 | Conversation column, composer with scope line, empty state | 2b5f3aa, be0f9ff |
| 8 | Evidence panel, header, three-column page; M1 page and CSS removed | e35926f |
| 9 | Evidence drawer (`<dialog>`) for 800–1279 px, phone layout, README | b525c25, cff3733 |
| Final review fixes | Phone upload feedback, drawer scroll order, indexing-phase copy, highlighter replay, Markdown block styles, inline caret, composer ring, drops on a full session, light theme only, and smaller items | d0b8ae2 .. ed923d9 |

Frontend: 206 tests (Vitest, node + jsdom), lint, typecheck and `next build` pass; the full
pre-commit suite passed before every commit.

## Owner decisions during execution

- Execution one task after another (no parallel waves).
- Light theme only for now; dark mode is deferred to its own pass (spec §1.2, §4.1 updated).
- The owner runs the browser visual check and the paid OpenAI screenshots personally.

## Rulings made during execution

- R1: a `--panel` token (`#FBFCFD`) for the evidence panel and active-turn tint, because hex values
  are allowed only in `globals.css`.
- R2: the old M1 `turn-view.tsx` was deleted in Task 8, not Task 7, so every commit builds.
- R3: the Docker visual pass moved from the Task 9 implementer to the controller; it could not run
  here (headless Chrome hangs in this environment) and is with the owner.
- R4: environment only: pre-commit and `next build` run outside the sandbox; npm uses a temporary
  cache when `~/.npm` is not writable.
- R5: `DropOverlay` takes `limits` to show the limits line (the plan's signature omitted it).
- R6: the highlighter stroke uses a hard-stop `linear-gradient`; it is the evidence mark the spec's
  sweep needs, not a decorative gradient.
- R7: on a phone, starting an upload opens the documents disclosure so per-file feedback is visible.
- R8: new copy for the indexing phase: "Your document is still being indexed." and "contract.pdf is
  being indexed. You can ask once it is ready." (the spec did not cover this state).
- R9: Markdown headings in answers render as styled paragraphs, so answers add no headings to the
  page outline.

## Deferred items

Accepted as deferred by the whole-branch review (none block a demo):

- Error-text lookups use plain objects (`Object.hasOwn` hardening); `describeError` has no docstring.
- A link definition such as `[S1]: http://x` would turn a marker into a link reference.
- Uploads queued at unmount are not cancelled; a failed first listing has no automatic retry (M1 parity).
- `TurnViewModel.status` is a string, not a union (M1 parity); restore/ask race while the stored
  conversation loads (M1 parity).
- Drag depth can drift if an entered element is removed mid-drag (the next drag resets it).
- Whole-turn activation is mouse-only (citations are the keyboard path); `aria-live` on the turns list
  announces every streamed token.
- Uncited passages have interactive `[n]` buttons; the evidence `[n]` hit area is small.
- The caret lands on its own line when an answer ends in a blockquote or code block.
- Every answer re-parses its Markdown on each streamed token (`TurnView` is not memoised); fine for a
  demo, worth memoising before long conversations.
- Dark mode (owner decision above).

M6 keeps the items listed in spec §2 (public pages, CSP and security headers, Stop during
conversation creation, malformed SSE events).

## Next

1. Owner's visual check on the dev stack (fake generator), then the PR into `main` with the owner's
   screenshots from a run with the real generator.
2. M2 (measurement) plan.
