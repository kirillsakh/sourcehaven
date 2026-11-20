# YouTube transcripts as a source type — findings (parked)

- **Date:** 2026-11-20
- **Status:** parked in the roadmap (owner decision, 2026-11-20). Revisit after the core milestones,
  at least M3, ideally after the public launch.
- **Idea (owner):** a visitor pastes a YouTube link (for example
  `https://www.youtube.com/watch?v=BmuckEepBAI`); Sourcehaven indexes the video's transcript and
  answers questions about it with timestamp citations.
- **Owner's current manual workflow:** get the transcript from
  [tactiq.io/tools/youtube-transcript](https://tactiq.io/tools/youtube-transcript), paste it into
  ChatGPT, ask questions. How that tool obtains transcripts was not checked.

## Scope

YouTube and URL ingestion are non-goals of the MVP brief (design §1.2, [R]). Adding them is a
product decision with its own design (design §16).

## Fit with the architecture

The seams exist (design §5.3, §16): a `SourceAdapter` per source type returning `ExtractedSource`,
and a `Location` union meant to gain `TimeSpan` beside `PageSpan`. A YouTube source would need:

- a migration so chunks carry a time range (`location jsonb` or time columns);
- ingestion that starts from a URL instead of an uploaded file, accepting only YouTube video ids and
  calling fixed endpoints (URL ingestion is an SSRF surface otherwise);
- citations shown as `12:34`, linking to `watch?v=<id>&t=<seconds>s`;
- per-type handling in summaries (M4), limits and errors (M3), retention and removal (M5).

## The blocker: obtaining transcripts from a server

- **Official API:** YouTube Data API `captions.download` needs an OAuth-authorised user with
  permission to edit the video (in practice the channel owner or a content partner), so it cannot
  fetch arbitrary public videos.
  [Captions: download](https://developers.google.com/youtube/v3/docs/captions/download)
- **Unofficial scraping** (`youtube-transcript-api`, `yt-dlp`): works from a home connection, but
  the library's documentation says YouTube blocks most cloud-provider IPs (`RequestBlocked` /
  `IpBlocked`), so it would likely fail on the Hetzner target; the usual workaround is paid rotating
  residential proxies (budget A5) and it sits uneasily with YouTube's terms (not reviewed legally).
  [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api),
  [issue #593](https://github.com/jdepoix/youtube-transcript-api/issues/593)
- **Own transcription** (e.g. Whisper): still requires downloading the audio (same problem) and is
  slow on 4 vCPUs, or costs money as a hosted service.
- **Caption quality:** many videos have only auto-generated captions with little punctuation, which
  breaks the sentence splitting that quote selection relies on; needs the M2 harness to evaluate.

## Options to decide when it is revisited

1. A hosted transcript service or residential proxies (cost, terms).
2. **Visitor supplies the transcript** — upload a `.srt`/`.vtt`/`.txt` file or paste text. Matches
   the owner's current workflow, avoids fetching from YouTube, keeps timestamps for `.srt`/`.vtt`.
   Probably the cheapest safe first step.
3. Only videos from the visitor's own channel through the official API (OAuth; needs accounts).

## Product notes

- More eye-catching for a demo than PDF tuning, but "chat with a YouTube video" is common;
  Sourcehaven's distinction is private isolated sessions and checkable citations, which M2 measures.
- Suggested sequencing: launch the PDF product, then announce transcripts as the first post-launch
  feature. A time-boxed local throwaway experiment (spike) is possible at any time to judge answer
  quality with timestamp citations.
