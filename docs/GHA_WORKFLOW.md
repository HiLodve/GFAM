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

- `greyzone` / `f2p` / `f2p_pr` / `smart`：自动发送 `-r`
- `13-4-train`：自动发送 `-134train`、`-full`、`train_team_count`、`-a`、`-keepmax`、`-y`、`-r`
- `13-4-resource`：自动发送 `-134`、`-a`、`-keepmax`、`-y`、`-r`
- `pick-data` / `pick`：自动发送 `-1`、`-r`，进入获取训练资料菜单并开始运行
- `pick-train`：自动发送 `-2`、`-count`、`-run`，进入自动训练菜单、统计并确认开始训练
- `epa`：默认不自动发送启动命令，建议在 `start_commands` 中写入需要的菜单命令

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


## 精简日志说明

开启 `compact_log` 时，GHA 日志会隐藏固定仪表盘、逐步移动日志、`当前地图未发现有效彩蛋，继续重置。`、Macro/Micro 常规循环记录等重复行。日志中仅保留关键事件、错误/停止信息、低频运行心跳和最终统计。


## 13-4 模块说明

GHA 页面已将 13-4 拆成两个独立选项：

- `13-4-train`：13-4 五战练级。Runner 会自动发送 `-134train`、默认 `-full`、练级梯队数量、`-a`、`-keepmax`、`-y`、`-r`。
- `13-4-resource`：13-4 双单人五战四项基础资源打捞。Runner 会自动发送 `-134`、`-a`、`-keepmax`、`-y`、`-r`。

`train_team_count` 只对 `13-4-train` 生效，表示从梯队2开始实际参与练级的梯队数量。例如填 `3`，会要求解析并轮转梯队2、梯队3、梯队4；梯队1仍固定为单人占位队。

灰域 `greyzone` 的默认启动逻辑保持不变。


## pick 模块说明

GHA 页面已将 pick_and_train 的常用流程拆成：

- `pick-data`：获取训练资料。Runner 默认发送 `-1`、`-r`。
- `pick-train`：自动训练。Runner 默认发送 `-2`、`-count`、`-run`。
- `pick`：兼容旧选项，等同于 `pick-data`。

如果需要其它自定义流程，可以在 `start_commands` 中手动覆盖默认命令。
