# `content-ingestion` Inbox Protocol v0.1

## 1. 目标

本协议定义 Windows Client 与 WSL Processor 之间的正式交接边界。

第一版目标是：

- 让 Windows 端稳定导出 job
- 让 WSL 端稳定发现并接管 job
- 让处理结果明确落入 `processed/` 或 `failed/`
- 优先保证低歧义、可回放、可排错

---

## 2. 目录结构

共享目录第一版约定如下：

```text
shared_inbox/
  incoming/
    <job_id>/
      metadata.json
      payload.html | payload.txt | payload.md
      READY
  processing/
    <job_id>/
      metadata.json
      payload.*
      READY
  processed/
    <job_id>/
      metadata.json
      payload.*
      normalized.json
      normalized.md
      pipeline.json
      status.json
  failed/
    <job_id>/
      metadata.json
      payload.*
      error.json
      status.json
```

约束：

- `job_id` 必须全局唯一
- 每个 job 目录只允许一个主 payload
- payload 文件名固定为 `payload.<ext>`
- `metadata.json` 必须存在
- `READY` 由 Windows 在所有文件写完后最后创建
- `processing/` 目录仅供 WSL 抢占和处理中转使用

---

## 3. Job 命名规则

建议 `job_id` 格式：

```text
YYYYMMDD_HHMMSS_<suffix>
```

示例：

```text
20260312_153000_ab12cd
```

---

## 4. Windows 写入协议

Windows Client 必须按以下顺序写入：

1. 创建 `incoming/<job_id>/`
2. 写入 `payload.<ext>`
3. 写入 `metadata.json`
4. 确认所有文件已落盘
5. 最后创建空文件 `READY`

Windows 第一版只负责写入 `incoming/`，不负责写入 `processing/`、`processed/`、`failed/`。

---

## 5. WSL 接管协议

WSL Processor 仅处理满足以下条件的 job：

- 目录位于 `incoming/`
- 存在 `metadata.json`
- 存在 `payload.html`、`payload.txt` 或 `payload.md`
- 存在 `READY`

接管规则：

1. 扫描 `incoming/`
2. 找到符合条件的 `job_id`
3. 将整个目录原子移动到 `processing/<job_id>/`
4. 如果移动成功，则当前实例获得处理权
5. 如果移动失败或源目录已不存在，则说明已被其他实例接管，直接跳过

第一版不依赖额外文件锁，采用 `READY + move` 即可。

---

## 6. Metadata 规范

`metadata.json` 第一版最小字段：

```json
{
  "job_id": "20260312_153000_ab12cd",
  "source_url": "https://example.com/article",
  "platform": "wechat",
  "collector": "windows-client",
  "collected_at": "2026-03-12T15:30:00+08:00",
  "content_type": "html",
  "title_hint": null,
  "author_hint": null
}
```

必填字段建议为：

- `job_id`
- `source_url`
- `collector`
- `collected_at`
- `content_type`

---

## 7. 第一版输出约定

成功处理后，WSL 将 job 输出到 `processed/<job_id>/`：

- `metadata.json`
- `payload.*`
- `normalized.json`
- `normalized.md`
- `pipeline.json`
- `status.json`

处理失败后，WSL 将 job 输出到 `failed/<job_id>/`：

- `metadata.json`
- `payload.*`
- `error.json`
- `status.json`

---

## 8. 状态与错误文件

`status.json` 第一版至少包含：

```json
{
  "job_id": "20260312_153000_ab12cd",
  "status": "success",
  "stage": "normalized",
  "processor": "wsl-processor",
  "processor_version": "0.1.0",
  "content_type": "html",
  "payload_filename": "payload.html",
  "source_url": "https://example.com/article",
  "started_at": "2026-03-12T15:59:58+08:00",
  "processed_at": "2026-03-12T16:00:00+08:00"
}
```

`error.json` 第一版至少包含：

```json
{
  "job_id": "20260312_153000_ab12cd",
  "stage": "process",
  "error_code": "job_protocol_error",
  "error_message": "metadata.json missing required fields: collector, collected_at, content_type",
  "processor": "wsl-processor",
  "processor_version": "0.1.0",
  "payload_filename": "payload.txt",
  "content_type": null,
  "source_url": "https://example.com/article",
  "started_at": "2026-03-12T15:59:58+08:00",
  "failed_at": "2026-03-12T16:00:00+08:00"
}
```

`pipeline.json` 第一版建议包含：

```json
{
  "job_id": "20260312_153000_ab12cd",
  "status": "success",
  "started_at": "2026-03-12T15:59:58+08:00",
  "finished_at": "2026-03-12T16:00:00+08:00",
  "payload_filename": "payload.html",
  "content_type": "html",
  "steps": [
    {"name": "load_metadata", "status": "success"},
    {"name": "parse_payload", "status": "success"},
    {"name": "write_outputs", "status": "success"}
  ]
}
```

---

## 9. 第一版范围约束

第一版协议只保证：

- 单 job 单 payload
- 单机共享目录交接
- watcher 或轮询接管
- 成功 / 失败双输出目录

第一版暂不保证：

- 自动重试
- 并发调度策略
- 崩溃恢复到中间阶段
- 多 payload 合并
- 高质量内容抽取
