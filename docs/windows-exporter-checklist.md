# `content-ingestion` Windows Exporter Checklist

## 1. 目标

这份清单用于验收 Windows 端“最小导出器”是否已经满足当前 WSL 侧接入要求。

只要这份清单通过，Windows 端就可以进入第一轮联调。

---

## 2. 最小能力范围

Windows 导出器第一版只需要做到：

1. 接收一个 URL
2. 产出一个符合协议的 job 目录
3. 让 WSL `watch-inbox --once` 成功处理

当前不要求：

- 完整 GUI 打磨
- 多任务并发导出
- 历史记录管理
- 结果展示页
- 自动重试

---

## 3. 目录与文件验收

以下检查必须全部通过：

- 已在共享目录下创建 `incoming/<job_id>/`
- job 目录中只有一个 payload 文件
- payload 文件名为 `payload.html`、`payload.txt` 或 `payload.md`
- job 目录中存在 `metadata.json`
- job 目录中存在 `READY`
- `READY` 是最后创建的文件

失败判定：

- payload 文件名不符合规范
- 同时存在多个 payload
- 没有 `metadata.json`
- `READY` 提前出现

---

## 4. Metadata 验收

`metadata.json` 至少要满足：

- `job_id` 存在
- `source_url` 存在
- `collector` 存在，且建议为 `windows-client`
- `collected_at` 存在，且使用 ISO 8601
- `content_type` 存在
- `metadata.json.job_id` 与目录名一致
- `content_type` 与 payload 后缀一致

推荐但非阻塞字段：

- `platform`
- `title_hint`
- `author_hint`

---

## 5. 导出顺序验收

以下时序必须成立：

1. 创建 job 目录
2. 写 payload
3. 写 `metadata.json`
4. 关闭文件句柄
5. 最后创建 `READY`

如果不能保证这一点，WSL 端可能读取到半成品 job。

---

## 6. 联调验收

联调前建议先运行：

```bash
python3 main.py validate-job <shared_inbox>/incoming/<job_id>
```

确认校验通过后，再执行：

```bash
python3 main.py watch-inbox <shared_inbox> --once
```

把 Windows 导出的 job 放进共享目录后，以下命令应成功：

```bash
python3 main.py watch-inbox <shared_inbox> --once
```

成功判定：

- 控制台输出 `job_output=.../processed/<job_id>`
- `incoming/<job_id>` 消失
- `processed/<job_id>/` 出现

---

## 7. 结果文件验收

WSL 成功处理后，以下文件必须存在：

- `processed/<job_id>/metadata.json`
- `processed/<job_id>/payload.*`
- `processed/<job_id>/normalized.json`
- `processed/<job_id>/normalized.md`
- `processed/<job_id>/pipeline.json`
- `processed/<job_id>/status.json`

如果处理失败，则应看到：

- `failed/<job_id>/metadata.json`
- `failed/<job_id>/payload.*`
- `failed/<job_id>/error.json`
- `failed/<job_id>/status.json`

---

## 8. 建议的手工验证项

建议至少手工验证这几项：

- HTML 导出能被 WSL 正常处理
- TXT 导出能被 WSL 正常处理
- Markdown 导出后 `normalized.md` 保留原始 markdown
- 错误输入时能稳定落到 `failed/`

---

## 9. 当前通过标准

如果下面 4 条都满足，就可以认为 Windows 最小导出器达标：

1. 能从 URL 生成合法 job
2. WSL 能接管该 job
3. WSL 能生成完整输出目录
4. 失败场景不会破坏共享目录结构
