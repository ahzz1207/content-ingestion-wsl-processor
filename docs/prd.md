# `content-ingestion` PRD v0.2

## 1. 项目定义

`content-ingestion` 是一个跨 Windows 与 WSL 协作的内容接入系统。

系统分为两个部分：

- `Windows Client`
  - 负责图形界面
  - 负责 URL 输入
  - 负责在用户真实浏览器环境中获取内容
  - 负责文件管理、总结查看、归档管理
- `WSL Processor`
  - 负责监听或定时处理 Windows 保存下来的原始文件
  - 负责标准化、结构化、归档、接入 OpenClaw

这个项目的核心不是在 WSL 里直接接管受限平台登录，而是把“内容获取”放在最适合的 Windows 侧，把“内容处理”放在最适合的 WSL 侧。

---

## 2. 目标与边界

### 2.1 一句话目标

让用户在 Windows 客户端输入一条 URL 后，系统能够自动完成内容获取、跨系统交接、标准化处理，并在客户端中查看整理后的结果和归档文件。

### 2.2 核心目标

1. Windows 端接收 URL 并获取内容。
2. Windows 端把原始内容与 metadata 写入共享收件箱。
3. WSL 端自动发现新文件并执行标准化处理。
4. WSL 端输出 markdown、json、OpenClaw 接入结果。
5. Windows 客户端能管理原始文件、处理结果、总结和归档内容。

### 2.3 非目标

以下内容不纳入当前阶段目标：

- 在 WSL 内直接完成微信读者登录流程
- 绕过平台登录限制或风控
- 自动读取公众号关注列表或订阅流
- 云端多租户部署
- 大规模分布式调度

---

## 3. 用户与场景

### 3.1 目标用户

第一阶段目标用户是单机使用的个人用户。

该用户具备以下特点：

- 日常使用 Windows 浏览器访问内容
- 后续处理链路运行在 WSL 中
- 需要一个统一界面管理内容、总结与归档

### 3.2 核心使用场景

#### 场景 A：输入 URL 并自动进入处理链

用户在 Windows 客户端输入一条 URL。

系统行为：

- 根据平台或内容形态获取原始内容
- 生成 `raw file + meta file`
- 保存到共享 inbox
- 通知或触发 WSL 处理器

#### 场景 B：WSL 自动处理新增文件

WSL 处理器持续监听或定时扫描共享 inbox。

系统行为：

- 检测新增内容包
- 解析原始文件
- 标准化为统一结构
- 产出 markdown、json
- 接入 OpenClaw

#### 场景 C：用户在 Windows 客户端查看结果

用户在 Windows 客户端浏览：

- 原始抓取文件
- 标准化内容
- 各类总结
- 已归档文件

---

## 4. 系统范围

### 4.1 Windows Client 职责

- 提供 GUI
- 接收 URL 输入
- 触发采集任务
- 将采集结果保存为原始文件
- 写入 metadata
- 管理原始文件和处理结果
- 展示总结与归档状态
- 可选触发 WSL 命令

### 4.2 WSL Processor 职责

- 监听或轮询共享 inbox
- 读取新增内容包
- 解析 html、txt、md 等原始文件
- 合并 metadata
- 生成标准 `ContentAsset`
- 输出标准化 json、markdown
- 调用 OpenClaw adapter

### 4.3 共享目录职责

共享目录是 Windows 与 WSL 之间的正式交接边界。

Windows 写入：

- 原始内容文件
- metadata 文件

WSL 读取并写回：

- 处理结果
- 状态标记
- 失败信息

---

## 5. 输入与输出

### 5.1 Windows 输入

- 单条 URL
- 可选平台标识
- 可选采集模式

### 5.2 Windows 输出

每次采集至少写入一个内容包：

```text
shared_inbox/
  incoming/
    20260312_001/
      payload.html | payload.txt | payload.md
      metadata.json
      READY
```

### 5.3 WSL 输入

- inbox 根目录
- 内容包目录
- 原始文件
- `metadata.json`
- `READY`

### 5.4 WSL 输出

```text
processed/
  20260312_001/
    metadata.json
    payload.*
    normalized.md
    normalized.json
    pipeline.json
    status.json
```

客户端最终可展示：

- 原始文件
- 标准化结果
- OpenClaw 任务结果
- 总结与归档内容

---

## 6. Inbox 协议

### 6.1 目录结构

建议约定如下：

```text
shared_inbox/
  incoming/
    <job_id>/
      payload.html | payload.txt | payload.md
      metadata.json
      READY
  processing/
    <job_id>/
      payload.*
      metadata.json
      READY
  processed/
    <job_id>/
      metadata.json
      payload.*
      normalized.md
      normalized.json
      pipeline.json
      status.json
  failed/
    <job_id>/
      payload.*
      metadata.json
      error.json
      status.json
```

