# Round 2 LLM Handoff 2026-03-16

This document records the current WSL-side stopping point for Round 2.

## What Landed

- the WSL processor now has a clearer Round 2 pipeline shape:
  - ingest
  - normalize
  - evidence
  - summarize
  - analyze
  - verify
  - synthesize
- HTML denoise improved for:
  - WeChat article container extraction
  - generic article container preference
  - block-level preservation for headings, paragraphs, list items, image captions, and table rows
- evidence infrastructure is now usable as a real contract:
  - stable `evidence_segment_id`
  - `evidence_index`
  - `resolved_evidence`
  - `evidence_backlinks`
  - `result_index`
- LLM interaction is no longer ad-hoc:
  - `LlmTaskSpec`
  - `LlmRequestEnvelope`
  - persisted request artifacts under `analysis/llm/`
- provider handshake metadata is now surfaced through:
  - `analysis_result.json`
  - `normalized.json`
  - `pipeline.json`
  - `status.json`

## Current Input Boundary

Round 2 currently constrains WSL -> LLM input to three logical modalities:

- `text`
- `image`
- `text_image`

Current runtime rule:

- the main analysis path now uses a unified multimodal-capable request shape
- the selected request modality is `text_image`
- if an asset has no useful images, the request still uses the same shape with an empty image list

Current normalization rules:

- article/post:
  - primary evidence is body text
  - content images can be attached
- audio:
  - Whisper transcript becomes the main text input
- video:
  - subtitle and Whisper transcript are text input
  - extracted frames are attached for visual checks when needed
- table:
  - image representation is acceptable when structural parsing is weak

## Current Policies

- `article_text_first_v1`
- `audio_text_only_v1`
- `video_text_first_v1`

These policies are now written into request artifacts and `llm_processing` metadata.

## Verified State

- `whisper` is available in WSL
- `ffmpeg` is available in WSL
- ZenMux-compatible OpenAI SDK calls are working through the `responses` API path
- the current WSL test slice is green

## Next Recommended Build Order

1. improve article-image selection so only meaningful images enter the main `text_image` request
2. keep denoise quality ahead of LLM expansion, especially for WeChat and generic article shells
3. run another real text-first acceptance pass after the next image-selection refinement
4. only after the Round 2 chain is stable, widen modality support beyond the current boundary
