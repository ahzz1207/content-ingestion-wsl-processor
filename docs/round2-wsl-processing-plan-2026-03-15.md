# Round 2 WSL Processing Plan

## Goal

Round 2 on the WSL side is not just about parsing more formats.

The goal is to build a stable, source-grounded processing pipeline for:

- text content
- audio content
- video content

The pipeline should support:

- normalization
- summary
- analysis
- verification
- synthesis

without losing the evidence needed to justify each result.

## Core Direction

The WSL processing pipeline should follow this shape:

```text
ingest
  -> normalize
  -> evidence
  -> summarize
  -> analyze
  -> verify
  -> synthesize
```

This means:

- `ingest` loads the raw handoff from Windows
- `normalize` turns payloads and attachments into a structured content asset
- `evidence` preserves transcript segments, text blocks, subtitles, and other source fragments
- `summarize` produces concise overview output
- `analyze` produces structured interpretation
- `verify` checks whether each claim is actually grounded in evidence
- `synthesize` produces the final answer or takeaway

## Design Rules

### 1. Evidence-first processing

No summary, analysis item, or verification result should exist without a source anchor.

The first acceptable verification model is:

- `supported`
- `partial`
- `unsupported`
- `unclear`

### 2. Preserve content shape

The processor should not flatten everything into one text blob.

The normalized asset should preserve:

- `blocks`
- `attachments`
- `evidence_segments`
- `transcript_text`
- `analysis_text`

### 3. Limit LLM input modalities on purpose

Round 2 should not send arbitrary raw file types to the LLM.

The in-scope LLM input modalities are only:

- `text`
- `image`
- `text_image`

Runtime rule:

- the main LLM path now uses one multimodal-capable request shape
- the selected request modality is `text_image`
- if an asset has no useful images, the request still uses the same shape with an empty image list

Normalization rules:

- `article/post`
  - body text is primary
  - images should be attached when present
- `audio`
  - attachment -> Whisper transcript -> `text`
- `video`
  - prefer subtitle text if available
  - extract audio and run Whisper
  - treat the main LLM request as `text_image`
  - add frames when visual verification is needed
- `table`
  - represent as `image` when structural parsing is not trustworthy

### 4. Structured results are the primary output

Round 2 results should be represented as a structured result object with:

- `summary`
- `key_points`
- `analysis_items`
- `verification_items`
- `synthesis`
- `warnings`

Flat legacy fields can remain for compatibility, but the structured result should be the source of truth.

### 5. Frontend-facing presentation metadata should be explicit

The processor should not leave all presentation decisions to the Windows UI.

Round 2 should emit lightweight presentation hints so the frontend can render a clean,
compact, evidence-first result view without inventing ad-hoc ordering rules.

The first presentation layer should stay simple:

- each summary / key point / analysis item / verification item / synthesis block gets a `display` payload
- the structured result includes a `display_plan`
- `display_plan` defines section order, default view, default expansion, and item IDs

This is not a visual design system.

It is a stable backend contract that makes future highlight / jump / evidence navigation
features easier to implement on the Windows side.

## Current Text Acceptance Notes

The first text-first acceptance path is WeChat article processing from the Windows GUI.

That path now depends on two concrete behaviors:

- the WSL HTML parser must extract the WeChat article container instead of flattening the entire page shell
- the parser must trim obvious post-body WeChat chrome such as reward, scan, comment, and next-article prompts

On the Windows side, the result workspace should now prefer the structured WSL result when it exists.

That means the GUI preview should show:

- summary
- key points
- analysis items
- verification items
- warnings

instead of only showing the normalized markdown preview.

## Next Execution Tracks

Round 2 now splits into two explicit work tracks.

### Track A: Denoise before analysis

The processor should not send raw page shell text into the LLM stage.

The current denoise target matrix is:

- `wechat article`
  - keep: title, author, published time, article body, meaningful image captions
  - drop: reward prompts, scan prompts, comment shell, next-article prompts, ad warnings, mini-program shell
