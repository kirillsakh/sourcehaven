#!/usr/bin/env bash
# Build the sdist and wheel, inspect both, then verify a clean non-editable install
# from outside the checkout.
set -euo pipefail

# Paths are matched against wheel members as listed and against sdist members after the
# "<name>-<version>/" prefix is stripped, so one list serves both artefacts.
REQUIRED_PATHS=(
    "sourcehaven/migrations/versions/0001_baseline.py"
    "sourcehaven/migrations/versions/0002_drop_detected_language.py"
    "sourcehaven/prompts/answer_system.txt"
)
SDIST_SOURCE_PREFIX="src/"
FORBIDDEN_PATTERN='(^|/)(tests|docs|\.claude|frontend|\.venv|__pycache__|uploads)/|(^|/)\.env($|\.)|\.(pyc|db|sqlite)$'

list_members() {
    python3 -I -c '
import sys, tarfile, zipfile

path = sys.argv[1]
if path.endswith(".whl"):
    names = zipfile.ZipFile(path).namelist()
else:
    # Drop the single top-level "<name>-<version>/" directory every sdist member sits under.
    names = [m.name.split("/", 1)[1] if "/" in m.name else "" for m in tarfile.open(path)]
print("\n".join(name for name in names if name))' "$1"
}

check_archive_contents() {
    local archive="$1"
    local source_prefix="${2:-}"
    local listing path
    listing="$(list_members "$archive")"

    for path in "${REQUIRED_PATHS[@]}"; do
        if ! grep -Fxq -- "$source_prefix$path" <<<"$listing"; then
            echo "package check failed: $(basename "$archive") is missing $source_prefix$path" >&2
            return 1
        fi
    done
    if grep -En -- "$FORBIDDEN_PATTERN" <<<"$listing" >&2; then
        echo "package check failed: $(basename "$archive") contains forbidden paths" >&2
        return 1
    fi
}

single_artifact() {
    local dist_dir="$1"
    local pattern="$2"
    local matches=()
    shopt -s nullglob
    matches=("$dist_dir"/$pattern)
    shopt -u nullglob
    if [[ ${#matches[@]} -ne 1 ]]; then
        echo "package check failed: expected exactly one $pattern in $dist_dir, found ${#matches[@]}" >&2
        return 1
    fi
    echo "${matches[0]}"
}

main() {
    local repo_root work_dir wheel sdist
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    work_dir="$(mktemp -d)"
    trap "rm -rf '$work_dir'" EXIT

    (cd "$repo_root" && uv build --out-dir "$work_dir/dist")
    wheel="$(single_artifact "$work_dir/dist" "*.whl")"
    sdist="$(single_artifact "$work_dir/dist" "*.tar.gz")"
    check_archive_contents "$wheel"
    check_archive_contents "$sdist" "$SDIST_SOURCE_PREFIX"

    uv venv --python 3.14 "$work_dir/venv"
    uv pip install --python "$work_dir/venv/bin/python" "$wheel"

    # Run from outside the checkout so imports cannot resolve against ./src.
    cd "$work_dir"
    "$work_dir/venv/bin/python" -I -c \
        "import sourcehaven, sourcehaven.api.app, sourcehaven.migrations"
    "$work_dir/venv/bin/python" -I -c \
        "from importlib.resources import files; assert files('sourcehaven.migrations').joinpath('env.py').is_file()"
    "$work_dir/venv/bin/python" -I -c \
        "from sourcehaven.generation.prompts import load_prompt; assert '[S' in load_prompt('answer_system')"
    "$work_dir/venv/bin/sourcehaven" --help >/dev/null

    echo "package check passed"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
