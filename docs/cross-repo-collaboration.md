# `content-ingestion` Cross-Repo Collaboration

## 1. Purpose

This document explains how the two active repositories fit together:

- Windows client: `H:\demo-win`
- WSL processor: `~/codex-demo`

It is the top-level coordination document for deployment, operator expectations, and shared inbox usage.

---

## 2. Repository Responsibilities

### 2.1 Windows Client

The Windows repository owns:

- URL input and operator-facing commands
- HTTP or browser-based collection
- persistent browser profile warm-up and reuse
- metadata hint extraction
- hint-first metadata handoff for title, author, and published-at when provided
- writing protocol-valid jobs into `shared_inbox/incoming/<job_id>/`

It does not own:

- `processing/`, `processed/`, or `failed/` outputs
- normalization
- downstream pipeline execution

### 2.2 WSL Processor

The WSL repository owns:

- shared inbox validation and claim logic
- moving jobs from `incoming/` to `processing/`
- raw parsing of html / txt / markdown payloads
- writing `processed/` and `failed/` outputs
- normalized artifacts and pipeline metadata
- preserving a filtered subset of handoff collection context in `normalized.json` for downstream traceability

It does not own the primary URL collection path.

---

## 3. Shared Inbox Contract

Both repositories coordinate through the shared inbox protocol.

Directory shape:

```text
shared_inbox/
  incoming/
    <job_id>/
      payload.html | payload.txt | payload.md
      metadata.json
      READY
  processing/
  processed/
  failed/
```

Write/claim rules:

1. Windows writes payload first.
2. Windows writes `metadata.json` second.
3. Windows creates `READY` last.
4. WSL only processes jobs that contain `payload.*`, `metadata.json`, and `READY`.
5. WSL claims a job by moving it into `processing/`.
6. WSL writes filtered handoff context into `processed/<job_id>/normalized.json` instead of echoing the full incoming `metadata.json`.

---

## 4. Shared Inbox Configuration

Both repositories should prefer the same environment variable:

- `CONTENT_INGESTION_SHARED_INBOX_ROOT`

Current contract:

- if an explicit CLI shared inbox path is provided, it wins
- otherwise both repos fall back to `CONTENT_INGESTION_SHARED_INBOX_ROOT`
- if the env var is absent, each repo still falls back to its local default under `data/shared_inbox`

This gives a shared operator-facing contract without breaking existing CLI usage.

---

## 5. Current End-to-End Status

Verified current status:

- Windows mock export works
- Windows HTTP export works
- Windows browser export works
- real WeChat browser export has been validated
- WSL `watch-inbox --once` successfully processes valid exported jobs
- processed outputs are already being written successfully
- a reproducible roundtrip script now exists at `H:\demo-win\scripts\run_windows_wsl_roundtrip.ps1`
- that roundtrip now verifies `metadata.json -> normalized.json` alignment for canonical URL and filtered handoff context

The system should therefore be treated as an active cross-repo MVP, not as separate incomplete prototypes.

---

## 6. Operator Baseline

Common Windows-side commands:

```powershell
python main.py doctor
python main.py browser-login --start-url https://mp.weixin.qq.com/
python main.py export-url-job <url>
python main.py export-browser-job <url>
powershell -ExecutionPolicy Bypass -File ./scripts/run_windows_wsl_roundtrip.ps1
```

Common WSL-side commands:

```bash
python3 main.py doctor
python3 main.py validate-inbox [shared_root]
python3 main.py watch-inbox [shared_root] --once
python3 main.py process-job <shared_root>/processing/<job_id>
```

Example shared configuration:

```bash
export CONTENT_INGESTION_SHARED_INBOX_ROOT=/mnt/h/demo-win/data/shared_inbox
```

---

## 7. Current Coordination Priorities

The current priority order is:

1. keep docs aligned with the actual system state
2. keep the shared inbox env-var contract stable across both repos
3. automate the reproducible roundtrip more fully over time
4. continue reducing duplicated metadata extraction logic where payload reparsing is still unnecessary
5. decide whether legacy `sources/` and `session/` remain frozen or are formally retired

---

## 8. Related Documents

Read next if needed:

- `docs/project-status.md`
- `docs/inbox-protocol.md`
- `docs/wsl-e2e-guide.md`
- `H:\demo-win\docs\windows-client-kickoff.md`
- `H:\demo-win\docs\cross-review-2026-03-14.md`
- `H:\demo-win\docs\windows-wsl-handoff-contract.md`
- `H:\demo-win\docs\windows-wsl-roundtrip.md`
