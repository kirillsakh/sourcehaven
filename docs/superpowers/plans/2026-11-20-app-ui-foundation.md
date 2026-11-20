# `/app` UI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/app` into the approved "ink and highlighter" three-column screen with
drag-and-drop upload, labelled document selection, Markdown answers with `[n]` citations and an
evidence panel, without any backend change.

**Architecture:** State moves out of the 488-line `page.tsx` into three hooks (session, documents,
conversation) backed by pure, unit-tested helpers in `src/lib/`. Presentational components live in
`src/components/` with one CSS Module each; `globals.css` holds only resets, tokens and fonts. The
page composes hooks and components into a three-column grid that degrades to a `<dialog>` drawer
and a single column.

**Tech Stack:** Next.js 16.4 App Router, React 19.3, TypeScript strict, CSS Modules, `react-markdown`
10.1, Fontsource variable fonts, Vitest 5 (node + jsdom), Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-20-app-ui-foundation-design.md` (read it before any task;
section numbers below refer to it). Approved mockups: `docs/superpowers/specs/2026-11-20-app-ui-foundation-mockups/`.

## Global Constraints

- No backend, API, `openapi.json` or `src/lib/api-types.ts` change; CI's stale-types check stays green.
- Runtime dependencies added: exactly `react-markdown@10.1.0`,
  `@fontsource-variable/atkinson-hyperlegible-next@5.3.0`, `@fontsource-variable/source-serif-4@5.3.1`.
  Dev dependencies added: exactly `jsdom@31.0.1`, `@testing-library/react@16.3.3`,
  `@testing-library/dom@10.4.2`, `@testing-library/user-event@14.6.13`, `@types/mdast@4.0.4`. Nothing else.
  If npm reports `EPERM` on `~/.npm`, run it with `npm_config_cache="$TMPDIR/npm-cache"`.
- Tokens (spec §4.1), verbatim: `--paper #FFFFFF`, `--ink #1D2433`, `--graphite #4A5263`,
  `--rule #D9DDE5`, `--wash #F3F5F9`, `--prussian #1F4E8C`, `--highlighter #FFE774`, `--ok #1F7A4D`,
  `--warn #8A5A00`, `--bad #B42318`; evidence panel tint `#FBFCFD`. Dark set per §4.1 under
  `@media (prefers-color-scheme: dark)`.
- Type (§4.2): interface `"Atkinson Hyperlegible Next Variable"`, quotes `"Source Serif 4 Variable"`;
  answers 16.5px/1.7, max 64ch; interface 15px; **no text below 12.5px**; nothing lighter than
  `--graphite` for text.
- Components use only CSS variables for colour; no hex values outside `globals.css`.
- No inline `style` attributes in rendered markup (future CSP). Progress uses `<progress>`.
- Radius by role: composer 12px, tray 10px, buttons 8px, chips 4px. No box shadows, no gradients.
- Focus: `outline: 2px solid var(--prussian); outline-offset: 2px` on every interactive element.
- Motion only on user action; every transition/animation disabled under `prefers-reduced-motion: reduce`.
- Copy: sentence case, no all-caps labels, no `a · b · c` strings; write "annex-b.pdf, page 2".
- Citations display as `[n]` (strip the leading `S`); the model and server keep `[S n]` labels.
- Every component/hook/function has explicit parameter and return types (components return
  `ReactElement`, or `ReactElement | null`).
- Absolute imports via `@/…` only.
- Preserve M1 behaviour listed in spec §6.7.
- Per-task checks before every commit, from the repo root:
  `npm --prefix frontend run lint && npm --prefix frontend run typecheck && npm --prefix frontend test && npm --prefix frontend run build`
  then `uv run pre-commit run --all-files` (needs to run outside the sandbox for the uv cache).
  Commit messages: imperative sentence, no prefix, no AI attribution (e.g. "Add evidence panel").

## Review Focus

1. **Drag overlay sticking or flickering:** `dragenter`/`dragleave` fire for every child element; a
   drag cancelled with Escape or dropped outside the window must hide the overlay. Expect it to show
   once on file drag and hide on leave, drop, or `dragend`. → Task 6, `drop-overlay.test.tsx`.
2. **Dropping more PDFs than free slots:** with 9 of 10 used, dropping 3 PDFs should upload one and
   reject two with "This session can hold up to 10 documents." → Task 2 (`checkFiles`) and Task 4.
3. **Mixed drops:** a PDF, a PNG and an empty `.pdf` dropped together: the PDF uploads, the other two
   get their own rows with reasons, and no request is sent for them. → Task 2 and Task 6.
4. **Hostile answer text:** `<img src=x onerror=alert(1)>`, `![x](http://evil/x.png)`,
   `[click](javascript:alert(1))` and `` `[S1]` `` in an answer: no element with `src`, no `href`,
   the code span keeps the literal `[S1]`. → Task 3, `answer-markdown.test.tsx`.
