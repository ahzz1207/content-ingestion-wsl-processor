# `content-ingestion` WSL MVP Plan v0.1

## 1. 目标

WSL 第一版只交付一个稳定的最小闭环：

```text
watch-inbox
  -> claim incoming job
  -> process payload + metadata
  -> write processed/failed outputs
```

第一版优先保证：

- 共享目录协议落地
- job 抢占与流转稳定
- 成功 / 失败结果可追踪

第一版暂不追求：

- 高质量内容抽取
- 并发调度
- 自动重试
- 崩溃恢复

---

## 2. 范围

### 2.1 本轮实现

- 新增 `inbox/` 模块
- 新增 `raw/` 模块
- 新增 `watch-inbox` CLI
- 新增 `process-job` CLI
- 支持 `payload.html`、`payload.txt`、`payload.md`
- 输出 `processed/<job_id>/` 或 `failed/<job_id>/`

### 2.2 本轮不实现

- Windows 端采集逻辑
- 旧 `fetch/login/ingest` 路径重构
- OpenClaw 深度集成优化
- 文件系统事件监听优化

---

## 3. 模块拆分

### 3.1 `inbox/protocol.py`

负责：

- 定义目录名和文件名常量
- 定义 metadata/status/error 的最小结构
- 校验 job 目录是否符合协议
- 定位 payload 文件

### 3.2 `inbox/watcher.py`

负责：

- 扫描 `incoming/`
- 过滤未完成 job
- 抢占 job 到 `processing/`
- 为 CLI 提供单次扫描和持续轮询能力

### 3.3 `inbox/processor.py`

负责：

- 从 `processing/<job_id>` 读取 job
- 调用 raw parser
- 组装 `ContentAsset`
- 写入 `processed/` 或 `failed/`

### 3.4 `raw/*`

负责：

- `html`、`txt`、`md` 三类 payload 的最小解析
- 将 metadata hint 合并进 `ContentAsset`
- 第一版只做基础抽取，不做平台定制优化

---

## 4. 交付顺序

1. 先落协议辅助代码
2. 再落 raw parser
3. 再落 processor
4. 再接 CLI
5. 最后补测试和一次端到端验证

---

## 5. CLI 设计

### 5.1 `watch-inbox`

用途：

- 扫描共享目录
- 抢占符合条件的 job
- 串行处理每个 job

建议参数：

```bash
python3 main.py watch-inbox /path/to/shared_inbox
python3 main.py watch-inbox /path/to/shared_inbox --once
python3 main.py watch-inbox /path/to/shared_inbox --interval-seconds 5
```

第一版支持：

- `--once`
- `--interval-seconds`

### 5.2 `process-job`

用途：

- 手动处理某个已进入 `processing/` 的 job
- 便于测试和调试

建议参数：

```bash
python3 main.py process-job /path/to/shared_inbox/processing/<job_id>
```

---

## 6. 第一版成功标准

以下场景成立即可认为本轮完成：

1. `incoming/<job_id>/` 下存在 `payload.*`、`metadata.json`、`READY`
2. `watch-inbox --once` 能发现该 job
3. job 被移动到 `processing/`
4. 处理成功时写入 `processed/<job_id>/`
5. 处理失败时写入 `failed/<job_id>/`
6. `status.json` 或 `error.json` 能说明结果

---

## 7. 测试策略

本轮至少补这几类测试：

- 协议校验与 payload 定位
- watcher 抢占 job
- `txt` / `md` / `html` 最小解析
- processor 成功输出
- processor 失败输出

---

## 8. 后续阶段

本轮完成后，下一阶段再考虑：

- 更强的 HTML 抽取
- OpenClaw 输出细化
- 失败重试
- Windows 端与 WSL 的联调
