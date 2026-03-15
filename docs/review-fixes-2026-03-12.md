# Review Fixes — 2026-03-12

## 范围

本文件记录对 [`docs/code-review-2026-03-12.md`](/home/ahzz1207/codex-demo/docs/code-review-2026-03-12.md) 中问题的处理结果。

---

## 已修复

### 1. watcher 跨文件系统移动

问题：

- `claim_job()` 原先使用 `Path.rename()`
- 在 Windows / WSL 联调时，跨文件系统移动可能失败

处理：

- 已改为 `shutil.move()`
- 位置：`src/content_ingestion/inbox/watcher.py`

### 2. watcher 存活性保护

问题：

- `watch()` 循环原先无外围异常处理
- 一次扫描异常可能导致 watcher 整体退出

处理：

- 已在循环中加入 `try/except`
- 异常时记录日志并继续运行
- 位置：`src/content_ingestion/inbox/watcher.py`

### 3. incoming 扫描竞态保护

问题：

- 扫描 `incoming/` 时目录可能瞬时消失

处理：

- 已对 `iterdir()` 增加 `FileNotFoundError` 保护
- 位置：`src/content_ingestion/inbox/protocol.py`

### 4. processor 静默覆盖已有结果

问题：

- `_move_job()` 会删除已有 `processed/failed` 目录

处理：

- 已改为拒绝覆盖
- 目标目录存在时抛 `JobProtocolError`
- 位置：`src/content_ingestion/inbox/processor.py`

### 5. failure 路径兜底增强

问题：

- failure 分支如果移动失败或写失败，原先缺少额外保护

处理：

- 已拆出 `_handle_failure()`
- 分别对 move 失败和 failure-output 写失败记录日志
- 位置：`src/content_ingestion/inbox/processor.py`

### 6. markdown payload 被模板覆盖

问题：

- `payload.md` 原始 markdown 会被 `render_markdown()` 覆盖

处理：

- 只有在 `asset.content_markdown` 为空时才调用 `render_markdown()`
- markdown payload 现在保留原始内容
- 位置：`src/content_ingestion/inbox/processor.py`

### 7. language 默认值误标

问题：

- `ContentAsset.language` 默认值硬编码为 `"zh-CN"`

处理：

- 已改为 `None`
- 位置：`src/content_ingestion/core/models.py`

### 8. markdown/text 清洗策略区分

问题：

- 原 `clean_text()` 会把所有非空行重组为双换行
- 对 markdown 内容会破坏原有结构

处理：

- 保留 `clean_text()` 作为通用清洗
- 新增 `clean_plaintext()` 和 `clean_markdown_text()`
- markdown parser 改为保留原有换行结构
- 位置：`src/content_ingestion/normalize/cleaning.py`
- 位置：`src/content_ingestion/raw/markdown_parser.py`
- 位置：`src/content_ingestion/raw/text_parser.py`

### 9. FetchStatus 枚举部分回收使用

问题：

- `service.py` 里有字符串字面量状态码

处理：

- `auth_required` 路径已改为 `FetchStatus.AUTH_REQUIRED.value`
- 位置：`src/content_ingestion/app/service.py`

### 10. 测试断言增强

处理：

- 增加了 `status.json` / `error.json` 内容断言
- 增加了 markdown 原文保留断言
- 增加了拒绝覆盖已有结果目录的断言
- 位置：`tests/unit/test_inbox_processor.py`
- 位置：`tests/unit/test_inbox_watcher.py`
- 位置：`tests/unit/test_raw_parsers.py`

---

## 部分处理 / 暂未处理

### 1. `watch-inbox` 优雅退出

状态：

- 已在 service 层捕获 `KeyboardInterrupt`
- CLI 会打印 `watcher_stopped=keyboard_interrupt`

限制：

- 目前还没有 `SIGTERM` handler
- 也没有更细粒度的 shutdown hook

### 2. `FetchStatus` 全量统一

状态：

- 当前只回收了已 review 指出的 service 路径

限制：

- 还没有把所有状态写入和 processor/pipeline 状态统一建模

### 3. sys.path 风格统一

状态：

- 本轮未处理

原因：

- 不影响当前主路径稳定性
- 优先级低于 inbox / watcher / processor 问题

---

## 验证结果

- `pytest` 已通过
- markdown payload 的 `normalized.md` 已验证保留原始 markdown