5. **Very long unbroken file names** (120 characters, no spaces): wrap inside the documents column and
   the evidence panel, never widen the page. → Task 6 and Task 8 CSS (`overflow-wrap: anywhere`),
   checked in Task 9's visual pass at 390px.

---

## File structure

```
frontend/
  package.json, package-lock.json        # deps (Tasks 1, 3)
  vitest.config.mts                      # include *.test.tsx, setup file (Task 3)
  vitest.setup.ts                        # Testing Library cleanup (Task 3)
  src/app/
    globals.css                          # resets, tokens, fonts, focus (Task 1)
    layout.tsx                           # imports fonts (Task 1)
    page.tsx, page.module.css            # landing restyle, styles moved out of globals (Task 1)
    app/page.tsx, app/page.module.css    # composition and grid (Task 8, responsive Task 9)
    app/turn-view.tsx                    # deleted in Task 7 (moved to components)
  src/lib/
    api.ts                               # + uploadDocumentWithProgress (Task 4)
    format.ts                            # formatPages wording (Task 2)
    messages.ts                          # error and status texts (Task 2)
    upload-checks.ts                     # client pre-checks (Task 2)
    selection.ts                         # tri-state and scope line (Task 2)
    citations.ts                         # displayLabel, remarkCitations (Task 3)
    use-session.ts                       # (Task 4)
    use-documents.ts                     # (Task 4)
    use-conversation.ts                  # (Task 5)
  src/components/
    app-header.tsx                                   # (Task 8)
    documents/ drop-tray, document-row, document-list, select-all, drop-overlay, documents-panel (Task 6)
    conversation/ answer-markdown, citation-button (Task 3); turn-view, composer, empty-state, conversation-panel (Task 7)
    evidence/ evidence-item, evidence-panel (Task 8); evidence-drawer (Task 9)
```

Each component `x.tsx` has a sibling `x.module.css` where it needs styles, and its test `x.test.tsx`.

---

