# Inbox Job Fixtures

这里放的是用于 Windows / WSL 联调和本地手工验证的 sample inbox jobs。

当前样例：

- `incoming/20260312_193000_sample_wechat_html/`

用法示例：

```bash
cp -R tests/fixtures/inbox_jobs/incoming/20260312_193000_sample_wechat_html /tmp/shared_inbox/incoming/
python3 main.py watch-inbox /tmp/shared_inbox --once
```

验证目标：

- WSL 能识别 `READY`
- WSL 能接管 job 并移动到 `processed/`
- 产出 `normalized.json`、`normalized.md`、`pipeline.json`、`status.json`
