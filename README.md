# Sourcehaven

A web application for asking grounded, cited questions about your own documents.

Anonymous visitors upload PDFs, a worker ingests them into Postgres with pgvector, and questions
are answered with streamed text and validated page citations. Each visitor's data is isolated by the
application and by row-level security.

Status: milestones M0 (skeleton and packaging) and M1 (end-to-end slice) are complete. See
`docs/superpowers/specs/` for the design, `docs/superpowers/plans/` for the plan and
`docs/superpowers/checkpoints/2026-11-20-m1-complete.md` for what was delivered and what is deferred.

## Setup

Requirements: Python 3.14, [uv](https://docs.astral.sh/uv/) 0.9.x, Docker with Compose (for the
integration tests and the dev stack) and Node 24 (frontend only).

```sh
uv sync                          # creates .venv with an editable install and the dev tools
uv run pre-commit install
uv run pre-commit run --all-files
```

## Tests

```sh
uv run pytest                    # unit tests; offline
uv run pytest -m integration     # needs the Compose db service (see below); no network, no API calls
npm --prefix frontend test       # frontend unit tests
bash scripts/check-package.sh    # builds the wheel and sdist, installs the wheel outside the checkout
```

Ordinary `pytest` runs exclude the `integration` (needs Compose Postgres) and `live` (paid providers)
markers. Integration tests create a throwaway database on the dev stack's Postgres
(`docker compose -f compose.yaml -f compose.dev.yaml up -d db`); they use the hash embedder and the
fake chat model. Cross-visitor isolation is covered by `tests/integration/test_isolation.py`.

Database roles are cluster-wide, so migrating the throwaway database also sets the passwords of the
`sourcehaven_app` and `sourcehaven_maintenance` roles that the running dev stack logs in with. The
tests take them from `SOURCEHAVEN_APP_ROLE_PASSWORD` and `SOURCEHAVEN_MAINTENANCE_ROLE_PASSWORD`
(default `devpassword`), and the Postgres superuser password from `POSTGRES_PASSWORD` (same
default) or a full URL in `SOURCEHAVEN_TEST_ADMIN_URL`; they do not read `.env`. If your `.env`
uses other values, export the same values before running the integration tests, or the dev stack's
api and worker can no longer log in.

## Development stack

```sh
cp .env.example .env   # replace every "replace-me"
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
./scripts/smoke-dev.sh
```

The stack runs the database, the embeddings server (TEI), a one-shot `migrate`, the `api`, the
ingestion `worker`, the Next.js `web` service and Caddy, which serves `http://127.0.0.1:8080` (`/api/*`
goes to the api, everything else to `web`). The smoke script uploads a fixture PDF,
waits for ingestion, and checks that a streamed answer yields `delta`, `sources` (page 1) and `done`
events through Caddy.

- Fully offline: set `SOURCEHAVEN_GENERATION_PROVIDER=fake` and `SOURCEHAVEN_EMBEDDING_PROVIDER=hash`
  in `.env`. With `fake` no `OPENAI_API_KEY` is needed and no network is used at runtime; answers are
  canned. With `hash` embeddings the TEI service still starts (it downloads the pinned model on first
  start); stop it or ignore it if you do not need it.
- Real providers: set `SOURCEHAVEN_EMBEDDING_PROVIDER=tei`, `SOURCEHAVEN_GENERATION_PROVIDER=openai`
  and a real `OPENAI_API_KEY` in `.env`, recreate the stack and run the smoke script again; it should
  print a streamed answer citing page 1 and costs a fraction of a cent. This check has not been run
  yet (no key was available during development).
- The first start downloads the embedding model into the `tei-models` volume. Stop the stack with
  `docker compose -f compose.yaml -f compose.dev.yaml down` (add `-v` only to delete all data).

## Frontend

The Next.js app lives in `frontend/` (its own `package.json` and lockfile; Node 24). Its checks run
from the repository root through pre-commit and in the CI `frontend` job.

```sh
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run gen:api   # regenerate src/lib/api-types.ts from the FastAPI schema
```

`gen:api` runs `uv run sourcehaven openapi` with the offline fake providers and needs no secrets.
Commit the regenerated `api-types.ts` whenever an API schema changes; CI fails if it is stale.

The `/app` screen has three columns at 1280 px and wider: documents, conversation and evidence. From
800 to 1279 px the evidence column becomes a drawer (a native `<dialog>`) that opens from a citation
or "Show evidence"; below 800 px the page is one column, the documents collapse into a disclosure at
the top, and the drawer fills the screen. The app uses a light theme only for now. Styles live in
`src/app/globals.css` (colour and type tokens and the focus ring) and in one CSS Module per
component. Component tests run under jsdom (`// @vitest-environment jsdom`) with Testing Library;
pure logic tests run in plain Node.

### Manual browser check

With the dev stack running, open `http://127.0.0.1:8080/app` and check (steps 1 and 2 work with the
fake generation provider):

1. Upload `tests/fixtures/documents/facts_small_en.pdf`. Its row shows the upload progress, then
   Queued and Indexing with a percentage, then Ready, and it is selected automatically. The line
   under the composer reads "Answering from 1 of 1 document".
2. Ask "What is the warranty period?". The answer streams with a blinking caret after the text and
   cites its sources as `[1]`. The evidence panel (the right column at 1280 px and wider, otherwise
   the drawer opened by a citation or "Show evidence") lists the quote from
   `facts_small_en.pdf, page 1`; clicking `[1]` highlights it.
3. Ask another question and reload the page while it is still streaming. After the reload the
   earlier turn ends with "This answer is incomplete." (the conversation is restored from the tab's
   session storage through `GET /api/conversations/{id}`). This step needs the real generation
   provider (`SOURCEHAVEN_GENERATION_PROVIDER=openai`): the fake one streams its whole answer at
   once, so the turn completes before a reload can interrupt it.
4. Remove a document that an answer cites, from its row in "Your documents". Its citation in the
   answer turns grey and is read as "document deleted", the evidence panel shows "This document was
   deleted, so its quote is no longer available." instead of the quote, and the line under the
   answer says a source was deleted.

## Current limitations

This is a development milestone; the production deployment is not ready.

- No Turnstile or other human verification (the dev stack sets it to `disabled`), no rate limits,
  admission queue or spending cap. Only size, page and document-count limits apply.
- No "end session" and no expiry sweeper yet, so uploaded data stays stored until it is removed,
  even after the session expires.
- No document or collection summaries, no follow-up history, no stop/cancel endpoint and no
  idempotent replay of a repeated request.
- Parsing runs in the worker process without child-process resource limits; only PDFs with a text
  layer are supported (no OCR).
- No production Compose file, backups, security headers or public pages (planned for M6 and M7).
- The embedding model and parser are provisional until the M2 measurements.
