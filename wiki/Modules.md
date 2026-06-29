# 功能模块

GFAM 包含 9 个主要功能模块和若干辅助模块。每个模块作为独立 Python 脚本运行，通过 gflzirc 与游戏服务器通信。

---

## EPA 打捞（epa_plus.py）

**5,833 行** | 核心打捞模块，覆盖普通/紧急/夜战全部关卡。

### 功能

自动化执行 EPA 关卡的完整流程：部署梯队 → 移动 → 战斗结算 → 收集掉落 → 拆解非保护产物。支持单梯队打捞（single 模式）和多梯队轮换练级（team 模式）。

### 运行模式

- **single 模式**：只使用梯队 1（不要求妖精），适合纯打捞
- **team 模式**：多梯队轮换（要求妖精），适合练级 + 打捞

### 关卡数据

| 难度 | 关卡范围 | mission_id 示例 |
|------|----------|-----------------|
| 普通 | A-1 至 A-10 | 145 (EX1) |
| 紧急 | A-1 至 A-6 | 对应紧急关卡 ID |
| 夜战 | A-1 至 A-6 | 对应夜战关卡 ID |

### 关键 CONFIG 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MACRO_LOOPS` | 200 | 外层大循环次数 |
| `MISSIONS_PER_RETIRE` | 8 | 内层小循环次数（每 N 次出击后批量拆解） |
| `MODE_NAME` | "single" | 运行模式 |
| `TRAIN_TEAM_COUNT` | 1 | 练级梯队数量 |
| `TRAIN_SCHEDULE_MODE` | "full" | 练级调度模式（full=满级切换 / equal=均等轮换） |
| `STOP_ON_MAX_LEVEL` | False | 目标满级后停机 |
| `STOP_AFTER_EACH_TARGET_DROPPED` | False | 每个目标各掉一个后停机 |
| `ENABLE_FILTER_PROTECTION` | False | 过滤保护（仅保留目标掉落） |
| `AUTO_LOCK_TARGET_EQUIP` | False | 自动锁定目标装备 |
| `ENABLE_EQUIP_AUTO_RETIRE` | False | 装备自动拆解 |
| `EQUIP_AUTO_RETIRE_MAX_RANK` | 4 | 装备自动拆解最高星级 |
| `SELECTED_DIFFICULTY` | "普通" | 难度选择 |
| `SELECTED_STAGE` | "" | 关卡选择 |
| `SELECTED_TARGET` | "" | 目标选择 |

### 游戏机制

完整的关卡自动化包括：`combInfo`（战斗配置）→ `startMission`（开始任务）→ 沿路线 `teamMove`（移动）→ 每个战斗点 `battleFinish`（结算）→ `endTurn`（结束回合）→ `startEnemyTurn`/`endEnemyTurn`（敌方回合）→ `startTurn`（新回合）。掉落的人形根据保护列表决定保留或拆解。夜战模式额外支持装备自动锁定。

### 紧急拆解

当仓库空间不足时，EPA 会自动触发紧急拆解流程：从 Index 中识别非保护人形，提交拆解释放空间，然后继续运行。

### 摘要输出

运行结束后生成 `.gfam_epa_summary.json`，包含运行时长、出击次数、掉落统计、资源变化、妖精状态、跟随制造统计。

---

## 13-4（gfam_13_4.py）

**6,215 行** | 13-4 关卡专家，继承 EPA 全部基础设施。

### 两种模式

- **`-134` 资源模式**：双单人梯队部署（梯队 1 驻守 91297，梯队 2 从 91263 出发走 5 战斗路线）。所有掉落自动拆解，追踪四项资源变化。
- **`-134train` 练级模式**：梯队 1 为占位假人，梯队 2+ 为练级梯队。走 5 战斗路线（91263→91264→91265→91266→91268→91271），mission_id=128。

### 关键 CONFIG 参数

| 参数 | 说明 |
|------|------|
| `RESOURCE_FARM_MODE` | 资源模式开关 |
| `TRAIN_13_4_MODE` | 练级模式开关 |
| `TRAIN_13_4_DUMMY_TEAM_ID` | 假人梯队 ID（默认 1） |
| `TRAIN_13_4_FIRST_TEAM_ID` | 第一个练级梯队 ID（默认 2） |

---

## A-10 资源（gfam_a10_resource.py）

**888 行** | A-10 关卡四项资源获取，不移动不战斗。

### 功能

