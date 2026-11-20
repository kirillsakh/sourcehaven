# Synthetic PDF fixtures

Committed, license-clean PDFs that drive the parser, ingestion, retrieval and isolation tests.
They contain no real data. Regenerate them with:

```text
uv run python -m tests.fixtures.generate_documents
```

Output is deterministic (reportlab `invariant=1`, fixed metadata), so regenerating must leave
`git status --porcelain tests/fixtures/documents` empty. Text is set in Helvetica, one of the
standard PDF base fonts, so no font file is embedded or vendored.

| File | Pages | Purpose | Content and expected results |
|---|---|---|---|
| `facts_small_en.pdf` | 2 | Small English fact lookup and page citations | p1: "The Sourcehaven warranty period is 24 months." p2: "Support requests are answered within 3 business days." |
| `multipage_en.pdf` | 6 | Chunking and page-number citations | Each page *n* holds a filler paragraph plus `MARKER-PAGE-n`. Page 4 also contains "The bridge was completed in 1931." |
| `visitor_x_en.pdf` | 1 | Visitor isolation (visitor X) | "Visitor X secret code: ALPHA-7731." |
| `visitor_y_en.pdf` | 1 | Visitor isolation (visitor Y) | "Visitor Y secret code: BRAVO-4410." |
| `blank_pages.pdf` | 2 | Document with no extractable text | Two pages with no text; the parser must yield no usable text. |