### Task 1: Visual foundation (tokens, fonts, landing page)

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`
- Modify: `frontend/src/app/globals.css` (rewrite), `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`
- Create: `frontend/src/app/page.module.css`

**Interfaces:**
- Produces: CSS custom properties from Global Constraints on `:root`; `--font-ui`,
  `--font-quote`; utility class `visually-hidden` (kept global, used by later tasks).

- [ ] **Step 1: Install the fonts**

Run: `npm --prefix frontend install @fontsource-variable/atkinson-hyperlegible-next@5.3.0 @fontsource-variable/source-serif-4@5.3.1 --save-exact`
Expected: both appear in `dependencies`.

- [ ] **Step 2: Rewrite `globals.css`** with: box-sizing reset; tokens (light + dark); `--font-ui:
  "Atkinson Hyperlegible Next Variable", ui-sans-serif, system-ui, sans-serif`; `--font-quote:
  "Source Serif 4 Variable", Georgia, serif`; `body { font: 15px/1.55 var(--font-ui); color: var(--ink);
  background: var(--paper); margin: 0 }`; `button, input, textarea { font: inherit; color: inherit }`;
  the focus rule; `.visually-hidden`; the reduced-motion rule
  (`*, *::before, *::after { transition: none !important; animation: none !important }` inside the
  media query). Remove every M1 component class (`.shell`, `.layout`, `.badge`, …) except what
  `app/app/page.tsx` still needs until Task 8: keep those M1 classes in a clearly marked block at
  the end, deleted in Task 8.

- [ ] **Step 3: Import fonts in `layout.tsx`** (`import "@fontsource-variable/atkinson-hyperlegible-next";`
  and `import "@fontsource-variable/source-serif-4";` before `./globals.css`) and give `RootLayout`
  an explicit `ReactElement` return type.

- [ ] **Step 4: Restyle `/`** with `page.module.css`: centred column max 40rem, wordmark "Source"
  + "haven" (second part `--prussian`, weight 700), the existing two sentences (content unchanged),
  the link styled as a primary button ("Open the app"). No new copy.

- [ ] **Step 5: Run checks** — the per-task command line in Global Constraints. Expected: all pass;
  `next build` lists `/` and `/app`.

- [ ] **Step 6: Commit** — `git add frontend/package.json frontend/package-lock.json frontend/src/app/globals.css frontend/src/app/layout.tsx frontend/src/app/page.tsx frontend/src/app/page.module.css`;
  message "Add visual tokens and bundled fonts".

---

### Task 2: Pure helpers for messages, statuses, upload checks and selection

**Files:**
- Create: `frontend/src/lib/messages.ts`, `messages.test.ts`
- Create: `frontend/src/lib/upload-checks.ts`, `upload-checks.test.ts`
- Create: `frontend/src/lib/selection.ts`, `selection.test.ts`
- Modify: `frontend/src/lib/format.ts`, `format.test.ts`

**Interfaces:**
- Consumes: `DocumentInfo`, `SessionLimits`, `ApiError` from `@/lib/api`.
- Produces:
  - `describeError(error: unknown): string` (moved from `page.tsx`, texts below)
  - `describeIngestionError(code: string | null): string`
  - `type StatusTone = "ok" | "warn" | "bad"`
  - `interface DocumentStatus { word: string; tone: StatusTone; detail: string | null; progress: { value: number; max: number } | null }`
  - `documentStatus(document: DocumentInfo): DocumentStatus`
  - `type FileCheck = { file: File; ok: true } | { file: File; ok: false; reason: string }`
  - `checkFiles(files: readonly File[], limits: SessionLimits, usedSlots: number): FileCheck[]`
  - `type SelectAllState = "all" | "some" | "none"`
  - `selectAllState(documents: readonly DocumentInfo[], selected: ReadonlySet<string>): SelectAllState`
  - `readySelectedIds(documents: readonly DocumentInfo[], selected: ReadonlySet<string>): string[]`
  - `scopeLine(readySelected: number, readyTotal: number): string`
  - `formatPages(start: number, end: number): string` now returns `"page 4"` / `"pages 9–10"`

- [ ] **Step 1: Write failing tests.** Key assertions (exact copy):

```ts
// messages.test.ts
expect(describeError(new ApiError(413, "too_large"))).toBe("Files can be up to 20 MB. Try splitting or compressing the PDF.");
expect(describeError(new ApiError(415, "unsupported_type"))).toBe("Only PDF files are supported right now.");
expect(describeError(new ApiError(422, "empty_file"))).toBe("This file is empty.");
expect(describeError(new ApiError(409, "session_document_limit"))).toBe("This session can hold up to 10 documents.");
expect(describeError(new ApiError(401, "session_required"))).toBe("Your session has expired. Reload the page to start a new one.");
expect(describeError(new ApiError(500, "mystery"))).toBe("Something went wrong. Try again.");
// unknown code with a server message: show the message (spec §11.3, busy/limit messages)
expect(describeError(new ApiError(422, "invalid_request", "question: too long"))).toBe("question: too long");
expect(describeError(new TypeError("x"))).toBe("The request failed. Check your connection and try again.");
expect(describeIngestionError("encrypted")).toBe("This PDF is password-protected. Remove the password and upload it again.");
expect(describeIngestionError("damaged")).toBe("We couldn't read this PDF; it may be damaged. Re-export or re-save it and try again.");
expect(describeIngestionError("too_many_pages")).toBe("PDFs can have up to 300 pages. Try splitting it.");
expect(describeIngestionError("empty")).toBe("We couldn't find any text in this PDF.");
expect(describeIngestionError("embedding_unavailable")).toBe("Processing is temporarily unavailable. Try again later.");
expect(describeIngestionError("internal")).toBe("Something went wrong while processing this file.");
expect(describeIngestionError(null)).toBe("Something went wrong while processing this file.");
expect(documentStatus(doc({ state: "queued" }))).toEqual({ word: "Queued", tone: "warn", detail: null, progress: null });
expect(documentStatus(doc({ state: "processing", progress: { stage: "embedding", done: 18, total: 30 } })))
  .toEqual({ word: "Indexing", tone: "warn", detail: "60%", progress: { value: 18, max: 30 } });
