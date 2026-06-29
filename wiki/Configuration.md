# 配置系统

GFAM 使用多层配置体系：环境变量 → 模块 CONFIG 字典 → 设置 JSON 文件 → 运行时缓存文件。

---

## 环境变量

### 通用环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `GFAM_SELECTED_SERVER` | 当前服务器 | SOP, RO635, M4A1, M16, AR-15, EN |
| `GFAM_USER_UID` | 用户 UID | 12345678 |
| `GFAM_SIGN_KEY` | 动态签名密钥 | abc123... |
| `PYTHONPATH` | Python 模块搜索路径 | 包含 `libs/ZIRC/src/core` |
| `PYTHONUNBUFFERED` | 禁用输出缓冲 | 1（GUI 模式必须设置） |
| `PYTHONUTF8` | 强制 UTF-8 模式 | 1 |
| `PYTHONIOENCODING` | 标准 IO 编码 | utf-8 |

### 调试环境变量

| 变量 | 说明 |
|------|------|
| `GFAM_DEBUG` | 启用调试日志 |
| `GFAM_SAVE_DEBUG_JSON` | 保存调试用 JSON 快照 |
| `GFAM_DISABLE_API_LOCK` | 禁用全局 API 锁（设为 1） |

### A-10 专用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GFAM_A10_RETIRE_BATCH_SIZE` | 80 | 每批拆解数量 |
| `GFAM_A10_RETIRE_BATCH_DELAY` | 0.25 | 批次间延迟（秒） |
| `GFAM_A10_PENDING_RETIRE_LIMIT` | 10 | 待拆触发阈值 |
| `GFAM_A10_RETIRE_FREE_NORMAL` | 5 | 空位预警线 |
| `GFAM_A10_RETIRE_FREE_TIGHT` | 2 | 空位紧张线 |
| `GFAM_A10_RETIRE_TIMEOUT` | 30 | 拆解请求超时（秒） |
| `GFAM_A10_TARGET_RPS` | 0 | 目标速率（0=不限） |
| `GFAM_A10_STEP_DELAY` | 0 | 步骤间延迟 |
| `GFAM_A10_ROUND_DELAY` | 0 | 轮次间延迟 |
| `GFAM_A10_FAILURE_DELAY` | 0.30 | 失败后延迟 |

### Index 缓存环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GFAM_SHARED_INDEX_TTL` | 300 | 共享文件缓存 TTL（秒） |

---

## 模块 CONFIG 字典

每个模块在文件顶部定义一个 `CONFIG` 字典，包含所有可配置参数。模块运行时通过命令行输入或 GUI 设置面板修改 CONFIG 值。

### CONFIG 通用键

| 键 | 类型 | 说明 |
|----|------|------|
| `SERVER_NAME` | str | 服务器名称 |
| `MODE_NAME` | str | 运行模式（single/team/resource134） |
| `MACRO_LOOPS` | int | 外层循环次数（0=无限） |
| `MAX_CONSECUTIVE_FAILURES` | int | 最大连续失败次数 |
| `STOP_ON_MAX_LEVEL` | bool | 目标满级停机 |
| `STOP_AFTER_EACH_TARGET_DROPPED` | bool | 各目标掉一个后停机 |
| `ENABLE_FILTER_PROTECTION` | bool | 过滤保护模式 |
| `AUTO_LOCK_TARGET_EQUIP` | bool | 自动锁定目标装备 |
| `ENABLE_EQUIP_AUTO_RETIRE` | bool | 装备自动拆解 |
| `EQUIP_AUTO_RETIRE_MAX_RANK` | int | 装备拆解最高星级 |
| `SELECTED_DIFFICULTY` | str | 难度（普通/紧急/夜战） |
| `SELECTED_STAGE` | str | 关卡编号 |
| `SELECTED_TARGET` | str | 目标名称 |
| `GUNS` | list | 梯队人形配置 |
| `FAIRY_ID` | int | 妖精 ID |
| `TEAM_ID` | int | 梯队 ID |

### EPA 特有键

| 键 | 说明 |
|----|------|
| `SINGLE_GUN_MODE` | 单人模式开关 |
| `TRAIN_TEAM_COUNT` | 练级梯队数量 |
| `TRAIN_SCHEDULE_MODE` | 练级调度（full/equal） |
| `MISSIONS_PER_RETIRE` | 每 N 次出击后拆解 |
| `DYNAMIC_MICRO_BY_STORAGE` | 按仓库空位动态调整拆解频率 |
| `PROTECTED_DROP_GUN_IDS` | 保护人形 ID 列表 |
| `BASE_MOVE_DELAY_SECONDS` | 移动基础延迟 |

### 灰域特有键

| 键 | 说明 |
|----|------|
| `TICKET_TYPE` | 票券类型（0=免费/1=探查/2=四项） |
| `RESET_DIFFICULTY` | 重置难度 |
| `AFTER_MISSION_DELAY` | 任务后延迟 |
| `ABORT_BEFORE_RUN` | 运行前清理残留战役 |