在 EPA 普通 A-10 关卡（mission_id=144）上，只部署单人梯队，不移动直接结束回合获取四项资源结算。受限于每轮结算需要多个请求响应交互，最高速率约为 1 结算/秒。

### 运行要求

- 梯队 1 必须为单人梯队
- 需要先通过 auth capture 获取 UID/SIGN

### 四级拆解触发

| 级别 | 条件 | 行为 |
|------|------|------|
| 常规 | 待拆人形 ≥ 10 个 | 批量拆解 |
| 预警 | 仓库空位 ≤ 5 | 提前拆解 |
| 紧张 | 仓库空位 ≤ 2 | 紧急拆解 |
| 耗尽 | 仓库空位 = 0 | 兜底拆解 |

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `A10_RETIRE_BATCH_SIZE` | 80 | 每批拆解数量 |
| `A10_PENDING_RETIRE_LIMIT` | 10 | 待拆触发阈值 |
| `A10_RETIRE_FREE_NORMAL` | 5 | 空位预警线 |
| `A10_RETIRE_FREE_TIGHT` | 2 | 空位紧张线 |
| `A10_RETIRE_TIMEOUT` | 30 | 拆解请求超时（秒） |

### 与制造模块协调

- 每 300 次出击同步制造模块的仓库缓存
- 拆解前获取 `RetireLock` 跨进程锁
- 拆解响应未知时保留待拆 UID，不丢弃

---

## 训练资料 / 自动训练（pick_and_train.py）

**3,362 行** | 训练资料获取 + 自动技能训练。

### 功能

自动化 mission 10352 获取训练资料（硬币），同时集成自动技能训练功能。当训练资料耗尽时自动切换到技能训练，资料恢复后切回获取，循环直到没有可训练人形。

### 运行模式

- **硬币获取**：单人梯队沿路线移动收集随机节点掉落，完成后 abortMission（不结算）
- **自动训练**：扫描 Index 中已锁定且技能低于目标等级的人形，排除后勤/战斗/探索中的，使用 `Gun/skillUpgrade` 训练

### 关键 CONFIG 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `PICK_FIXED_TEAM_ID` | 1 | 获取资料的梯队 ID |
| `AUTO_SKILL_TARGET_LEVEL` | 10 | 技能目标等级 |
| `AUTO_SKILL_ONLY_LOCKED` | True | 只训练已锁定人形 |
| `AUTO_SKILL_EXCLUDE_BUSY` | True | 排除正在执行任务的人形 |
| `TRAIN_PICK_CYCLE_ENABLED` | True | 训练-获取循环模式 |

---

## 零元购 f2p（f2p.py）

**1,297 行** | 零消耗关卡打捞。

### 功能

自动化 mission 11880，该关卡不消耗任何资源。使用玩家的重装小队（heavy squad）部署在指定位置，通过回合结算获取人形掉落和资源奖励。

### 运行特点

- 无需梯队移动，纯回合结算
- 使用 `Index/guide`（GUIDE_COURSE_11880）获取引导奖励
- 默认服务器 M4A1
- 支持批量拆解和紧急拆解

---

## 零元购 PR（f2p_pr.py）

**1,366 行** | 零元购的 PR 变体。

### 与 f2p 的区别

- 使用 mission 10801（非 11880）
- 部署系统友方梯队（ally_team_id=6480101）而非玩家重装
- 两回合制任务，有实际移动路线
- 使用 `Mission/allyMySideMove` 进行友方移动

---

## 一键打捞 Smart EPA（gfam_smart_epa.py）

**6,143 行** | 全关卡智能自动打捞。

### 功能

"一键"自动规划打捞路线，遍历所有 EPA 关卡的目标人形/装备，自动跳过已拥有的目标，逐个打捞直到全部收集完成。

### 计划类型

- **gun 计划**：遍历普通/紧急 A-1 至 A-10 的人形目标
- **equip 计划**：遍历夜战 A-1 至 A-6 的装备目标

### 运行机制

1. 从 Index 获取已拥有的人形/装备列表
2. 对比各关卡目标，生成打捞计划（只包含未拥有的）
3. 按计划逐个关卡运行，当前目标掉落后自动切换到下一个
4. 全部完成后停止

---

## 跟随模块制造（gfam_factory_auto.py）

**1,391 行** | 后台制造守护进程。

### 功能

作为独立后台进程运行，在其他模块执行期间自动进行人形/装备制造。支持公式选择、目标保护、非保护产物自动拆解。

### 人形制造

