# `/app` UI foundation — design

- **Date:** 2026-11-20
- **Status:** approved by the owner (2026-11-20)
- **Branch / delivery:** `ui/app-foundation`, one pull request into `main`
- **Parent spec:** `docs/superpowers/specs/2026-11-19-sourcehaven-design.md` (§11.3 Frontend, §15 Milestones)
- **Mockups:** `2026-11-20-app-ui-foundation-mockups/` next to this file (HTML fragments made during the
  design conversation; open in a browser. They load Google Fonts for convenience; the app must not.)

Markers: **[O]** owner decision in the design conversation, **[C]** my call, open to correction,
**[B]** left to the builder within the stated constraints.

## 1. Intent

The owner opened `/app` locally and found it looking "like the 90s": a bare file input, no drag and
drop, plain text answers and sources. They want to show Sourcehaven from their own machine to other
people, for example in a job interview while presenting their projects [O]. The pass happens now,
before M2, and is a foundation: later milestones (M4 summaries, M5 deletion and end session, M6 full
product UI) build on it rather than replace it [O].

### 1.1 Goals

- **G1. Looks deliberate and modern on a white background** [O], with a visual identity drawn from
  what the product does (answering from documents and showing evidence), not a template look.
- **G2. Readable on a laptop or projector** [O]: sizes, contrast and line lengths in §4.2.
- **G3. Drag-and-drop upload** [O] anywhere on the page, with per-file progress and per-file errors.
- **G4. Answer and evidence side by side** [O]: three-column layout with an evidence panel (§5).
- **G5. Citations shown as `[1]`, `[2]`** [O], not `S1`, `S2`.
- **G6. Document selection is understandable** [O]: the checkboxes say what they do (§6.3).
- **G7. A demo-worthy first visit**: an empty state with one obvious first step.

### 1.2 Non-goals

- Any backend or API change. Everything here works against the current API [O, verified §8].
- Features whose API does not exist yet: deleting a document, ending the session, summaries, the
  Turnstile challenge. The layout leaves room for them; it does not show disabled placeholders [C].
- Public pages (`/`, `/how-it-works`, `/privacy`), metadata, sitemap, security headers (M6). `/`
  only inherits the new fonts and tokens; its content does not change [C].
- Previewing original PDFs (spec §1.2 non-goal): evidence stays quoted snippets with page numbers.
- Dark mode. The owner chose the light theme only for now [O, 2026-11-20]: `color-scheme: light`, no
  dark tokens. Dark mode returns later as its own designed and checked pass.

### 1.3 Anti-goals

- Looking like a generic SaaS template: identical rounded cards with soft shadows, gradient washes,
  ALL-CAPS eyebrow labels, `a · b · c` meta strings, default indigo.
- Pale grey text that fails contrast (the problem the owner noticed in the first mockup).
- Breaking what M1 already does: polling, parallel uploads (max 3), stop, retry, conversation
  restore after reload, the error texts' meaning.
- Changing what M2 measures: the model still emits and the server still validates `[S1]` labels.

## 2. Milestone placement

This pass pulls part of M6 ("Full app screen") forward. M6 keeps: public pages, security headers
and CSP, final copy review, and the M6 frontend cleanup items listed in the M1 checkpoint (Stop
during conversation creation, malformed SSE events dropped silently, unchecked casts, post-abort
guard). Items from that list that this rewrite naturally touches (stale `pollError`, unannotated
component return types, the thin provisional-text cue) are fixed here [C]. The parent spec's §15 M6
entry gets a one-line pointer to this document.

## 3. Approaches considered

### 3.1 Visual direction

| | Clean neutral | Warm editorial | Dark-first tech | **Ink and highlighter (chosen)** |
|---|---|---|---|---|
| Look | white, zinc greys, indigo | paper tones, serif, terracotta | navy, cyan→indigo gradients | white, ink-blue text and accent, highlighter yellow for evidence only |
| Verdict | readable but templated | distinctive, but a common generated look | trendy, dates fast, washes out on projectors | owner's pick [O] |

### 3.2 Layout

| | A. Evidence under each answer | **B. Evidence panel (chosen)** | C. Centred chat, docs in a rail |
|---|---|---|---|
| Strength | simplest; each turn self-contained | answer and proof side by side; best demo moment | most "chat app" |
| Cost | scroll to verify long answers | three columns need a drawer below ~1280 px; more state | hides upload progress |

