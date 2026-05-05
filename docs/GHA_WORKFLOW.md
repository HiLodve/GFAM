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
- `train_team_count`：仅对 `13-4-train` 生效
- `run_minutes`：运行多少分钟后自动发送 `-q` 和 `-E` 安全停止
- `compact_log`：默认开启，隐藏固定仪表盘和高频普通日志

## 3. 模块默认启动命令

Workflow 会通过 `gha_manual_runner.py` 向模块标准输入发送命令。默认启动命令如下：

- `greyzone`：保持原样，按灰域模块默认逻辑发送 `-r`
- `f2p` / `f2p_pr` / `smart`：自动发送 `-r`
- `13-4-train`：自动发送 `-134train`、`-full`、`train_team_count`、`-a`、`-keepmax`、`-y`、`-r`
- `13-4-resource`：自动发送 `-134`、`-a`、`-keepmax`、`-y`、`-r`
- `pick_and_train`：自动发送 `-2`、`-count`、`-run`，先进入自动训练；训练资料不足时由模块内部循环切换到获取资料，达到模块内条件后返回训练

GHA 不再提供独立 `epa` 入口；EPA 参数链较长，GHA 中使用 `smart` 一键打捞替代。若外部仍传入 `epa`，runner 会兼容映射到 `smart`。

灰域可通过 `ticket_type` 自动发送：

- `ticket1` -> `-ticket1`
- `ticket2` -> `-ticket2`

到达 `run_minutes` 后，默认发送：

```text
-q
-E
```

如需自定义，可填写 `stop_commands`。

## 4. 13-4 模块说明

GHA 页面已将 13-4 拆成两个独立选项：

- `13-4-train`：13-4 五战练级。Runner 会自动发送 `-134train`、默认 `-full`、练级梯队数量、`-a`、`-keepmax`、`-y`、`-r`。
- `13-4-resource`：13-4 双单人五战四项基础资源打捞。Runner 会自动发送 `-134`、`-a`、`-keepmax`、`-y`、`-r`。

`train_team_count` 只对 `13-4-train` 生效，表示从梯队2开始实际参与练级的梯队数量。例如填 `3`，会要求解析并轮转梯队2、梯队3、梯队4；梯队1仍固定为单人占位队。

## 5. pick_and_train 模块说明

GHA 页面只保留统一入口：

- `pick_and_train`

默认行为：

1. 进入自动训练菜单。
2. 执行 `-count` 获取 Index/index 并统计可训练对象。
3. 执行 `-run` 开始自动训练。
4. 当训练资料不足时，模块内部自动切换到获取训练资料。
5. 当资料达到模块内写定的切换条件后，返回自动训练继续训练技能。
6. 循环持续到 `run_minutes` 到达并由 runner 发送安全停止，或模块判断没有可训练对象/无法继续。

灰域 `greyzone` 的默认启动逻辑保持不变。

## 6. GHA 精简日志

`compact_log` 默认开启。开启后，`gha_manual_runner.py` 会在 GitHub Actions 端过滤固定状态仪表盘刷新和高频移动步骤日志，仅保留：

- GHA 启动、运行窗口、安全停止信息
- 模块开始、发现目标、开始任务、完成任务、错误、停止、统计等关键日志
- 运行结束后的模块统计整段内容（本次运行统计、资源变化、掉落统计、妖精自动统计等）
- 低频运行心跳

开启 `compact_log` 时，GHA 会隐藏妖精自动固定状态行与重复计数行，例如 `妖精自动：操作 建造启动 0/0，领取 0/1，强化 0/0；状态 ...`。实际建造、领取、强化的成功/失败、错误、停止和运行结束统计仍会保留；最终统计段不会被 compact_log 过滤。

如需排查详细步骤，可在手动运行 workflow 时关闭 `compact_log`。

## 7. 注意

- Workflow 只适合手动触发，不建议设置定时运行。
- 运行中不会抓 UID/SIGN，也不会启动 Windows 代理。
- 若 SIGN 失效，需要重新获取 SIGN 并更新仓库 Secret。
- 单个 job 默认最长 360 分钟，建议先用 10～30 分钟短测。

## 6. GHA 运行结束资源统计

GHA runner 会为缺少模块内资源统计的模块补充一次四项基础资源统计：运行前请求一次 `Index/index` 记录人力、弹药、口粮、零件；模块安全停止后再请求一次 `Index/index`，计算本次变化与每小时效率。

已自带资源统计的模块不会重复打印 GHA wrapper 统计：

- `13-4-train`
- `13-4-resource`
- `f2p`
- `f2p_pr`

其余模块，例如 `greyzone`、`smart`、`pick_and_train`，会在日志末尾显示：

```text
=========== GHA 四项基础资源统计 ===========
起始库存：人力 ... / 弹药 ... / 口粮 ... / 零件 ...
结束库存：人力 ... / 弹药 ... / 口粮 ... / 零件 ...
本次变化：人力 +... / 弹药 -... / 口粮 +... / 零件 -...
每小时效率：人力 +... / 弹药 -... / 口粮 +... / 零件 -...
===========================================
```

如需临时关闭 GHA wrapper 资源统计，可在 workflow 环境变量中设置：

```text
GFAM_GHA_RESOURCE_SUMMARY=0
```
