# Research: Python 3.14 compatibility of candidate libraries (verified 2026-11-19)

Method: PyPI JSON metadata (`https://pypi.org/pypi/<name>/json`) and GitHub issues. Packaging facts only; no import or runtime test on 3.14 was run. A CI smoke test on 3.14 must confirm runtime behaviour.

## Summary
- Pure Python or cp314 wheels on Linux x86_64/aarch64 and macOS arm64: langchain 1.5.2, langchain-core 1.8.3, langchain-text-splitters 1.1.3, langgraph 1.2.23, langgraph-checkpoint-postgres 3.2.1, llama-index-core 0.14.26 (3.14 support merged), langchain-openai 1.8.3, torch 2.15.0, sentence-transformers 6.3.0, transformers 5.23.0, fastembed 0.9.1, onnxruntime 1.32.0, tokenizers 0.23.3, pypdf 7.1.1, pypdfium2 5.15.2, pdfplumber 0.11.10, psycopg 3.3.9 (binary), asyncpg 0.32.0, pgvector 0.5.1, sqlalchemy 2.1.9, alembic 1.20.1, qdrant-client 1.20.0, pymongo 4.20.1, fastapi 0.165.0, starlette 1.10.0, uvicorn 0.54.0, pydantic 2.14.4, pydantic-settings 2.16.3, django 6.1.3, gradio 6.32.0, tiktoken 0.14.0, python-multipart 0.0.34, hatchling 1.33.0, uv-build 0.13.9.
- Docker: `python:3.14-slim` (Debian trixie), current patch `3.14.10-slim-trixie`.

## Blockers and risks
1. chromadb 1.5.9: open 3.14 issues (#5554 `overrides` import AttributeError; #6984 macOS arm64 segfault; #5983 build failure). Avoid.
2. torch on Linux from PyPI pulls CUDA 13 libraries; use the PyTorch CPU index for Linux if torch is needed, or avoid torch in the app image.
3. pymupdf is AGPL-3.0 or commercial; avoid for a publicly served app. Use pypdf or pypdfium2 (permissive).
4. Pins: langchain-postgres requires `pgvector<0.4`; langchain-huggingface and fastembed require `huggingface-hub<2.0`.
5. httpx 0.28.1 (2024-12) is effectively unmaintained but required transitively by OpenAI/LangChain; needs httpcore>=1.0.8 on 3.14.
6. llama-index-core pulls a heavy dependency set (nltk, tiktoken, aiohttp, networkx, pillow, sqlalchemy, ...); some integrations had separate 3.14 issues.
7. langchain-qdrant: no release since 2025-10-22.

Sources: https://pypi.org/pypi/<name>/json for each package; GitHub chroma-core/chroma issues #5554, #6984, #5983; Docker Hub `library/python` tags.

2026-11-19 note: the build backend is pinned to `uv_build>=0.9.17,<0.10` (not 0.13.9 as listed above) and uv to 0.9.17 in CI and the Dockerfile, because the owner's local uv 0.9.17 cannot build the sdist produced by uv_build 0.13.