The owner chose B [O]; my recommendation had been A for lower cost.

### 3.3 Styling technology

| | **CSS Modules + tokens (chosen)** | Tailwind CSS v4 | shadcn/ui (Radix + Tailwind) |
|---|---|---|---|
| New deps | none | Tailwind + PostCSS plugin | Tailwind + several Radix packages |
| CSP (M6) | nothing to fight | fine | fine |
| Fit | six named tokens map directly to CSS variables | tokens must be re-mapped into the theme | default look is the templated style we rejected |

The owner chose CSS Modules [O]. The drawer uses the native `<dialog>` element.

## 4. Visual system

### 4.1 Colour tokens (light, demo theme)

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#FFFFFF` | page background |
| `--ink` | `#1D2433` | text (≈14:1 on paper) |
| `--graphite` | `#4A5263` | secondary text (≈7.9:1); nothing lighter is used for text |
| `--rule` | `#D9DDE5` | borders and dividers |
| `--wash` | `#F3F5F9` | drop tray, panel tint (the evidence panel uses `#FBFCFD`) |
| `--prussian` | `#1F4E8C` | actions, links, citations, focus ring, progress |
| `--highlighter` | `#FFE774` | evidence highlight and hovered/active citation **only** |
| `--ok` / `--warn` / `--bad` | `#1F7A4D` / `#8A5A00` / `#B42318` | Ready / in progress / failed status words |

Dark tokens: deferred with dark mode (§1.2). A candidate set from the design conversation, not
checked: paper `#12161F`, ink `#E6E9EF`, graphite `#A9B1C1`, rule `#2A3242`, wash `#1A202B`, prussian
`#8FB3FF`, highlighter `rgba(255, 231, 116, 0.35)`, ok `#6FD08C`, warn `#F0B955`, bad `#FF8A80`.

All tokens live in `src/app/globals.css` on `:root`; components use only the variables.

### 4.2 Typography

- **Interface:** Atkinson Hyperlegible Next (variable), designed by the Braille Institute for
  legibility. Package `@fontsource-variable/atkinson-hyperlegible-next` (5.3.0, OFL-1.1).
- **Quoted evidence:** Source Serif 4 (variable, optical sizes) so document text visibly reads as
  "from the document". Package `@fontsource-variable/source-serif-4` (5.3.1, OFL-1.1).
- Both are bundled with the app (imported once in the root layout); no runtime request to Google.
  `next/font/google` is not used: it fetches at build time, which the Docker build should not
  depend on [C].
- **Sizes:** answer text 16.5 px / line-height 1.7, max 64 characters per line; question 15.5–17 px
  semibold; interface 15 px; quotes 15–16 px / 1.6; **minimum 12.5 px** for any text.
- Sentence case everywhere; no all-caps labels; no middle-dot meta strings (write
  "annex-b.pdf, page 2").

### 4.3 Shape and structure

- No card shadows or gradients. Lists are separated by `--rule` lines, not boxes.
- Radius by role: composer 12, drop tray 10, buttons 8, small chips 4.
- Visible keyboard focus: 2 px `--prussian` outline with offset on every interactive element.
- Motion only in response to an action: the highlighter sweep (≈350 ms, `background-size`) and the
  drawer opening. Both are disabled under `prefers-reduced-motion`.

