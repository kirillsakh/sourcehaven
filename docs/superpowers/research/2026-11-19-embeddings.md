# Research: CPU embedding models (verified 2026-11-19)

Scope: English retrieval on a CPU-only small VPS (narrowed on 2026-11-20; see the design spec's decision register). Nothing was downloaded or benchmarked.
Sources: Hugging Face model cards (`https://huggingface.co/<model-id>`) and `https://huggingface.co/api/models/<model-id>` unless noted.

## Candidates

| Model | Params | Dim | Max tokens | Licence | Prefixes | Notes |
|---|---|---|---|---|---|---|
| intfloat/multilingual-e5-small | 118M | 384 | 512 | MIT | `query: ` / `passage: ` | Official ONNX incl. qint8 |
| intfloat/multilingual-e5-base | 278M | 768 | 512 | MIT | `query: ` / `passage: ` | Official ONNX incl. qint8 |
| intfloat/multilingual-e5-large | 560M | 1024 | 512 | MIT | `query: ` / `passage: ` | Only mE5 in FastEmbed built-ins |
| BAAI/bge-m3 | ~568M | 1024 | 8192 | MIT | none | Sparse/ColBERT outputs need FlagEmbedding (torch) |
| Alibaba-NLP/gte-multilingual-base | 305M | 768 | 8192 | Apache-2.0 | none | `trust_remote_code` in ST; TEI native |
| Snowflake/snowflake-arctic-embed-m-v2.0 | 305M | 768 (MRL 256) | 8192 | Apache-2.0 | `query: ` | Official ONNX incl. int8; TEI native |
| google/embeddinggemma-300m | 303M | 768 (MRL) | 2048 | Gemma Terms (not OSI; gated) | task prompts | Pass-through use restrictions |
| Qwen/Qwen3-Embedding-0.6B | 596M | 1024 (MRL) | 32K | Apache-2.0 | instruction on queries | Highest MMTEB retrieval (64.64); no official ONNX |
| nomic-ai/nomic-embed-text-v2-moe | 475M (305M active) | 768 | 512 | Apache-2.0 | `search_query:` / `search_document:` | `trust_remote_code` |

Dropped: jina-embeddings-v3 (CC BY-NC 4.0), paraphrase-multilingual-* (paraphrase models, 128-token limit).

## Benchmark caveats
- Published MIRACL/CLEF/BEIR/MMTEB figures (Snowflake cards, MMTEB) only shortlist candidates.

## Runtimes
- sentence-transformers 6.3.0 + torch 2.15.0 (cp314 manylinux x86_64 wheels): works for all; large image; some models need `trust_remote_code`.
- FastEmbed 0.9.1 declares Python 3.14; built-in multilingual dense: paraphrase MiniLM/mpnet and mE5-large; custom ONNX models via `add_custom_model()`. https://qdrant.github.io/fastembed/examples/Supported_Models/
- onnxruntime 1.32.0 has cp314 wheels.
- Hugging Face TEI CPU image `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9` (Rust server, independent of Python version) supports XLM-R (mE5, bge-m3 dense), GTE (gte-multilingual, arctic-m-v2), Qwen3, Gemma3, nomic-v2-moe. https://huggingface.co/docs/text-embeddings-inference/supported_models

## CPU performance
No verified published CPU numbers for these models. Vespa (https://blog.vespa.ai/embedding-tradeoffs-quantified/, 2026-01-14): INT8 is 2.7–3.4x faster than FP32 at 94–98% quality for a small English model.
ESTIMATES ONLY (4–8 vCPU x86, batch 1): small ~5–15 ms/query; ~300M ~15–40 ms/query, ~10–30 chunks/s ingestion; ~0.6B ~40–120 ms/query, single-digit chunks/s.

## Shortlist to benchmark on our own English documents
1. snowflake-arctic-embed-m-v2.0 (primary)
2. multilingual-e5-base (and e5-small) (baseline)
3. Qwen3-Embedding-0.6B (quality ceiling; slower)

This shortlist was originally chosen for multilingual use. M2 should also benchmark English-only candidates, such as smaller English embedding models.
