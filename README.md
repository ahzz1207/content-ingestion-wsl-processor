# content-ingestion

`content-ingestion` is a two-part system:

- a `Windows Client` in `H:\demo-win` for URL intake, page capture, metadata hints, and shared inbox job export
- a `WSL Processor` in `~/codex-demo` for inbox takeover, normalization, processed/failed outputs, and downstream pipeline hooks

The current repository is the WSL-side processor codebase.

## Product direction

The main path is now:

```text
Windows URL input or browser capture
  -> Windows export job
  -> shared_inbox/incoming/<job_id>/
  -> WSL watch-inbox or process-job
  -> normalized outputs in processed/
  -> downstream pipeline integration
```

Direct platform login/fetch inside the WSL repository should be treated as experimental support code, not the primary path.

## Documents

- Project status: `docs/project-status.md`
- Cross-repo collaboration: `docs/cross-repo-collaboration.md`
- Architecture: `docs/architecture.md`
- Inbox protocol: `docs/inbox-protocol.md`
- Windows job export: `docs/windows-job-export.md`
- WSL MVP plan: `docs/wsl-mvp-plan.md`
- WSL E2E guide: `docs/wsl-e2e-guide.md`
- Review fixes: `docs/review-fixes-2026-03-12.md`

## Shared inbox configuration

Both repos should now prefer the same environment variable:

- `CONTENT_INGESTION_SHARED_INBOX_ROOT`

Explicit CLI paths still override the environment variable.

## Current repository status

This repository currently contains:

- inbox protocol, watcher, and processor
- html / txt / markdown raw parsers
- normalization helpers and artifact output writing
- processed / failed output generation
- validation commands for single jobs and inbox scans
- an OpenClaw adapter scaffold
- legacy `sources/` and `session/` code kept as experimental/frozen support paths

## Current priorities

The next practical priorities for this repository are:

- keep repository docs aligned with the actual two-repo system state
- keep the shared inbox env-var contract stable across both repos
- keep the reproducible Windows -> WSL roundtrip path healthy and later automate it in CI
- decide the longer-term metadata contract for Windows hints vs WSL reparsing
