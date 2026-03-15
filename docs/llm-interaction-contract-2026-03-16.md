# LLM Interaction Contract

## Goal

The WSL processor should not talk to an LLM through ad-hoc prompt strings.

Round 2 should use a stable interaction contract with three layers:

1. input contract
2. task contract
3. interaction policy

This keeps output shape stable and makes future provider swaps safer.

## 1. Input Contract

Every LLM request should be built from a canonical envelope.

The minimum envelope contains:

- provider
- base URL
- model
- task metadata
- content shape
- content policy
- source metadata
- task intent
- structured document payload

The structured document payload should prefer explicit fields over flattened text:

- `title`
- `author`
- `published_at`
- `content_text`
- `transcript_text`
- `blocks`
- `attachments`
- `allowed_evidence_ids`
- `evidence_segments`

## 2. Task Contract

The first task specs are:

- `text_analysis_v1`
  - stage: `summarize_analyze_verify`
  - goal: produce summary, key points, analysis, verification, synthesis
- `multimodal_verification_v1`
  - stage: `multimodal_verify`
  - goal: validate transcript and analysis against extracted frames

Each task spec should define:

- task id
- stage
- goal
- output schema name
- schema mode
- selected input modality
- whether multimodal input is required

## 3. Interaction Policy

The processor should apply these default rules:

- only three logical input modalities are in scope for Round 2:
  - `text`
  - `image`
  - `text_image`
- the runtime request path is now unified around a multimodal-capable model:
  - primary request modality: `text_image`
  - text-only content still uses the same request shape, with an empty image list
- article and post-like content are text-first semantically:
  - primary evidence source: body text
  - images are attached whenever available
- audio is normalized before LLM:
  - source attachment -> Whisper transcript -> `text`
- video is normalized before LLM:
  - prefer subtitle text when available
  - extract audio and run Whisper
  - primary request modality remains `text_image`
  - if extracted frames are needed for visual cross-checks, they are attached as additional images
- tables are represented as `image` when visual fidelity matters
- if no API key is configured, skip early with an explicit `skip_reason`
- if evidence references are invalid, repair once, then downgrade conservatively

## Content Policies

Current contract policies are:

- `article_text_first_v1`
  - supported modalities: `text`, `image`, `text_image`
  - default intent: `summarize_article_with_optional_image_grounding`
- `audio_text_only_v1`
  - supported modalities: `text`, `text_image`
  - default intent: `summarize_and_verify_audio_transcript`
- `video_text_first_v1`
  - supported modalities: `text`, `text_image`
  - default intent: `summarize_video_from_subtitle_and_whisper_transcript`

These policies are emitted into:

- `analysis/llm/text_request.json`
- `analysis/llm/multimodal_request.json`
- `normalized.json -> asset.metadata.llm_processing`
- `normalized.json -> asset.metadata.llm_processing.handshake`

## Request Artifacts

For traceability, each processed job should persist its outbound request envelopes:

- `analysis/llm/text_request.json`
- `analysis/llm/multimodal_request.json`, when multimodal is used

These paths should be surfaced through:

- `analysis_result.json`
- `normalized.json -> asset.metadata.llm_processing.request_artifacts`

## Current Scope

This contract is provider-agnostic at the data layer.

Current runtime validation still targets the OpenAI-compatible path first, but the envelope
format should stay stable across:

- OpenAI-compatible providers
- ZenMux
- future Gemini / Claude adapters
