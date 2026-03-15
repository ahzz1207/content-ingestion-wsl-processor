# Code Review — 2026-03-12

Reviewer: Claude Opus 4.6 (acting as project reviewer)

Review scope: 全量代码 + 全量测试，基于 WSL MVP 第一版已完成状态。

---

## 0. 测试结果

- 11/11 passed, 0.02s
- 无警告、无跳过

---

## 1. 整体评价

Codex 交付的 WSL MVP 第一版质量整体不错：

- 模块划分清晰，inbox / raw / normalize / pipeline 各司其职
- 协议实现与文档（inbox-protocol.md、wsl-mvp-plan.md）一致
- 测试覆盖了主链路关键路径
- MVP 边界把控得当，旧 experimental 链路正确冻结

以下按严重程度分级列出需要关注的问题。

---

## 2. P0 — 潜在数据丢失 / 安全风险

### 2.1 `_move_job` 静默覆盖已有结果

文件: `src/content_ingestion/inbox/processor.py:42-43`

```python
def _move_job(self, source_dir: Path, target_dir: Path) -> Path:
    if target_dir.exists():
        shutil.rmtree(target_dir)  # 静默删除已有的 processed/failed 结果
    return Path(shutil.move(str(source_dir), str(target_dir)))
```

问题: 如果同一个 `job_id` 被重复提交（Windows 端 bug 或人为操作），已有的处理结果会被无声删除。

建议: 至少加一条 `logging.warning`；更稳妥的做法是 rename 原有目录加时间戳后缀，或直接拒绝覆盖并报错。

### 2.2 `_write_failure_outputs` 自身可能失败导致僵尸 job

文件: `src/content_ingestion/inbox/processor.py:36-39`

```python
except Exception as exc:
    target_dir = self._move_job(job.job_dir, job.failed_dir)
    self._write_failure_outputs(target_dir, job.job_id, exc)
    return target_dir
```

问题: `process()` 的 `except Exception` 分支调用了 `_move_job` + `_write_failure_outputs`，但如果此时 `_move_job` 本身也失败（磁盘满、权限问题等），异常会逃逸且无 fallback，job 留在 `processing/` 成为僵尸。

建议: 在 failure 路径内部再加一层 try/except，至少记录日志，确保不会无声丢失错误信息。

---

## 3. P1 — 逻辑缺陷

### 3.1 `claim_job` 使用 `Path.rename()` 不支持跨文件系统

文件: `src/content_ingestion/inbox/watcher.py:25`

```python
return job.job_dir.rename(target)
```

问题: `Path.rename()` 在 Linux 上只能在同一文件系统内工作。真实的 Windows-WSL 联调场景中，`incoming/` 可能位于 `/mnt/c/`（Windows NTFS），`processing/` 可能在 WSL 本地 ext4 上，此时会抛 `OSError`。

建议: 改用 `shutil.move` 作为实现，或先尝试 `rename` 再 fallback 到 `shutil.move`。这个问题在真实联调中大概率会踩到。

### 3.2 `watch` 循环没有任何异常处理

文件: `src/content_ingestion/inbox/watcher.py:38-41`

```python
def watch(self, interval_seconds: float) -> None:
    while True:
        self.scan_once()
        time.sleep(interval_seconds)
```

问题: `scan_once` 内部 processor 有 try/except，但 `claim_job` 或 `iter_incoming_jobs`（如权限错误、目录被删）抛异常会直接终止整个 watcher。

建议: 在 `watch` 的 while 循环内加 try/except，捕获非致命异常后 log + continue，保持 watcher 存活。

### 3.3 `iter_incoming_jobs` 存在竞态条件

文件: `src/content_ingestion/inbox/protocol.py:89`

```python
for child in sorted(paths.incoming.iterdir()):
```

问题: 虽然 `ensure_shared_inbox` 会创建目录，但如果在扫描一瞬间目录被外部删除，`iterdir()` 会抛 `FileNotFoundError`。

建议: 用 try/except 包裹 `iterdir()` 调用，或在调用前重新检查目录存在性。

---

## 4. P2 — 设计 / 可靠性建议

### 4.1 `language` 默认硬编码 `"zh-CN"`

文件: `src/content_ingestion/core/models.py:17`

```python
language: str | None = "zh-CN"
```

问题: 协议未对 language 做约束。未来接入英文或其他语言内容时，默认值会导致误标。

建议: 改为 `None`，由各 parser 根据实际内容或 metadata 显式设置。

