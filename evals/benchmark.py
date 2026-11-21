import argparse
import asyncio
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx
from pydantic import ValidationError

from evals.corpus import (
    CorpusError,
    Manifest,
    document_path,
    extract_document,
    fetch_corpus,
    file_sha256,
    load_manifest,
    verify_file,
)
from evals.embedding import CachedEmbedder, VectorCache, benchmark_config, ensure_tokenizer
from evals.pipeline import BenchmarkResult, run_benchmark
from evals.questions import Question, QuestionFileError, load_questions
from evals.report import (
    RunContext,
    count_locations,
    render_review_sheet,
    write_report,
)
from evals.scoring import Metrics, SpanLocation, locate_span, summarize
from sourcehaven.config import Settings
from sourcehaven.domain.models import ExtractedSource
from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.protocol import (
    Embedder,
    EmbedderNotReady,
    EmbedderUnavailable,
    TokenCounter,
)
from sourcehaven.embeddings.tei import HfTokenCounter, TeiEmbedder
from sourcehaven.ingestion.errors import IngestionError
from sourcehaven.ingestion.pdf import PdfAdapter

_EVALS_DIR: Final[Path] = Path(__file__).resolve().parent
_DEFAULT_TEI_URL: Final[str] = "http://127.0.0.1:8081"
_FETCH_TIMEOUT_SECONDS: Final[float] = 120.0
_GIT_TIMEOUT_SECONDS: Final[float] = 10.0
_LABEL_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]+")
_EXIT_FAILURE: Final[int] = 2
_REVIEW_SHEET: Final[str] = "review-sheet.md"


class BenchmarkError(Exception):
    """A benchmark command cannot run as configured."""


_HANDLED_ERRORS: Final[tuple[type[Exception], ...]] = (
    BenchmarkError,
    CorpusError,
    QuestionFileError,
    EmbedderNotReady,
    EmbedderUnavailable,
    IngestionError,
    httpx.HTTPError,
)


@dataclass(frozen=True)
class CommonOptions:
    """Options shared by every command.

    Attributes:
        max_pages: Page limit for parsing a document, from the application's settings.
    """

    manifest: Path
    questions: Path
    files: Path
    cache: Path
    reports: Path
    max_pages: int


@dataclass(frozen=True)
class RunOptions(CommonOptions):
    """Options of the `run` command."""

    tei_url: str
    chunk_tokens: int
    chunk_overlap: int
    label: str
    tokenizer_file: Path | None


@dataclass(frozen=True)
class CheckSummary:
    """Outcome of `check`: where the review sheet went and how the gold spans were found."""

    sheet: Path
    counts: dict[SpanLocation, int]


def git_commit() -> str:
    """Revision of the checkout, `unknown` without Git, with `-dirty` for uncommitted changes."""
    head: str | None = _git("rev-parse", "HEAD")
    if not head:
        return "unknown"
    return f"{head}-dirty" if _git("status", "--porcelain") else head


async def fetch_command(manifest_path: Path, files_dir: Path) -> list[Path]:
    """Download and verify every corpus file, printing one line per verified file."""
    manifest: Manifest = load_manifest(manifest_path)
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        paths: list[Path] = await fetch_corpus(manifest, files_dir, client)
    for document, path in zip(manifest.documents, paths, strict=True):
        print(f"{document.id}: verified {path}")
    return paths


def check_command(options: CommonOptions) -> CheckSummary:
    """Validate the inputs offline and write the review sheet to the reports directory.

    Raises:
        CorpusError: If the manifest is invalid or a corpus file is missing or unverified.
        QuestionFileError: If the question file is invalid.
        IngestionError: If a document cannot be parsed.
    """
    manifest: Manifest = load_manifest(options.manifest)
    questions: tuple[Question, ...] = load_questions(options.questions, manifest)
    _require_verified_files(manifest, options.files)
    adapter: PdfAdapter = PdfAdapter()
    sources: dict[str, ExtractedSource] = {
        document.id: extract_document(
            document, document_path(options.files, document), adapter, max_pages=options.max_pages
        )
        for document in manifest.documents
    }
    locations: dict[tuple[str, int], SpanLocation] = {
        (question.id, index): locate_span(span, sources[span.document].pages)
        for question in questions
        for index, span in enumerate(question.gold)
    }
    options.reports.mkdir(parents=True, exist_ok=True)
    sheet: Path = options.reports / _REVIEW_SHEET
    sheet.write_text(render_review_sheet(questions, locations), encoding="utf-8")
    return CheckSummary(sheet=sheet, counts=count_locations(locations))


