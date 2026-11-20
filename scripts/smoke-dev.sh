#!/usr/bin/env bash
# End-to-end smoke check of the development stack through Caddy: session, upload, ingestion,
# conversation and a streamed, cited answer. Start the stack first:
#   docker compose -f compose.yaml -f compose.dev.yaml up -d --build
# Works offline with SOURCEHAVEN_GENERATION_PROVIDER=fake; with `openai` it spends a few tokens.
set -euo pipefail

BASE_URL="${SMOKE_BASE_URL:-http://127.0.0.1:8080}"
READY_TIMEOUT_SECONDS="${SMOKE_READY_TIMEOUT_SECONDS:-180}"
QUESTION="${SMOKE_QUESTION:-What is the Sourcehaven warranty period?}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="$REPO_ROOT/tests/fixtures/documents/facts_small_en.pdf"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
COOKIES="$WORK_DIR/cookies.txt"
STREAM="$WORK_DIR/stream.txt"

fail() {
    echo "smoke check failed: $*" >&2
    exit 1
}

# Every request is bounded so the readiness deadline below cannot be overrun by a hung connection.
CURL=(curl -fsS --connect-timeout 5 --max-time 30)

json_field() {
    python3 -I -c '
import json
import sys

raw = sys.stdin.read()
try:
    print(json.loads(raw)[sys.argv[1]])
except (ValueError, KeyError, TypeError):
    sys.exit(f"smoke check failed: no field {sys.argv[1]!r} in response: {raw[:300]}")
' "$1"
}

"${CURL[@]}" -c "$COOKIES" -b "$COOKIES" -X POST "$BASE_URL/api/session" >/dev/null \
    || fail "cannot create a session at $BASE_URL"

upload="$("${CURL[@]}" -b "$COOKIES" -c "$COOKIES" -F "file=@$FIXTURE;type=application/pdf" \
    "$BASE_URL/api/documents")" || fail "upload was rejected"
document_id="$(json_field id <<<"$upload")"
echo "uploaded document $document_id"

deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
state=""
while ((SECONDS < deadline)); do
    document="$("${CURL[@]}" -b "$COOKIES" "$BASE_URL/api/documents/$document_id")" \
        || fail "cannot read document $document_id"
    state="$(json_field state <<<"$document")"
    echo "document state: $state"
    case "$state" in
        ready) break ;;
        failed) fail "ingestion failed: $document" ;;
    esac
    sleep 2
done
[[ "$state" == "ready" ]] || fail "document not ready after ${READY_TIMEOUT_SECONDS}s (last state: $state)"

conversation="$("${CURL[@]}" -b "$COOKIES" -X POST "$BASE_URL/api/conversations")" \
    || fail "cannot create a conversation"
conversation_id="$(json_field id <<<"$conversation")"

request_id="$(python3 -I -c 'import uuid; print(uuid.uuid4())')"
body="$(python3 -I -c '
import json, sys
print(json.dumps({"client_request_id": sys.argv[1], "kind": "question",
                  "question": sys.argv[2], "document_ids": [sys.argv[3]]}))' \
    "$request_id" "$QUESTION" "$document_id")"

# -N disables curl's output buffering so deltas are written as Caddy relays them.
curl -fsS -N -b "$COOKIES" -H "Content-Type: application/json" -d "$body" \
    --max-time 120 "$BASE_URL/api/conversations/$conversation_id/turns" >"$STREAM" \
    || fail "the turn stream failed"

python3 -I - "$STREAM" <<'PY'
import json
import sys

events: list[tuple[str, str]] = []
name = ""
for line in open(sys.argv[1], encoding="utf-8").read().splitlines():
    if line.startswith("event:"):
        name = line.split(":", 1)[1].strip()
    elif line.startswith("data:") and name:
        events.append((name, line.split(":", 1)[1].strip()))
        name = ""

names = [event for event, _ in events]
if "error" in names:
    sys.exit(f"smoke check failed: error event: {events[names.index('error')][1]}")
if "delta" not in names or "sources" not in names or "done" not in names:
    sys.exit(f"smoke check failed: missing delta/sources/done events, saw {names}")
if not names.index("delta") < names.index("sources") < len(names) - 1 - names[::-1].index("done"):
    sys.exit(f"smoke check failed: events out of order: {names}")

sources = json.loads(events[names.index("sources")][1])["sources"]
if not any(s["pages"]["start"] <= 1 <= s["pages"]["end"] for s in sources):
    sys.exit(f"smoke check failed: no source covers page 1: {sources}")

answer = "".join(json.loads(data)["text"] for event, data in events if event == "delta")
print(f"events: {names.count('delta')} delta, sources (page 1 present), done")
print(f"answer: {answer}")
PY

echo "smoke check passed"