### 4.2 `clean_text` 会破坏 markdown 结构

文件: `src/content_ingestion/normalize/cleaning.py:1-4`

```python
def clean_text(value: str) -> str:
    lines = [line.strip() for line in value.splitlines()]
    non_empty = [line for line in lines if line]
    return "\n\n".join(non_empty)
```

问题: 所有非空行用 `\n\n` 拼接，原本用单换行分隔的列表项、代码块等会被拆成多段。`markdown_parser` 也调用了 `clean_text` 来生成 `content_text`，markdown 原始结构会被破坏。

建议: 对 markdown 类型的 payload，考虑使用不同的清洗策略，或仅对 `content_text` 做清洗而保留 `content_markdown` 不变。

### 4.3 `render_markdown` 会覆盖 markdown payload 的原始内容

文件: `src/content_ingestion/inbox/processor.py:32`

```python
asset.content_markdown = render_markdown(asset)
```

问题: `markdown_parser` 已经把原始 markdown 存进了 `asset.content_markdown`，但 processor 无条件用 `render_markdown` 覆盖。对 `payload.md` 来说，最终输出的 markdown 是生成的模板，丢失了原始格式。

建议: 在 processor 中增加判断：如果 `asset.content_markdown` 已经有值，则跳过 `render_markdown`；或者用原始值作为 `normalized.md` 的输出。

### 4.4 `FetchStatus` 枚举定义了但未在代码中使用

文件: `src/content_ingestion/core/enums.py`

问题: 定义了 `FetchStatus` 枚举（`OK`, `AUTH_REQUIRED`, `NOT_SUPPORTED`, `FAILED`），但 `service.py` 中的状态码全部使用字符串字面量，未引用此枚举。

建议: 要么统一使用枚举，要么在确认不需要后删除，避免代码与实际行为不一致。

---

## 5. P3 — 代码卫生

### 5.1 `_optional_str` 重复定义 3 次

文件:
- `src/content_ingestion/raw/html_parser.py:53`
- `src/content_ingestion/raw/text_parser.py:29`
- `src/content_ingestion/raw/markdown_parser.py:30`

建议: 提取到 `raw/__init__.py` 或公共工具模块中。

### 5.2 `sys.path` hack 重复

文件:
- `tests/conftest.py:4` — `ROOT = Path(__file__).resolve().parents[1]`
- `main.py:4` — `PROJECT_ROOT = Path(__file__).resolve().parent`

问题: 两处逻辑一致但写法不统一。

建议: 统一风格即可，非阻塞问题。

### 5.3 `watch-inbox` 非 `--once` 模式无法优雅退出

文件: `src/content_ingestion/app/service.py:147-148`

```python
watcher.watch(interval_seconds=interval_seconds)
return []  # 永远不会执行到
```

问题: `watch()` 是 `while True` 死循环，`return []` 是死代码。CLI 层会 hang，没有 signal handler 支持 Ctrl+C 优雅退出。

建议: 后续增加 `SIGINT`/`SIGTERM` handler，或改为有限次轮询 + 退出条件。

---

## 6. 测试层面建议

当前测试覆盖了"文件是否生成"，但缺少对**文件内容正确性**的断言。例如：

- `test_job_processor_writes_processed_outputs` 没有验证 `status.json` 中 `status` 是否为 `"success"`
- `test_job_processor_moves_invalid_job_to_failed` 没有验证 `error.json` 中 `error_code` 是否正确
- 缺少 `payload.md` 和 `payload.txt` 的 processor 端到端测试（目前只有 `payload.txt` 的成功路径）
- 缺少 `render_markdown` 的单元测试

建议: 在现有测试中增加 `json.loads` + 字段断言，补充 md/html payload 的 processor 级测试。

---

## 7. 建议修复优先级

| 顺序 | 问题编号 | 理由 |
|------|----------|------|
| 1 | 3.1 | 跨文件系统 rename — Windows-WSL 联调必踩，修复成本低 |
| 2 | 2.1 | 静默覆盖 — 加一行 warning 即可，防止数据丢失 |
| 3 | 2.2 | failure 路径保护 — 加内层 try/except + logging |
| 4 | 3.2 | watcher 异常保护 — 保证长期运行稳定性 |
| 5 | 4.3 | render_markdown 覆盖问题 — 影响 md payload 输出质量 |
| 6 | 其余 | 按迭代节奏逐步处理 |

---

*Review completed at 2026-03-12. Next review will be scheduled after fixes are applied.*
