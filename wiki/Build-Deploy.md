# 构建与部署

## GUI 可执行文件构建

GFAM GUI 通过 PyInstaller 打包为单文件 exe。

### 前置条件

- Python 3.11+
- PyInstaller（`pip install pyinstaller`）
- 构建前需关闭正在运行的 GFAM GUI（否则 DLL 文件被锁定）

### 构建命令

```bash
# 一键构建
build_gfam_gui_exe.bat

# 或手动执行
python tools/build_gfam_gui_exe.py
```

### 构建脚本（build_gfam_gui_exe.py）

```python
def add_data_arg(src, dest):
    """添加数据文件参数"""

def build():
    """执行 PyInstaller 构建"""
    # 入口: tools/gfam_gui_launcher.py
    # 输出: dist/GFAM-GUI/GFAM-GUI.exe
    # 包含: modules/*.py, libs/ZIRC/**, data/*.json, assets/*.png, assets/gfam.ico
```

### 输出结构

```
dist/GFAM-GUI/
├── GFAM-GUI.exe              ← 用户双击运行
└── _internal/
    ├── modules/              ← 后端 .py 文件（运行时加载）
    ├── libs/ZIRC/            ← gflzirc 通信库
    ├── data/                 ← 数据字典
    └── assets/               ← 图标和图片资源
```

### 重要：后端更新 vs GUI 更新

- **纯后端修改**（modules/*.py）：直接 `cp` 到 `dist/GFAM-GUI/_internal/modules/`，无需重新编译
- **GUI 修改**（tools/gfam_gui_launcher.py）：必须重新运行 `build_gfam_gui_exe.bat`

### PyInstaller DLL 冲突处理

GUI exe 的 `_internal` 目录包含 `python311.dll`。如果子进程继承了包含此目录的 PATH，可能加载错误的 DLL 版本。`gfam_gui_launcher.py` 在 `_launch_gfam_backend()` 中处理：

1. 从子进程 PATH 中移除 exe 所在目录
2. 清除 `_MEIPASS` / `_MEIPASS2` 环境变量

---

## 便携包打包

```bash
python tools/build_portable_package.py
```

生成包含所有必要文件的 zip 包，用户解压即可运行。

---

## Windows 启动流程

### run_windows.bat（211 行）

```
1. 执行 setup_windows.ps1 → 环境检查
2. 启动 main.js → 交互式主菜单
3. main.js 退出码 77 → 读取 .gfam_next_module.cmd
4. 设置 PYTHONPATH 包含 gflzirc
5. 可选启动妖精后台（start_gfam_background.ps1）
6. 可选启动制造后台
7. 运行选定模块（python -u modules/<file>.py）
8. 模块退出 → 停止后台进程 → 返回主菜单
```

### setup_windows.ps1（153 行）

```
1. 检测 Node.js → 缺失则 winget 安装 OpenJS.NodeJS.LTS
2. 检测 Python/py → 缺失则 winget 安装 Python.Python.3.11
3. 检测 requests 依赖 → 缺失则 pip install（失败不阻断）
4. 验证 gflzirc 存在
```

关键设计：`requests` 安装失败为**警告**而非错误，因为 GFAM 主要依赖内置 gflzirc。

### start_gfam_background.ps1（15 行）

使用 `Start-Process -WindowStyle Hidden` 启动后台 Python 进程，写入 PID 文件供 GUI 追踪。

---

## GitHub Actions 部署

### 工作流文件

`.github/workflows/gfam-manual.yml`

### 触发方式

手动触发（workflow_dispatch），通过 GitHub Web UI 或 API。

### 输入参数

| 参数 | 类型 | 选项 |
|------|------|------|
| `module` | choice | greyzone, 13-4-train, 13-4-resource, a10-resource, f2p, f2p_pr, smart-gun, smart-equip, pick_and_train |
| `server` | choice | SOP, RO635, M4A1, M16, AR-15, EN |
| `fairy` | boolean | 启用妖精自动 |
| `ticket_type` | choice | default, ticket1, ticket2 |
| `train_team_count` | string | 练级梯队数（默认 1） |
| `run_minutes` | string | 运行时长（默认 30 分钟） |
| `compact_log` | boolean | 精简日志（默认 true） |

### 必需 Secrets

| Secret | 说明 |
|--------|------|
| `GFAM_USER_UID` | 游戏 UID |
| `GFAM_SIGN_KEY` | 签名密钥 |

### 执行流程

```
1. checkout 代码
2. 安装 Python 3.11
3. pip install -r requirements-gha.txt
4. 验证 GFAM_USER_UID 和 GFAM_SIGN_KEY
5. 运行 gha_manual_runner.py（带全部参数）
```

### GHA 入口文件

| 文件 | 行数 | 用途 |
|------|------|------|
| `gfam_gha.py` | 276 | GHA/Linux 启动器入口 |
| `gha_manual_runner.py` | 974 | 非交互式 GHA 控制器 |

`gha_manual_runner.py` 通过 stdin 向模块注入预设命令序列，模拟用户交互。支持精简日志模式（隐藏仪表盘和高频循环输出）。

### 超时与并发

- 任务超时：360 分钟
- 并发控制：`gfam-${repository}-${server}`（同一仓库+服务器不并发）
- 不取消进行中的任务

---

## 部署检查清单

发布前需确认（参考 `docs/PUBLIC_RELEASE_CHECKLIST.txt`）：

1. 不包含真实 UID/SIGN/Index 响应
2. 不包含 `.gfam_auth.json` 等凭证文件
3. `.gitignore` 排除所有运行时缓存和敏感文件
4. gflzirc 库完整包含在 `libs/ZIRC/`
5. `data/` 中的字典文件为静态数据，不含用户数据
6. README 中所有示例使用占位值
