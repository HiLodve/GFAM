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
./run_gha.sh --module 13-4 --server M4A1
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
