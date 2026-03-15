# `content-ingestion` Project Status

## 1. Current Position

`content-ingestion` is now operating as a two-repository system:

- `Windows Client` in `H:\demo-win`
  - accepts URLs
  - collects or captures page content on Windows
  - extracts metadata hints
  - exports protocol-valid jobs into the shared inbox
- `WSL Processor` in `~/codex-demo`
  - validates and claims inbox jobs
  - parses raw payloads
  - writes `processed/` or `failed/` outputs
  - exposes a minimal downstream pipeline hook

This repository only carries the WSL processor side.

The main product path is already:

```text
Windows URL input
  -> Windows collector/exporter
  -> shared_inbox/incoming/<job_id>/
  -> WSL watch-inbox
  -> processing
  -> processed / failed
```

---

## 2. Verified System State

As of 2026-03-14, the following is true across the two repos:

- Windows client has completed its CLI-first path through Milestone 2 slice 4
- Windows browser export has already been validated with real WeChat article URLs
- Windows export now surfaces structured CLI errors through `WindowsClientError`
- WSL processor MVP is implemented and runnable
- Windows -> WSL handoff has already been validated end-to-end
- WSL normalized outputs now retain filtered handoff context such as `collection_mode` and browser wait/profile settings
- `H:\demo-win\data\shared_inbox\processed` currently contains 10 processed jobs
- a reproducible Windows -> WSL roundtrip script now exists in `H:\demo-win\scripts\run_windows_wsl_roundtrip.ps1`
- the current roundtrip check now validates `metadata.json -> normalized.json` alignment for canonical URL and filtered handoff metadata

This means the project is no longer in a "WSL done, waiting for Windows" state.
It is now in a "main cross-repo handoff works, coordination and engineering polish need to catch up" state.

---

## 3. WSL Repository Status

The current WSL repository already includes:

- inbox protocol and shared inbox directory helpers
- inbox watcher with `--once` support
- job processor for `payload.html`, `payload.txt`, and `payload.md`
- success and failure output writing
- validation commands for jobs and inboxes
- normalization helpers and markdown rendering
- an OpenClaw adapter scaffold

Main code areas:

- `src/content_ingestion/inbox/`
- `src/content_ingestion/raw/`
- `src/content_ingestion/normalize/`
- `src/content_ingestion/storage/`
- `src/content_ingestion/pipeline/`

Experimental or frozen areas still present:

- `src/content_ingestion/sources/`
- `src/content_ingestion/session/`

---

## 4. Windows Alignment Status

The Windows repository is no longer hypothetical.

It already provides:

- `doctor`
- `export-mock-job`
- `export-url-job`
- `browser-login`
- `export-browser-job`
- browser profile warm-up and automatic reuse for recognized platforms
- selector waiting controls for dynamic pages
- metadata hints including `platform`, `title_hint`, `author_hint`, and `published_at_hint`
- shared inbox alignment through `CONTENT_INGESTION_SHARED_INBOX_ROOT`
- a reproducible Windows -> WSL roundtrip script

The authoritative Windows-side alignment references are:

- `H:\demo-win\docs\windows-client-kickoff.md`
- `H:\demo-win\docs\windows-handoff-2026-03-13.md`
- `H:\demo-win\docs\cross-review-2026-03-14.md`
- `H:\demo-win\docs\windows-wsl-roundtrip.md`

---

## 5. Current Risks and Gaps

The main gaps are now coordination and quality gaps, not missing mainline functionality.

Current issues:

- documentation still needs to stay synchronized across two repos
- shared inbox configuration is aligned by env var now, but not yet enforced by CI or deployment tooling
- duplicated metadata and platform extraction logic still exists across Windows and WSL, although WSL now prefers Windows hints for title/author/published_at and preserves filtered handoff context in normalized output
- a reproducible roundtrip exists, but it is not yet promoted into CI automation
- no CI configuration in either repo
- no explicit `SIGTERM` handling in the watcher path
- `OpenClawAdapter` is still a stub
- `codex-demo` still has no initial commit history

---

## 6. Current Recommended Order

The current recommended order is:

1. keep the repository docs true to the actual two-repo state
2. keep the shared inbox env-var contract stable across both repos
3. promote the reproducible roundtrip into a more automated integration check when practical
4. decide the longer-term metadata contract for hints vs reparsing
5. only then consider deeper parser deduplication or larger refactors

---

## 7. Verified Tests

Verified on 2026-03-14:

- Windows client: `33` unit tests passed
- WSL processor: `22` unit tests passed

---

## 8. Review Entry Points

For a fast review of the current true state, read in this order:

1. `README.md`
2. `docs/project-status.md`
3. `docs/cross-repo-collaboration.md`
4. `docs/inbox-protocol.md`
5. `docs/wsl-e2e-guide.md`
6. `H:\demo-win\docs\cross-review-2026-03-14.md`
7. `H:\demo-win\docs\windows-wsl-roundtrip.md`
