# `content-ingestion` WSL E2E Guide

## 1. 目标

本指南用于本地验证 WSL 侧是否能正确处理一个符合协议的 Windows 导出 job。

---

## 2. 使用现成 sample job

仓库中提供了一个现成样例：

- `tests/fixtures/inbox_jobs/incoming/20260312_193000_sample_wechat_html/`

---

## 3. 操作步骤

### 3.1 准备临时 shared inbox

```bash
rm -rf /tmp/content-ingestion-e2e
mkdir -p /tmp/content-ingestion-e2e/shared_inbox/incoming
```

### 3.2 复制 sample job

```bash
cp -R tests/fixtures/inbox_jobs/incoming/20260312_193000_sample_wechat_html \
  /tmp/content-ingestion-e2e/shared_inbox/incoming/
```

### 3.3 处理前先校验 job

在执行处理前，先检查复制进去的 job 是否符合协议：

```bash
python3 main.py validate-job /tmp/content-ingestion-e2e/shared_inbox/incoming/20260312_193000_sample_wechat_html
```

期望结果：

- 输出 JSON
- `is_valid` 为 `true`

注意：

- `validate-job` 这里必须在 `watch-inbox --once` 之前执行
- 一旦执行处理，job 会被移动到 `processed/` 或 `failed/`
- 如果需要再次校验 `incoming/` 下的同一个样例，需要重新复制一份 sample job

### 3.4 执行一次处理

```bash
python3 main.py watch-inbox /tmp/content-ingestion-e2e/shared_inbox --once
```

期望输出：

```text
job_output=/tmp/content-ingestion-e2e/shared_inbox/processed/20260312_193000_sample_wechat_html
```

### 3.5 检查结果

```bash
find /tmp/content-ingestion-e2e/shared_inbox -maxdepth 3 -type f | sort
```

期望在 `processed/<job_id>/` 中看到：

- `metadata.json`
- `payload.html`
- `normalized.json`
- `normalized.md`
- `pipeline.json`
- `status.json`

---

## 4. 核对重点

建议重点检查：

- `normalized.md` 是否可读
- `normalized.json` 是否保留核心 asset 字段
- `pipeline.json` 是否记录了步骤
- `status.json` 是否带有 `processor`、`content_type`、`payload_filename`

---

## 5. 批量校验补充

除了校验单个 job，也可以批量检查整个 inbox：

```bash
python3 main.py validate-inbox /tmp/content-ingestion-e2e/shared_inbox
```

如果 `is_valid` 为 `false`，优先先修 Windows 导出侧，再做处理联调。

---

## 6. 当前用途

这份指南主要用于：

- 本地回归验证
- Windows / WSL 联调前置检查
- 后续 Windows 导出器开发时的验收基线