## 5. Layout

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Sourcehaven                         Files and answers are deleted 24 hours after …    │
├──────────────────┬───────────────────────────────────────────┬───────────────────────┤
│ Your documents   │ (older turn, muted)                        │ Evidence              │
│        3 of 10   │ Who are the parties to the contract?       │ For "How long is the  │
│ ┌ Drop PDFs here ┐│ Northwind Ltd and Dana Kowalski [1].       │  notice period…"      │
│ └ or choose files┘│ ┌───────────────────────────────────────┐ │ [1] employment-       │
│ ☑ Use all ready   │ │ How long is the notice period…?        │ │  contract.pdf, page 4 │
│ ───────────────── │ │ The notice period is three months [1]. │ │  “Either party may …” │
│ ☑ contract.pdf    │ │ It can be shortened only if:            │ │  (highlighted)        │
│   Ready 14 pages  │ │  • both sides agree in writing [2]      │ │ [2] annex-b.pdf, p. 2 │
│ ☐ report.pdf      │ └───────────────────────────────────────┘ │  “The notice …”       │
│   Indexing 60% ▬▬ │ [ Ask a question about your selected … ][Ask] │ ▸ 2 more passages   │
│                   │ Answering from 2 of 3 documents             │   were read, not cited│
└──────────────────┴───────────────────────────────────────────┴───────────────────────┘
```

- **≥ 1280 px:** three columns: documents ≈ 260 px, conversation flexible, evidence ≈ 340 px [B: exact
  widths].
- **800–1279 px:** documents + conversation; the evidence panel becomes a right-side drawer
  (`<dialog>`), opened by clicking a citation or "Show evidence" under an answer [C].
- **< 800 px:** one column. Documents collapse into a disclosure at the top ("Your documents, 3 of
  10"); evidence opens in the same drawer as full-screen sheet [C].
- The conversation column scrolls; the composer stays pinned at its bottom; the side columns scroll
  independently. No horizontal page scroll at any width.

## 6. Behaviour

### 6.1 Upload

- **Drop anywhere:** dragging files over the window shows a full-page overlay: "Drop to upload N
  PDFs" (N from `dataTransfer.items` when available, otherwise "Drop to upload PDFs") with the
  limits line. Dropping outside the documents column works. The overlay ignores drags that carry no
  files (text, links) [C].
- **Choose files:** the tray's "choose files" is a real `<button>` opening the hidden file input, so
  keyboard and screen-reader users have the same path.
- **Client pre-checks** before sending, using the session limits from `POST /api/session`: not a PDF
  (by MIME type or `.pdf` extension), empty file, larger than `max_upload_bytes`, or more files than
  the remaining document slots. The rejected file gets a row with the reason and no request is sent.
  The server stays authoritative; its error codes map to the same texts [C].
- **Per-file progress:** a pending row appears immediately: "Uploading 45%" (byte progress via
  `XMLHttpRequest` upload events, because `fetch` has no upload progress) → the server's document
  replaces the pending row → "Queued" → "Indexing 60%" (from `progress.done/total`; the stage
  `publishing` shows "Finishing") → "Ready, 14 pages". Max 3 parallel uploads stays.
- **Duplicates:** the server returns the existing document for a same-owner duplicate; the pending
  row merges into it, no error [C].
- **Errors stay on their file** with a plain explanation and, where possible, the fix. Today a failed
  document shows its raw code ("Failed: encrypted"); this pass maps upload error codes and the
  ingestion codes that exist (`encrypted`, `damaged`, `too_many_pages`, `empty`,
  `embedding_unavailable`, `internal`) to the visitor messages of parent spec §6.3, e.g. "This PDF
  is password-protected. Remove the password and upload it again." Unknown codes get a generic
  message, never the raw code alone [C]. A failed
  pending row can be dismissed (client-only; it never existed on the server) [C]. Failed server
  documents stay listed until M5 adds deletion.

### 6.2 Documents column

- Heading "Your documents" with "3 of 10" (count of server documents vs `max_documents`).
- Rows: checkbox, file name (wraps, never truncated mid-word without a tooltip [B]), status word in
  its status colour, detail ("14 pages", "60%"), a thin `<progress>` while in progress.
- Total pages of the session ("412 of 600 pages", spec §11.3 sketch) is **not** shown: the API does
  not report it, and it is not needed for the demo [C].

### 6.3 Selection

- The checkboxes decide which documents an answer may use (unchanged semantics; the API takes the
  ids per question, 1–10, all must be ready).
- New row above the list: "Use all ready documents" — a tri-state checkbox (checked / mixed /
  unchecked) that selects or clears all ready documents [O].
- Only Ready documents can be checked; newly ready documents are checked automatically (as today).
- Under the composer: "Answering from 2 of 3 documents" (ready selected / ready total). With none
  selected: "Select at least one ready document to ask a question." and Ask is disabled. While no
  document is ready but some are queued or processing: "Your document is still being indexed." (or
  "Your documents are …" for several); with no documents, or only failed ones: "Add a PDF to ask a
  question." Clicking the line moves focus to the documents list (on small screens, opens the
  documents disclosure) [C].

### 6.4 Conversation column

- **Empty state (first visit, no documents):** the middle column is one large drop target:
  heading "Ask questions about your PDFs", one line "Every answer shows the passages it came from.",
  and the tray. With documents but no questions yet: a short prompt above the composer, for example
  "Ask something about contract.pdf" [B: final copy]. While none is ready yet and some are being
  indexed: "contract.pdf is being indexed. You can ask once it is ready." (several: "Your documents
  are being indexed. You can ask once one is ready.").
- **Turns:** question (semibold) then the answer. Older turns are muted (graphite); the turn whose
  evidence is in the panel is the **active turn**, marked with a subtle border and background.
  Clicking a turn or any of its citations makes it active. A new question becomes active when sent.
- **Answer rendering:** Markdown via `react-markdown` (10.1, MIT): raw HTML skipped, images not
  rendered (alt text only), links rendered as plain text, per spec §7.3. CommonMark only, no
  `remark-gfm` [C]. Citation markers are turned into components by a small remark plugin that
  reuses `splitCitations` on text nodes (markers inside code spans stay literal) [B: implementation].
- **Citations:** `[S3]` is displayed as `[3]` by stripping the `S` (display only; the model and
  validation still use `S` labels) [O]. A matched citation is a `<button>` in `--prussian`, bold,
  12.5–13 px; hover, focus and active state use the highlighter background. Unmatched markers
  (labels the server reported in `invalid_citation_labels` or that have no source) are shown as
  plain, non-interactive `[9]` in `--graphite`, never as `[S9]`, together with the existing note
  below the answer; colour and the missing button affordance keep them distinct from real
  citations [C]. Activating a citation makes its turn active, scrolls the evidence panel to
  that source, and sweeps the highlighter across its quote; on narrow screens it opens the drawer.
- **Statuses:** generating shows a blinking caret after the text and a Stop button in place of Ask;
  before the first token, "Searching your documents…" [C]. Interrupted: "Stopped. This answer is
  incomplete." Failed: the error text plus "Try again" when retryable. Complete with no valid
  citation: "No sources were cited. Treat this answer with caution." Unmatched markers: "Some
  citation markers could not be matched to sources."
- **Under a complete answer:** "Sources from 2 documents" (distinct `document_name`s among cited
  sources; the API does not return a turn's selection after reload) [C].

### 6.5 Evidence panel

- Heading "Evidence", then "For “<question, truncated to one line>”".
- One entry per **cited** source in label order: `[n]`, "**file.pdf**, page 4" (or "pages 9–10" via
  `formatPages` reworded to full words [C]), the quote in Source Serif 4. The quote of the citation
  last activated gets the highlighter; by default the first one.
- "N more passages were read but not cited" as a collapsed `<details>` with the uncited sources,
  visually quieter (spec §7.5).
- Panel states: no turns — "Evidence for each answer appears here."; active turn generating —
  "Sources appear when the answer is finished." (the server sends validated sources only at the
  end); interrupted or failed — "No evidence for an incomplete answer."; complete without sources —
  the caution text.

### 6.6 Header

"Source**haven**" wordmark (the second half in `--prussian`) and the retention note "Files and
answers are deleted 24 hours after your last activity." (spec §10: 24 h idle expiry) [C].

### 6.7 Unchanged behaviour to preserve

Session start, document polling every 2 s only while something is in progress (no overlapping
requests, merge rather than replace), conversation id kept in `sessionStorage` and restored on
reload, request ids per question, Stop via `AbortController`, error-code texts, the `ApiError`
contract in `src/lib/api.ts`.

## 7. Code structure

`src/app/app/page.tsx` (488 lines today) becomes a thin composition [C; names B]:

```
src/app/app/
  page.tsx                  # composes the hooks and the three columns
  page.module.css
