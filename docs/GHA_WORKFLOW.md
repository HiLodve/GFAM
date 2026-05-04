# GFAM GitHub Actions 手动运行说明

本仓库提供 `.github/workflows/gfam-manual.yml`，可在 GitHub Actions 页面手动运行 GFAM GHA 版。

## 1. 配置 Secrets

进入仓库：

`Settings -> Secrets and variables -> Actions -> New repository secret`

添加：

- `GFAM_USER_UID`：当前账号 UID
- `GFAM_SIGN_KEY`：当前账号 SIGN

不要把 UID/SIGN 写入仓库文件。

## 2. 手动运行 Workflow

进入：

`Actions -> GFAM Manual Run -> Run workflow`

常用参数：

- `module`：默认 `greyzone`
- `server`：服务器，如 `SOP`
- `fairy`：是否启用妖精自动
- `ticket_type`：灰域票券类型，`ticket2` 表示四项模式
- `run_minutes`：运行多少分钟后自动发送 `-q` 和 `-E` 安全停止

## 3. 命令输入规则

Workflow 会通过 `gha_manual_runner.py` 向模块标准输入发送命令。

默认启动命令：

- `greyzone` / `13-4` / `f2p` / `f2p_pr` / `smart`：自动发送 `-r`
- `pick` / `epa`：默认不自动发送启动命令，建议在 `start_commands` 中写入需要的菜单命令

灰域可通过 `ticket_type` 自动发送：

- `ticket1` -> `-ticket1`
- `ticket2` -> `-ticket2`

到达 `run_minutes` 后，默认发送：

```text
-q
-E
```

如需自定义，可填写 `stop_commands`。

## 4. 注意

- Workflow 只适合手动触发，不建议设置定时运行。
- 运行中不会抓 UID/SIGN，也不会启动 Windows 代理。
- 若 SIGN 失效，需要重新获取 SIGN 并更新仓库 Secret。
- 单个 job 默认最长 360 分钟，建议先用 10～30 分钟短测。

## GHA 精简日志

`compact_log` 默认开启。开启后，`gha_manual_runner.py` 会在 GitHub Actions 端过滤固定状态仪表盘刷新和高频移动步骤日志，仅保留：

- GHA 启动、运行窗口、安全停止信息
- 模块开始、发现彩蛋、开始任务、完成任务、错误、停止、统计等关键日志
- 运行结束后的模块统计
- 灰域地图重置尝试日志会保留前几次，并按间隔摘要显示，避免 Actions 日志过长

如需排查详细步骤，可在手动运行 workflow 时关闭 `compact_log`。