expect(documentStatus(doc({ state: "processing", progress: { stage: "publishing", done: 30, total: 30 } })).word).toBe("Finishing");
expect(documentStatus(doc({ state: "ready", page_count: 14 }))).toEqual({ word: "Ready", tone: "ok", detail: "14 pages", progress: null });
expect(documentStatus(doc({ state: "ready", page_count: 1 })).detail).toBe("1 page");
expect(documentStatus(doc({ state: "failed", error_code: "encrypted" })).tone).toBe("bad");
```

  Keep the existing texts for `document_not_ready`, `turn_in_progress`, `duplicate_request`. The
  `embedding_unavailable` deliberately differs from parent spec §6.3 ("We'll retry automatically"):
  the UI only sees it after retries are exhausted. The "10" and "20 MB" in limit texts come from `SessionLimits` where the function receives them;
  `describeError` uses the spec defaults because it has no limits (acceptable: limits are fixed
  settings in this release).

```ts
// upload-checks.test.ts — limits: max_upload_bytes 20 MiB, max_documents 10
const results = checkFiles([pdf("a.pdf"), png("b.png"), pdf("c.pdf", 0)], limits, 2);
expect(results.map((r) => r.ok)).toEqual([true, false, false]);
expect(results[1]).toMatchObject({ ok: false, reason: "Only PDF files are supported right now." });
expect(results[2]).toMatchObject({ ok: false, reason: "This file is empty." });
// accepted by extension when the browser reports no MIME type
expect(checkFiles([file("x.PDF", "")], limits, 0)[0].ok).toBe(true);
// size
expect(checkFiles([pdf("big.pdf", 20 * 1024 * 1024 + 1)], limits, 0)[0]).toMatchObject({ ok: false, reason: "Files can be up to 20 MB. Try splitting or compressing the PDF." });
// slots: 9 used, 3 PDFs → first ok, the rest rejected; invalid files do not consume slots
expect(checkFiles([pdf("1.pdf"), png("x.png"), pdf("2.pdf"), pdf("3.pdf")], limits, 9).map((r) => r.ok)).toEqual([true, false, false, false]);
expect(checkFiles([pdf("1.pdf"), pdf("2.pdf")], limits, 9)[1]).toMatchObject({ reason: "This session can hold up to 10 documents." });
```

```ts
// selection.test.ts
expect(selectAllState([ready("a"), ready("b"), processing("c")], new Set(["a", "b"]))).toBe("all");
expect(selectAllState([ready("a"), ready("b")], new Set(["a"]))).toBe("some");
expect(selectAllState([ready("a")], new Set())).toBe("none");
expect(selectAllState([processing("c")], new Set())).toBe("none");
expect(readySelectedIds([ready("a"), processing("c")], new Set(["a", "c"]))).toEqual(["a"]);
expect(scopeLine(2, 3)).toBe("Answering from 2 of 3 documents");
expect(scopeLine(1, 1)).toBe("Answering from 1 of 1 document");
expect(scopeLine(0, 3)).toBe("Select at least one ready document to ask a question.");
expect(scopeLine(0, 0)).toBe("Add a PDF to ask a question.");
// format.test.ts (updated)
expect(formatPages(4, 4)).toBe("page 4");
expect(formatPages(9, 10)).toBe("pages 9–10");
```

- [ ] **Step 2: Run** `npm --prefix frontend test` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement** the four modules. PDF check: MIME `application/pdf` **or** name ending
  `.pdf` case-insensitively. Size: `file.size > limits.max_upload_bytes`. Empty: `size === 0`
  (checked before size). Slots: count accepted files; reject once `usedSlots + accepted >= max_documents`.
  Percent: `Math.round(done / max(total, 1) * 100)`.

- [ ] **Step 4: Run** `npm --prefix frontend test` — Expected: PASS.

- [ ] **Step 5: Checks + commit** — message "Add message, upload-check and selection helpers".
  (`page.tsx` keeps compiling: it still has its own `describeError` until Task 8, or import the new
  one now — either is fine as long as checks pass.)

---

### Task 3: Markdown answers with `[n]` citation buttons

**Files:**
- Modify: `frontend/package.json`, `package-lock.json`, `frontend/vitest.config.mts`
- Create: `frontend/vitest.setup.ts`
- Create: `frontend/src/lib/citations.ts`, `citations.test.ts`
- Create: `frontend/src/components/conversation/citation-button.tsx`, `citation-button.module.css`
- Create: `frontend/src/components/conversation/answer-markdown.tsx`, `answer-markdown.module.css`, `answer-markdown.test.tsx`

**Interfaces:**
- Produces:
  - `displayLabel(label: string): string` — `"S3"` → `"3"`; anything not matching `/^S\d+$/` unchanged.
  - `remarkCitations(options: { knownLabels: ReadonlySet<string> }): (tree: Root) => void` — a remark
    plugin (types from `mdast`) that splits text nodes on `/\[(S\d+)\]/g`; known labels become
    citation nodes rendered through `components`, unknown ones become plain-text "unmatched" nodes;
    `inlineCode` and `code` nodes are untouched.
  - `CitationButton(props: { label: string; active: boolean; onActivate: (label: string) => void }): ReactElement`
    — `<button type="button" aria-pressed={active} aria-label={`Source ${displayLabel(label)}`}>[{displayLabel(label)}]</button>`.
  - `AnswerMarkdown(props: { text: string; knownLabels: ReadonlySet<string>; activeLabel: string | null; onCitation: (label: string) => void }): ReactElement`

- [ ] **Step 1: Install test tooling and Markdown**

Run: `npm --prefix frontend install react-markdown@10.1.0 --save-exact` and
`npm --prefix frontend install -D jsdom@31.0.1 @testing-library/react@16.3.3 @testing-library/dom@10.4.2 @testing-library/user-event@14.6.13 @types/mdast@4.0.4 --save-exact`.

- [ ] **Step 2: Configure Vitest:** `include: ["src/**/*.test.ts", "src/**/*.test.tsx"]`,
  `setupFiles: ["./vitest.setup.ts"]` (calls `cleanup` from Testing Library `afterEach`). Component
  tests opt into jsdom with a first-line `// @vitest-environment jsdom` comment; existing tests stay
  on `node`. Confirm with `npm --prefix frontend test` (existing tests pass).