src/components/             # presentational; each with its own .module.css
  app-header.tsx
  documents/  drop-tray.tsx, document-list.tsx, document-row.tsx, select-all.tsx, drop-overlay.tsx
  conversation/  turn-view.tsx, answer-markdown.tsx, citation-button.tsx, composer.tsx, empty-state.tsx
  evidence/  evidence-panel.tsx, evidence-item.tsx, evidence-drawer.tsx
src/lib/
  api.ts                    # + uploadDocumentWithProgress (XMLHttpRequest)
  use-session.ts, use-documents.ts, use-conversation.ts   # state and effects moved out of page.tsx
  upload-checks.ts          # pure client pre-checks
  citations.ts              # display label, remark plugin (or kept in format.ts) [B]
```

- Every component has an explicit return type (`ReactElement`), matching the project's typing rule.
- No inline `style` attributes in rendered markup (M6's CSP will restrict `style-src`); progress uses
  `<progress>`, widths come from classes or CSS variables set through the CSSOM [C].
- `globals.css` keeps resets, tokens and font-family setup only.

## 8. Backend compatibility (verified 2026-11-20)

- `QuestionRequest.document_ids: list[UUID] = Field(min_length=1)`; the route caps it at
  `max_documents_per_question = 10`; `max_documents_per_session = 10`, so "use all" always fits.
- `QaService._check_scope` rejects unknown, foreign or not-ready documents (`document_not_ready`).
- `GET /api/documents` gives `state`, `progress {stage, done, total}`, `page_count`, `error_code`.
  Ingestion stages are `embedding` and `publishing`.
- `TurnResponse` has no selected-document field, hence §6.4's "Sources from N documents".
- No change to `openapi.json` or `src/lib/api-types.ts` is expected; CI's stale-types check must stay
  green.

## 9. Dependencies

| Package | Kind | Why |
|---|---|---|
| `react-markdown` 10.1 | runtime | safe Markdown rendering (spec §7.3) |
| `@fontsource-variable/atkinson-hyperlegible-next` 5.3 | runtime (CSS/fonts) | interface font |
| `@fontsource-variable/source-serif-4` 5.3 | runtime (CSS/fonts) | evidence font |
| `jsdom`, `@testing-library/react`, `@testing-library/user-event` | dev | component tests (§10) [C] |

Versions are pinned through `package-lock.json`; exact ranges [B]. Builder verifies React 19.3 /
Next 16.4 compatibility of each at install time.

## 10. Testing and verification

- **Unit (Vitest, node):** upload pre-checks; citation display labels and the remark plugin
  (markers in text vs code, unknown labels stay text); progress text mapping; selection tri-state
  logic; Markdown safety (raw HTML not rendered, links as text, images not loaded).
- **Component (Vitest + jsdom + Testing Library)** [C]: drop overlay appears only for file drags and
  uploads dropped PDFs; rejected files get their reason without a request; citation click activates
  the turn and marks the right evidence item; "Use all ready documents" toggles and shows mixed
  state; composer scope line and disabled Ask.
- Existing `format.test.ts` and `sse.test.ts` keep passing; the include glob extends to `*.test.tsx`.
- **Checks:** `npm run lint`, `typecheck`, `test`, `build` in `frontend/`, and
  `uv run pre-commit run --all-files` before every commit.
- **Rich answers in tests:** Markdown lists, several citations, evidence from two documents and
  uncited passages are covered by unit and component tests with fixture `TurnEvent`s and
  `Conversation` objects. The offline fake generator (one plain sentence, one `[S1]`) is not changed
  (§1.2), and no frontend mock mode is added [C].
- **Visual check:** run the dev stack, upload the committed fixtures, and capture screenshots of: first
  visit, drag-over, uploading/indexing, an answer with evidence and an active citation, a stopped
  answer, the 1024 px drawer and a 390 px phone view. Screenshots go in the PR description, not the
  repo [C]. Realistic answers need the real generator: the owner's local `.env` already uses
  `SOURCEHAVEN_GENERATION_PROVIDER=openai`. **The owner runs this step** with their own key [O]; the
  builder prepares a short checklist of the states to capture and runs everything that needs no paid
  call (fake generator) itself.
- **Builder defaults** [C]: after a reload the latest turn is active; pending uploads count against
  the remaining document slots; `/`'s layout styles move from `globals.css` into its own module.

## 11. Left to the builder

Exact column widths and spacing scale; component and hook names; whether citation helpers live in
`format.ts` or a new module; final microcopy within the voice above (plain, sentence case, errors
say what happened and how to fix it); how the evidence panel scrolls to an item; the drawer's
open/close animation within the reduced-motion rule.
