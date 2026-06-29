# 开发指南

## 目录结构

```
GFAM/
├── .github/workflows/           # GitHub Actions 工作流
├── assets/                      # GUI 图标和图片资源
├── cache/                       # 运行时缓存（.gitkeep 保留目录）
├── data/                        # 静态数据字典（gun.json, equip.json）
├── docs/                        # 文档和更新日志
│   └── reference/               # 参考资料（夜战装备 ID 映射等）
├── examples/                    # 配置示例
├── libs/ZIRC/src/core/gflzirc/  # 内置通信库
│   ├── __init__.py              # 导出：GFLClient, GFLProxy, SERVERS, 常量
│   ├── client.py                # HTTP 客户端（加密请求/响应）
│   ├── constants.py             # 服务器 URL、API 端点、静态密钥
│   ├── crypto.py                # RC4 变体加密（gf_authcode）
│   └── proxy.py                 # MITM 代理 + Windows 系统代理管理
├── modules/                     # 功能模块（核心代码）
│   ├── epa_plus.py              # EPA 打捞（5833 行）
│   ├── gfam_13_4.py             # 13-4 关卡（6215 行）
│   ├── gfam_a10_resource.py     # A-10 资源（888 行）
│   ├── gfam_greyzone_halloween.py # 灰域彩蛋（2093 行）
│   ├── gfam_smart_epa.py        # 一键打捞（6143 行）
│   ├── f2p.py / f2p_pr.py       # 零元购（~1300 行/个）
│   ├── pick_and_train.py        # 训练资料（3362 行）
│   ├── gfam_factory_auto.py     # 跟随制造后台（1391 行）
│   ├── gfam_factory_config.py   # 制造配置（2375 行）
│   ├── gfam_fairy_auto.py       # 妖精自动后台（1071 行）
│   ├── gfam_fairy_stats.py      # 妖精统计（509 行）
│   ├── gfam_auth_capture.py     # 认证获取（118 行）
│   ├── gfam_index_cache.py      # Index 缓存（385 行）
│   ├── gfam_api_lock.py         # API 锁（164 行）
│   ├── gfam_crossprocess_lock.py # 拆解锁（115 行）
│   ├── gfam_common.py           # 通用工具（78 行）
│   └── gfam_greyzone_data.py    # 灰域静态数据（64 行）
├── tools/                       # GUI 和构建工具
│   ├── gfam_gui_launcher.py     # GUI 主程序（4015 行）
│   ├── build_gfam_gui_exe.py    # PyInstaller 打包
│   ├── build_portable_package.py # 便携包打包
│   └── start_gfam_background.ps1 # 后台进程启动
├── main.js                      # Node.js 主菜单入口
├── run_windows.bat              # Windows 主启动脚本
├── setup_windows.ps1            # 环境检查脚本
├── gfam_gha.py                  # GHA 入口
└── gha_manual_runner.py         # GHA 非交互控制器
```

## 编码约定

### 模块结构

每个功能模块遵循统一结构：

```python
# 1. 导入和路径设置
ROOT_DIR = Path(__file__).resolve().parents[1]
GFLZIRC_CORE_DIR = ROOT_DIR / "libs" / "ZIRC" / "src" / "core"
sys.path.insert(0, str(GFLZIRC_CORE_DIR))

# 2. 可选模块导入（容错）
try:
    from gfam_index_cache import IndexCacheManager
except ImportError:
    IndexCacheManager = None

try:
    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()
except Exception:
    pass

# 3. CONFIG 字典
CONFIG = {
    "SERVER_NAME": "",
    "MODE_NAME": "single",
    ...
}

# 4. 业务函数
def farm_worker():
    ...

# 5. 菜单和入口
def print_menu():
    ...

def main():
    ...

if __name__ == "__main__":
    sys.exit(main())
```

### 命名规范

- 模块文件：`gfam_<功能>.py`（如 `gfam_a10_resource.py`）
- 内部函数：`_<name>` 前缀（如 `_farm_worker_impl`）
- 跨模块函数：`gfam_` 前缀（如 `gfam_request_index_for_storage`）
- CONFIG 键：大写蛇形（如 `MACRO_LOOPS`）
- 运行时缓存文件：`.gfam_<用途>.json`（如 `.gfam_index_cache.json`）
- 摘要文件：`.gfam_<模块>_summary.json`

### 错误处理

