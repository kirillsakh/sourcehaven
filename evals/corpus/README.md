# Benchmark corpus

Six public documents that the retrieval benchmark runs over (design:
[corpus and harness](../../docs/superpowers/specs/2026-11-20-corpus-and-harness-design.md),
section 3.4). `manifest.toml` pins each file by URL, size and SHA-256.

The PDFs are not redistributed in this repository: they are downloaded on demand into
`evals/corpus/files/`, which is git-ignored.

```sh
uv run python -m evals.benchmark fetch   # download and verify the PDFs
uv run python -m evals.benchmark check   # validate the manifest and questions
```

`evals/questions.toml` quotes short excerpts of these documents under the same licences.

## Attributions

- **Model Services Contract: Core Terms** (MHCLG edition, TCMSC 11.25), Ministry of Housing,
  Communities and Local Government, issued by the Cabinet Office. Crown copyright, licensed under
  the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
  Source: <https://assets.publishing.service.gov.uk/media/6953ae6897f1c5e3c92a8322/MHCLG__Model_Services_Contract_Terms_and_Conditions.pdf>.
  Licence evidence: <https://www.gov.uk/government/publications/model-services-contract-terms>.
  Contains public sector information licensed under the Open Government Licence v3.0.
- **BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding**, Jacob
  Devlin, Ming-Wei Chang, Kenton Lee and Kristina Toutanova (NAACL-HLT 2019, ACL Anthology
  N19-1423). Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  Source: <https://aclanthology.org/N19-1423.pdf>.
  Licence evidence: <https://aclanthology.org/faq/copyright/>.
- **Guide for the Use of the International System of Units (SI)** (NIST Special Publication 811,
  2008 edition), Ambler Thompson and Barry N. Taylor, National Institute of Standards and
  Technology. Public domain (U.S. Government work).
  Source: <https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication811e2008.pdf>.
  Licence evidence: <https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications>.
- **UK Energy in Brief 2025**, Department for Energy Security and Net Zero. Crown copyright,
  licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
  Source: <https://assets.publishing.service.gov.uk/media/688890c3a11f859994409132/UK_Energy_in_Brief_2025.pdf>.
  Licence evidence: <https://www.gov.uk/government/statistics/uk-energy-in-brief-2025>.
  Contains public sector information licensed under the Open Government Licence v3.0.
- **Introduction to Intellectual Property**, OpenStax (senior contributing authors David Kline and
  David Kappos, presented by Gary Michelson, M.D.; derived from *The Intangible Advantage* by The
  Michelson 20MM Foundation). Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  Source: <https://assets.openstax.org/oscms-prodcms/media/documents/introduction-intellectual-property_-_WEB.pdf>.
  Licence evidence: <https://openstax.org/details/books/introduction-intellectual-property>.
  Excerpt: physical pages 17-100.
- **UK Energy in Brief 2024**, Department for Energy Security and Net Zero. Crown copyright,
  licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
  Source: <https://assets.publishing.service.gov.uk/media/687f4cf592957f2ec567c64f/UK_Energy_in_Brief_2024.pdf>.
  Licence evidence: <https://www.gov.uk/government/statistics/uk-energy-in-brief-2024>.
  Contains public sector information licensed under the Open Government Licence v3.0. Not part of
  the default run; it exists so that the two editions give conflicting figures.