async def run_command(
    options: RunOptions,
    *,
    embedder: Embedder,
    counter: TokenCounter,
    measure_latency: bool,
) -> Path:
    """Run the benchmark and write its report.

    Args:
        options: Parsed `run` options; `tokenizer_file`, when set, is recorded in the report
            with its SHA-256.
        embedder: The embedding service; it must be ready, which is checked before any work.
        counter: Token counter of the embedding model's tokenizer.
        measure_latency: Time single-query embedding against the uncached embedder.

    Returns:
        The report directory.

    Raises:
        EmbedderNotReady: If the embedding service does not serve the configured model.
        CorpusError: If the manifest is invalid or a corpus file is missing or unverified.
        QuestionFileError: If the question file is invalid.
        IngestionError: If a document cannot be parsed.
    """
    await embedder.check_ready()
    manifest: Manifest = load_manifest(options.manifest)
    questions: tuple[Question, ...] = load_questions(options.questions, manifest)
    _require_verified_files(manifest, options.files)
    created_at: datetime = datetime.now(UTC)
    cache: VectorCache = VectorCache(options.cache / "vectors.sqlite3")
    try:
        result: BenchmarkResult = await run_benchmark(
            manifest,
            questions,
            options.files,
            adapter=PdfAdapter(),
            counter=counter,
            embedder=CachedEmbedder(embedder, cache),
            latency_embedder=embedder if measure_latency else None,
            chunk_tokens=options.chunk_tokens,
            chunk_overlap=options.chunk_overlap,
            max_pages=options.max_pages,
        )
    finally:
        cache.close()
    metrics: Metrics = summarize(result.outcomes)
    context: RunContext = RunContext(
        created_at=created_at,
        git_commit=git_commit(),
        corpus_version=manifest.version,
        questions_sha256=file_sha256(options.questions),
        label=options.label,
        tokenizer_file=options.tokenizer_file,
        tokenizer_sha256=(
            file_sha256(options.tokenizer_file) if options.tokenizer_file is not None else None
        ),
    )
    return write_report(result, metrics, context, options.reports)