- [ ] **Step 3: Write failing tests**

```ts
// citations.test.ts
expect(displayLabel("S3")).toBe("3");
expect(displayLabel("X1")).toBe("X1");
```

```tsx
// answer-markdown.test.tsx (jsdom)
it("renders Markdown structure", …): render "**three months**\n\n- one [S1]\n- two [S2]" with known {S1,S2}
  → a <strong> "three months", two <li>, buttons named "Source 1" and "Source 2" with text "[1]" / "[2]".
it("calls onCitation with the server label", …): click "Source 2" → onCitation called with "S2".
it("marks the active citation", …): activeLabel "S1" → "Source 1" has aria-pressed="true".
it("shows unknown markers as plain [n] text", …): "see [S9]" known {S1} → no button; text "[9]" present; never the text "S9".
it("keeps markers in code literal", …): "`[S1]`" known {S1} → <code> text "[S1]", no button.
it("does not render raw HTML, images or links", …):
  text `<img src=x onerror=alert(1)> ![pic](http://evil.test/x.png) [click](javascript:alert(1)) [site](https://example.com)`
  → container.querySelector("img, script, a, [src], [href]") is null; text "click" and "site" visible; alt text "pic" visible.
```

- [ ] **Step 4: Run** `npm --prefix frontend test` — Expected: FAIL.

- [ ] **Step 5: Implement.** `AnswerMarkdown` uses `<Markdown remarkPlugins={[[remarkCitations, { knownLabels }]]} skipHtml components={…}>`;
  `a` renders its children in a `<span>`; `img` renders its `alt` as text. Connect citation nodes to
  React through mdast `data.hName`/`data.hProperties` and a matching `components` entry — verify the
  mechanism against react-markdown 10 / mdast-util-to-hast 13 behaviour with the tests; do not
  guess. Styles: answer 16.5px/1.7, `max-width: 64ch`, `overflow-wrap: anywhere`; citation button
  per spec §6.4 (no border, `--prussian`, 700, 13px, `vertical-align: 1px`, hover/focus/`[aria-pressed=true]`
  background `--highlighter`, colour `--ink`); unmatched marker `--graphite`.

- [ ] **Step 6: Run** tests — Expected: PASS. **Checks + commit** — "Render answers as Markdown with numbered citations".

---

### Task 4: Session and documents state with upload progress

**Files:**
- Modify: `frontend/src/lib/api.ts`; Create: `frontend/src/lib/api-upload.test.ts`
- Create: `frontend/src/lib/use-session.ts`, `frontend/src/lib/use-documents.ts`, `use-documents.test.tsx`

**Interfaces:**
- Consumes: Task 2 helpers.
- Produces:
  - `uploadDocumentWithProgress(file: File, onProgress: (fraction: number) => void, createRequest?: () => XMLHttpRequest): Promise<DocumentInfo>`
    — `POST /api/documents`, multipart field `file`, `withCredentials` same-origin; resolves with the
    parsed body on 2xx; rejects with `ApiError(status, code, message)` parsed like `toApiError`; network
    error → `TypeError("Network error")`. `createRequest` is the test seam (default `() => new XMLHttpRequest()`).
  - `useSession(): { limits: SessionLimits | null; error: string | null }` — calls `createSession`
    once (guard against React strict double effects, as today).
  - `type UploadRow = { key: string; name: string; status: "uploading"; fraction: number } | { key: string; name: string; status: "rejected"; reason: string }`
  - `useDocuments(limits: SessionLimits | null): { documents: DocumentInfo[]; uploads: UploadRow[]; selected: ReadonlySet<string>; pollError: string | null; addFiles: (files: readonly File[]) => void; dismissUpload: (key: string) => void; toggle: (id: string) => void; setAllSelected: (all: boolean) => void }`
    — initial `listDocuments` once `limits` is set; polling every 2000 ms only while any document is
    queued/processing, never overlapping, merge not replace (copy the M1 logic); `addFiles` runs
    `checkFiles` with `usedSlots = documents.length + uploading rows`, creates `rejected` rows for
    failures and `uploading` rows for the rest, uploads at most 3 in parallel; on success the row is
    removed and the document merged (a duplicate returns an existing id: merge, no error); on failure
    the row becomes `rejected` with `describeError`; newly ready documents are auto-selected; a
    `session_required` poll error sets `pollError` and stops polling, and `pollError` clears on the
    next successful list.

- [ ] **Step 1: Failing tests.** `api-upload.test.ts` with a fake request object: progress events
  call `onProgress(0.5)`; status 201 resolves the parsed document; status 413 with
  `{"code":"too_large"}` rejects with `ApiError` code `too_large`; `onerror` rejects with `TypeError`.
  `use-documents.test.tsx` (jsdom, `vi.mock("@/lib/api")`, fake timers):
  - dropping `[a.pdf, b.png]` creates one uploading row and one rejected row; `uploadDocumentWithProgress` called once;
  - 9 documents + 3 PDFs → one upload, two rejected rows with the limit text;
  - 5 files → never more than 3 uploads in flight;
  - a successful upload removes its row and lists the document;
  - polling calls `listDocuments` again after 2000 ms while one is processing and stops when all are ready;
  - a document turning ready is added to `selected`; `setAllSelected(false)` empties it; `setAllSelected(true)` selects every ready id only;
  - a `session_required` poll error sets `pollError`; a later successful list clears it.

- [ ] **Step 2: Run** — Expected: FAIL. **Step 3: Implement.** **Step 4: Run** — Expected: PASS.

- [ ] **Step 5: Checks + commit** — "Add documents state with upload progress".

---

### Task 5: Conversation state with an active turn

**Files:**
- Create: `frontend/src/lib/use-conversation.ts`, `use-conversation.test.tsx`

**Interfaces:**
- Produces:
  - `interface TurnViewModel` (as M1's, plus `progressStage: string | null`)
  - `useConversation(limits: SessionLimits | null): { turns: TurnViewModel[]; generating: boolean; askError: string | null; question: string; setQuestion: (text: string) => void; ask: (text: string, documentIds: string[]) => Promise<void>; stop: () => void; activeTurnKey: string | null; activeLabel: string | null; activate: (turnKey: string, label?: string) => void }`
  - Behaviour copied from M1 `page.tsx` (`turnsFromConversation`, `applyEvent`, restore from
    `sessionStorage` key `sourcehaven.conversation`, `ApiError` before streaming removes the turn and
    restores the question, interruption texts). New: `progress` events set `progressStage`; a new
    question becomes active with `activeLabel = null`; restore makes the latest turn active;
    `activate(key, label)` sets both; when a turn's `sources` arrive while it is active and
    `activeLabel` is null, `activeLabel` becomes its first cited label. Interrupted text: "Stopped.
    This answer is incomplete."

- [ ] **Step 1: Failing tests** (jsdom, `vi.mock("@/lib/api")`, `streamQuestion` returns an async
  generator of fixture events):
  - asking appends a turn, streams deltas into `text`, ends `complete`, and it is the active turn;
  - `sources` with cited S1, S2 → `activeLabel` "S1"; `activate(key, "S2")` → "S2";
  - stopping mid-stream → status `interrupted`, `errorMessage` "Stopped. This answer is incomplete.";
  - `createConversation` rejecting with `ApiError("turn_in_progress")` → no turn, `askError` set, question restored;
  - a stored conversation id is restored and its last turn is active.
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: Checks + commit** — "Add conversation state with active turn".

---

### Task 6: Documents column and drag-and-drop

**Files:**
- Create in `frontend/src/components/documents/`: `drop-tray.tsx`, `document-row.tsx`,
  `document-list.tsx`, `select-all.tsx`, `drop-overlay.tsx`, `documents-panel.tsx` (+ `.module.css`
  each as needed), tests `documents-panel.test.tsx`, `drop-overlay.test.tsx`.

**Interfaces:**
- Consumes: Task 2 `documentStatus`, `describeIngestionError`, `selectAllState`; Task 4 `UploadRow`.
- Produces:
  - `DocumentsPanel(props: { limits: SessionLimits | null; documents: DocumentInfo[]; uploads: UploadRow[]; selected: ReadonlySet<string>; onFiles: (files: File[]) => void; onToggle: (id: string) => void; onSelectAll: (all: boolean) => void; onDismissUpload: (key: string) => void; listRef?: Ref<HTMLUListElement> }): ReactElement`
  - `DropTray(props: { limits: SessionLimits | null; disabled: boolean; onFiles: (files: File[]) => void; large?: boolean }): ReactElement`
    — "Drop PDFs here" / "or choose files. Up to 20 MB and 300 pages each." (numbers from limits:
    `Math.round(max_upload_bytes / 1048576)`, `max_pages_per_document`); "choose files" is a
    `<button>` that clicks a visually hidden `<input type="file" accept="application/pdf,.pdf" multiple>`.
    `large` is the empty-state variant used by Task 7.
  - `DropOverlay(props: { enabled: boolean; onFiles: (files: File[]) => void }): ReactElement | null`
    — listens on `window` for `dragenter`/`dragover`/`dragleave`/`drop`/`dragend`; only drags whose
    `dataTransfer.types` include `"Files"` count; a depth counter avoids child flicker; shows
    "Drop to upload N PDFs" (N = `dataTransfer.items.length` when > 0, else "Drop to upload PDFs")
    and the limits line; `preventDefault` on `dragover`/`drop` so the browser never opens the PDF.
- Headings and copy: "Your documents" + "3 of 10"; select-all row "Use all ready documents"
  (checkbox `indeterminate` set via ref when `"some"`, disabled with no ready documents); status
  word in tone colour, detail in `--graphite`, `<progress>` for in-progress; failed rows show the
  `describeIngestionError` text; rejected upload rows show the reason and a "Dismiss" button;
  uploading rows "Uploading 45%". File names `overflow-wrap: anywhere`.

- [ ] **Step 1: Failing tests:**
  - panel lists rows with "Ready" + "14 pages", "Indexing" + "60%", the failed text for `encrypted`;
  - checkbox of a processing document is disabled; clicking a ready one calls `onToggle(id)`;
  - "Use all ready documents" is checked for "all", `indeterminate` for "some", calls `onSelectAll(false)` / `(true)`;
  - choosing files through the hidden input calls `onFiles` with them;
  - overlay: a `dragenter` with types `["Files"]` shows "Drop to upload 2 PDFs"; `dragenter` on a child + `dragleave` on another child keeps it; final `dragleave` hides it; `dragend` hides it; a drag with types `["text/plain"]` never shows it; `drop` calls `onFiles` and hides it.
  (Build events with `new Event("dragenter", { bubbles: true })` and assign a `dataTransfer` stub via `Object.defineProperty`; jsdom has no `DataTransfer`.)
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: Checks + commit** — "Add documents column with drag-and-drop upload".

---

### Task 7: Conversation column

**Files:**
- Create in `frontend/src/components/conversation/`: `turn-view.tsx`, `composer.tsx`,
  `empty-state.tsx`, `conversation-panel.tsx` (+ css), tests `turn-view.test.tsx`, `composer.test.tsx`.
- Delete: `frontend/src/app/app/turn-view.tsx` (`git rm`).

**Interfaces:**
- Consumes: Task 3 `AnswerMarkdown`; Task 5 `TurnViewModel`; Task 2 `scopeLine`.
- Produces:
  - `TurnView(props: { turn: TurnViewModel; active: boolean; activeLabel: string | null; onActivate: (turnKey: string, label?: string) => void; onRetry: (question: string) => void; onShowEvidence: () => void }): ReactElement`
  - `Composer(props: { question: string; maxChars: number; generating: boolean; readySelected: number; readyTotal: number; error: string | null; onChange: (text: string) => void; onAsk: () => void; onStop: () => void; onScopeClick: () => void }): ReactElement`
    — Enter submits, Shift+Enter inserts a newline; Ask disabled when the question is blank, nothing
    is selected, or generating; Stop replaces Ask while generating; the scope line is a `<button>`
    with `scopeLine(...)` text that calls `onScopeClick`.
  - `EmptyState(props: { limits: SessionLimits | null; onFiles: (files: File[]) => void }): ReactElement`
    — "Ask questions about your PDFs", "Every answer shows the passages it came from.", `DropTray large`.
  - `ConversationPanel(props: { … composes the above … })` [builder names the props]. With ready
    documents but no turns it shows one hint line above the composer: "Ask something about
    contract.pdf" (one ready document) or "Ask something about your 3 documents".
- TurnView copy (spec §6.4): before the first delta "Searching your documents…"; caret while
  generating; failed: message + "Try again" if retryable; complete with no cited source: "No sources
  were cited. Treat this answer with caution."; invalid labels: "Some citation markers could not be
  matched to sources."; complete with sources: "Sources from N documents" (distinct `document_name`
  of cited sources; "1 document") followed by a "Show evidence" button (hidden by CSS at ≥1280px,
  calls `onShowEvidence`). Non-active turns use `--graphite` text; the active turn gets a `--rule`
  border and `#FBFCFD`-token background. Clicking anywhere in a non-active turn activates it.

- [ ] **Step 1: Failing tests:** generating turn with no text shows "Searching your documents…";
  complete turn with cited S1/S2 from two documents shows "Sources from 2 documents"; clicking `[2]`
  calls `onActivate(key, "S2")`; failed retryable turn's "Try again" calls `onRetry(question)`;
  composer: Enter calls `onAsk`, Shift+Enter does not; Ask disabled with `readySelected` 0 and the
  scope line reads "Select at least one ready document to ask a question."; generating shows "Stop".
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: Checks + commit** — "Add conversation column".

---

### Task 8: Evidence panel and page composition

**Files:**
- Create: `frontend/src/components/evidence/evidence-item.tsx`, `evidence-panel.tsx` (+ css), `evidence-panel.test.tsx`
- Create: `frontend/src/components/app-header.tsx` (+ css)
- Modify (rewrite): `frontend/src/app/app/page.tsx`; Create: `frontend/src/app/app/page.module.css`, `frontend/src/app/app/page.test.tsx`
- Modify: `frontend/src/app/globals.css` (delete the M1 block left in Task 1)

**Interfaces:**
- Consumes: Tasks 4–7.
- Produces:
  - `EvidencePanel(props: { turn: TurnViewModel | null; activeLabel: string | null; onActivate: (label: string) => void }): ReactElement`
    — heading "Evidence"; "For “…”" (question, one line, ellipsis via CSS); cited sources in label
    order as `EvidenceItem`; `<details>` "N more passages were read but not cited" with the uncited
    ones; empty states per spec §6.5 ("Evidence for each answer appears here.", "Sources appear when
    the answer is finished.", "No evidence for an incomplete answer.", the caution text). The active
    item's quote gets class `highlighted` (highlighter sweep via `background-size` 0→100%, 350ms) and
    is scrolled into view (`scrollIntoView({ block: "nearest" })`, guarded for jsdom).
  - `EvidenceItem(props: { source: TurnSource; active: boolean; onActivate: (label: string) => void }): ReactElement`
    — `[n]`, "**file.pdf**, page 4" (via `formatPages`), quote in `--font-quote` within curly quotes.
  - `AppHeader(): ReactElement` — wordmark and "Files and answers are deleted 24 hours after your last activity."
  - `page.tsx`: three-column grid (`260px minmax(0, 1fr) 340px` at ≥1280px), each column scrolls on
    its own, composer pinned at the conversation column's bottom; renders `DropOverlay` (enabled once
    limits are known and slots remain); session start error replaces the grid with the header and
    an alert. The scope-line click focuses the first checkbox in the documents list.

- [ ] **Step 1: Failing tests:** panel shows "[1]" "[2]" items with "employment-contract.pdf, page 4";
  the item for `activeLabel` has the highlighted class; uncited count text; the three empty-state
  texts by turn status. `page.test.tsx` (all of `@/lib/api` mocked): after a streamed answer with two
  cited sources, clicking `[2]` in the answer marks evidence item 2 highlighted; with no documents
  the empty state's "Ask questions about your PDFs" is shown.
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: Checks + commit** — "Add evidence panel and three-column app screen".

---

### Task 9: Narrow screens, drawer and visual pass

**Files:**
- Create: `frontend/src/components/evidence/evidence-drawer.tsx` (+ css), `evidence-drawer.test.tsx`
- Modify: `frontend/src/app/app/page.tsx`, `page.module.css`, `documents-panel.tsx`
- Modify: `README.md` (Frontend section)

**Interfaces:**
- Produces:
  - `EvidenceDrawer(props: { open: boolean; onClose: () => void; children: ReactNode }): ReactElement`
    — native `<dialog>` opened with `showModal()` when `open` becomes true, closed with Escape, the
    close button ("Close evidence") or a backdrop click; returns focus to the opener (dialog default).
  - Layout: 800–1279px two columns, the evidence aside hidden, citations and "Show evidence" open the
    drawer (decide with `window.matchMedia("(min-width: 1280px)").matches` at activation time);
    <800px one column, documents become a `<details>` "Your documents, 3 of 10" at the top (open
    while there are no documents; the scope-line click opens it before focusing the first
    checkbox), the drawer becomes a full-screen sheet. No horizontal scroll.
- [ ] **Step 1: Failing tests:** with `matchMedia` stubbed to not match, activating a citation opens
  the dialog (`showModal` called — stub it on `HTMLDialogElement.prototype` since jsdom lacks it);
  "Close evidence" calls `onClose`; with `matchMedia` matching, no dialog opens.
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS).
- [ ] **Step 5: Visual pass (fake generator, no paid calls).** Start the dev stack as the README
  describes with `SOURCEHAVEN_GENERATION_PROVIDER=fake` overriding the local `.env` for this run;
  upload `tests/fixtures/documents/facts_small_en.pdf` and `multipage_en.pdf`, ask a question, and
  check at 1440, 1024 and 390px: first visit, drag-over, uploading/indexing, answer + evidence +
  active citation, a stopped answer, drawer, phone layout, a 120-character file name. Fix what
  is off. Record anything that needs the owner's eyes.
- [ ] **Step 6: README** — Frontend section: one paragraph on the layout and where styles live
  (`globals.css` tokens, CSS Modules per component), and that component tests run under jsdom.
- [ ] **Step 7: Checks + commit** — "Add evidence drawer and narrow-screen layouts".

---

### After the tasks (controller, not a task)

- Whole-branch review; fix Critical/Important findings.
- Update `docs/superpowers/checkpoints/` with a short UI-foundation checkpoint (what shipped, calls made, deferred items).
- Prepare the owner's screenshot checklist (spec §10 list) for the PR description.
- Ask the owner before pushing `ui/app-foundation` and opening the PR.
