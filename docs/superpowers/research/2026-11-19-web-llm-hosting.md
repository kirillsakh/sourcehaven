# Research: web stack, generation API pricing, hosting (verified 2026-11-19)

Prices are list prices excluding VAT; UNVERIFIED items were not confirmed on an official page.

## Web stack
- Next.js 16.4.6, Node >= 20.9.0. Route handlers can return streaming `Response`; built-in sitemap/robots/OG metadata; `output: "standalone"` for Docker (copy `public/` and `.next/static`; build-time `.env` files are copied into output). Self-hosting guide: disable proxy buffering for streaming. `compress: false` when the proxy compresses.
  https://nextjs.org/docs/app/api-reference/file-conventions/route, https://nextjs.org/docs/app/api-reference/config/next-config-js/output, https://nextjs.org/docs/app/guides/self-hosting
- Community reports (not official) of SSE buffering through Next.js rewrites/route proxies → route `/api/*` from the reverse proxy directly to the Python backend.
- FastAPI 0.165.0: native SSE since 0.135.0 (`fastapi.sse.EventSourceResponse`, `ServerSentEvent`), keep-alive pings every 15 s, sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`, supports `Last-Event-ID`. https://fastapi.tiangolo.com/tutorial/server-sent-events/ . Disconnect detection via Starlette `Request.is_disconnected()`: UNVERIFIED this session.
- Django 6.1.3: async `StreamingHttpResponse` under ASGI with cancellation on disconnect; built-in Tasks framework ships only dev/test backends. https://docs.djangoproject.com/en/6.1/topics/tasks/
- Gradio 6.32.0: per-session `gr.State`, `session_hash`; suited to demos rather than a branded public product.
- Caddy flushes `text/event-stream` immediately; exclude streaming routes from `encode`. https://caddyserver.com/docs/caddyfile/directives/reverse_proxy

## Generation APIs (USD per 1M tokens)
| Model | Input | Cached input | Output | Notes |
|---|---|---|---|---|
| OpenAI `gpt-6-luna` | 0.10 | 0.01 | 0.50 | 1.05M ctx / 128K out; batch -50% |
| OpenAI `gpt-5-nano` | 0.05 | 0.005 | 0.40 | |
| OpenAI `gpt-5-mini` (deprecated) | 0.25 | 0.025 | 2.00 | |
| OpenAI `gpt-4.1-mini` | 0.40 | 0.10 | 1.60 | |
| Anthropic `claude-haiku-5-5` (<=100K prompt) | 0.10 | 0.01 | 0.50 | |
| Google `gemini-3.5-flash-lite` | 0.30 | 0.03 | 2.50 | |
| Mistral Small 4 | 0.15 | UNVERIFIED | 0.60 | EU provider |
Sources: https://developers.openai.com/api/docs/pricing, https://platform.claude.com/docs/en/about-claude/pricing, https://docs.mistral.ai/models/mistral-small-4-0-26-03
Generation quality on our English documents: not verified by any source; must be evaluated.

OpenAI data handling: API data not used for training by default; abuse-monitoring logs retained up to 30 days; Zero Data Retention requires approval. https://developers.openai.com/api/docs/guides/your-data
DeepSeek: data stored in the PRC; not recommended.

## Hosting (monthly, excl. VAT)
| Option | Spec | Price |
|---|---|---|
| Hetzner CX33 | 4 vCPU / 8 GB / 80 GB | EUR 8.99 |
| Hetzner CX43 | 8 vCPU / 16 GB / 160 GB | EUR 16.49 |
| Hetzner CAX21 (ARM) | 4 vCPU / 8 GB | EUR 10.99 |
| Hetzner CCX (dedicated vCPU) | dedicated | from EUR 36.99 |
| DigitalOcean Basic 8 GB | 4 vCPU / 8 GB | USD 48 |
| Supabase Pro + Small compute | managed pgvector | ~USD 40 |
Hetzner backups ~20% of server price; snapshots EUR 0.0143/GB. Plan availability displayed as "currently unavailable" on fetched pages (UNVERIFIED stock issue).
https://www.hetzner.com/cloud/cost-optimized/, https://www.digitalocean.com/pricing/droplets, https://neon.com/pricing, https://supabase.com/pricing
