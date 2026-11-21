import hashlib
import json
import shutil
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from evals.benchmark import RunOptions, git_commit, main, run_command
from evals.corpus import CorpusError
from sourcehaven.embeddings.hashing import HashEmbedder, WhitespaceTokenCounter
from sourcehaven.embeddings.protocol import EmbedderNotReady
from tests.support.embeddings import NotReadyEmbedder
from tests.support.fixtures import fixture

_DOCUMENT_IDS: tuple[str, ...] = ("facts", "multipage")
_FIXTURE_FILES: dict[str, str] = {"facts": "facts_small_en.pdf", "multipage": "multipage_en.pdf"}
_CHUNK_TOKENS: int = 20


class CountingNotReadyEmbedder(NotReadyEmbedder):
    """Not-ready embedder that also counts calls to the embedding methods."""

    def __init__(self) -> None:
        super().__init__()
        self.embed_calls: int = 0

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls += 1
        return await super().embed_documents(texts)

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls += 1
        return await super().embed_queries(texts)


def manifest_text(files: Path) -> str:
    entries: list[str] = []
    for document_id in _DOCUMENT_IDS:
        content: bytes = (files / f"{document_id}.pdf").read_bytes()
        entries.append(
            "[[document]]\n"
            f'id = "{document_id}"\n'
            f'title = "{document_id}"\n'
            'author = "Test"\n'
            f'url = "https://example.test/{document_id}.pdf"\n'
            f'sha256 = "{hashlib.sha256(content).hexdigest()}"\n'
            f"size_bytes = {len(content)}\n"
            "page_count = 6\n"
            'licence = "Test"\n'
            'licence_url = "https://example.test/licence"\n'
            'layout = "plain"\n'
        )
    return "version = 2\n\n" + "\n".join(entries)


QUESTIONS_TEXT: str = """
[[question]]
id = "warranty"
kind = "answerable"
text = "How long is the warranty period?"
documents = ["facts"]
reference_answer = "The Sourcehaven warranty period is 24 months."
[[question.gold]]
document = "facts"
page = 1
text = "The Sourcehaven warranty period is 24 months."

[[question]]
id = "bridge"
kind = "answerable"
text = "When was the bridge completed?"
documents = ["multipage"]
reference_answer = "The bridge was completed in 1931."
[[question.gold]]
document = "multipage"
page = 4
text = "The bridge was completed in 1931."

[[question]]
id = "peru"
kind = "unanswerable"
text = "What is the capital of Peru?"
"""


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's `.env` and environment out of `Settings()`."""
    work: Path = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_PROVIDER", "tei")
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_MODEL_REVISION", "rev-1")


@pytest.fixture
def options(tmp_path: Path) -> RunOptions:
    files: Path = tmp_path / "files"
    files.mkdir()
    for document_id, name in _FIXTURE_FILES.items():
        shutil.copy(fixture(name), files / f"{document_id}.pdf")
    manifest: Path = tmp_path / "manifest.toml"
    manifest.write_text(manifest_text(files))
    questions: Path = tmp_path / "questions.toml"
    questions.write_text(QUESTIONS_TEXT)
    return RunOptions(
        manifest=manifest,
        questions=questions,
        files=files,
        cache=tmp_path / "cache",
        reports=tmp_path / "reports",
        max_pages=100,
        tei_url="http://127.0.0.1:1",
        chunk_tokens=_CHUNK_TOKENS,
        chunk_overlap=0,
        label="test",
        tokenizer_file=None,
    )


def shared_args(options: RunOptions) -> list[str]:
    return [
        "--manifest",
        str(options.manifest),
        "--questions",
        str(options.questions),
        "--files",
        str(options.files),
        "--cache",
        str(options.cache),
        "--reports",
        str(options.reports),
    ]


