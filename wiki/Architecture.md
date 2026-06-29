# 系统架构

## 分层架构

GFAM 采用四层架构，每层职责清晰分离：

```
┌─────────────────────────────────────────────────────┐
│  GUI 层 (tools/gfam_gui_launcher.py)               │
│  Tkinter 图形界面 · 进程管理 · 日志渲染 · 弹窗路由  │
├─────────────────────────────────────────────────────┤
│  菜单层 (main.js / run_windows.bat)                 │
│  交互式菜单 · 服务器选择 · 模块调度 · 环境检查      │
├─────────────────────────────────────────────────────┤
│  模块层 (modules/*.py)                              │
│  各功能独立脚本 · GFLClient 通信 · 自动化循环       │
├─────────────────────────────────────────────────────┤
│  通信层 (libs/ZIRC/gflzirc)                         │
│  HTTP 客户端 · RC4 加密 · MITM 代理 · 系统代理管理  │
└─────────────────────────────────────────────────────┘
```

## 进程模型

GFAM 运行时最多产生 **4 个独立 OS 进程**：

```
GFAM-GUI.exe (PyInstaller)
  │
  ├── python modules/gfam_auth_capture.py    ← UID/SIGN 获取（临时）
  │
  ├── python main.js                         ← 主菜单 + 模块调度
  │     │
  │     └── python modules/<module>.py       ← 当前运行的功能模块
  │
  ├── python modules/gfam_fairy_auto.py      ← 妖精后台（可选，伴随模块）
  │
  └── python modules/gfam_factory_auto.py    ← 制造后台（可选，伴随模块）
```

进程间通过以下机制协调：

| 机制 | 文件 | 用途 |
|------|------|------|
| 凭证共享 | `.gfam_auth.json` | UID/SIGN 写入后所有进程读取 |
| Index 缓存 | `.gfam_index_cache.json` | 跨进程共享 Index/index 数据 |
| 仓库缓存 | `.gfam_factory_warehouse_cache.json` | 制造模块写入，A-10 读取 |
| 妖精缓存 | `.gfam_fairy_auto_cache.json` | 妖精后台写入，前台模块读取 |
| API 锁 | `.gfam_api.lock` | 序列化所有 GFL 服务器请求 |
| 拆解锁 | `.gfam_retire.lock` | 序列化拆解请求（Gun/retireGun、Equip/retire） |
| 摘要文件 | `.gfam_*_summary.json` | 模块结束后写入，GUI 读取弹窗 |

## 启动流程

### GUI 模式

1. 用户双击 `GFAM-GUI.exe`
2. PyInstaller 解压运行时环境到临时目录
3. `gfam_gui_launcher.py` 启动 Tkinter 主窗口
4. GUI 检测 Node.js / Python 环境（`shutil.which`），缺失则弹窗提示安装
5. 用户选择服务器 → GUI 启动子进程运行 `run_windows.bat`
6. `run_windows.bat` 执行 `setup_windows.ps1` 环境检查
7. `setup_windows.ps1` 检测 Node.js、Python、gflzirc、requests
8. `main.js` 启动交互式菜单
9. 用户选择 auth capture → 运行 `gfam_auth_capture.py`，设置 Windows 系统代理
10. 用户登录游戏 → 代理拦截 UID/SIGN → 保存到 `.gfam_auth.json`
11. 用户选择功能模块 → `main.js` 以 exit code 77 退出，`run_windows.bat` 读取 `.gfam_next_module.cmd` 启动对应模块
12. 可选启动妖精/制造后台进程
13. 模块运行结束 → 生成 JSON 摘要 → GUI 检测 `[SUMMARY]` 标记 → 弹出统计窗口

### 命令行模式

直接运行 `run_windows.bat`，跳过 GUI 层，其余流程相同。

### GitHub Actions 模式

1. `gfam-manual.yml` workflow_dispatch 触发
2. `run_gha.sh` 安装 Python 依赖
3. `gha_manual_runner.py` 读取 Secrets（UID、SIGN）
4. 通过 stdin 向模块注入预设命令序列
5. 精简日志模式（隐藏仪表盘和高频循环输出）

## 数据流

### 认证流

```
游戏客户端 ──HTTP──▶ GFLProxy(127.0.0.1:12335) ──转发──▶ GFL 服务器
                          │
                          ├─ 解密响应体 (gf_authcode/RC4)
                          ├─ 提取 uid + sign → SYS_KEY_UPGRADE 事件
                          ├─ 缓存 Index/index → .gfam_index_cache.json
                          └─ 回调 on_traffic()
                                  │
                                  └─ 写入 .gfam_auth.json
```