---

## 设置 JSON 文件

### .gfam_epa_settings.json

GUI 设置面板写入，模块启动时通过 `apply_epa_settings_from_file()` 加载。

```json
{
  "module": "epa",
  "mode": "team",
  "schedule": "full",
  "train_count": 4,
  "stop_on_max": false,
  "stop_on_drop": false,
  "filter_protection": false,
  "equip_auto_lock": false,
  "difficulty": "普通",
  "stage": "A-6",
  "target": "Vector",
  "enable_equip_retire": false,
  "equip_retire_max_rank": 4,
  "auto_stop_minutes": 0
}
```

`module` 字段决定哪个模块读取此文件：`epa`、`13-4`、`smart`。

### .gfam_factory_state.json

跟随制造配置状态，持久化制造设置。

```json
{
  "doll_enabled": false,
  "doll_formula": "handgun",
  "doll_protect_mode": "retire_all_outputs",
  "doll_protect_ids": [],
  "doll_target_count": 0,
  "equip_enabled": false,
  "equip_formula": "optic",
  "equip_protect_mode": "auto_5star_outputs",
  "equip_protect_ids": []
}
```

---

## 运行时缓存文件

| 文件 | 写入者 | 读取者 | 用途 |
|------|--------|--------|------|
| `.gfam_auth.json` | auth_capture | 所有模块 | UID/SIGN 凭证 |
| `.gfam_index_cache.json` | auth_capture / 各模块 | 所有模块 | 共享 Index/index 缓存 |
| `.gfam_factory_auto_cache.json` | factory_auto | 各模块摘要 | 制造统计（doll_stats, equip_stats） |
| `.gfam_factory_warehouse_cache.json` | factory_auto | A-10 | 仓库空位状态 |
| `.gfam_fairy_auto_cache.json` | fairy_auto | 各模块摘要 | 妖精状态和统计 |
| `.gfam_api.lock` | API 锁 | 所有进程 | 跨进程 API 请求序列化 |
| `.gfam_retire.lock` | 拆解锁 | A-10 / factory | 跨进程拆解序列化 |
| `.gfam_epa_summary.json` | EPA | GUI | 运行统计弹窗 |
| `.gfam_13_4_summary.json` | 13-4 | GUI | 运行统计弹窗 |
| `.gfam_a10_summary.json` | A-10 | GUI | 运行统计弹窗 |
| `.gfam_f2p_summary.json` | f2p | GUI | 运行统计弹窗 |
| `.gfam_f2p_pr_summary.json` | f2p_pr | GUI | 运行统计弹窗 |
| `.gfam_greyzone_summary.json` | 灰域 | GUI | 运行统计弹窗 |
| `.gfam_auth_capture.pid` | auth_capture | GUI | 子进程 PID 追踪 |
| `.gfam_auto_stop.signal` | 定时器 | 模块主循环 | 运行时长限制信号 |

---

## 数据字典

### data/gun.json

人形目录，JSON 数组。每条记录包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 人形 ID |
| `name` | str | 内部名称键 |
| `en_name` | str | 英文名 |
| `code` | str | 短码 |
| `type` | int | 类型（1=HG, 2=SMG, 3=RF, 4=AR, 5=MG, 6=SG） |
| `rank` | int | 星级 |
| `develop_duration` | int | 制造时间（毫秒） |
| `baseammo` / `basemre` | int | 基础弹药/口粮消耗 |
| `retiremp` / `retireammo` / `retiremre` / `retirepart` | int | 拆解回收资源 |
| `ratio_*` | float | 成长比率 |

### data/equip.json

装备目录，JSON 数组。每条记录包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 装备 ID |
| `name` | str | 内部名称键 |
| `rank` | int | 星级 |
| `category` | int | 装备类别 |
| `pow` / `hit` / `dodge` / `speed` / `rate` | int/str | 属性加成 |
| `critical_harm_rate` / `critical_percent` | int/str | 暴击相关 |
| `armor_piercing` / `armor` | int/str | 穿甲/护甲 |

---

## 服务器列表

| 编号 | 名称 | 简称 |
|------|------|------|
| 1 / -1 | SOP | 默认 |
| 2 / -2 | RO635 | RO |
| 3 / -3 | M4A1 | M4 |
| 4 / -4 | M16 | — |
| 5 / -5 | AR-15 | — |
| 6 / -6 | EN | 国际服 |

---

## 模块停机命令

| 命令 | 说明 |
|------|------|
| `-q` | 安全停机：完成当前大循环后停止 |
| `-Q` | 安全停机：完成当前小循环后停止 |
| `-E` | 返回主菜单 |
| `-go` | 开始运行（EPA 系列） |
| `-a` | 自动编队（EPA 系列） |