- `generic article`
  - keep: title, article body, meaningful headings, table text, image-adjacent text
  - drop: nav, search, auth prompts, related content, sidebar, footer, copyright shell
- `bilibili video page`
  - keep: title, uploader, description, subtitle/transcript, danmaku, media attachments
  - drop: recommendation rail, comment shell, engagement chrome, unrelated page copy

Acceptance rule:

- if the extracted content would obviously mislead the LLM, denoise is not good enough yet

Current parser baseline:

- HTML article parsing now preserves ordered `blocks` for:
  - headings
  - paragraphs
  - list items
  - image captions
  - table rows
- WeChat block extraction now applies the same footer-shell trimming rule used by plain text extraction, so removed shell text does not leak back in through structured blocks

### Track B: WSL to LLM handshake visibility

The processor must make it obvious whether the LLM stage really ran.

The minimum handshake surface is:

- provider
- base URL
- analysis model
- multimodal model
- schema mode
- content policy id
- supported input modalities
- selected text input modality
- selected multimodal input modality
- task intent
- skip reason, when skipped

This handshake data should be visible in:

- `analysis/llm/analysis_result.json`
- `normalized.json -> asset.metadata.llm_processing`
- `pipeline.json`
- `status.json`

## Result Schema

### `summary`

- `headline`
- `short_text`

### `key_points`

- `id`
- `title`
- `details`
- `evidence_segment_ids`

### `analysis_items`

- `id`
- `kind`
- `statement`
- `evidence_segment_ids`
- `confidence`

### `verification_items`

- `id`
- `claim`
- `status`
- `evidence_segment_ids`
- `rationale`
- `confidence`

Status values:

- `supported`
- `partial`
- `unsupported`
- `unclear`

### `synthesis`

- `final_answer`
- `next_steps`
- `open_questions`

### `display`

Each display-capable object can expose:

- `kind`
- `priority`
- `label`
- `tone`
- `compact_text`

### `warnings`

Warnings should be structured objects, not only loose strings.

Each warning can expose:

- `code`
- `severity`
- `message`
- `related_refs`

Each related ref can expose:

- `kind`
- `id`
- `role`

### `display_plan`

The structured result can expose section-level rendering hints:

- `version`
- `sections`

Each section can expose:

- `id`
- `title`
- `priority`
- `default_view`
- `default_expanded`
- `item_count`
- `item_ids`
- `pinned_item_ids` when needed

### `evidence_backlinks`

The structured result can expose a reverse index from evidence to result items.

This allows the frontend to start from one evidence segment and discover:

- which key points cite it
- which analysis items cite it
- which verification items cite it

### `result_index`

The structured result can expose a direct item lookup index.

This allows the frontend to start from an item id and discover:

- which section it belongs to
- what kind of result object it is
- which evidence ids it references
- which display priority / tone it should use

## Media Processing Strategy

### Audio

- use Whisper to generate transcript text
- split transcript into evidence segments
- feed transcript and evidence into LLM summary / analysis / verification

### Video

- use `ffmpeg` to extract audio
- use Whisper on extracted audio
- use `ffmpeg` to extract key frames
- use transcript plus frames for text analysis and multimodal verification

## Initial Acceptance Set

Round 2 should be validated on:

- one generic article
- one Bilibili audio-only job
- one Bilibili full-video job

Acceptance means:

- the job completes
- `normalized.json` includes structured result output
- key conclusions reference evidence
- missing evidence produces warnings instead of silent success

## Immediate Implementation Steps

1. Introduce the structured result schema into WSL models.
2. Make LLM text analysis produce structured summary, key points, analysis items, verification items, and synthesis.
3. Keep flat compatibility fields while making the structured result the source of truth.
4. Extend processor output and metadata to surface structured-result availability and counts.
5. Add tests that validate the new schema on a video processing sample.
