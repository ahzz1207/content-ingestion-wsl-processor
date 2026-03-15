# `content-ingestion` Architecture v0.2

## 1. 总体架构

```text
[Windows Client]
GUI
  ->
Collector Service
  ->
Browser / Manual Export / Platform Adapter
  ->
Shared Inbox (Windows <-> WSL)

[WSL Processor]
Inbox Watcher
  ->
Job Loader
  ->
Raw Parser
  ->
Normalizer
  ->
Artifact Store
  ->
OpenClaw Adapter
```

---

## 2. 子系统划分

### 2.1 Windows Client

建议职责：

- URL 输入
- 任务创建
- 原始文件保存
- metadata 写入
- 结果文件浏览
- 总结和归档查看
- 可选触发 `wsl.exe` 命令

推荐未来目录：

```text
windows-client/
  app/
  collector/
  views/
  storage/
```

### 2.2 WSL Processor

当前仓库演进方向：

```text
src/content_ingestion/
  app/
  core/
  inbox/
  raw/
  normalize/
  storage/
  pipeline/
  sources/        # experimental
  session/        # experimental
```

---

## 3. WSL 处理链

### 3.1 Inbox Watcher

负责：

- 轮询或监听 `incoming/`
- 找到尚未处理的 `job_id`
- 校验 `READY`、`metadata.json`、`payload.*`
- 原子移动到 `processing/`
- 调用 processor

建议模块：

- `inbox/watcher.py`
- `inbox/protocol.py`

### 3.2 Job Processor

负责：

- 读取 `payload.*`
- 读取 `metadata.json`
- 调用合适的 raw parser
- 生成 `ContentAsset`
- 调用 normalize / artifact / pipeline

建议模块：

- `inbox/processor.py`

### 3.3 Raw Parser

负责：

- `html -> ContentDraft`
- `txt -> ContentDraft`
- `md -> ContentDraft`
- metadata 合并

建议模块：

- `raw/html_parser.py`
- `raw/text_parser.py`
- `raw/markdown_parser.py`
- `raw/meta_loader.py`

### 3.4 Normalize

负责：

- 文本清洗
- markdown 生成
- metadata 补齐

已有模块可继续沿用：

- `normalize/cleaning.py`
- `normalize/markdown.py`
- `normalize/metadata.py`

### 3.5 Artifact Store

负责：

- 输出 `normalized.md`
- 输出 `normalized.json`
- 输出处理状态文件

已有模块可继续扩展：

- `storage/artifact_store.py`

### 3.6 OpenClaw Adapter

负责：

- 将 `ContentAsset` 转成 OpenClaw 输入
- 记录任务结果

已有模块可继续沿用：

- `pipeline/openclaw_adapter.py`

---

## 4. 数据协议

### 4.1 Incoming Job

```text
incoming/<job_id>/
  payload.html | payload.txt | payload.md
  metadata.json
  READY
```

### 4.2 Processing Job

```text
processing/<job_id>/
  payload.html | payload.txt | payload.md
  metadata.json
  READY
```

### 4.3 Processed Job

```text
processed/<job_id>/
  metadata.json
  payload.*
  normalized.md
  normalized.json
  pipeline.json
  status.json
```

### 4.4 Failed Job

```text
failed/<job_id>/
  payload.*
  metadata.json
  error.json
  status.json
```

### 4.5 接管规则

- Windows 必须最后写入 `READY`
- WSL 只处理存在 `READY` 的 job
- WSL 通过将目录移动到 `processing/` 来抢占处理权
- `processing/` 只用于处理中转，不作为最终输出

---

## 5. 现有系统如何调整

### 5.1 保留的部分

- `core/models.py`
- `core/exceptions.py`
- `normalize/*`
- `storage/artifact_store.py`
- `pipeline/openclaw_adapter.py`

这些都是 WSL 处理器的稳定基础。

### 5.2 降级为实验性的部分

- `sources/wechat/*`
- `session/*`
- `fetch/login` 这类直接抓平台页面的流程

这些可以保留，但不再作为主路径。

### 5.3 下一步必须新增的部分

- `app`：
  - `watch-inbox`
  - `process-job`
- `inbox/`
  - watcher
  - processor
  - protocol
- `raw/`
  - html parser
  - text parser
  - markdown parser
  - metadata loader

---

## 6. 推荐 CLI 变更

WSL 主路径应逐步调整为：

```bash
python3 main.py watch-inbox /mnt/c/Users/<user>/Documents/content_ingestion_inbox
python3 main.py process-job /mnt/c/Users/<user>/Documents/content_ingestion_inbox/processing/<job_id>
python3 main.py doctor
```

原有命令：

- `login`
- `fetch`
- `ingest`

应保留为实验性命令，后续可以隐藏到 `experimental` 分组。

---

## 7. Windows 与 WSL 的连接方式

推荐两种方式：

### 方式 A：Watcher 模式

- Windows 客户端只负责写入共享目录
- WSL 长驻 watcher 自动处理

优点：

- 耦合低
- 实现简单

### 方式 B：主动触发模式

- Windows 客户端写入后直接调用：
  - `wsl.exe bash -lc "cd ... && python3 main.py watch-inbox <shared_inbox> --once"`

优点：

- 用户等待更短
- 任务反馈更直接

建议：

- 第一阶段先做 `Watcher`
- 第二阶段再加主动触发

---

## 8. 当前推荐实现顺序

1. 把 PRD 和 README 改成 Windows Client + WSL Processor 版本
2. 定义 `incoming/processing/processed/failed` 协议
3. 实现 `watch-inbox`
4. 实现 `process-job`
5. 实现 `raw/*` 解析层
6. 最后再考虑 Windows GUI 原型
