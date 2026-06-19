# GFAM GHA / Linux 使用说明

本版本用于 GHA / Linux / 服务器环境。它不依赖 Windows 批处理和 Node.js 主菜单，入口为：

```bash
./run_gha.sh
```

## 1. 初始化环境

```bash
cd GFAM
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-gha.txt
```

如果你的环境已经安装 `requests`，也可以直接运行。

## 2. 配置 UID/SIGN

复制示例配置：

```bash
cp examples/gha.env.example .env
nano .env
```

填写：

```env
GFAM_SERVER=SOP
GFAM_USER_UID=你的UID
GFAM_SIGN_KEY=你的SIGN
GFAM_FAIRY_AUTO_ENABLED=0
```

`.env` 包含账号数据，不要提交到公开仓库。

## 3. 交互运行

```bash
./run_gha.sh
```

GHA 入口会显示模块菜单。模块启动后仍由该模块接管命令行。

## 4. 直接启动某个模块

```bash
./run_gha.sh --module greyzone --server SOP
./run_gha.sh --module a10-resource --server M4A1
./run_gha.sh --module 13-4 --server M4A1
./run_gha.sh --module pick --server SOP --fairy
./run_gha.sh --module f2p --server SOP --fairy
```

可用模块：

```bash
./run_gha.sh --list
```

## 5. 与 Windows 版的区别

- GHA 版不启动代理，不抓取 UID/SIGN。
- GHA 版从 `.env` 或环境变量读取 `GFAM_USER_UID` / `GFAM_SIGN_KEY`。
- GHA 版不需要 Node.js。
- GHA 版仍使用项目内置 `libs/ZIRC/src/core/gflzirc`。
- 开启妖精自动时，`gfam_gha.py` 会在前台模块运行期间启动后台 `gfam_fairy_auto.py`，模块退出后自动停止后台循环。

## 6. 安全提醒

不要公开以下文件：

```text
.env
cache/*.json
*_Index_index_*.json
index_debug.json
*.log
```

## GitHub Actions 手动运行

本包已内置手动 Workflow：

```text
.github/workflows/gfam-manual.yml
```

使用前请在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 中添加：

```text
GFAM_USER_UID
GFAM_SIGN_KEY
```

然后进入 `Actions -> GFAM Manual Run -> Run workflow` 手动选择模块、服务器、运行时长和是否启用妖精自动。

更多说明见：`docs/GHA_WORKFLOW.md`。

## 模块选择建议

- `greyzone`：灰域自动彩蛋，保持原有 GHA 默认逻辑。
- `13-4-train`：13-4 练级模式，`train_team_count` 表示从梯队2开始练几个实际练级梯队。
- `13-4-resource`：13-4 双单人五战四项资源打捞模式。
- `a10-resource`：普通 A-10 四项资源获取；第一梯队必须为单人梯队，不移动直接结束回合并结算。
- `pick_and_train`：统一训练循环。先自动训练，训练资料不足时切换获取资料，达到模块内条件后返回训练。
- `smart`：一键打捞入口。GHA 不再提供独立 `epa` 入口，EPA 相关流程建议由 smart 替代。
- `f2p` / `f2p_pr`：零元购相关模块。

默认情况下，13-4 与 pick_and_train 不需要填写 `start_commands`，runner 会自动补全启动命令。

## 日志输出建议

GitHub Actions 页面不适合长期显示本地版那种固定下方仪表盘。手动 workflow 默认启用 `compact_log`，会隐藏仪表盘刷新和大部分逐步移动日志，只保留正常运行、错误、停止和结束统计相关信息；结束统计段会强制完整保留。

开启 `compact_log` 时，GHA 会隐藏妖精自动固定状态行与重复计数行，例如 `妖精自动：操作 建造启动 0/0，领取 0/1，强化 0/0；状态 ...`。实际建造、领取、强化的成功/失败、错误、停止和运行结束统计仍会保留；最终统计段不会被 compact_log 过滤。

排查路线或接口问题时，可以在 Run workflow 页面将 `compact_log` 改为 `false`，临时恢复完整日志。

## 7. GHA 运行结束资源统计

在 GitHub Actions 中运行时，`gha_manual_runner.py` 会为没有模块内资源统计的模块补充运行前后资源对比。该统计通过运行前、运行结束后各请求一次 `Index/index` 获得，不会在运行中反复请求。

`13-4`、`f2p`、`f2p_pr` 已有模块内资源统计，GHA wrapper 不重复打印。`greyzone`、`a10-resource`、`smart`、`pick_and_train` 等模块会在结束时显示 GHA 四项基础资源统计。


## v1.0 GHA 停止与统计说明

- `compact_log=true` 时仍会隐藏固定仪表盘和高频循环日志。
- GHA runner 会在所有模块运行前后各请求一次 `Index/index`，输出四项基础资源变化，用于运行结束兜底确认。
- 默认停止流程不再连续发送 `-q` 和 `-E`；而是先发送 `-q`，等待模块输出结算/统计后，再发送 `-E` 退出。等待时间可通过环境变量 `GFAM_GHA_STOP_WAIT_SECONDS` 调整，默认 75 秒。


## f2p / f2p_pr 默认确认

在 GHA 中选择 `f2p` 或 `f2p_pr` 时，runner 默认会依次发送：

```text
-r
-y
```

原因是零元购模块在 `-r` 后会进入运行确认界面，需要 `-y` 才会真正启动战役。

### 停止流程说明

默认停止流程为先发送 `-q`。GHA runner 会监听模块输出；如果检测到“本次运行结束”、最终统计或模块菜单已经出现，会立即发送 `-E` 退出，不再固定等待完整停止宽限时间。这样可以保留结算统计，同时避免 f2p/f2p_pr 已回到菜单后仍继续占用 job 时间。

## 8. GHA 子进程退出码兼容

GFAM 的部分交互模块在菜单退出或无任务结束时可能返回非 0。GHA runner 默认会区分“技术性错误”和“交互模块正常结束”：没有 `Traceback`、导入失败、缺少 UID/SIGN 等技术性错误时，非 0 子进程退出码不会让 Actions 失败；超时强制终止仍会失败。

可通过环境变量关闭该兼容：

```bash
export GFAM_GHA_TOLERATE_MODULE_EXIT=0
```


## smart 一键打捞 GHA 模式

GHA 中不再使用单一 `smart` 选项，而是拆分为：

- `smart-gun`：人形一键打捞（普通/紧急）。默认自动发送 `-gun`、`-r`、`-all`、`-run`、`-go`、`-r`。其中 `-all` 用于处理“普通/紧急目标都已拥有，是否改为全部目标各打一只”的提示。
- `smart-equip`：装备一键打捞（夜战专属装备）。默认自动发送 `-equip`、`-r`、`-all`、`-run`、`-go`、`-r`。其中 `-all` 用于处理“目标都已拥有时继续生成兜底计划”的提示。

原 `smart` / `epa` 仍作为兼容别名映射到 `smart-gun`。

`compact_log=true` 时会隐藏 smart 计划中的大段编号目标列表，只保留计划生成、当前路线、运行、错误、停止与结束统计等关键日志。