- 服务器请求：统一通过 `check_step_error()` 检查
- 自适应延迟：错误时自动增加延迟，成功时逐步衰减
- 连续失败：达到 `MAX_CONSECUTIVE_FAILURES` 时安全退出
- 拆解响应未知：保留待拆 UID 队列，不丢弃

### 跨进程协调接入

新模块如需与服务器通信，应按以下顺序接入：

```python
# 1. 接入全局 API 锁（模块导入时）
try:
    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()
except Exception:
    pass

# 2. 接入 Index 缓存（按需）
try:
    from gfam_index_cache import IndexCacheManager
except ImportError:
    IndexCacheManager = None

_index_mgr = None

def request_index(client, label="Index/index", *, bypass=False):
    global _index_mgr
    if _index_mgr is None and IndexCacheManager is not None:
        _index_mgr = IndexCacheManager(client, ttl=60, label="<模块名>",
                                       shared_file=".gfam_index_cache.json")
    if _index_mgr is not None:
        if bypass:
            return _index_mgr.bypass(client, reason=label)
        return _index_mgr.get(reason=label)
    # 降级：直接请求
    resp = client.send_request(API_INDEX_INDEX, {"time": int(time.time()), "furniture_data": False})
    return resp if not check_step_error(resp, label) else None

# 3. 拆解操作使用拆解锁
try:
    from gfam_crossprocess_lock import RetireLock
except ImportError:
    RetireLock = None

def retire_guns(client, uids):
    lock = RetireLock() if RetireLock else None
    if lock:
        lock.acquire()
    try:
        resp = client.send_request(API_GUN_RETIRE, {"gun_ids": uids})
        ...
    finally:
        if lock:
            lock.release()
```

### 摘要 JSON 输出

模块运行结束时生成摘要文件供 GUI 弹窗使用：

```python
def print_run_summary():
    _summary = {
        "kind": "<模块标识>",
        "title": "<显示标题>",
        "elapsed_seconds": elapsed,
        "macro": MACRO_COUNT,
        "total_drops": DROP_COUNT,
        "stop_reason": STOP_REASON,
        "resource_start": start_inv,
        "resource_end": end_inv,
    }
    # 妖精状态（可选）
    try:
        _fs = read_fairy_snapshot()
        if _fs:
            _summary["fairy"] = _fs
    except Exception:
        pass
    # 跟随制造统计（可选）
    try:
        _factory_cache_path = os.path.join(_gfam_root, ".gfam_factory_auto_cache.json")
        if os.path.exists(_factory_cache_path):
            with open(_factory_cache_path, "r", encoding="utf-8") as _fc:
                _factory_cache = json.load(_fc)
            _factory_data = {}
            for _fk in ("doll", "equip"):
                _fstats = _factory_cache.get("%s_stats" % _fk)
                if _fstats and int(_fstats.get("build_attempts", 0)) > 0:
                    _factory_data[_fk] = {"formula_name": ..., "stats": dict(_fstats)}
            if _factory_data:
                _summary["factory"] = _factory_data
    except Exception:
        pass
    # 写入文件并打印标记
    with open(os.path.join(_gfam_root, ".gfam_<模块>_summary.json"), "w", encoding="utf-8") as _f:
        json.dump(_summary, _f, ensure_ascii=False, indent=2)
    print("[SUMMARY] <模块> 统计报告已生成。")
```

GUI 端通过检测 stdout 中的 `[SUMMARY]` 标记来触发弹窗。

## 维护原则

1. **核心战斗流程不做大范围重写**：已跑通的 mission 执行逻辑保持稳定
2. **最小化 Index/index 请求**：能通过本地缓存、安全计数或服务器返回值推导的状态，不重复请求
3. **运行结束只拆遗留掉落**：不全仓库扫描，只处理本次运行记录的 UID
4. **占位值保护**：用户隐私/账号相关配置默认使用占位值
5. **容错导入**：跨模块依赖使用 `try/except` 包装，降级到无该功能状态

## 调试

### 启用调试模式

```bash
set GFAM_DEBUG=1
set GFAM_SAVE_DEBUG_JSON=1
run_windows_debug.bat
```

### 查看运行时缓存

```bash
# Index 缓存
cat .gfam_index_cache.json | python -m json.tool

# 制造缓存
cat .gfam_factory_auto_cache.json | python -m json.tool

# 妖精缓存
cat .gfam_fairy_auto_cache.json | python -m json.tool
```

### PyInstaller 调试

如果遇到 DLL 冲突或子进程异常，检查 `_launch_gfam_backend()` 中的 PATH 清理和 `_MEIPASS` 清除逻辑。