- 公式：手枪(130/130/130/30)、冲锋枪(400/400/100/200)、步枪(400/100/400/200)、突击步枪(100/400/400/200)、机枪(800/800/100/400)
- 保护模式：保留目标人形、全部拆解、保留五星
- 使用 `Gun/developMultiGun` 批量制造，`Gun/finishAllDevelop` 完成

### 装备制造

- 公式：18 种装备公式（光学、全息、红点、夜视、消音、穿甲、状态、高速、霰弹、外骨骼、护甲、弹药箱、披风、混合、备用瞄具、芯片、特种穿甲、两脚架、管、测距仪）
- 保护模式：自动保护五星、保护全息/红点、自定义保护列表
- 使用 `Equip/developMulti` 批量制造

### 运行机制

- 主循环间隔 45 秒
- Index 刷新间隔 300 秒
- 只使用普通建造槽（不使用重型槽）
- 通过 `RetireLock` 与 A-10 协调拆解
- 仓库至少保留 1 个空位

---

## 灰域彩蛋（gfam_greyzone_halloween.py）

**2,093 行** | 灰域万圣节活动自动化。

### 功能

自动化灰域彩蛋活动：重置地图 → 搜索彩蛋任务（580001-580006）→ 执行 MOVE/BATTLE 路线 → 获取万圣节积分（每轮 6000 分）。

### 任务类型

| 任务 ID | 类型 | 说明 |
|---------|------|------|
| 580001 | BATTLE | 战斗型，含 buildingSkillPerformOnDeath |
| 580002-580005 | MOVE | 移动型，无战斗 |
| 580006 | BATTLE | 战斗型 |

### 票券类型

- **Type 1**：探查点数（每次消耗 6 个）
- **Type 2**：四项资源（每次消耗 60 点，每资源 -10）

### 运行机制

- `MapParser` 解析重置后的地图数据，通过 `GREYZONE_RESPAWN_MAP` 查找相邻彩蛋
- MOVE 型：startMission → teamMove → allyMove → endTurn
- BATTLE 型：startMission → teamMove → battleFinish + buildingSkillPerformOnDeath → allyMove → endTurn
- Index/index 仅在运行前请求一次，后续通过本地缓存估算进度
- Index/index 请求支持 5 次重试（间隔 5 秒）

---

## 辅助模块

### 妖精自动（gfam_fairy_auto.py）

**1,071 行** | 后台妖精建造/收集/强化守护进程。

- 三步循环：完成建造 → 自动强化 → 开始新建造
- 建造公式：固定 500/500/500/500
- 默认每轮都强化（`STRENGTHEN_ALWAYS=True`）
- 缓存写入 `.gfam_fairy_auto_cache.json`

### 妖精统计（gfam_fairy_stats.py）

**509 行** | 跨模块妖精统计追踪。

- 从 Index/index 解析妖精库存、建造槽、活跃建造
- 提供 `read_fairy_snapshot()`、`fairy_runtime_status_line()` 供前台模块使用

### 认证获取（gfam_auth_capture.py）

**118 行** | UID/SIGN 凭证获取。

- 启动 GFLProxy 在端口 12335
- 设置 Windows 系统代理指向本地代理
- 用户登录游戏后拦截 SYS_KEY_UPGRADE 事件提取 UID/SIGN
- 顺带缓存 Index/index 供后续模块复用

### 灰域数据（gfam_greyzone_data.py）

**64 行** | 静态数据定义。

- `GREYZONE_RESPAWN_MAP`：4 个出生点 → 相邻检查点映射
- `MISSION_CONFIGS`：6 个彩蛋任务的路线和配置

### 通用工具（gfam_common.py）

**78 行** | 共享路径和调试工具。

- `gfam_find_data_file()`：搜索数据文件（data/ → root → cwd → modules/）
- `gfam_debug_log()`：条件调试输出

---

## 模块交互矩阵

| 模块 | Index 缓存 | API 锁 | 拆解锁 | 制造缓存 | 妖精缓存 | 摘要 JSON |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| EPA | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 13-4 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| A-10 | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| 训练资料 | ✓ | ✓ | — | — | — | — |
| 零元购 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 零元购 PR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Smart EPA | ✓ | ✓ | — | — | — | — |
| 跟随制造 | ✓ | ✓ | ✓ | ✓ | — | — |
| 灰域 | ✓ | ✓ | — | — | — | ✓ |
| 妖精自动 | ✓ | ✓ | — | — | ✓ | — |
| 认证获取 | ✓ | — | — | — | — | — |