def test_check_writes_the_review_sheet_offline(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", *shared_args(options)]) == 0

    sheet: str = (options.reports / "review-sheet.md").read_text()
    assert "warranty" in sheet
    assert "bridge" in sheet
    assert "peru" in sheet
    output: str = capsys.readouterr().out
    assert "on_page: 2" in output
    assert "missing: 0" in output


def test_check_reports_a_span_that_is_not_in_the_document(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    options.questions.write_text(
        QUESTIONS_TEXT.replace(
            'text = "The bridge was completed in 1931."\n\n',
            'text = "A sentence that is not in the file."\n\n',
        )
    )

    assert main(["check", *shared_args(options)]) == 0

    assert "missing: 1" in capsys.readouterr().out
    assert "[missing]" in (options.reports / "review-sheet.md").read_text()


def test_check_fails_on_an_invalid_question_file(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    options.questions.write_text(QUESTIONS_TEXT.replace("answerable", "guessable", 1))

    assert main(["check", *shared_args(options)]) == 2

    assert "warranty" in capsys.readouterr().err
    assert not (options.reports / "review-sheet.md").exists()


def test_check_fails_on_an_invalid_manifest(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    options.manifest.write_text("version = 0\n")

    assert main(["check", *shared_args(options)]) == 2

    assert "version" in capsys.readouterr().err


def test_check_asks_for_a_fetch_when_a_file_is_missing(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    (options.files / "facts.pdf").unlink()

    assert main(["check", *shared_args(options)]) == 2

    error: str = capsys.readouterr().err
    assert "facts" in error
    assert "fetch" in error


def test_check_rejects_a_file_that_does_not_match_the_manifest(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    (options.files / "facts.pdf").write_bytes(b"not the pinned file")

    assert main(["check", *shared_args(options)]) == 2

    assert "fetch" in capsys.readouterr().err


def test_fetch_lists_files_that_are_already_verified(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch", *shared_args(options)]) == 0

    lines: list[str] = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "facts" in lines[0]
    assert "multipage" in lines[1]


def test_fetch_fails_on_an_invalid_manifest(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    options.manifest.write_text("version = 0\n")

    assert main(["fetch", *shared_args(options)]) == 2

    assert "version" in capsys.readouterr().err


def test_run_needs_a_model_revision(
    options: RunOptions, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SOURCEHAVEN_EMBEDDING_MODEL_REVISION")

    assert main(["run", *shared_args(options)]) == 2

    assert "embedding_model_revision" in capsys.readouterr().err


def test_run_needs_the_tei_provider(
    options: RunOptions, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_PROVIDER", "hash")

    assert main(["run", *shared_args(options)]) == 2

    assert "tei" in capsys.readouterr().err


def test_run_rejects_a_label_with_unsafe_characters(
    options: RunOptions, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["run", *shared_args(options), "--label", "../escape"])

    assert exit_info.value.code == 2
    assert "label" in capsys.readouterr().err


def test_run_reports_an_unreachable_tei_without_writing_anything(
    options: RunOptions, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tokenizer: Tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "hello": 1}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer_file: Path = tmp_path / "tokenizer.json"
    tokenizer.save(str(tokenizer_file))

    exit_code: int = main(
        [
            "run",
            *shared_args(options),
            "--tei-url",
            options.tei_url,
            "--tokenizer-file",
            str(tokenizer_file),
        ]
    )

    assert exit_code == 2
    assert "unreachable" in capsys.readouterr().err
    assert not options.reports.exists()
    assert not options.cache.exists()


async def test_run_stops_before_any_work_when_tei_is_not_ready(options: RunOptions) -> None:
    embedder: CountingNotReadyEmbedder = CountingNotReadyEmbedder()

    with pytest.raises(EmbedderNotReady):
        await run_command(
            options, embedder=embedder, counter=WhitespaceTokenCounter(), measure_latency=False
        )

    assert embedder.embed_calls == 0
    assert not options.reports.exists()
    assert not options.cache.exists()


async def test_run_command_writes_a_report_on_the_fixtures(options: RunOptions) -> None:
    directory: Path = await run_command(
        options, embedder=HashEmbedder(), counter=WhitespaceTokenCounter(), measure_latency=True
    )

    assert directory.parent == options.reports
    assert directory.name.endswith("-test")
    created: datetime = datetime.strptime(directory.name.removesuffix("-test"), "%Y%m%dT%H%M%SZ")
    assert abs((datetime.now(UTC).replace(tzinfo=None) - created).total_seconds()) < 120
    data: dict[str, Any] = json.loads((directory / "report.json").read_text())
    assert data["context"]["corpus_version"] == 2
    assert (
        data["context"]["questions_sha256"]
        == hashlib.sha256(options.questions.read_bytes()).hexdigest()
    )
    assert data["context"]["label"] == "test"
    assert data["metrics"]["answered_questions"] == 2
    assert data["metrics"]["recall_at_8"] == 1.0
    assert data["speed"]["query_p50_ms"] is not None
    assert [item["id"] for item in data["documents"]] == ["facts", "multipage"]
    assert [item["question"]["id"] for item in data["outcomes"]] == ["warranty", "bridge", "peru"]
    assert "Recall@8" in (directory / "summary.md").read_text()
    assert (options.cache / "vectors.sqlite3").is_file()


async def test_run_command_skips_latency_when_not_measured(options: RunOptions) -> None:
    directory: Path = await run_command(
        options, embedder=HashEmbedder(), counter=WhitespaceTokenCounter(), measure_latency=False
    )

    data: dict[str, Any] = json.loads((directory / "report.json").read_text())
    assert data["speed"]["query_p50_ms"] is None


async def test_run_command_asks_for_a_fetch_when_a_file_is_missing(options: RunOptions) -> None:
    (options.files / "multipage.pdf").unlink()

    with pytest.raises(CorpusError, match="fetch"):
        await run_command(
            replace(options, label="again"),
            embedder=HashEmbedder(),
            counter=WhitespaceTokenCounter(),
            measure_latency=False,
        )

    assert not options.reports.exists()


def test_git_commit_is_a_revision_with_an_optional_dirty_mark() -> None:
    commit: str = git_commit()

    assert commit == "unknown" or commit.removesuffix("-dirty").isalnum()
