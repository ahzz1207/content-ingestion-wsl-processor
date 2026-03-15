# `content-ingestion` Windows Kickoff Plan v0.1

## 1. 目标

本文件用于指导 Windows 侧新项目的最小开工顺序。

目标不是一次做完整产品，而是尽快做出一个可与当前 WSL Processor 联调的最小 Windows 导出器。

---

## 2. 当前前提

当前 WSL 侧已经具备：

- 稳定的 inbox 协议
- `validate-job` / `validate-inbox`
- `watch-inbox --once`
- sample job 和 E2E guide
- `processed/` / `failed/` 标准输出

因此 Windows 侧第一阶段不需要再猜 WSL 期望什么，只需按现有协议导出 job。

---

## 3. Windows 侧第一阶段目标

Windows 新项目第一阶段只交付下面这条链路：

```text
URL input
  -> collect content
  -> export payload + metadata + READY
  -> write to shared_inbox/incoming
```

当前不要求：

- 完整产品级 GUI
- 复杂状态管理
- 历史任务列表
- 归档浏览
- 多平台适配完整支持

---

## 4. 推荐模块拆分

建议 Windows 项目第一版至少拆成这几层：

### 4.1 `ui/`

负责：

- 输入 URL
- 触发导出
- 展示导出是否成功

### 4.2 `collector/`

负责：

- 调浏览器或采集器获取内容
- 返回原始 html / txt / md

### 4.3 `job_exporter/`

负责：

- 生成 `job_id`
- 选择 payload 类型
- 写 `payload.*`
- 写 `metadata.json`
- 最后写 `READY`

### 4.4 `config/`

负责：

- 配置 shared inbox 路径
- 配置默认导出格式

---

## 5. 建议开发顺序

### 阶段 A：无 GUI 先打通导出

先不急着做复杂 UI，优先做一个最小可调用的导出器：

1. 输入一个 URL
2. 用固定 mock 内容导出 job
3. 让 WSL 成功处理

目标：

- 验证 Windows 路径处理是否正确
- 验证 job 目录真实写入行为是否正确

### 阶段 B：接真实采集

在 A 阶段稳定后，再接真实浏览器采集：

1. 用浏览器打开 URL
2. 获取页面内容
3. 选择导出 `payload.html`

### 阶段 C：补最小 GUI

再补最小交互：

- URL 输入框
- 导出按钮
- 导出结果提示

---

## 6. 第一阶段验收标准

Windows 项目第一阶段完成的标准是：

1. 可以输入一个 URL
2. 可以生成合法 job 目录
3. `validate-job` 返回 `is_valid: true`
4. `watch-inbox --once` 能产出 `processed/<job_id>/`

---

## 7. 推荐联调流程

建议后续在 Windows 项目里固定使用下面顺序联调：

1. Windows 导出 job
2. WSL 执行 `validate-job`
3. WSL 执行 `watch-inbox --once`
4. 检查 `processed/` 或 `failed/`

这个流程会比“直接导出然后猜哪里错了”稳定很多。

---

## 8. Windows 侧第一版最需要避免的坑

- 不要让 `READY` 提前写入
- 不要同时写多个 payload
- 不要让 `content_type` 和 payload 后缀不一致
- 不要在 Windows 端提前写 `status.json` / `error.json`
- 不要把 Windows GUI 逻辑和 WSL 处理逻辑耦合在同一个运行环境里

---

## 9. 建议你在 Windows 新项目启动后优先让我做的事

等你在 Windows 下开新项目后，建议第一步先让我做下面其中之一：

1. 搭一个最小 job exporter
2. 先做 shared inbox 配置和写入模块
3. 先做一个命令行版导出器，再补 GUI

这三种里，我更推荐第 3 种：先命令行版，后 GUI。