### 6.2 Metadata 结构

`metadata.json` 第一版建议字段：

```json
{
  "job_id": "20260312_001",
  "source_url": "https://mp.weixin.qq.com/s/...",
  "platform": "wechat",
  "collector": "windows-client",
  "collected_at": "2026-03-12T10:00:00+08:00",
  "content_type": "html",
  "title_hint": null,
  "author_hint": null
}
```

### 6.3 完成标记与接管规则

- Windows 必须在所有文件写完后最后创建 `READY`
- WSL 只处理存在 `READY` 的 job
- WSL 接管时先将 `incoming/<job_id>` 移动到 `processing/<job_id>`
- 如果目录已被其他实例移动，则当前实例跳过

---

## 7. MVP 范围

### 7.1 第一阶段支持

- Windows 客户端输入单条 URL
- Windows 端保存原始文件和 metadata 到共享目录
- WSL 侧 `watch-inbox`
- WSL 侧接管 `incoming -> processing -> processed/failed`
- 支持解析 `.html`、`.txt`、`.md`
- 输出标准 markdown 与 json
- 接入 OpenClaw
- Windows 客户端展示已处理结果

### 7.2 第一阶段不支持

- 直接在 WSL 内完成微信会话管理
- 自动发现公众号订阅流
- 多平台并发任务调度中心
- 远程数据库或服务端部署

---

## 8. 功能需求

### FR-1 URL 采集入口

Windows 客户端必须允许用户输入单条 URL 并创建采集任务。

### FR-2 原始内容落盘

Windows 客户端必须将获取到的原始内容写入共享 inbox。

### FR-3 Metadata 写入

Windows 客户端必须为每个采集任务生成 metadata 文件。

### FR-4 WSL 自动发现

WSL 处理器必须支持监听或定时扫描共享 inbox 中的新内容包。

### FR-5 文件解析

WSL 处理器必须支持解析至少三类输入：

- html
- txt
- markdown

### FR-6 标准化输出

WSL 处理器必须将解析结果转换为统一的 `ContentAsset`。

### FR-7 结果持久化

WSL 处理器必须输出标准化 markdown 与 json。

### FR-8 OpenClaw 接入

WSL 处理器应支持将 `ContentAsset` 送入 OpenClaw。

### FR-9 状态追踪

系统必须区分并保存至少三种处理状态：

- pending
- processed
- failed

### FR-10 Windows 结果管理

Windows 客户端必须能够查看原始文件、处理结果和归档状态。

---

## 9. 非功能需求

### NFR-1 跨系统边界清晰

Windows 与 WSL 的交接必须通过共享目录协议完成，不直接耦合进程内状态。

### NFR-2 可恢复

WSL 处理器在失败后必须保留原始文件和错误信息，便于重试。

### NFR-3 可扩展

新增内容类型或平台时，不应改动核心 inbox 协议。

### NFR-4 可维护

原始文件解析必须和平台采集逻辑解耦。

### NFR-5 可观察

采集和处理阶段都必须留下可追踪日志和状态文件。

---

## 10. 关键流程

### 10.1 URL 到处理结果

```text
Windows GUI 输入 URL
  ->
Windows Collector 获取内容
  ->
写入 shared inbox/incoming/<job_id>/
  ->
WSL Watcher 检测到新任务
  ->
WSL Processor 解析原始文件
  ->
标准化为 ContentAsset
  ->
输出 normalized.md / normalized.json
  ->
调用 OpenClaw
  ->
结果写回 processed/<job_id>/
  ->
Windows GUI 展示结果
```

### 10.2 失败处理

```text
WSL Processor 处理失败
  ->
写入 failed/<job_id>/
  ->
保留 payload 与 metadata
  ->
写入 error.json
  ->
Windows GUI 可见失败状态
```

---

## 11. MVP 验收标准

以下条件全部满足时，第一阶段视为完成：

1. 用户可以在 Windows 客户端输入一条 URL。
2. Windows 端可以生成完整内容包并写入共享 inbox。
3. WSL 端可以自动发现新增内容包。
4. WSL 端可以处理 html、txt、md 中至少一种真实输入。
5. 系统可以输出标准 markdown 与 json。
6. 系统可以记录 processed 或 failed 状态。
7. Windows 客户端可以查看处理结果和归档状态。

---

## 12. 当前结论

当前版本的正确主路径不再是“WSL 直接控制受限平台页面”，而是：

- Windows 侧负责真实采集与文件管理
- WSL 侧负责标准化与工具流处理

微信相关的直接抓取逻辑可以保留为实验性能力，但不再作为当前 MVP 主路径。