def build_parser() -> argparse.ArgumentParser:
    shared: argparse.ArgumentParser = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--manifest",
        type=Path,
        default=_EVALS_DIR / "corpus" / "manifest.toml",
        help="corpus manifest",
    )
    shared.add_argument(
        "--questions", type=Path, default=_EVALS_DIR / "questions.toml", help="question file"
    )
    shared.add_argument(
        "--files", type=Path, default=_EVALS_DIR / "corpus" / "files", help="corpus PDF directory"
    )
    shared.add_argument(
        "--cache", type=Path, default=_EVALS_DIR / ".cache", help="vector and tokenizer cache"
    )
    shared.add_argument(
        "--reports", type=Path, default=_EVALS_DIR / "reports", help="report directory"
    )

    parser: argparse.ArgumentParser = argparse.ArgumentParser(prog="python -m evals.benchmark")
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser] = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND"
    )
    subparsers.add_parser(
        "fetch",
        parents=[shared],
        help="Download and verify the corpus.",
        description="Download and verify the corpus.",
    )
    subparsers.add_parser(
        "check",
        parents=[shared],
        help="Validate the inputs offline and write the review sheet.",
        description="Validate the manifest and questions, extract every document and write the "
        "review sheet to the reports directory. Needs no embedding service.",
    )
    run: argparse.ArgumentParser = subparsers.add_parser(
        "run",
        parents=[shared],
        help="Run the benchmark against TEI.",
        description="Run the full benchmark against a running TEI service.",
    )
    run.add_argument(
        "--tei-url", default=_DEFAULT_TEI_URL, help="TEI base URL (default: %(default)s)"
    )
    run.add_argument(
        "--chunk-tokens",
        type=_positive_int,
        default=None,
        help="passage size in tokens (default: SOURCEHAVEN_CHUNK_TOKENS)",
    )
    run.add_argument(
        "--chunk-overlap",
        type=_non_negative_int,
        default=None,
        help="tokens shared by consecutive passages (default: SOURCEHAVEN_CHUNK_OVERLAP)",
    )
    run.add_argument(
        "--label", type=_label, default="run", help="name appended to the report directory"
    )
    run.add_argument(
        "--tokenizer-file",
        type=Path,
        default=None,
        help="tokenizer.json of the model (default: download it into the cache)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark command line.

    Args:
        argv: Arguments excluding the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 on success, 2 when a command reports a problem.
    """
    args: argparse.Namespace = build_parser().parse_args(argv)
    try:
        _dispatch(args)
    except _HANDLED_ERRORS as error:
        print(f"benchmark {args.command}: {_describe(error)}", file=sys.stderr)
        return _EXIT_FAILURE
    return 0


def _dispatch(args: argparse.Namespace) -> None:
    if args.command == "fetch":
        asyncio.run(fetch_command(args.manifest, args.files))
        return
    settings: Settings = _load_settings(embeddings=args.command == "run")
    common: CommonOptions = _common_options(args, max_pages=settings.max_pages_per_document)
    if args.command == "check":
        summary: CheckSummary = check_command(common)
        for location, count in summary.counts.items():
            print(f"{location}: {count}")
        print(f"Review sheet: {summary.sheet}")
        return
    options: RunOptions = RunOptions(
        manifest=common.manifest,
        questions=common.questions,
        files=common.files,
        cache=common.cache,
        reports=common.reports,
        max_pages=common.max_pages,
        tei_url=args.tei_url,
        chunk_tokens=args.chunk_tokens if args.chunk_tokens is not None else settings.chunk_tokens,
        chunk_overlap=(
            args.chunk_overlap if args.chunk_overlap is not None else settings.chunk_overlap
        ),
        label=args.label,
        tokenizer_file=args.tokenizer_file,
    )
    report: Path = asyncio.run(_run_against_tei(options, settings))
    print(f"Report: {report}")


async def _run_against_tei(options: RunOptions, settings: Settings) -> Path:
    try:
        config: EmbeddingConfig = benchmark_config(
            settings, chunk_tokens=options.chunk_tokens, chunk_overlap=options.chunk_overlap
        )
    except ValueError as error:
        raise BenchmarkError(str(error)) from error
    if config.model_revision is None:
        raise BenchmarkError("SOURCEHAVEN_EMBEDDING_MODEL_REVISION is required")
    # The settings' TEI address points inside Compose, so the host-side URL comes from the options.
    async with (
        httpx.AsyncClient(base_url=options.tei_url) as tei_client,
        httpx.AsyncClient() as hub_client,
    ):
        tokenizer_file: Path = options.tokenizer_file or await ensure_tokenizer(
            config.model_id, config.model_revision, options.cache, hub_client
        )
        return await run_command(
            replace(options, tokenizer_file=tokenizer_file),
            embedder=TeiEmbedder(tei_client, config),
            counter=HfTokenCounter(tokenizer_file),
            measure_latency=True,
        )


def _common_options(args: argparse.Namespace, *, max_pages: int) -> CommonOptions:
    return CommonOptions(
        manifest=args.manifest,
        questions=args.questions,
        files=args.files,
        cache=args.cache,
        reports=args.reports,
        max_pages=max_pages,
    )


def _load_settings(*, embeddings: bool) -> Settings:
    try:
        # Without the embedding service the model revision is irrelevant, and the hash provider
        # is the one that does not demand it.
        return Settings() if embeddings else Settings(embedding_provider="hash")
    except ValidationError as error:
        # Pydantic's own message echoes the offending values, which may be credentials.
        problems: str = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or 'settings'}: {item['msg']}"
            for item in error.errors()
        )
        raise BenchmarkError(f"invalid settings: {problems}") from error


def _require_verified_files(manifest: Manifest, files_dir: Path) -> None:
    unverified: list[str] = [
        f"{document.id} ({document_path(files_dir, document)})"
        for document in manifest.documents
        if not verify_file(document_path(files_dir, document), document)
    ]
    if unverified:
        raise CorpusError(
            f"missing or unverified corpus files: {', '.join(unverified)}; "
            "run `python -m evals.benchmark fetch` first"
        )


def _git(*arguments: str) -> str | None:
    try:
        completed: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", *arguments],
            cwd=_EVALS_DIR,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _describe(error: Exception) -> str:
    if isinstance(error, EmbedderNotReady):
        return error.reason
    if isinstance(error, IngestionError):
        return f"cannot extract a document: {error.code}"
    if isinstance(error, httpx.HTTPError):
        return f"HTTP request failed: {error!r}"
    return str(error) or type(error).__name__


def _positive_int(value: str) -> int:
    number: int = _integer(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value} is not a positive integer")
    return number


def _non_negative_int(value: str) -> int:
    number: int = _integer(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"{value} is negative")
    return number


def _integer(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value} is not an integer") from None


def _label(value: str) -> str:
    if not _LABEL_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("label must match [A-Za-z0-9_-]+")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