### 制造统计流

```
gfam_factory_auto.py
  │ 制造/拆解操作
  ├─ 写入 .gfam_factory_auto_cache.json (doll_stats, equip_stats)
  │
  └─ 各模块 print_run_summary()
       │ 读取 factory cache
       ├─ 合并到 _summary["factory"]
       ├─ 写入 .gfam_xxx_summary.json
       └─ 打印 [SUMMARY] 标记
              │
              └─ GUI _route_summary_popup() → 弹窗显示
```

### Index 缓存流

```
模块请求 Index/index
  │
  ├─ IndexCacheManager.get()
  │    ├─ 内存缓存命中 (TTL 内) → 直接返回
  │    ├─ 共享文件缓存命中 (.gfam_index_cache.json) → 返回并更新内存
  │    └─ 缓存未命中 → 发送网络请求 → 更新两级缓存
  │
  └─ IndexCacheManager.bypass()
       └─ 跳过缓存，直接请求服务器（用于错误恢复、装备锁定验证）
```

## 通信协议

### gflzirc 加密

所有 GFL 服务器通信使用基于 RC4 变体的对称加密：

- **请求加密**：POST body 中 `outdatacode` 字段，值为 `gf_authcode(plaintext, 'ENCODE', key)` 的 Base64 编码
- **响应解密**：响应体中 `#` 后的 Base64 数据，用 `gf_authcode(b64data, 'DECODE', key)` 解密
- **密钥升级**：首次使用 `STATIC_KEY`（内置静态密钥），登录成功后服务器返回动态 `sign` 作为新密钥

### API 端点

| 端点 | 用途 |
|------|------|
| `Index/index` | 获取账号全量数据（人形、装备、资源、仓库等） |
| `Index/guide` | 新手引导奖励领取 |
| `Mission/combInfo` | 获取关卡战斗配置 |
| `Mission/startMission` | 开始任务 |
| `Mission/teamMove` | 梯队移动 |
| `Mission/battleFinish` | 战斗结算 |
| `Mission/buildingSkillPerformOnDeath` | 灰域建筑技能结算 |
| `Mission/endTurn` | 结束回合 |
| `Mission/startEnemyTurn` / `endEnemyTurn` | 敌方回合 |
| `Mission/startTurn` | 开始新回合 |
| `Mission/abortMission` | 中止任务 |
| `Mission/allyMySideMove` | 友方移动（零元购 PR） |
| `Gun/developMultiGun` | 批量人形制造 |
| `Gun/finishAllDevelop` | 完成所有人形制造 |
| `Gun/retireGun` | 拆解人形 |
| `Gun/skillUpgrade` | 技能训练 |
| `Equip/developMulti` | 批量装备制造 |
| `Equip/finishAllDevelop` | 完成所有装备制造 |
| `Equip/retire` | 拆解装备 |
| `Equip/changeLock` | 装备锁定/解锁 |
| `Fairy/develop` | 妖精建造 |
| `Fairy/finishAllDevelop` | 完成所有妖精建造 |
| `Fairy/eatFairy` | 妖精强化 |
| `Daily/resetMap` | 灰域地图重置 |

## 跨进程锁

### 全局 API 锁（gfam_api_lock.py）

- 锁文件：`.gfam_api.lock`
- 实现：`O_CREAT | O_EXCL` 原子文件创建
- 陈旧超时：20 秒自动回收
- 默认超时：15 秒
- 重试间隔：0.15 秒
- 作用：序列化所有 `GFLClient.send_request()` 调用
- 接入方式：模块导入时调用 `patch_gfl_client()`，自动 monkey-patch GFLClient
- 可通过 `GFAM_DISABLE_API_LOCK=1` 禁用

### 拆解锁（gfam_crossprocess_lock.py）

- 锁文件：`.gfam_retire.lock`
- 实现：同 API 锁
- 陈旧超时：45 秒
- 默认超时：8 秒
- 重试间隔：0.3 秒
- 作用：专门序列化 `Gun/retireGun` 和 `Equip/retire` 请求
- 使用场景：A-10 和制造模块同时运行时的拆解协调

## 自适应时序

所有模块内置自适应延迟机制，在服务器返回错误时自动增加请求间隔：

- `error:300`（认证过期）→ 延长延迟 + 尝试清理运行时认证状态
- `error:2` / `plaintext response`（服务器过载）→ 延长延迟
- `error:3`（时序同步错误）→ 延长延迟
- 连续成功后逐步衰减延迟回基准值
