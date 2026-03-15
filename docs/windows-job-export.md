# `content-ingestion` Windows Job Export Spec v0.1

## 1. 目标

本文件定义 Windows Client 第一版如何把一次 URL 采集结果导出为 WSL 可接管的 job。

目标是让 Windows 端只需遵守固定导出格式，WSL 端即可直接处理，不需要额外适配。

---

## 2. 当前整体思路

当前项目按运行环境拆分为两个明确部分：

- `Windows Client`
  - 接收 URL 输入
  - 在 Windows 浏览器环境中完成内容采集
  - 将采集结果导出为 job 目录
- `WSL Processor`
  - 监听共享目录
  - 接管已完成 job
  - 产出 `processed/` 或 `failed/`

当前仓库只实现 `WSL Processor`，但 Windows 导出格式必须现在就定清楚，因为它是两边唯一正式边界。

---

## 3. 导出目标目录

Windows Client 需要把 job 写入共享根目录下的 `incoming/`：

```text
shared_inbox/
  incoming/
    <job_id>/
      payload.html | payload.txt | payload.md
      metadata.json
      READY
```

WSL 不要求 Windows 写入 `processing/`、`processed/`、`failed/`。

---

## 4. Job 生成规则

### 4.1 `job_id`

建议格式：

```text
YYYYMMDD_HHMMSS_<suffix>
```

示例：

```text
20260312_193000_ab12cd
```

要求：

- 对单机场景保持唯一
- 与 `metadata.json.job_id` 完全一致

### 4.2 payload 文件

第一版只允许一个 payload 文件，文件名固定：

- `payload.html`
- `payload.txt`
- `payload.md`

Windows 端根据采集结果选择其中一种。

### 4.3 metadata 文件

文件名固定为：

```text
metadata.json
```

### 4.4 完成标记

文件名固定为：

```text
READY
```

这是一个空文件，由 Windows 在所有内容写完后最后创建。

---

## 5. Windows 写入顺序

必须严格按下面顺序执行：

1. 创建 `incoming/<job_id>/`
2. 写入 `payload.<ext>`
3. 写入 `metadata.json`
4. flush / close 所有文件
5. 最后创建 `READY`

如果 `READY` 提前出现，WSL 可能会读到半写入状态的 job。

---

## 6. Metadata 最小字段

第一版建议写入：

```json
{
  "job_id": "20260312_193000_ab12cd",
  "source_url": "https://example.com/article",
  "platform": "wechat",
  "collector": "windows-client",
  "collected_at": "2026-03-12T19:30:00+08:00",
  "content_type": "html",
  "title_hint": "Optional title",
  "author_hint": "Optional author"
}
```

必填字段：

- `job_id`
- `source_url`
- `collector`
- `collected_at`
- `content_type`

推荐约束：

- `collector` 第一版固定为 `windows-client`
- `content_type` 与 payload 后缀保持一致
- `collected_at` 使用 ISO 8601

---

## 7. Windows 端导出策略建议

第一版建议遵守这些策略：

- 优先保留最原始内容，不要在 Windows 端提前做重清洗
- 如果采集到的是完整 DOM，优先导出 `payload.html`
- 如果只能拿到纯文本，再导出 `payload.txt`
- 如果采集工具本身已经产出结构化 markdown，再导出 `payload.md`

第一版不建议：

- 一个 job 同时写多个 payload
- 在 Windows 端写入 `status.json` 或 `error.json`
- 在 Windows 端预测 WSL 处理结果

---

## 8. 联调样例

仓库中已有一个可用于联调的 sample job：

- `tests/fixtures/inbox_jobs/incoming/20260312_193000_sample_wechat_html/`

可用它验证：

- 目录结构是否符合协议
- `watch-inbox --once` 是否能顺利接管
- WSL 输出是否符合预期

---

## 9. 当前建议

在开始 Windows GUI 开发之前，建议先做一个最小 Windows 导出器原型，只需要完成：

1. 输入一个 URL
2. 导出一个符合本规范的 job 目录
3. 让 WSL `watch-inbox --once` 能成功处理

这能最快验证 Windows / WSL 的真实边界是否正确。

配套验收清单：

- `docs/windows-exporter-checklist.md`
