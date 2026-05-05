# ===== GFAM project-local dependency loader =====
# 优先加载项目内 ZIRC submodule 的 src/core，避免依赖 PyPI 或系统环境里的旧版本。
# gflzirc 位于：libs/ZIRC/src/core/gflzirc
import os as _gfam_os
import sys as _gfam_sys
_gfam_root = _gfam_os.path.abspath(_gfam_os.path.join(_gfam_os.path.dirname(__file__), ".."))
_gfam_zirc_core = _gfam_os.path.join(_gfam_root, "libs", "ZIRC", "src", "core")
if _gfam_zirc_core not in _gfam_sys.path:
    _gfam_sys.path.insert(0, _gfam_zirc_core)
# ===============================================

import sys
import re
import time
import threading
import traceback
import copy
import json
import os
from gfam_common import gfam_debug_log, gfam_find_data_file, gfam_write_debug_json
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_COMBINFO, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN, API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN, API_MISSION_ABORT, API_GUN_RETIRE,
    API_MISSION_SUPPLY, API_MISSION_BATTLE_FINISH,
)

try:
    from gflzirc import API_INDEX_INDEX
except ImportError:
    API_INDEX_INDEX = "Index/index"

# 强制覆盖装备拆解接口。
# 不再信任 gflzirc 内置常量，避免其仍然指向错误的 "3000/Equip_retire"。
API_EQUIP_RETIRE = "Equip/retire"
# 装备上锁接口：不同客户端/服可能字段名略有差异，实际调用时会使用多种兼容 payload 尝试。
API_EQUIP_LOCK = "Equip/changeLock"

try:
    from gflzirc import API_INDEX_HOME
except ImportError:
    API_INDEX_HOME = "3000/Index/home"

try:
    from gflzirc import API_SANGVIS_GASHA
except ImportError:
    API_SANGVIS_GASHA = "3000/Sangvis_gasha"

try:
    from gfam_fairy_stats import read_fairy_snapshot, fairy_runtime_status_line, print_fairy_summary, update_fairy_cache_from_index_payload
except Exception:
    def read_fairy_snapshot():
        return {}
    def fairy_runtime_status_line():
        return ""
    def print_fairy_summary(start_snapshot=None):
        return None
    def update_fairy_cache_from_index_payload(payload, source="Index/index"):
        return False

CONFIG = {
# === Authentication & Connection ===
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "SERVER_NAME": "SOP",
    "BASE_URL": SERVERS["SOP"],
    "PROXY_PORT": 12335,

# === Farm Loop Settings ===
    "MACRO_LOOPS": 200,
    # 运行中 Micro 失败时，先尝试一次人形应急拆解并重试当前 Micro。
    "ENABLE_GUN_EXCEPTION_SELF_REPAIR": True,
    # 5个掉落（一关）*10次循环，拆一次（大概50-60个左右）
    "MISSIONS_PER_RETIRE": 8,
    # 动态仓库 Micro 上限计算的基础上限；运行中只在此基础上按仓库空位下调。
    "MISSIONS_PER_RETIRE_BASE": 0,
    # 根据当前人形仓库空位自动下调 Micro 上限；按战斗掉落 + 胜利结算随机人形估算。
    "DYNAMIC_MICRO_BY_STORAGE": True,
    "STORAGE_MICRO_RESERVE": 0,
    "STORAGE_MICRO_BATTLES_PER_RUN": 0,
    "STORAGE_MICRO_EXTRA_GUN_DROPS_PER_RUN": 1,
    "STORAGE_MICRO_EXTRA_EQUIP_DROPS_PER_RUN": 1,
    "STORAGE_MICRO_LIMIT_BLOCKED": False,
    # 自适应间隔：默认保持原有速度；当连续出现 error:300/error:2/error:3 或 plaintext 响应时，自动放慢关键接口节奏。
    "ADAPTIVE_TIMING_ENABLED": True,
    "ADAPTIVE_TIMING_MAX_LEVEL": 8,
    "ADAPTIVE_TIMING_TRIGGER_ERRORS": 1,
    "ADAPTIVE_TIMING_DECAY_SUCCESSES": 120,
    "ADAPTIVE_TIMING_STEP_EXTRA": 0.10,
    "ADAPTIVE_TIMING_STATE_EXTRA": 0.25,
    "ADAPTIVE_TIMING_REPAIR_EXTRA": 0.50,


# === Mission Specific Config ===
    # EPA: EX1
    "MISSION_ID": 145,
    "START_SPOT": 97061,
    "ROUTE": [97039, 97040, 97041, 97036, 97031],

    # 当前菜单选择（后续可继续扩展为真正的关卡配置）
    "SELECTED_DIFFICULTY": None,
    "SELECTED_STAGE": None,
    "SELECTED_TARGET": None,
    "SELECTED_TARGET_LABEL": None,
    "SELECTED_BATTLE_TEMPLATE": None,
    "SINGLE_GUN_MODE": False,
    "SINGLE_GUN_INDEX": 0,
    "MODE_SELECTED_EARLY": False,
    "MODE_NAME": "single",   # single=打捞, team=练级, smart_epa=第6项一键打捞
    "SMART_EPA_PLAN_MODE": False,
    "SMART_EPA_PLAN": [],
    "SMART_EPA_INDEX": 0,
    "SMART_EPA_CURRENT_TARGET_IDS": [],
    "SMART_EPA_TARGET_TYPE": "gun",   # gun=人形一键打捞，equip=夜战装备一键打捞
    "TRAIN_TEAM_COUNT": 1,
    "TRAIN_SCHEDULE_MODE": "full",   # full=当前梯队练到全满再切下一个, equal=均等练级轮转
    "CURRENT_TRAIN_TEAM_INDEX": 0,
    "STOP_ON_MAX_LEVEL": False,
    # 默认与菜单中的“回车默认 -keepmax”保持一致；-go 一键运行也默认不因满级停机。
    # single 打捞模式：当当前目标人形至少各掉落 1 个后自动停止。
    "STOP_AFTER_EACH_TARGET_DROPPED": False,
    "AUTO_MONITOR_MODE": False,
    "AUTO_CAPTURE_EXPECTED_COUNT": 1,
    "INDEX_FETCH_READY": False,

    # 运行节奏控制：用于减少 teamMove/battleFinish 等接口过快导致的 error:300 / plaintext。
    # 可用环境变量覆盖，例如 set GFAM_BASE_MOVE_DELAY_SECONDS=0.4
    "BASE_MOVE_DELAY_SECONDS": 0.20,
    "AFTER_MOVE_DELAY_SECONDS": 0.20,
    "BASE_BATTLE_DELAY_SECONDS": 0.20,
    "AFTER_BATTLE_DELAY_SECONDS": 0.20,
    "BASE_END_TURN_DELAY_SECONDS": 0.20,
    "TEAM_MOVE_RETRY_ATTEMPTS": 3,
    "TEAM_MOVE_RETRY_SLEEP_SECONDS": 0.50,

    # 自动拆解保护：
    # 1) 会自动保护当前关卡菜单里“已选择目标”的配置 ID
    # 2) 也会额外保护下面手动填写的 gun_id
    "PROTECTED_DROP_GUN_IDS": [],

    # 当连续两次自动拆解后仍然提示仓库空间不足时，自动停机
    "STOP_AFTER_RETIRE_NO_SPACE_TIMES": 2,
    "ENABLE_FILTER_PROTECTION": True,

    # 夜战 EPA 装备自动拆解 / 装备仓库保护
    "ENABLE_EQUIP_AUTO_RETIRE": True,   # 启用装备自动拆解 / 装备仓库应急拆解
    "EQUIP_RETIRE_MAX_COUNT": 40,
    "EQUIP_SPACE_RESERVED": 0,
    "EQUIP_AUTO_RETIRE_MAX_RANK": 4,
    # 严格拆解过滤：必须同时满足“低星或星级未知、未上锁、未装备、非 EPA 夜战专属装备、非运行期保护 UID/ID”才拆。
    "EQUIP_AUTO_RETIRE_STRICT_AND": True,
    "EQUIP_AUTO_RETIRE_ALLOW_UNKNOWN_RANK": True,
    # 夜战目标装备掉落后自动上锁。即使上锁接口失败，也会先加入运行期 UID 保护，避免本轮被自动拆解。
    "AUTO_LOCK_TARGET_EQUIP": True,
    "EQUIP_STORAGE_MICRO_LIMIT_BLOCKED": False,
    "EQUIP_STORAGE_MICRO_INFO": {},

    "PROTECTED_DROP_EQUIP_IDS": [],


    # 实际运行时无需使用此config，仅作占位作用，如果需要获取请自行运行monitor.py来获取并输入。
    "USER_DEVICE": "1145141919810",

    # === Team Config ===
    # Echelon ID
    # 梯队ID
    "TEAM_ID": 1,

    # Target Fairy UID (Set to 0 or None if no fairy is equipped)
    "FAIRY_ID": 159357,
    "FAIRY": None,

      "GUNS": [
        {"id": 115599, "life": 444},
        {"id": 335577, "life": 1130},
        {"id": 225588, "life": 420},
        {"id": 336699, "life": 300},
        {"id": 114477, "life": 248}
    ]
}

NORMAL_STAGE_OPTIONS = [f"A-{i}" for i in range(1, 11)]
EMERGENCY_STAGE_OPTIONS = [f"A-{i}" for i in range(1, 7)]
NIGHT_STAGE_OPTIONS = [f"A-{i}" for i in range(1, 7)]

NORMAL_STAGE_DATA = {
    "A-1": {
        "MISSION_ID": 135,
        "DEFAULT_START_SPOT": 89761,
        "OPTIONS": {
            "-1": {"label": "M1887&M1A1", "start_spot": 89761, "route": [89755, 89756, 89757, 89758, 89759]},
            "-2": {"label": "FN-57&FMG-9", "start_spot": 89761, "route": [89750, 89751, 89752, 89753, 89754]},
            "-3": {"label": "OTs-14&格洛克17", "start_spot": 89761, "route": [89745, 89746, 89747, 89748, 89749]},
            "-4": {"label": "PP-19&56式半", "start_spot": 89761, "route": [89740, 89741, 89742, 89743, 89744]},
            "-5": {"label": "SPP-1&M21", "start_spot": 89761, "route": [89735, 89736, 89737, 89738, 89739]},
        },
    },
    "A-2": {
        "MISSION_ID": 136,
        "DEFAULT_START_SPOT": 89790,
        "OPTIONS": {
            "-1": {"label": "UMP40&谢尔久科夫", "start_spot": 89790, "route": [89764, 89765, 89766, 89767, 89768]},
            "-2": {"label": "KLIN&S-SASS", "start_spot": 89790, "route": [89769, 89770, 89771, 89772, 89773]},
            "-3": {"label": "CZ75&M249 SAW", "start_spot": 89790, "route": [89774, 89775, 89776, 89777, 89778]},
            "-4": {"label": "ART556&RPD", "start_spot": 89790, "route": [89779, 89780, 89781, 89782, 89783]},
            "-5": {"label": "DSR-50&CZ-805", "start_spot": 89790, "route": [89784, 89785, 89786, 89787, 89788]},
        },
    },
    "A-3": {
        "MISSION_ID": 137,
        "DEFAULT_START_SPOT": 89819,
        "OPTIONS": {
            "-1": {"label": "Ak 5&6P62", "start_spot": 89819, "route": [89793, 89794, 89795, 89796, 89797]},
            "-2": {"label": "XM3&PSM", "start_spot": 89819, "route": [89798, 89799, 89800, 89801, 89802]},
            "-3": {"label": "JS05&EVO 3", "start_spot": 89819, "route": [89803, 89804, 89805, 89806, 89807]},
            "-4": {"label": "芭莉斯塔&59式", "start_spot": 89819, "route": [89808, 89809, 89810, 89811, 89812]},
            "-5": {"label": "HK21&AR70", "start_spot": 89819, "route": [89813, 89814, 89815, 89816, 89817]},
        },
    },
    "A-4": {
        "MISSION_ID": 138,
        "DEFAULT_START_SPOT": 89848,
        "OPTIONS": {
            "-1": {"label": "雷电&SCW", "start_spot": 89848, "route": [89822, 89823, 89824, 89825, 89826]},
            "-2": {"label": "蜜獾&ASh-12.7", "start_spot": 89848, "route": [89827, 89828, 89829, 89830, 89831]},
            "-3": {"label": "SRS&MT-9", "start_spot": 89848, "route": [89832, 89833, 89834, 89835, 89836]},
            "-4": {"label": "AUG&SSG 69", "start_spot": 89848, "route": [89837, 89838, 89839, 89840, 89841]},
            "-5": {"label": "TAC-50&HK45", "start_spot": 89848, "route": [89842, 89843, 89844, 89845, 89846]},
        },
    },
    "A-5": {
        "MISSION_ID": 139,
        "DEFAULT_START_SPOT": 89877,
        "OPTIONS": {
            "-1": {"label": "CZ2000&P226", "start_spot": 89877, "route": [89851, 89852, 89853, 89854, 89855]},
            "-2": {"label": "Cx4 风暴&M12", "start_spot": 89877, "route": [89856, 89857, 89858, 89859, 89860]},
            "-3": {"label": "PM-06&八一式马", "start_spot": 89877, "route": [89861, 89862, 89863, 89864, 89865]},
            "-4": {"label": "蟒蛇&TMP", "start_spot": 89877, "route": [89866, 89867, 89868, 89869, 89870]},
            "-5": {"label": "AK-74U&wz.29", "start_spot": 89877, "route": [89871, 89872, 89873, 89874, 89875]},
        },
    },
    "A-6": {
        "MISSION_ID": 140,
        "DEFAULT_START_SPOT": 89906,
        "OPTIONS": {
            "-1": {"label": "Mk 12&CZ52", "start_spot": 89906, "route": [89880, 89881, 89882, 89883, 89884]},
            "-2": {"label": "A-91&OTs-39", "start_spot": 89906, "route": [89885, 89886, 89887, 89888, 89889]},
            "-3": {"label": "M870&T65", "start_spot": 89906, "route": [89890, 89891, 89892, 89893, 89894]},
            "-4": {"label": "M82A1&HK23", "start_spot": 89906, "route": [89895, 89896, 89897, 89898, 89899]},
            "-5": {"label": "JS 9&猎豹M1", "start_spot": 89906, "route": [89900, 89901, 89902, 89903, 89904]},
        },
    },
    "A-7": {
        "MISSION_ID": 141,
        "DEFAULT_START_SPOT": 89935,
        "OPTIONS": {
            "-1": {"label": "Mk46&GSh-18", "start_spot": 89935, "route": [89909, 89910, 89911, 89912, 89913]},
            "-2": {"label": "KSVK&Model L", "start_spot": 89935, "route": [89914, 89915, 89916, 89917, 89918]},
            "-3": {"label": "P22&SM-1", "start_spot": 89935, "route": [89919, 89920, 89921, 89922, 89923]},
            "-4": {"label": "HS2000&T77", "start_spot": 89935, "route": [89924, 89925, 89926, 89927, 89928]},
            "-5": {"label": "X95&MP-443", "start_spot": 89935, "route": [89929, 89930, 89931, 89932, 89933]},
        },
    },
    "A-8": {
        "MISSION_ID": 142,
        "DEFAULT_START_SPOT": 89964,
        "OPTIONS": {
            "-1": {"label": "UKM-2000&RT-20", "start_spot": 89964, "route": [89938, 89939, 89940, 89941, 89942]},
            "-2": {"label": "SSG3000&62式", "start_spot": 89964, "route": [89943, 89944, 89945, 89946, 89947]},
            "-3": {"label": "刘易斯&OBR", "start_spot": 89964, "route": [89948, 89949, 89950, 89951, 89952]},
            "-4": {"label": "PM-9&MP-448", "start_spot": 89964, "route": [89953, 89954, 89955, 89956, 89957]},
            "-5": {"label": "R93&03式", "start_spot": 89964, "route": [89958, 89959, 89960, 89961, 89962]},
        },
    },
    "A-9": {
        "MISSION_ID": 143,
        "DEFAULT_START_SPOT": 89993,
        "OPTIONS": {
            "-1": {"label": "M1895 CB&马盖尔", "start_spot": 89993, "route": [89967, 89968, 89969, 89970, 89971]},
            "-2": {"label": "MAT-49&HK33", "start_spot": 89993, "route": [89972, 89973, 89974, 89975, 89976]},
            "-3": {"label": "沙漠之鹰&TEC-9", "start_spot": 89993, "route": [89977, 89978, 89979, 89980, 89981]},
            "-4": {"label": "ACR&侦察者", "start_spot": 89993, "route": [89982, 89983, 89984, 89985, 89986]},
            "-5": {"label": "Kord&隼", "start_spot": 89993, "route": [89987, 89988, 89989, 89990, 89991]},
        },
    },
    "A-10": {
        "MISSION_ID": 144,
        "DEFAULT_START_SPOT": 97026,
        "OPTIONS": {
            "-1": {"label": "SL8&K3", "start_spot": 97026, "route": [97020, 97021, 97022, 97023, 97024]},
            "-2": {"label": "韦伯利&T-CMS", "start_spot": 97026, "route": [97015, 97016, 97017, 97018, 97019]},
            "-3": {"label": "R5&MP41", "start_spot": 97026, "route": [97010, 97011, 97012, 97013, 97014]},
            "-4": {"label": "M82&CPS-12", "start_spot": 97026, "route": [97005, 97006, 97007, 97008, 97009]},
            "-5": {"label": "CF05&VP70", "start_spot": 97026, "route": [97000, 97001, 97002, 97003, 97004]},
        },
    },
}

EMERGENCY_STAGE_DATA = {
    "A-1": {
        "MISSION_ID": 145,
        "START_SPOTS": {"-1": 97061, "-2": 97061, "-3": 97061, "-4": 97059, "-5": 97059, "-6": 97059},
        "OPTIONS": {
            "-1": {"label": "防卫者&Vepr", "route": [97029, 97030, 97031, 97032, 97033]},
            "-2": {"label": "蒙德拉贡M1908&高标10型", "route": [97034, 97035, 97036, 97037, 97038]},
            "-3": {"label": "PM1910&CAR", "route": [97039, 97040, 97041, 97042, 97043]},
            "-4": {"label": "卢萨&英萨斯", "route": [97044, 97045, 97046, 97047, 97048]},
            "-5": {"label": "AUG SMG&Zas M76", "route": [97049, 97050, 97051, 97052, 97053]},
            "-6": {"label": "刘氏步枪&43M", "route": [97054, 97055, 97056, 97057, 97058]},
        },
    },
    "A-2": {
        "MISSION_ID": 146,
        "START_SPOTS": {"-1": 97095, "-2": 97095, "-3": 97095, "-4": 97093, "-5": 97093, "-6": 97093},
        "OPTIONS": {
            "-1": {"label": "德林加&CAR", "route": [97063, 97064, 97065, 97066, 97067]},
            "-2": {"label": "菲德洛夫&MAS-38", "route": [97068, 97069, 97070, 97071, 97072]},
            "-3": {"label": "APC556&C14", "route": [97073, 97074, 97075, 97076, 97077]},
            "-4": {"label": "VHS&43M", "route": [97078, 97079, 97080, 97081, 97082]},
            "-5": {"label": "蜂鸟&Vepr", "route": [97083, 97084, 97085, 97086, 97087]},
            "-6": {"label": "VP1915&高标10型", "route": [97088, 97089, 97090, 97091, 97092]},
        },
    },
    "A-3": {
        "MISSION_ID": 147,
        "START_SPOTS": {"-1": 97129, "-2": 97129, "-3": 97129, "-4": 97127, "-5": 97127, "-6": 97127},
        "OPTIONS": {
            "-1": {"label": "FARA 83&WKp", "route": [97097, 97098, 97099, 97100, 97101]},
            "-2": {"label": "PPQ&StG-940", "route": [97102, 97103, 97104, 97105, 97106]},
            "-3": {"label": "沙维奇99型&高标10型", "route": [97107, 97108, 97109, 97110, 97111]},
            "-4": {"label": "TKB-408&CAR", "route": [97112, 97113, 97114, 97115, 97116]},
            "-5": {"label": "SP9&MAS-38", "route": [97117, 97118, 97119, 97120, 97121]},
            "-6": {"label": "KH2002&C14", "route": [97122, 97123, 97124, 97125, 97126]},
        },
    },
    "A-4": {
        "MISSION_ID": 148,
        "START_SPOTS": {"-1": 97163, "-2": 97163, "-3": 97163, "-4": 97161, "-5": 97161, "-6": 97161},
        "OPTIONS": {
            "-1": {"label": "TF-Q&GM6 Lynx", "route": [97131, 97132, 97133, 97134, 97135]},
            "-2": {"label": "LS26&TS12", "route": [97136, 97137, 97138, 97139, 97140]},
            "-3": {"label": "MG338&MAS-38", "route": [97141, 97142, 97143, 97144, 97145]},
            "-4": {"label": "芮诺&C14", "route": [97146, 97147, 97148, 97149, 97150]},
            "-5": {"label": "斯特林&WKp", "route": [97151, 97152, 97153, 97154, 97155]},
            "-6": {"label": "QBZ-191&StG-940", "route": [97156, 97157, 97158, 97159, 97160]},
        },
    },
    "A-5": {
        "MISSION_ID": 149,
        "START_SPOTS": {"-1": 97197, "-2": 97197, "-3": 97197, "-4": 97195, "-5": 97195, "-6": 97195},
        "OPTIONS": {
            "-1": {"label": "P290&QSB-91", "route": [97165, 97166, 97167, 97168, 97169]},
            "-2": {"label": "Saiga 308&SUB-2000", "route": [97170, 97171, 97172, 97173, 97174]},
            "-3": {"label": "M327&WKp", "route": [97175, 97176, 97177, 97178, 97179]},
            "-4": {"label": "AR-18&StG-940", "route": [97180, 97181, 97182, 97183, 97184]},
            "-5": {"label": "M240L&GM6 Lynx", "route": [97185, 97186, 97187, 97188, 97189]},
            "-6": {"label": "Jatimatic&TS12", "route": [97190, 97191, 97192, 97193, 97194]},
        },
    },
    "A-6": {
        "MISSION_ID": 150,
        # 紧急 A-6 的路线节点为 97199~97228。
        # 按前几个紧急关卡的编号规律，部署点应为路线后方的 97231 / 97229，
        # 不是路线内部节点 97221，也不是夜战/其他区域节点 97239。
        "START_SPOTS": {"-1": 97231, "-2": 97231, "-3": 97231, "-4": 97229, "-5": 97229, "-6": 97229},
        "OPTIONS": {
            "-1": {"label": "CMR-30&英萨斯", "route": [97199, 97200, 97201, 97202, 97203]},
            "-2": {"label": "VP9&Zas M76", "route": [97204, 97205, 97206, 97207, 97208]},
            "-3": {"label": "VRB&GM6 Lynx", "route": [97209, 97210, 97211, 97212, 97213]},
            "-4": {"label": "LAMG&TS12", "route": [97214, 97215, 97216, 97217, 97218]},
            "-5": {"label": "TPS&QSB-91", "route": [97219, 97220, 97221, 97222, 97223]},
            "-6": {"label": "P2000&SUB-2000", "route": [97224, 97225, 97226, 97227, 97228]},
        },
    },
}

NIGHT_STAGE_DATA = {
    "A-1": {
        "MISSION_ID": 151,
        "START_SPOTS": {
            "-1": 97255,
            "-2": 97255,
            "-3": 97253,
            "-4": 97253,
        },
        "OPTIONS": {
            "-1": {"label": "国家竞赛穿甲弹", "route": [97233, 97234, 97235, 97236, 97237]},
            "-2": {"label": ".300BLK高速弹", "route": [97238, 97239, 97240, 97241, 97242]},
            "-3": {"label": "Titan火控芯片", "route": [97243, 97244, 97245, 97246, 97247]},
            "-4": {"label": "GSG UX外骨骼", "route": [97248, 97249, 97250, 97251, 97252]},
        },
    },
    "A-2": {
        "MISSION_ID": 152,
        "START_SPOTS": {
            "-1": 97279,
            "-2": 97279,
            "-3": 97277,
            "-4": 97277,
        },
        "OPTIONS": {
            "-1": {"label": "Hayha记忆芯片", "route": [97257, 97258, 97259, 97260, 97261]},
            "-2": {"label": "特殊战机动护甲", "route": [97262, 97263, 97264, 97265, 97266]},
            "-3": {"label": "无限弹链箱", "route": [97267, 97268, 97269, 97270, 97271]},
            "-4": {"label": "FÉLIN系统瞄具", "route": [97272, 97273, 97274, 97275, 97276]},
        },
    },
    "A-3": {
        "MISSION_ID": 153,
        "START_SPOTS": {
            "-1": 97303,
            "-2": 97303,
            "-3": 97301,
            "-4": 97301,
        },
        "OPTIONS": {
            "-1": {"label": "APS专用枪托", "route": [97281, 97282, 97283, 97284, 97285]},
            "-2": {"label": "战术耳机", "route": [97286, 97287, 97288, 97289, 97290]},
            "-3": {"label": "星条领带", "route": [97291, 97292, 97293, 97294, 97295]},
            "-4": {"label": "7.62纳甘弹", "route": [97296, 97297, 97298, 97299, 97300]},
        },
    },
    "A-4": {
        "MISSION_ID": 154,
        "START_SPOTS": {
            "-1": 97327,
            "-2": 97327,
            "-3": 97325,
            "-4": 97325,
        },
        "OPTIONS": {
            "-1": {"label": "司登手枪弹", "route": [97305, 97306, 97307, 97308, 97309]},
            "-2": {"label": "7.63毛瑟弹", "route": [97310, 97311, 97312, 97313, 97314]},
            "-3": {"label": "pks-07瞄准镜", "route": [97315, 97316, 97317, 97318, 97319]},
            "-4": {"label": "StG瞄准镜", "route": [97320, 97321, 97322, 97323, 97324]},
        },
    },
    "A-5": {
        "MISSION_ID": 155,
        "START_SPOTS": {
            "-1": 97351,
            "-2": 97351,
            "-3": 97349,
            "-4": 97349,
        },
        "OPTIONS": {
            "-1": {"label": "G3特制弹", "route": [97329, 97330, 97331, 97332, 97333]},
            "-2": {"label": "SC特制弹", "route": [97334, 97335, 97336, 97337, 97338]},
            "-3": {"label": "牛仔帽", "route": [97339, 97340, 97341, 97342, 97343]},
            "-4": {"label": "8×42瞄准镜", "route": [97344, 97345, 97346, 97347, 97348]},
        },
    },
    "A-6": {
        "MISSION_ID": 156,
        "START_SPOTS": {
            "-1": 97368,
            "-2": 97368,
            "-3": 97368
        },
        "OPTIONS": {
            "-1": {"label": "皇家作战披风", "route": [97353, 97354, 97355, 97356, 97357]},
            "-2": {"label": "KR步枪弹", "route": [97358, 97359, 97360, 97361, 97362]},
            "-3": {"label": "PK-A内红点瞄准镜", "route": [97363, 97364, 97365, 97366, 97367]}
        }
    }
}

EQUIP_ID_OVERRIDE = {
    # EPA 夜战专属装备 / 2026-05-02 由 Equip/gunEquip 的 equip_with_user_id
    # 在同一份 Index/index 的 equip_with_user_info 中反查确认。
    # 这些 ID 同时用于：目标掉落统计、Macro 后装备拆解过滤、装备仓库应急拆解过滤。
    "国家竞赛穿甲弹": 59,
    ".300BLK高速弹": 60,
    "Titan火控芯片": 61,
    "GSG UX外骨骼": 62,

    "Hayha记忆芯片": 86,
    "特殊战机动护甲": 91,
    "无限弹链箱": 107,
    "FÉLIN系统瞄具": 119,

    "APS专用枪托": 133,
    "战术耳机": 165,
    "星条领带": 485,
    "7.62纳甘弹": 486,

    "司登手枪弹": 487,
    "7.63毛瑟弹": 488,
    "pks-07瞄准镜": 489,
    "StG瞄准镜": 490,

    "G3特制弹": 491,
    "SC特制弹": 492,
    "牛仔帽": 493,
    "8×42瞄准镜": 494,

    "皇家作战披风": 495,
    "KR步枪弹": 496,
    "PK-A内红点瞄准镜": 497,
}


def gfam_normalize_equip_id_set(value):
    """兼容 int / str / list 写法，统一转为正整数 ID 集合。"""
    ids = set()
    if value is None:
        return ids
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    for item in values:
        try:
            item = int(item)
            if item > 0:
                ids.add(item)
        except Exception:
            pass
    return ids


def gfam_get_all_known_epa_night_equip_ids():
    """返回全部已确认 EPA 夜战专属装备 ID，用于防止任何专属装备被自动拆解。"""
    ids = set()
    for value in EQUIP_ID_OVERRIDE.values():
        ids.update(gfam_normalize_equip_id_set(value))
    return ids


def apply_gfam_auth_from_env():
    """从 GFAM 主启动器接收已经抓取好的 UID/SIGN。"""
    try:
        uid = str(os.environ.get("GFAM_USER_UID") or "").strip()
        sign = str(os.environ.get("GFAM_SIGN_KEY") or "").strip()
        if uid and sign and sign != DEFAULT_SIGN:
            CONFIG["USER_UID"] = uid
            CONFIG["SIGN_KEY"] = sign
            if "INDEX_FETCH_READY" in CONFIG:
                CONFIG["INDEX_FETCH_READY"] = True
            print("[+] 已沿用 GFAM 主菜单获取的 UID/SIGN。")
            return True
    except Exception:
        pass
    return False


def resolve_equip_id_by_name(name: str):
    if name in EQUIP_ID_OVERRIDE:
        return int(EQUIP_ID_OVERRIDE[name])
    return None
def _gfam_to_int(value, default=0):
    try:
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        return int(float(text))
    except Exception:
        return default


def resolve_equip_name_by_id(equip_id):
    """根据已确认的装备 ID 映射返回装备名称。

    早期临时探测逻辑里曾使用 runtime_map，清理临时功能后该变量已删除。
    这里统一使用 EQUIP_ID_OVERRIDE，避免夜战装备掉落统计时触发 NameError。
    """
    try:
        equip_id = int(equip_id)
    except Exception:
        return "equip-%s" % str(equip_id)

    for name, mapped_id in EQUIP_ID_OVERRIDE.items():
        try:
            if equip_id in gfam_normalize_equip_id_set(mapped_id):
                return name
        except Exception:
            continue
    return "equip-%s" % equip_id


def gfam_extract_equip_rank(equip):
    if not isinstance(equip, dict):
        return 0
    for key in (
        "rank", "star", "stars", "rarity", "rare",
        "equip_rank", "equipment_rank", "quality", "color", "rank_level"
    ):
        if key in equip:
            value = _gfam_to_int(equip.get(key), 0)
            if value > 0:
                return value
    return 0


def gfam_extract_equip_uid(equip):
    if not isinstance(equip, dict):
        return 0
    for key in ("equip_with_user_id", "id", "uid", "equip_uid", "equipment_uid"):
        if key in equip:
            uid = _gfam_to_int(equip.get(key), 0)
            if uid > 0:
                return uid
    return 0


def gfam_extract_equip_id(equip):
    if not isinstance(equip, dict):
        return 0
    for key in ("equip_id", "equipment_id", "item_id", "tpl_id", "type_id"):
        if key in equip:
            equip_id = _gfam_to_int(equip.get(key), 0)
            if equip_id > 0:
                return equip_id
    return 0


def gfam_get_static_selected_target_equip_ids():
    """只读取配置/静态映射中的目标装备 ID。"""
    protected_ids = set()
    try:
        for value in CONFIG.get("PROTECTED_DROP_EQUIP_IDS", []):
            try:
                value = int(value)
                if value > 0:
                    protected_ids.add(value)
            except Exception:
                pass
    except Exception:
        pass

    label = CONFIG.get("SELECTED_TARGET_LABEL")
    if label:
        for name in split_target_label(label):
            if name in EQUIP_ID_OVERRIDE:
                try:
                    protected_ids.add(int(EQUIP_ID_OVERRIDE[name]))
                except Exception:
                    pass
    return protected_ids


A10_SINGLE_BATTLE_TEMPLATE = {
    "1000": {
        "10": 1228,
        "11": 1228,
        "12": 1228,
        "13": 1228,
        "15": 12006,
        "16": 0,
        "17": 106,
        "33": 10018,
        "40": 15,
        "18": 0,
        "19": 0,
        "20": 0,
        "21": 0,
        "22": 0,
        "23": 0,
        "24": 3900,
        "25": 0,
        "26": 3900,
        "27": 4,
        "34": 84,
        "35": 84,
        "41": 260,
        "42": 0,
        "43": 0,
        "44": 0
    },
    "1001": {},
    "1005": {},
    "1007": {},
    "1008": {},
    "1009": {}
}

MENU_STATE = {
    "selection_unlocked": False,
    "difficulty": None,
    "stage": None,
    "awaiting_gun_mode": False,
    "awaiting_stop_on_max": False,
    "awaiting_target_drop_stop": False,
    "awaiting_equip_auto_lock": False,
    "awaiting_filter_protection": False,
    "awaiting_run_confirm": False,
}

current_worker_thread = None
worker_mode = None
proxy_instance = None

stop_macro_flag = False
stop_micro_flag = False

AUTO_CAPTURE_STATE = {
    "team_id": None,
    "fairy_id": None,
    "guns": [],
    "completed": False,
}

CAPTURED_TEAM_CONFIGS = []
TEAM_SWITCH_PENDING = False
TRAIN_COMPLETED_TEAM_INDICES = set()

DROPPED_UID_TO_GUN_ID = {}
DROPPED_UID_TO_EQUIP_ID = {}
DROPPED_UID_TO_EQUIP_RANK = {}
DROPPED_UID_TO_EQUIP_RAW = {}
# 运行期装备保护：用于保护目标装备 UID，防止自动上锁未确认前被拆解。
RUNTIME_PROTECTED_EQUIP_IDS = set()
RUNTIME_PROTECTED_EQUIP_UIDS = set()
RUNTIME_LOCKED_TARGET_EQUIP_UIDS = set()
RETIRE_NO_SPACE_COUNT = 0
LAST_GFL_ERROR = None

RUN_STATS = {
    "start_time": None,
    "end_time": None,
    "target_counts": {},
    "current_macro": 0,
    "current_micro": 0,
    "current_step": 0,
    "current_team_no": 1,
    "macro_drop_names": [],
    "last_micro_exp_lines": [],
    "panel_enabled": True,
    "recent_logs": [],
    "drop_marquee_offset": 0,
    "drop_marquee_last_key": "",
    "panel_last_refresh_at": 0.0,
    "panel_min_refresh_interval": 0.75,
}

PANEL_LINES_LAST = 0
PANEL_ACTIVE = False

TEAM_PROGRESS_STATE = {
    "current_active_team_id": None,
    "current_active_started_at": None,
}




GUN_CATALOG_CACHE = None
GUN_NAME_ALIAS = {
    "格洛克17": "Glock17",
    "56式半": "56-1",
    "谢尔久科夫": "Serdyukov",
    "S-SASS": "SSGSSASS",
    "芭莉斯塔": "Ballista",
    "59式": "59type",
    "雷电": "Thunder",
    "蜜獾": "HoneyBadger",
    "Cx4 风暴": "Cx4Storm",
    "八一式马": "Type81R",
    "蟒蛇": "Python",
    "猎豹M1": "Gepard M1",
    "62式": "Type62",
    "刘易斯": "Lewis",
    "03式": "Type03",
    "马盖尔": "Magal",
    "沙漠之鹰": "Desert Eagle",
    "侦察者": "Scout",
    "隼": "Falcon",
    "防卫者": "Defender",
    "蒙德拉贡M1908": "Mondragon M1908",
    "高标10型": "General Liu",
    "卢萨": "Lusa",
    "英萨斯": "INSAS",
    "刘氏步枪": "Liu",
    "德林加": "Derringer",
    "菲德洛夫": "Fedorov",
    "沙维奇99型": "Savage99",
    "芮诺": "Reno",
    "斯特林": "Sterling",
    "韦伯利": "Webley",
    # DP-12 为 gun_id 282；CPS-12 也叫 Six12，gun_id 278。
    "DP-12": "DP12",
    "DP12": "DP12",
    "CPS-12": "Six12",
    "Six12": "Six12",
    "CF05": "CF-05",
    "FN-57": "Five-seveN",
    "AK 5": "Ak 5",
    "英萨斯": "INSAS",
    "防卫者": "Defender",
    "刘氏步枪": "Liu Rifle",
    "AUG SMG": "AUG Para",
    "高标10型": "General Liu",
    "TF-Q": "TF Q",
    "6P62": "6P62",
    "Ak 5": "AK 5",
    "STG-940": "StG-940",
    "StG940": "StG-940",
    "stg940": "StG-940",
}

GUN_ID_OVERRIDE = {
    "6P62": 138,
    "Ak 5": 187,
    "AK 5": 187,
    "雷电": 202,
    "SCW": 169,
    # DP-12 的 gun_id = 282。
    "DP-12": 282,
    "DP12": 282,
    # CPS-12 也叫 Six12，gun_id = 278。
    "CPS-12": 278,
    "Six12": 278,
    # 德林加在资料表中为 Derringer，gun_id = 332。
    "德林加": 332,
    "Derringer": 332,
    # StG-940 在资料表中 en_name=StG-940, code=stg940, gun_id=314。
    "StG-940": 314,
    "STG-940": 314,
    "StG940": 314,
    "stg940": 314,
    # 03式在资料表中为 Type03，gun_id = 239。
    "03式": 239,
    "Type03": 239,
    "03type": 239,
    # 猎豹M1在资料表中英文名为 Gepard M1，之前写成 CheetahM1 会导致目标保护失败。
    "猎豹M1": 201,
    "Gepard M1": 201,
    "GepardM1": 201,
    "CheetahM1": 201,
}

def load_gun_catalog():
    global GUN_CATALOG_CACHE
    if GUN_CATALOG_CACHE is not None:
        return GUN_CATALOG_CACHE

    fp = gfam_find_data_file("gun.json", "gun1(1).json", "gun1.json")
    if fp:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                GUN_CATALOG_CACHE = json.load(f)
                gfam_debug_log("[*] 已加载枪械目录：%s" % fp)
                return GUN_CATALOG_CACHE
        except Exception as e:
            print("[!] 读取枪械目录失败：%s | %s" % (fp, e))

    print("[!] 未找到 data/gun.json / data/gun1.json，自动拆解保护将无法按目标名解析。")
    GUN_CATALOG_CACHE = []
    return GUN_CATALOG_CACHE


def normalize_gun_name(name: str) -> str:
    if not name:
        return ""
    return str(name).lower().replace(" ", "").replace("-", "").replace(".", "")


def resolve_gun_id_by_name(name: str):
    candidates = [name]
    alias = GUN_NAME_ALIAS.get(name)
    if alias:
        candidates.append(alias)

    for cand in candidates:
        if cand in GUN_ID_OVERRIDE:
            return int(GUN_ID_OVERRIDE[cand])

    catalog = load_gun_catalog()
    if not catalog:
        return None

    best_id = None
    for cand in candidates:
        n = normalize_gun_name(cand)
        for gun in catalog:
            for field in ("en_name", "code", "name"):
                value = normalize_gun_name(gun.get(field, ""))
                if not value:
                    continue
                if n == value:
                    return int(gun["id"])

        for gun in catalog:
            values = [normalize_gun_name(gun.get(field, "")) for field in ("en_name", "code", "name")]
            values = [v for v in values if v]
            if any(n in value or value in n for value in values):
                gid = int(gun["id"])
                if best_id is None or gid < best_id:
                    best_id = gid

    return best_id



# ================= 第6项：教练の妙妙小巧思 / 一键打捞 =================
SMART_EPA_GUN_NAME_ALIAS_PATCH = {
    "43M": "Danuvia43M", "56式半": "56typeR", "62式": "Type62",
    "AUG SMG": "AUGPARA", "AUG Para": "AUGPARA", "Cx4 风暴": "Cx4Storm",
    "JS 9": "JS9mm", "M1895 CB": "M1895CB", "M870": "M870P",
    "S-SASS": "SSGSSASS", "SRS": "DTASRS", "八一式马": "Type81R",
    "刘易斯": "Lewis", "刘氏步枪": "Liu", "卢萨": "Lusa", "斯特林": "Sterling",
    "沙漠之鹰": "Desert Eagle", "沙维奇99型": "Savage99", "芮诺": "Reno",
    "英萨斯": "INSAS", "菲德洛夫": "Fedorov", "蒙德拉贡M1908": "MondragonM1908",
    "蜂鸟": "Kolibri", "蜜獾": "HoneyBadger", "谢尔久科夫": "Serdyukov",
    "防卫者": "Defender", "马盖尔": "Magal", "高标10型": "HSM10",
    "德林加": "Derringer", "TF-Q": "TFQ", "GM6 Lynx": "GM6Lynx",
    "StG-940": "StG940", "STG-940": "StG940",
}
SMART_EPA_GUN_ID_OVERRIDE_PATCH = {
    "43M": 291, "56式半": 49, "62式": 249, "AUG SMG": 315, "AUG Para": 315,
    "Cx4 风暴": 225, "JS 9": 234, "M870": 229, "SRS": 211,
    "沙维奇99型": 334, "蒙德拉贡M1908": 317, "高标10型": 299,
    "谢尔久科夫": 235, "蜜獾": 213, "M1895 CB": 305, "防卫者": 327,
    "刘氏步枪": 354, "芮诺": 309, "S-SASS": 124,
}
try:
    GUN_NAME_ALIAS.update(SMART_EPA_GUN_NAME_ALIAS_PATCH)
    GUN_ID_OVERRIDE.update(SMART_EPA_GUN_ID_OVERRIDE_PATCH)
except Exception:
    pass


def _smart_split_target_label(label: str):
    s = str(label or "")
    for sep in ["&", "＆", "/", "、", ",", "，"]:
        s = s.replace(sep, "&")
    return [x.strip() for x in s.split("&") if x.strip()]


def _smart_resolve_target_ids(label: str):
    result = []
    missed = []
    for name in _smart_split_target_label(label):
        gid = resolve_gun_id_by_name(name)
        if gid is None:
            missed.append(name)
        else:
            result.append(int(gid))
    return sorted(set(result)), missed


def _smart_collect_owned_gun_ids_from_index(index_data):
    owned = set()
    if not isinstance(index_data, dict):
        return owned
    def as_int(v, default=0):
        try: return int(v)
        except Exception: return default
    def add_gid(gid):
        gid = as_int(gid, 0)
        if gid <= 0: return
        owned.add(gid)
        if 20000 <= gid < 30000:
            owned.add(gid - 20000)
    raw = index_data.get("gun_with_user_info", [])
    if isinstance(raw, dict): raw = list(raw.values())
    if isinstance(raw, list):
        for gun in raw:
            if isinstance(gun, dict): add_gid(gun.get("gun_id") or gun.get("id"))
    positive_keys = {"is_get", "get", "got", "has", "owned", "is_unlock", "unlock", "unlocked", "is_collected", "collected", "collect", "is_open", "open", "is_finish", "finish", "reward_unlock", "reward_unlocked"}
    positive_values = {"1", "true", "yes", "on", "open", "unlock", "unlocked", "collected", "get", "got", "owned"}
    def is_positive(v):
        if isinstance(v, bool): return v
        if isinstance(v, (int, float)): return int(v) > 0
        if isinstance(v, str): return v.strip().lower() in positive_values
        return False
    def walk(node):
        if isinstance(node, dict):
            gid = as_int(node.get("gun_id"), 0)
            if gid <= 0 and any("gun" in str(k).lower() for k in node.keys()):
                gid = as_int(node.get("id"), 0)
            if gid > 0:
                for k, v in node.items():
                    lk = str(k).lower()
                    if lk in positive_keys or any(x in lk for x in ["unlock", "collect", "is_get", "reward"]):
                        if is_positive(v):
                            add_gid(gid); break
            for v in node.values(): walk(v)
        elif isinstance(node, list):
            for v in node: walk(v)
    for key, val in index_data.items():
        lk = str(key).lower()
        if any(x in lk for x in ["gun", "collect", "collection", "unlock", "album", "illustration", "reward"]): walk(val)
    return owned


def _smart_build_targets_from_stage_data():
    result = []
    for difficulty, src in (("普通", NORMAL_STAGE_DATA), ("紧急", EMERGENCY_STAGE_DATA)):
        for stage, data in sorted(src.items(), key=lambda x: int(str(x[0]).split("-")[1])):
            for target_no, opt in sorted((data.get("OPTIONS", {}) or {}).items(), key=lambda x: int(str(x[0]).replace("-", "") or 0)):
                start_spot = opt.get("start_spot", data.get("DEFAULT_START_SPOT")) if difficulty == "普通" else data.get("START_SPOTS", {}).get(target_no)
                result.append({"difficulty": difficulty, "stage": stage, "target_no": target_no, "label": opt.get("label", ""), "mission_id": data.get("MISSION_ID"), "start_spot": start_spot, "route": list(opt.get("route", []) or [])})
    return result


def smart_epa_is_equip_plan():
    return str(CONFIG.get("SMART_EPA_TARGET_TYPE") or "gun").strip().lower() == "equip"


def smart_epa_plan_type_label():
    return "装备一键打捞（夜战专属装备）" if smart_epa_is_equip_plan() else "人形一键打捞（普通/紧急）"


def smart_epa_set_plan_type(kind):
    kind = str(kind or "").strip().lower()
    if kind in ("equip", "equipment", "eq", "装备", "装备一键", "装备一键打捞", "night", "夜战"):
        CONFIG["SMART_EPA_TARGET_TYPE"] = "equip"
        print("[教练の妙妙小巧思] 已选择：装备一键打捞。")
        print("[教练の妙妙小巧思] 计划范围：EPA 夜战 A-1～A-6 专属装备；按装备仓库空位计算 Micro。")
        print("[教练の妙妙小巧思] 提示：装备掉落后会按已确认 equip_id 统计，并沿用装备拆解过滤/自动上锁保护。")
        return True
    if kind in ("gun", "guns", "doll", "dolls", "human", "人形", "人形一键", "人形一键打捞", "普通", "紧急"):
        CONFIG["SMART_EPA_TARGET_TYPE"] = "gun"
        print("[教练の妙妙小巧思] 已选择：人形一键打捞。")
        print("[教练の妙妙小巧思] 计划范围：EPA 普通/紧急目标人形；按人形仓库空位计算 Micro。")
        return True
    return False


def print_smart_epa_plan_type_hint():
    print("[教练の妙妙小巧思] 当前计划类型：%s。" % smart_epa_plan_type_label())
    print("[教练の妙妙小巧思] 输入 -gun 选择人形一键打捞；输入 -equip 选择装备一键打捞；确认后输入 -r 生成计划并进入确认。")


def _smart_collect_owned_equip_ids_from_index(index_data):
    owned = set()
    if not isinstance(index_data, dict):
        return owned

    def as_int(v, default=0):
        try:
            return int(v)
        except Exception:
            return default

    def add_eid(eid):
        eid = as_int(eid, 0)
        if eid > 0:
            owned.add(eid)

    user_info = index_data.get("user_info") if isinstance(index_data.get("user_info"), dict) else {}
    collect = user_info.get("equip_collect") or index_data.get("equip_collect")
    if isinstance(collect, str):
        for part in collect.replace("，", ",").split(","):
            add_eid(part.strip())
    elif isinstance(collect, (list, tuple, set)):
        for part in collect:
            add_eid(part)

    raw = index_data.get("equip_with_user_info", [])
    if isinstance(raw, dict):
        raw = list(raw.values())
    if isinstance(raw, list):
        for equip in raw:
            if isinstance(equip, dict):
                add_eid(equip.get("equip_id") or equip.get("id"))

    return owned


def _smart_build_equip_targets_from_stage_data():
    result = []
    for stage, data in sorted(NIGHT_STAGE_DATA.items(), key=lambda x: int(str(x[0]).split("-")[1])):
        for target_no, opt in sorted((data.get("OPTIONS", {}) or {}).items(), key=lambda x: int(str(x[0]).replace("-", "") or 0)):
            start_spot = (data.get("START_SPOTS", {}) or {}).get(target_no)
            label = opt.get("label", "")
            equip_id = resolve_equip_id_by_name(label)
            result.append({
                "difficulty": "夜战",
                "stage": stage,
                "target_no": target_no,
                "label": label,
                "mission_id": data.get("MISSION_ID"),
                "start_spot": start_spot,
                "route": list(opt.get("route", []) or []),
                "target_equip_ids": [int(equip_id)] if equip_id is not None else [],
                "all_target_equip_ids": [int(equip_id)] if equip_id is not None else [],
                "target_kind": "equip",
            })
    return result


def _smart_build_equip_plan(index_data, force_all=False):
    owned = _smart_collect_owned_equip_ids_from_index(index_data)
    plan, unresolved = [], []
    for entry in _smart_build_equip_targets_from_stage_data():
        ids = list(entry.get("target_equip_ids", []) or [])
        if not ids:
            unresolved.append(entry.get("label", ""))
            continue
        missing_ids = [eid for eid in ids if eid not in owned]
        target_ids = ids if force_all else missing_ids
        if not target_ids:
            continue
        item = dict(entry)
        item["target_equip_ids"] = sorted(set(target_ids))
        item["all_target_equip_ids"] = sorted(set(ids))
        plan.append(item)
    return plan, owned, sorted(set(x for x in unresolved if x))


def _smart_build_plan(index_data, force_all=False):
    owned = _smart_collect_owned_gun_ids_from_index(index_data)
    plan, unresolved = [], []
    for entry in _smart_build_targets_from_stage_data():
        ids, missed = _smart_resolve_target_ids(entry.get("label", ""))
        unresolved.extend(missed)
        if not ids: continue
        missing_ids = [gid for gid in ids if gid not in owned]
        target_ids = ids if force_all else missing_ids
        if not target_ids: continue
        item = dict(entry); item["target_gun_ids"] = sorted(set(target_ids)); item["all_target_gun_ids"] = ids; plan.append(item)
    return plan, owned, sorted(set(unresolved))


def _smart_find_team_from_index(index_data, team_id=1):
    for team in build_team_configs_from_index(index_data):
        try:
            if int(team.get("team_id", 0)) == int(team_id): return team
        except Exception: pass
    return None


def smart_epa_apply_target(idx=None):
    if idx is not None:
        CONFIG["SMART_EPA_INDEX"] = int(idx)
    plan = CONFIG.get("SMART_EPA_PLAN", []) or []
    cur = int(CONFIG.get("SMART_EPA_INDEX", 0) or 0)
    if cur >= len(plan):
        return False

    item = plan[cur]
    CONFIG["MISSION_ID"] = int(item["mission_id"])
    CONFIG["START_SPOT"] = int(item["start_spot"])
    CONFIG["ROUTE"] = list(item["route"])
    CONFIG["SELECTED_DIFFICULTY"] = item.get("difficulty")
    CONFIG["SELECTED_STAGE"] = item.get("stage")
    CONFIG["SELECTED_TARGET"] = item.get("target_no")
    CONFIG["SELECTED_TARGET_LABEL"] = item.get("label")
    CONFIG["SELECTED_BATTLE_TEMPLATE"] = A10_SINGLE_BATTLE_TEMPLATE if CONFIG["SELECTED_DIFFICULTY"] == "普通" and CONFIG["SELECTED_STAGE"] == "A-10" else None

    if item.get("target_kind") == "equip" or CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
        CONFIG["SMART_EPA_CURRENT_TARGET_IDS"] = list(item.get("target_equip_ids", []) or [])
        CONFIG["SMART_EPA_TARGET_TYPE"] = "equip"
        id_label = "equip_id"
        ids = item.get("target_equip_ids", [])
        CONFIG["AUTO_LOCK_TARGET_EQUIP"] = CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True)
    else:
        CONFIG["SMART_EPA_CURRENT_TARGET_IDS"] = list(item.get("target_gun_ids", []) or [])
        CONFIG["SMART_EPA_TARGET_TYPE"] = "gun"
        id_label = "gun_id"
        ids = item.get("target_gun_ids", [])

    init_run_target_counts()
    print("\n[教练の妙妙小巧思] 当前路线 %d/%d：%s %s %s -> %s | 目标 %s=%s" % (
        cur + 1, len(plan), item.get("difficulty"), item.get("stage"), item.get("target_no"),
        item.get("label"), id_label, ids
    ))
    print("[教练の妙妙小巧思] MISSION_ID=%s START_SPOT=%s ROUTE=%s" % (CONFIG["MISSION_ID"], CONFIG["START_SPOT"], CONFIG["ROUTE"]))
    # smart 一键打捞切换下一条路线时不重新请求 Index/index，
    # 但要立刻按当前本地仓库缓存重新计算 Micro 上限，避免继续沿用
    # 初始默认值 8 或上一条路线的旧上限。
    try:
        gfam_recompute_storage_micro_limit_from_cache(
            "equip" if smart_epa_is_equip_plan() else "gun",
            reason="第6项路线切换后本地缓存"
        )
        RUN_STATS["current_micro"] = 0
    except Exception:
        pass
    return True

def smart_epa_current_target_done():
    ids = set(int(x) for x in CONFIG.get("SMART_EPA_CURRENT_TARGET_IDS", []) or [])
    if not ids or not RUN_STATS.get("target_counts"): return False
    for item in RUN_STATS.get("target_counts", {}).values():
        try:
            if int(item.get("item_id", 0)) in ids and int(item.get("count", 0)) <= 0: return False
        except Exception: return False
    return True


def smart_epa_advance_if_needed():
    global stop_macro_flag, stop_micro_flag
    if not smart_epa_current_target_done(): return False
    CONFIG["SMART_EPA_INDEX"] = int(CONFIG.get("SMART_EPA_INDEX", 0) or 0) + 1
    if CONFIG["SMART_EPA_INDEX"] >= len(CONFIG.get("SMART_EPA_PLAN", []) or []):
        panel_safe_print(colorize("[教练の妙妙小巧思] 所有计划目标均已获得至少 1 只，程序将安全停止。", "success"))
        stop_macro_flag = True; stop_micro_flag = True
        return True
    panel_safe_print(colorize("[教练の妙妙小巧思] 当前路线目标已完成，切换下一条路线。", "success"))
    smart_epa_apply_target()
    return True


def smart_epa_prepare_from_index(index_data):
    team = _smart_find_team_from_index(index_data, 1)
    if not team:
        print("[-] 教练の妙妙小巧思：Index/index 中没有找到可用梯队1。")
        return False

    CAPTURED_TEAM_CONFIGS.clear()
    CAPTURED_TEAM_CONFIGS.append({
        "team_id": team["team_id"],
        "fairy_id": team.get("fairy_id", 0),
        "fairy": copy.deepcopy(team.get("fairy")),
        "guns": copy.deepcopy(team.get("guns", [])),
        "runtime_seconds": 0.0,
        "completed": False,
    })
    CONFIG["TEAM_ID"] = team["team_id"]
    CONFIG["FAIRY_ID"] = team.get("fairy_id", 0)
    CONFIG["FAIRY"] = copy.deepcopy(team.get("fairy"))
    CONFIG["GUNS"] = copy.deepcopy(team.get("guns", []))

    equip_plan = smart_epa_is_equip_plan()
    if equip_plan:
        plan, owned, unresolved = _smart_build_equip_plan(index_data, force_all=False)
        id_label = "equip_id"
        owned_label = "已解锁/持有装备 equip_id 数"
        plan_title = "教练の妙妙小巧思 装备一键打捞计划"
        if unresolved:
            print("[教练の妙妙小巧思] 以下目标装备未能解析 equip_id：%s" % "、".join(unresolved))
            print("[教练の妙妙小巧思] 为避免漏保护/漏追踪目标，当前装备计划已停止。")
            return False
        if not plan:
            print("教练翻完装备小本本：检测到 EPA 夜战专属装备都已拥有。")
            if input("是否改为夜战专属装备全部各打一件？输入 -all 继续，否则返回菜单> ").strip().lower() != "-all":
                print("教练合上装备箱：那今天先不折腾夜战装备，等你想刷再来。")
                return False
            plan, owned, unresolved = _smart_build_equip_plan(index_data, force_all=True)
            if unresolved or not plan:
                print("[-] 教练の妙妙小巧思：没有可执行的装备一键打捞计划。")
                return False
    else:
        plan, owned, unresolved = _smart_build_plan(index_data, force_all=False)
        id_label = "gun_id"
        owned_label = "已拥有人形 gun_id 数"
        plan_title = "教练の妙妙小巧思 人形一键打捞计划"
        if unresolved:
            print("[教练の妙妙小巧思] 以下目标名未能解析 gun_id：%s" % "、".join(unresolved))
            print("[教练の妙妙小巧思] 为避免漏保护/漏追踪目标，当前智能计划已停止。")
            return False
        if not plan:
            print("教练挠头：检测到普通/紧急目标都已拥有。")
            if input("是否改为全部目标各打一只？输入 -all 继续，否则返回菜单> ").strip().lower() != "-all":
                print("教练摊手：那今天先放过她们，等你想好再来。")
                return False
            plan, owned, unresolved = _smart_build_plan(index_data, force_all=True)
            if unresolved or not plan:
                print("[-] 教练の妙妙小巧思：没有可执行计划。")
                return False

    CONFIG["SMART_EPA_PLAN"] = plan
    CONFIG["SMART_EPA_INDEX"] = 0
    CONFIG["SMART_EPA_PLAN_MODE"] = True
    CONFIG["MODE_NAME"] = "smart_epa"
    CONFIG["SINGLE_GUN_MODE"] = True
    CONFIG["SINGLE_GUN_INDEX"] = 0
    CONFIG["ENABLE_FILTER_PROTECTION"] = True
    # 第6项 smart 计划的默认运行选项应与菜单提示一致：满级时继续运行，目标达成后也继续运行。
    # 用户仍可在后续菜单中手动选择 -stopmax / -stopdrop 覆盖该默认值。
    CONFIG["STOP_ON_MAX_LEVEL"] = False
    CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = False
    if equip_plan:
        CONFIG["AUTO_LOCK_TARGET_EQUIP"] = True
        CONFIG["ENABLE_EQUIP_AUTO_RETIRE"] = True

    print("\n=========== %s ===========" % plan_title)
    print("%s：%d" % (owned_label, len(owned)))
    for i, item in enumerate(plan, start=1):
        ids = item.get("target_equip_ids") if item.get("target_kind") == "equip" else item.get("target_gun_ids")
        print("%02d. %s %s %s | %s | 目标 %s=%s" % (
            i, item.get("difficulty"), item.get("stage"), item.get("target_no"),
            item.get("label"), id_label, ids
        ))
    print("================================================")
    if equip_plan:
        print("提示：装备一键打捞固定使用梯队1；按装备仓库空位计算 Micro，并保护全部已确认 EPA 夜战专属装备。")
        print("提示：目标装备掉落后默认尝试自动上锁；掉到当前目标后会自动切换下一条夜战路线。")
    else:
        print("提示：人形一键打捞固定使用梯队1；按人形仓库空位计算 Micro。")
    if input("输入 -run 确认执行第6项计划，其他输入返回菜单> ").strip().lower() != "-run":
        print("教练收起小本本：计划先放这里，等你准备好了再来。")
        return False
    return smart_epa_apply_target(0)

def get_stage_data(difficulty: str, stage: str):
    if difficulty == "普通":
        return NORMAL_STAGE_DATA.get(stage)
    if difficulty == "紧急":
        return EMERGENCY_STAGE_DATA.get(stage)
    if difficulty == "夜战":
        return NIGHT_STAGE_DATA.get(stage)
    return None


def get_stage_options(difficulty: str, stage: str):
    stage_data = get_stage_data(difficulty, stage)
    if not stage_data:
        return {}
    return stage_data.get("OPTIONS", {})


def split_target_label(label: str):
    return [part.strip() for part in str(label).split("&") if part.strip()]

def reset_auto_capture_state():
    AUTO_CAPTURE_STATE["team_id"] = None
    AUTO_CAPTURE_STATE["fairy_id"] = None
    AUTO_CAPTURE_STATE["guns"] = []
    AUTO_CAPTURE_STATE["completed"] = False


def reset_captured_team_configs():
    CAPTURED_TEAM_CONFIGS.clear()
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = 0


def get_current_team_config():
    if CAPTURED_TEAM_CONFIGS:
        if CONFIG.get("MODE_NAME") == "team":
            idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0)
            idx = max(0, min(idx, len(CAPTURED_TEAM_CONFIGS) - 1))
            return CAPTURED_TEAM_CONFIGS[idx]
        return CAPTURED_TEAM_CONFIGS[0]
    return {
        "team_id": CONFIG["TEAM_ID"],
        "fairy_id": CONFIG["FAIRY_ID"],
        "fairy": CONFIG.get("FAIRY"),
        "guns": CONFIG["GUNS"],
    }


def get_current_team_id():
    return get_current_team_config()["team_id"]


def get_current_fairy_id():
    return get_current_team_config()["fairy_id"]


def advance_to_next_training_team():
    global TEAM_SWITCH_PENDING
    if CONFIG.get("MODE_NAME") != "team":
        return
    switch_to_next_available_training_team("当前练级梯队已全部满级")


def reset_training_progress():
    TRAIN_COMPLETED_TEAM_INDICES.clear()
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = 0
    TEAM_PROGRESS_STATE["current_active_team_id"] = None
    TEAM_PROGRESS_STATE["current_active_started_at"] = None
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        team_cfg["runtime_seconds"] = 0.0
        team_cfg["completed"] = False
        team_cfg["maxed_member_uids"] = set()
        team_cfg["warned_max_member_uids"] = set()


def mark_current_training_team_completed():
    idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0)
    TRAIN_COMPLETED_TEAM_INDICES.add(idx)


def get_active_training_team_indices():
    return [i for i in range(len(CAPTURED_TEAM_CONFIGS)) if i not in TRAIN_COMPLETED_TEAM_INDICES]



def switch_to_next_available_training_team(reason: str = ""):
    global TEAM_SWITCH_PENDING, stop_macro_flag, stop_micro_flag
    if CONFIG.get("MODE_NAME") != "team":
        return

    current_idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0)
    current_cfg = CAPTURED_TEAM_CONFIGS[current_idx] if 0 <= current_idx < len(CAPTURED_TEAM_CONFIGS) else None
    pause_current_team_runtime()

    if current_cfg and current_idx in TRAIN_COMPLETED_TEAM_INDICES and not current_cfg.get("completed", False):
        current_cfg["completed"] = True
        elapsed = get_team_runtime_seconds(current_cfg)
        panel_safe_print(colorize("[梯队完成] 第 %d 队练级完成，用时：%s" % (current_idx + 1, format_duration(elapsed)), "success"))

    active_indices = get_active_training_team_indices()
    if not active_indices:
        stop_macro_flag = True
        stop_micro_flag = True
        TEAM_SWITCH_PENDING = False
        panel_safe_print(colorize("[全部完成] 所有已配置练级梯队已完成，程序将安全停止。", "success"))
        return

    if current_idx not in active_indices:
        CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = active_indices[0]
        TEAM_SWITCH_PENDING = False
        activate_team_runtime(CAPTURED_TEAM_CONFIGS[CONFIG["CURRENT_TRAIN_TEAM_INDEX"]]["team_id"])
        if reason:
            panel_safe_print("[梯队切换] %s，当前梯队：%d / %d" % (
                reason,
                CONFIG["CURRENT_TRAIN_TEAM_INDEX"] + 1,
                len(CAPTURED_TEAM_CONFIGS),
            ))
        return

    pos = active_indices.index(current_idx)
    next_idx = active_indices[(pos + 1) % len(active_indices)]
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = next_idx
    TEAM_SWITCH_PENDING = False
    activate_team_runtime(CAPTURED_TEAM_CONFIGS[next_idx]["team_id"])
    if reason:
        panel_safe_print("[梯队切换] %s，当前梯队：%d / %d" % (
            reason,
            next_idx + 1,
            len(CAPTURED_TEAM_CONFIGS),
        ))


def build_team_configs_from_index(payload: dict):
    if not isinstance(payload, dict):
        return []

    gun_list = payload.get("gun_with_user_info", [])
    fairy_data = payload.get("fairy_with_user_info", {})

    team_map = {}

    if isinstance(fairy_data, dict):
        # 有的 Index/index 里 fairy_with_user_info 是“单个妖精对象”；
        # 也有的版本是 {uid: {...}} 这样的映射。
        if any(k in fairy_data for k in ("team_id", "fairy_id", "fairy_lv", "fairy_exp", "id", "fairy_with_user_id")):
            fairy_iter = [fairy_data]
        else:
            fairy_iter = [v for v in fairy_data.values() if isinstance(v, dict)]
    elif isinstance(fairy_data, list):
        fairy_iter = fairy_data
    else:
        fairy_iter = []

    for fairy in fairy_iter:
        if not isinstance(fairy, dict):
            continue
        team_id_raw = fairy.get("team_id", "0")
        try:
            team_id = int(team_id_raw)
        except Exception:
            continue
        if team_id < 1 or team_id > 14:
            continue
        fairy_uid = fairy.get("id") or fairy.get("fairy_with_user_id")
        fairy_type_id = fairy.get("fairy_id", 0)
        try:
            fairy_uid = int(fairy_uid)
        except Exception:
            fairy_uid = 0
        try:
            fairy_type_id = int(fairy_type_id)
        except Exception:
            fairy_type_id = 0

        team_map.setdefault(team_id, {"team_id": team_id, "fairy_id": 0, "guns": [], "fairy": None})
        if fairy_uid > 0:
            team_map[team_id]["fairy_id"] = fairy_uid
            team_map[team_id]["fairy"] = {
                "id": fairy_uid,
                "fairy_id": fairy_type_id,
                "level": int(
                    fairy.get("fairy_lv",
                    fairy.get("level",
                    fairy.get("lv", 1))) or 1
                ),
                "exp": int(
                    fairy.get("fairy_exp",
                    fairy.get("exp",
                    fairy.get("now_exp", 0))) or 0
                ),
                "team_id": team_id,
            }

    if not isinstance(gun_list, list):
        gun_list = []

    for gun in gun_list:
        if not isinstance(gun, dict):
            continue
        team_id_raw = gun.get("team_id", "0")
        try:
            team_id = int(team_id_raw)
        except Exception:
            continue
        if team_id < 1 or team_id > 14:
            continue

        gun_uid = gun.get("id") or gun.get("gun_with_user_id")
        gun_type_id = gun.get("gun_id", 0)
        life = gun.get("life")
        try:
            gun_uid = int(gun_uid)
            gun_type_id = int(gun_type_id or 0)
            life = int(life)
        except Exception:
            continue

        team_map.setdefault(team_id, {"team_id": team_id, "fairy_id": 0, "guns": [], "fairy": None})
        team_map[team_id]["guns"].append({
            "id": gun_uid,
            "gun_id": gun_type_id,
            "life": life,
            "level": int(gun.get("gun_level", gun.get("level", 1)) or 1),
            "exp": int(gun.get("gun_exp", gun.get("exp", 0)) or 0),
            "team_id": team_id,
        })

    teams = []
    for team_id in sorted(team_map.keys()):
        team_cfg = team_map[team_id]
        if team_cfg["guns"]:
            # 本地版 GFAM：打捞/智能计划允许不带妖精，不能因为 fairy_id=0 忽略梯队。
            init_team_progress_runtime_fields(team_cfg)
            teams.append(team_cfg)

    return teams


def try_update_auto_capture_from_index_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False

    if "gun_with_user_info" not in payload or "fairy_with_user_info" not in payload:
        return False

    teams = build_team_configs_from_index(payload)
    if not teams:
        return False

    reset_captured_team_configs()

    if CONFIG.get("MODE_NAME") == "team":
        expected = max(1, min(10, int(CONFIG.get("TRAIN_TEAM_COUNT", 1))))
        selected = teams[:expected]
        for team_cfg in selected:
            CAPTURED_TEAM_CONFIGS.append({
                "team_id": team_cfg["team_id"],
                "fairy_id": team_cfg["fairy_id"],
                "fairy": copy.deepcopy(team_cfg.get("fairy")),
                "guns": copy.deepcopy(team_cfg["guns"]),
                "runtime_seconds": 0.0,
                "completed": False,
            })
        if CAPTURED_TEAM_CONFIGS:
            CONFIG["TEAM_ID"] = CAPTURED_TEAM_CONFIGS[0]["team_id"]
            CONFIG["FAIRY_ID"] = CAPTURED_TEAM_CONFIGS[0]["fairy_id"]
            CONFIG["FAIRY"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0].get("fairy"))
            CONFIG["GUNS"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0]["guns"])
        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = len(CAPTURED_TEAM_CONFIGS)
    else:
        first_team = teams[0]
        CAPTURED_TEAM_CONFIGS.append({
            "team_id": first_team["team_id"],
            "fairy_id": first_team["fairy_id"],
            "fairy": copy.deepcopy(first_team.get("fairy")),
            "guns": copy.deepcopy(first_team["guns"]),
            "runtime_seconds": 0.0,
            "completed": False,
        })
        CONFIG["TEAM_ID"] = first_team["team_id"]
        CONFIG["FAIRY_ID"] = first_team["fairy_id"]
        CONFIG["FAIRY"] = copy.deepcopy(first_team.get("fairy"))
        CONFIG["GUNS"] = copy.deepcopy(first_team["guns"])
        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 1

    user_info = payload.get("user_info", {})
    if isinstance(user_info, dict):
        user_id = user_info.get("user_id")
        try:
            user_id = str(int(user_id))
            if user_id:
                CONFIG["USER_UID"] = user_id
        except Exception:
            pass

    AUTO_CAPTURE_STATE["completed"] = True
    return True




# === GFAM: 根据当前仓库空位自动计算 Micro 上限 ===
def _gfam_storage_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def gfam_get_base_micro_limit():
    """返回 Micro 人工上限。

    默认不再固定封顶到 8，而是按仓库空位 / 每轮最大占用计算。
    如需手动限制，可在运行前设置环境变量 GFAM_MICRO_CAP=8 或其他正整数。
    """
    env_cap = _gfam_storage_int(os.environ.get("GFAM_MICRO_CAP", "0"), 0)
    if env_cap > 0:
        return max(1, env_cap)
    base = _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE_BASE", 0), 0)
    if base > 0 and base != 8:
        return max(1, base)
    return 999999


def gfam_micro_base_label(base_limit):
    try:
        base_limit = int(base_limit)
    except Exception:
        base_limit = 0
    if base_limit >= 999999:
        return "不设固定上限"
    return str(base_limit)


def gfam_is_night_equip_farm_mode():
    return CONFIG.get("SELECTED_DIFFICULTY") == "夜战" and CONFIG.get("MODE_NAME") != "team"


def gfam_get_gun_storage_from_index_payload(payload):
    if not isinstance(payload, dict):
        return 0, 0, 0
    user_info = payload.get("user_info", {}) or {}
    if not isinstance(user_info, dict):
        user_info = {}
    max_gun = 0
    for key in ("maxgun", "max_gun", "max_gun_num", "gun_max", "max_doll", "maxdoll"):
        max_gun = _gfam_storage_int(user_info.get(key), 0)
        if max_gun > 0:
            break
    guns = payload.get("gun_with_user_info", [])
    if isinstance(guns, dict):
        guns = list(guns.values())
    used = len(guns) if isinstance(guns, list) else 0
    if used <= 0:
        for key in ("gun_num", "doll_num", "gun_count"):
            used = _gfam_storage_int(user_info.get(key), 0)
            if used > 0:
                break
    free = max(0, max_gun - used) if max_gun > 0 else 0
    return max_gun, used, free

def gfam_estimate_drop_battles_per_run():
    """估算每个 Micro 至少需要预留的人形/装备仓库占用。

    普通/紧急/13-4 等人形掉落流程：战役内每场战斗可能掉落 1 个人形，
    战役胜利结算还可能额外给 1 个随机人形，所以默认按 len(ROUTE) + 1
    预留人形仓库空位。

    夜战装备打捞：战役内每场战斗可能掉落 1 件装备，
    战役胜利结算还可能额外给 1 件随机装备，所以默认按 len(ROUTE) + 1
    预留装备仓库空位。
    如需特殊覆盖，可设置 STORAGE_MICRO_BATTLES_PER_RUN 为正数。
    """
    manual = _gfam_storage_int(CONFIG.get("STORAGE_MICRO_BATTLES_PER_RUN", 0), 0)
    if manual > 0:
        return manual
    route = CONFIG.get("ROUTE", [])
    if isinstance(route, (list, tuple)):
        base = max(1, len(route))
    else:
        base = 1
    if gfam_is_night_equip_farm_mode():
        extra = max(0, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_EXTRA_EQUIP_DROPS_PER_RUN", 1), 1))
        return base + extra
    extra = max(0, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_EXTRA_GUN_DROPS_PER_RUN", 1), 1))
    return base + extra


def gfam_note_storage_usage_after_micro(dropped):
    """按本 Micro 实际掉落实时更新本地仓库缓存。

    游戏只会在战役开始前检查仓库是否已满；如果开始时仍有空位，
    战役过程中即使掉落数量超过剩余空位也能正常结算。因此 Micro 上限
    不能只用“空位 // 理论最大掉落数”硬截断，而应允许最后一轮在
    0 < 空位 < 理论最大掉落数时继续运行，并在每轮结束后用实际掉落
    扣减本地缓存。缓存可用空位为 0 时，再停止当前 Macro，先拆解/刷新。
    """
    if not isinstance(dropped, dict) or not CONFIG.get("DYNAMIC_MICRO_BY_STORAGE", True):
        return True
    if gfam_is_night_equip_farm_mode():
        info_key = "EQUIP_STORAGE_MICRO_INFO"
        delta = len(dropped.get("equips", []) or [])
        label = "装备仓库"
    else:
        info_key = "STORAGE_MICRO_INFO"
        delta = len(dropped.get("guns", []) or [])
        label = "人形仓库"
    info = CONFIG.get(info_key)
    if delta <= 0:
        # 夜战装备掉落有时不会在返回包中稳定给出 UID；此时如果完全不更新缓存，
        # 面板会长期停在旧仓库数量，且 Macro 末尾也不会触发装备应急拆解。
        # 因此夜战装备模式在“未解析到 UID”时按当前空位与理论最大掉落做保守扣减。
        if gfam_is_night_equip_farm_mode() and isinstance(info, dict) and info:
            try:
                free_now = _gfam_storage_int(info.get("free", 0), 0)
                fallback_delta = max(1, gfam_estimate_drop_battles_per_run())
                if free_now > 0:
                    delta = min(fallback_delta, free_now)
                    gfam_debug_log("[装备仓库缓存] 本轮未解析到具体装备 UID，按夜战装备保守估算扣减本地缓存 %s 件。" % delta)
                else:
                    return False
            except Exception:
                return True
        else:
            return True
    if not isinstance(info, dict) or not info:
        return True
    used = _gfam_storage_int(info.get("used", 0), 0) + delta
    free = max(0, _gfam_storage_int(info.get("free", 0), 0) - delta)
    reserve = max(0, _gfam_storage_int(info.get("reserve", 0), 0))
    usable_free = max(0, free - reserve)
    info["used"] = used
    info["free"] = free
    info["usable_free"] = usable_free
    info["last_local_update_time"] = time.time()
    if usable_free <= 0:
        gfam_debug_log("[%s] 本 Micro 实际掉落 %s 后，本地缓存可用空位已为 0；当前战役已正常结算，将先结束本轮 Macro 并执行拆解/刷新。" % (label, delta))
        return False
    return True


def gfam_note_storage_recovered_after_retire(storage_kind, count):
    """自动拆解成功后按本地数量恢复仓库缓存，并立即刷新面板。

    注意：这里不请求 Index/index。服务器已经返回拆解成功时，本地缓存应直接
    按实际拆解数量扣减 used、恢复 free；否则状态面板会继续显示拆解前库存，
    看起来像“拆解后仓库数量没有变化”。
    """
    try:
        count = int(count or 0)
    except Exception:
        count = 0
    if count <= 0:
        return False
    if storage_kind == "equip":
        info_key = "EQUIP_STORAGE_MICRO_INFO"
        max_key = "max_equip"
        label = "装备仓库"
    else:
        info_key = "STORAGE_MICRO_INFO"
        max_key = "max_gun"
        label = "人形仓库"
    info = CONFIG.get(info_key)
    if not isinstance(info, dict) or not info:
        gfam_debug_log("[%s缓存] 拆解成功 %s 个，但本地仓库缓存不存在，跳过本地扣减；下一次必要 Index 会校准。" % (label, count))
        return False
    max_val = _gfam_storage_int(info.get(max_key, 0), 0)
    old_used = _gfam_storage_int(info.get("used", 0), 0)
    old_free = _gfam_storage_int(info.get("free", 0), 0)
    used = max(0, old_used - count)
    free = old_free + count
    if max_val > 0:
        # 如果运行中曾经超过上限，free 应以 max-used 为准；否则按拆解数量恢复。
        free = max(0, min(max_val - used, free))
    reserve = max(0, _gfam_storage_int(info.get("reserve", 0), 0))
    info["used"] = used
    info["free"] = free
    info["usable_free"] = max(0, free - reserve)
    info["last_local_update_time"] = time.time()
    gfam_debug_log("[%s缓存] 拆解成功：-%s，本地库存 %s/%s 空位 %s -> %s/%s 空位 %s。" % (
        label, count, old_used, max_val or "?", old_free, used, max_val or "?", free
    ))
    try:
        refresh_runtime_panel()
    except Exception:
        pass
    return True


def gfam_recompute_storage_micro_limit_from_cache(storage_kind="gun", reason="本地仓库缓存"):
    """不请求 Index/index，直接根据本地仓库缓存重新计算下一轮 Micro 上限。

    用于自动拆解成功后：服务器已确认拆解成功，此时直接用拆解数量更新
    本地 used/free/usable_free，再按相同的 ceil 规则计算下一轮上限，避免
    每次仓库到 0 或拆解后都重新拉 Index/index。
    """
    if storage_kind == "equip":
        info_key = "EQUIP_STORAGE_MICRO_INFO"
        block_key = "EQUIP_STORAGE_MICRO_LIMIT_BLOCKED"
        label = "装备仓库"
    else:
        info_key = "STORAGE_MICRO_INFO"
        block_key = "STORAGE_MICRO_LIMIT_BLOCKED"
        label = "仓库"
    info = CONFIG.get(info_key)
    if not isinstance(info, dict) or not info:
        return True
    usable_free = max(0, _gfam_storage_int(info.get("usable_free", info.get("free", 0)), 0))
    battles = max(1, _gfam_storage_int(info.get("battles_per_run", gfam_estimate_drop_battles_per_run()), 1))
    base_limit = gfam_get_base_micro_limit()
    old_limit = _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE", base_limit), base_limit)
    if storage_kind == "equip":
        # 装备仓库必须有足够跑完整一轮的安全空位；199/200 且每轮估算 6 件时应为 0，先拆解而不是开跑。
        auto_limit = 0 if usable_free < battles else max(1, usable_free // battles)
    else:
        # 人形仓库继续沿用旧策略：最后不足一整轮时允许开一轮并按实际掉落扣减缓存。
        auto_limit = 0 if usable_free <= 0 else max(1, (usable_free + battles - 1) // battles)
    info["base_limit"] = base_limit
    info["old_limit"] = old_limit
    info["auto_limit"] = auto_limit
    info["last_local_update_time"] = time.time()
    if auto_limit <= 0:
        CONFIG["MISSIONS_PER_RETIRE"] = 0
        CONFIG[block_key] = True
        gfam_debug_log("[%s] %s：本地缓存可用空位不足一整轮，下一轮将先整理/拆解，不请求 Index/index。" % (label, reason))
        return False
    new_limit = max(1, min(base_limit, auto_limit))
    CONFIG["MISSIONS_PER_RETIRE"] = new_limit
    CONFIG[block_key] = False
    gfam_debug_log("[%s] %s：已按本地缓存重新计算 Micro 上限：%s -> %s（可用空位 %s，每轮最多 %s）。" % (label, reason, old_limit, new_limit, usable_free, battles))
    return True

def gfam_apply_dynamic_micro_limit_from_index_payload(payload, reason="Index/index"):
    if gfam_is_night_equip_farm_mode():
        CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = False
        return True
    if not CONFIG.get("DYNAMIC_MICRO_BY_STORAGE", True):
        return True
    max_gun, used, free = gfam_get_gun_storage_from_index_payload(payload)
    if max_gun <= 0:
        print("[仓库] 无法从 %s 读取人形仓库容量，保留当前 Micro 上限：%s。" % (reason, CONFIG.get("MISSIONS_PER_RETIRE")))
        return True
    reserve = max(0, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_RESERVE", 0), 0))
    usable_free = max(0, free - reserve)
    battles = max(1, gfam_estimate_drop_battles_per_run())
    base_limit = gfam_get_base_micro_limit()
    old_limit = _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE", base_limit), base_limit)
    auto_limit = 0 if usable_free <= 0 else max(1, (usable_free + battles - 1) // battles)
    CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = False
    CONFIG["STORAGE_MICRO_INFO"] = {
        "max_gun": max_gun,
        "used": used,
        "free": free,
        "usable_free": usable_free,
        "reserve": reserve,
        "battles_per_run": battles,
        "base_limit": base_limit,
        "old_limit": old_limit,
        "auto_limit": auto_limit,
    }
    if auto_limit <= 0:
        CONFIG["MISSIONS_PER_RETIRE"] = 0
        CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = True
        print("[仓库] 当前人形仓库：%s/%s，空位 %s；本模式按每轮最多 %s 个人形仓库占用估算。" % (used, max_gun, free, battles))
        print("[仓库] 可安全执行的 Micro 上限为 0。请先整理/拆解人形仓库后再运行，避免触发应急拆解。")
        return False
    new_limit = max(1, min(base_limit, auto_limit))
    CONFIG["MISSIONS_PER_RETIRE"] = new_limit
    print("[仓库] 当前人形仓库：%s/%s，空位 %s；本模式按每轮最多 %s 个人形仓库占用估算（含胜利结算随机人形）。" % (used, max_gun, free, battles))
    if new_limit != old_limit:
        print("[仓库] 已按人工上限 %s 与当前仓库空位，将本次 Micro 上限从 %s 调整为 %s（按完整安全轮数计算）。" % (gfam_micro_base_label(base_limit), old_limit, new_limit))
    else:
        print("[仓库] 当前空位足够，Micro 上限保持为 %s。" % new_limit)
    return True


def gfam_storage_micro_blocked():
    if gfam_is_night_equip_farm_mode():
        return bool(CONFIG.get("EQUIP_STORAGE_MICRO_LIMIT_BLOCKED", False)) or _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE", 1), 1) <= 0
    return bool(CONFIG.get("STORAGE_MICRO_LIMIT_BLOCKED", False)) or _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE", 1), 1) <= 0


# === GFAM: 仓库空位不足时的应急拆解 ===
def gfam_is_gun_locked_for_emergency(gun):
    if not isinstance(gun, dict):
        return True
    for key in ("if_locked", "is_locked", "locked", "lock", "is_lock"):
        if key in gun:
            val = str(gun.get(key)).strip().lower()
            if val in ("1", "true", "yes", "y"):
                return True
    return False

def gfam_get_gun_team_id_for_emergency(gun):
    if not isinstance(gun, dict):
        return 0
    for key in ("team_id", "team", "location"):
        if key in gun:
            return _gfam_storage_int(gun.get(key), 0)
    return 0

def gfam_get_gun_uid_for_emergency(gun):
    if not isinstance(gun, dict):
        return 0
    for key in ("gun_with_user_id", "id", "uid"):
        if key in gun:
            return _gfam_storage_int(gun.get(key), 0)
    return 0

def gfam_get_gun_id_for_emergency(gun):
    if not isinstance(gun, dict):
        return 0
    return _gfam_storage_int(gun.get("gun_id", gun.get("gun", 0)), 0)

def gfam_emergency_protected_gun_ids():
    try:
        return set(int(x) for x in get_selected_protected_gun_ids())
    except Exception:
        return set()

def gfam_collect_emergency_retire_uids_from_index(payload, protected_ids=None):
    protected_ids = set(protected_ids or [])
    guns = payload.get("gun_with_user_info", []) if isinstance(payload, dict) else []
    if isinstance(guns, dict):
        guns = list(guns.values())
    if not isinstance(guns, list):
        return []
    uids = []
    for gun in guns:
        if not isinstance(gun, dict):
            continue
        if gfam_is_gun_locked_for_emergency(gun):
            continue
        if gfam_get_gun_team_id_for_emergency(gun) != 0:
            continue
        gun_id = gfam_get_gun_id_for_emergency(gun)
        if gun_id in protected_ids:
            continue
        uid = gfam_get_gun_uid_for_emergency(gun)
        if uid > 0:
            uids.append(uid)
    return uids

def gfam_request_index_for_emergency(client):
    payload = {"time": int(time.time()), "furniture_data": False}
    resp = client.send_request(API_INDEX_INDEX, payload)
    if isinstance(resp, dict) and "error" not in resp and "error_local" not in resp:
        update_fairy_cache_from_index_payload(resp, source="smart Index/index")
        return resp
    return None

def gfam_try_emergency_retire_then_refresh_index(client, payload, reason="仓库空位不足"):
    protected_ids = gfam_emergency_protected_gun_ids()
    uids = gfam_collect_emergency_retire_uids_from_index(payload, protected_ids)
    if not uids:
        print("[仓库] %s，但当前没有可用于应急拆解的未上锁、未编队人形。" % reason)
        return None
    print("[仓库] %s，正在先尝试应急拆解 %d 名未上锁、未编队人形……" % (reason, len(uids)))
    if protected_ids:
        print("[仓库] 已保留受保护目标 gun_id：%s" % sorted(protected_ids))
    resp = client.send_request(API_GUN_RETIRE, uids)
    if not (isinstance(resp, dict) and resp.get("success")):
        print("[仓库] 应急拆解失败：%s" % str(resp))
        return None
    print("[仓库] 应急拆解成功，已按拆解数量更新本地仓库缓存，不再立即请求 Index/index。")
    gfam_note_storage_recovered_after_retire("gun", len(uids))
    gfam_recompute_storage_micro_limit_from_cache("gun", reason="应急拆解后本地缓存")
    time.sleep(0.3)
    return payload

def gfam_apply_dynamic_micro_limit_with_emergency_retire(client, payload, reason="Index/index"):
    ok = gfam_apply_dynamic_micro_limit_from_index_payload(payload, reason=reason)
    if ok:
        return payload, True
    refreshed = gfam_try_emergency_retire_then_refresh_index(client, payload, reason="仓库空位不足，Micro 上限为 0")
    if not refreshed:
        return payload, False
    ok2 = gfam_recompute_storage_micro_limit_from_cache("gun", reason="应急拆解后本地缓存")
    if not ok2:
        print("[仓库] 应急拆解后本地缓存仍显示无可用空位，已取消本次运行。")
        return refreshed, False
    return refreshed, True

def gfam_local_gun_storage_usable_free():
    info = CONFIG.get("STORAGE_MICRO_INFO")
    if not isinstance(info, dict):
        return 0
    try:
        return max(0, _gfam_storage_int(info.get("usable_free", info.get("free", 0)), 0))
    except Exception:
        return 0


def emergency_retire_guns_from_index(client, reason="EPA Micro Error Before Retry"):
    """运行中 Micro 失败后的轻量自修复。

    先看本地仓库缓存：如果本地仍有可用空位，通常是状态同步/节奏问题，
    不请求 Index/index，也不拆解。只有本地缓存已经为 0 或缺失时，
    才把 Index/index 作为兜底校准，用于寻找可拆人形。
    """
    if not CONFIG.get("ENABLE_GUN_EXCEPTION_SELF_REPAIR", True):
        print("[自修复] 人形异常自修复已关闭，跳过应急拆解。")
        return False
    if gfam_last_error_is_auth():
        print("[自修复] 最近错误明确为 UID/SIGN 失效，跳过人形应急拆解。")
        return False
    local_free = gfam_local_gun_storage_usable_free()
    if local_free > 0:
        print("[自修复] 本地人形仓库缓存仍有可用空位 %s，本次按同步异常处理，不请求 Index/index、不触发拆解。" % local_free)
        return False
    payload = gfam_request_index_for_emergency(client)
    if not payload:
        print("[自修复] 无法获取 Index/index，跳过人形应急拆解。")
        return False
    refreshed = gfam_try_emergency_retire_then_refresh_index(client, payload, reason=reason)
    return refreshed is not None

# === GFAM: 仓库空位不足时的应急拆解结束 ===



# === GFAM: 夜战装备仓库与装备应急拆解 ===
def gfam_get_equip_uid_for_emergency(equip):
    if not isinstance(equip, dict):
        return 0
    for key in ("equip_with_user_id", "id", "uid"):
        if key in equip:
            uid = _gfam_storage_int(equip.get(key), 0)
            if uid > 0:
                return uid
    return 0


def gfam_get_equip_rank_for_emergency(equip):
    if not isinstance(equip, dict):
        return 0
    for key in ("rank", "star", "rarity"):
        if key in equip:
            value = _gfam_storage_int(equip.get(key), 0)
            if value > 0:
                return value
    return 0


def gfam_get_equip_level_for_emergency(equip):
    if not isinstance(equip, dict):
        return 0
    for key in ("level", "equip_level", "lv"):
        if key in equip:
            return _gfam_storage_int(equip.get(key), 0)
    return 0


def gfam_is_equip_locked_for_emergency(equip):
    if not isinstance(equip, dict):
        return True
    for key in ("if_locked", "is_locked", "locked", "lock", "is_lock"):
        if key in equip:
            val = str(equip.get(key)).strip().lower()
            if val in ("1", "true", "yes", "y"):
                return True
    return False


def gfam_is_equip_equipped_for_emergency(equip):
    if not isinstance(equip, dict):
        return True
    for key in ("gun_with_user_id", "gun_id", "team_id", "squad_id", "slot", "position", "location", "equip_position", "equip_slot"):
        if key in equip:
            val = equip.get(key)
            try:
                if int(val or 0) != 0:
                    return True
            except Exception:
                if val:
                    return True
    return False


def gfam_extract_equips_from_index_payload(payload):
    if not isinstance(payload, dict):
        return []
    candidates = []
    for key in (
        "equip_with_user_info",
        "equip_with_user",
        "equipment_with_user_info",
        "equipment_with_user",
        "equip_user_info",
        "equip_info",
        "equipment_info",
        "equip_list",
        "equipment_list",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.extend(list(value.values()))
        elif isinstance(value, list):
            candidates.extend(value)
    # 去重，避免同一个装备列表被不同字段重复引用时影响仓库占用计算。
    seen = set()
    equips = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        uid = gfam_get_equip_uid_for_emergency(item)
        if uid > 0:
            if uid in seen:
                continue
            seen.add(uid)
        equips.append(item)
    return equips


def _gfam_find_first_int_by_keys(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                value = _gfam_storage_int(obj.get(key), 0)
                if value > 0:
                    return value
        for value in obj.values():
            found = _gfam_find_first_int_by_keys(value, keys)
            if found > 0:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _gfam_find_first_int_by_keys(item, keys)
            if found > 0:
                return found
    return 0


def gfam_get_equip_storage_from_index_payload(payload):
    if not isinstance(payload, dict):
        return 0, 0, 0
    user_info = payload.get("user_info", {}) or {}
    if not isinstance(user_info, dict):
        user_info = {}
    max_keys = (
        "maxequip",
        "max_equip",
        "max_equips",
        "max_equipment",
        "equip_max",
        "equipment_max",
        "equip_limit",
        "equipment_limit",
        "equip_with_user_limit",
        "max_equip_num",
    )
    used_keys = (
        "equip_num",
        "equipment_num",
        "equip_count",
        "equipment_count",
        "equip_with_user_count",
        "used_equip",
        "used_equipment",
    )
    max_equip = _gfam_find_first_int_by_keys(user_info, max_keys)
    if max_equip <= 0:
        max_equip = _gfam_find_first_int_by_keys(payload, max_keys)
    equips = gfam_extract_equips_from_index_payload(payload)
    list_used = len(equips) if isinstance(equips, (list, tuple, dict)) else 0
    counter_used = _gfam_find_first_int_by_keys(user_info, used_keys)
    if counter_used <= 0:
        counter_used = _gfam_find_first_int_by_keys(payload, used_keys)
    # Index 里常见情况是“装备列表字段不完整，但 user_info / payload 计数字段准确”。
    # 因此显示与 Micro 估算优先使用计数字段；列表数量只在缺少计数字段时兜底。
    if counter_used > 0:
        used = counter_used
        if list_used > 0 and abs(list_used - counter_used) >= 2:
            gfam_debug_log("[装备仓库] Index装备列表数量 %s 与计数字段 %s 不一致，优先使用计数字段。" % (list_used, counter_used))
    else:
        used = list_used
    free = max(0, max_equip - used) if max_equip > 0 else 0
    return max_equip, used, free


def gfam_apply_dynamic_equip_limit_from_index_payload(payload, reason="Index/index"):
    if not gfam_is_night_equip_farm_mode():
        CONFIG["EQUIP_STORAGE_MICRO_LIMIT_BLOCKED"] = False
        return True
    max_equip, used, free = gfam_get_equip_storage_from_index_payload(payload)
    if max_equip <= 0:
        print("[装备仓库] 无法从 %s 读取装备仓库容量，保留当前 Micro 上限：%s。" % (reason, CONFIG.get("MISSIONS_PER_RETIRE")))
        CONFIG["EQUIP_STORAGE_MICRO_LIMIT_BLOCKED"] = False
        return True
    reserve = max(0, _gfam_storage_int(CONFIG.get("EQUIP_SPACE_RESERVED", 0), 0))
    usable_free = max(0, free - reserve)
    battles = max(1, gfam_estimate_drop_battles_per_run())
    base_limit = gfam_get_base_micro_limit()
    old_limit = _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE", base_limit), base_limit)
    auto_limit = 0 if usable_free < battles else max(1, usable_free // battles)
    CONFIG["EQUIP_STORAGE_MICRO_LIMIT_BLOCKED"] = False
    CONFIG["EQUIP_STORAGE_MICRO_INFO"] = {
        "max_equip": max_equip,
        "used": used,
        "free": free,
        "usable_free": usable_free,
        "reserve": reserve,
        "battles_per_run": battles,
        "base_limit": base_limit,
        "old_limit": old_limit,
        "auto_limit": auto_limit,
    }
    if auto_limit <= 0:
        CONFIG["MISSIONS_PER_RETIRE"] = 0
        CONFIG["EQUIP_STORAGE_MICRO_LIMIT_BLOCKED"] = True
        print("[装备仓库] 当前装备仓库：%s/%s，空位 %s，保留空位 %s；本模式按每轮最多 %s 件装备仓库占用估算（含胜利结算随机装备）。" % (used, max_equip, free, reserve, battles))
        if CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
            print("[装备仓库] 可安全执行的 Micro 上限为 0，将先尝试装备应急拆解。")
        else:
            print("[装备仓库] 可安全执行的 Micro 上限为 0；当前已关闭装备自动/应急拆解，将停止运行以便手动检查仓库。")
        return False
    new_limit = max(1, min(base_limit, auto_limit))
    CONFIG["MISSIONS_PER_RETIRE"] = new_limit
    print("[装备仓库] 当前装备仓库：%s/%s，空位 %s，保留空位 %s；本模式按每轮最多 %s 件装备仓库占用估算（含胜利结算随机装备）。" % (used, max_equip, free, reserve, battles))
    if new_limit != old_limit:
        print("[装备仓库] 已按人工上限 %s 与当前仓库空位，将本次 Micro 上限从 %s 调整为 %s（按完整安全轮数计算）。" % (gfam_micro_base_label(base_limit), old_limit, new_limit))
    else:
        print("[装备仓库] 当前空位足够，Micro 上限保持为 %s。" % new_limit)
    return True


def gfam_collect_emergency_retire_equip_uids_from_index(payload, max_count=None):
    equips = gfam_extract_equips_from_index_payload(payload)
    if not equips:
        return []
    max_rank = _gfam_storage_int(CONFIG.get("EQUIP_AUTO_RETIRE_MAX_RANK", 4), 4)
    selected = []
    for equip in equips:
        if not isinstance(equip, dict):
            continue
        uid = gfam_get_equip_uid_for_emergency(equip)
        if uid <= 0:
            continue
        equip_id = gfam_extract_equip_id(equip)
        rank = gfam_get_equip_rank_for_emergency(equip)
        ok, reason = gfam_should_auto_retire_equip_by_rules(uid, equip_id, rank=rank, raw=equip, source="emergency-index")
        if not ok:
            continue
        # 关键：应急拆解从 Index 选择出来的 UID 也必须把原始字段写入运行期映射。
        # retire_equips 会再次按 AND 规则复核；如果这里不保存 raw，二次过滤会因为“缺少原始字段”把全部对象跳过。
        DROPPED_UID_TO_EQUIP_ID[uid] = equip_id
        DROPPED_UID_TO_EQUIP_RANK[uid] = rank
        DROPPED_UID_TO_EQUIP_RAW[uid] = equip
        selected.append({"uid": uid, "rank": rank, "level": gfam_get_equip_level_for_emergency(equip)})
    selected.sort(key=lambda x: (x["rank"], x["level"], x["uid"]))
    if max_count is None:
        max_count = _gfam_storage_int(CONFIG.get("EQUIP_RETIRE_MAX_COUNT", 40), 40)
    return [x["uid"] for x in selected[:max(1, max_count)]]


def gfam_try_emergency_equip_retire_then_refresh_index(client, payload, reason="装备仓库空位不足"):
    if not CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
        print("[装备仓库] %s；已关闭装备自动/应急拆解，不会自动清理装备。" % reason)
        return None
    if gfam_last_error_is_auth():
        print("[装备仓库] 最近错误明确为 UID/SIGN 失效，跳过装备应急拆解。")
        return None
    uids = gfam_collect_emergency_retire_equip_uids_from_index(payload)
    if not uids:
        print("[装备仓库] %s，但当前没有同时满足“低星、未上锁、未装备、非专属/非保护”的安全可拆装备。" % reason)
        return None
    print("[装备仓库] %s，正在先尝试应急拆解 %d 件低星未装备装备……" % (reason, len(uids)))
    if not retire_equips(client, uids):
        print("[装备仓库] 装备应急拆解失败。")
        return None
    retired_count = gfam_get_last_equip_retire_count()
    if retired_count > 0:
        print("[装备仓库] 装备应急拆解成功，已按实际拆解数量更新本地装备仓库缓存，不再立即请求 Index/index。")
        gfam_note_storage_recovered_after_retire("equip", retired_count)
        gfam_recompute_storage_micro_limit_from_cache("equip", reason="装备应急拆解后本地缓存")
    else:
        print("[装备仓库] 装备应急拆解接口完成，但过滤后实际拆解 0 件，本地装备仓库缓存不扣减。")
        return None
    time.sleep(0.3)
    return payload


def gfam_apply_dynamic_equip_limit_with_emergency_retire(client, payload, reason="Index/index"):
    ok = gfam_apply_dynamic_equip_limit_from_index_payload(payload, reason=reason)
    if ok:
        return payload, True
    refreshed = gfam_try_emergency_equip_retire_then_refresh_index(client, payload, reason="装备仓库空位不足，Micro 上限为 0")
    if not refreshed:
        return payload, False
    ok2 = gfam_recompute_storage_micro_limit_from_cache("equip", reason="装备应急拆解后本地缓存")
    if not ok2:
        print("[装备仓库] 装备应急拆解后本地缓存仍显示无可用空位，已取消本次运行。")
        return refreshed, False
    return refreshed, True


def gfam_local_equip_storage_usable_free():
    info = CONFIG.get("EQUIP_STORAGE_MICRO_INFO")
    if not isinstance(info, dict):
        return 0
    try:
        return max(0, _gfam_storage_int(info.get("usable_free", info.get("free", 0)), 0))
    except Exception:
        return 0


def emergency_retire_equips_from_index(client, reason="Night EPA Recovery"):
    if not CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
        print("[夜战EPA] 已关闭装备自动/应急拆解，本次不会从装备仓库自动拆解。原因：%s" % reason)
        return False
    local_free = gfam_local_equip_storage_usable_free()
    try:
        battles = max(1, gfam_estimate_drop_battles_per_run())
    except Exception:
        battles = 1
    # 旧逻辑只要 local_free > 0 就直接跳过，导致 199/200、空位 1 这种“不足下一轮”的情况无法拆解。
    # 现在只有空位足够下一轮，且本地缓存未标记危险时，才跳过 Index/index。
    if local_free >= battles and not gfam_equip_storage_tight_for_next_run():
        gfam_debug_log("[夜战EPA] 本地装备仓库缓存仍有可用空位 %s，足够下一轮估算 %s 件；本次不请求 Index/index、不触发应急拆解。" % (local_free, battles))
        return False
    if local_free > 0:
        gfam_debug_log("[夜战EPA] 本地装备仓库仍有空位 %s，但不足下一轮估算 %s 件，继续执行装备应急拆解。" % (local_free, battles))
    print("[夜战EPA] 正在执行装备应急拆解：%s" % reason)
    payload = gfam_request_index_for_emergency(client)
    if not payload:
        print("[夜战EPA] 无法获取 Index/index，装备应急拆解失败。")
        return False
    uids = gfam_collect_emergency_retire_equip_uids_from_index(payload)
    if not uids:
        print("[夜战EPA] 没有找到安全可拆的低星未装备装备。")
        return False
    ok = retire_equips(client, uids)
    if not ok:
        return False
    retired_count = gfam_get_last_equip_retire_count()
    if retired_count <= 0:
        print("[夜战EPA] 装备应急拆解完成但实际拆解 0 件，本地装备仓库缓存不扣减。")
        return False
    gfam_note_storage_recovered_after_retire("equip", retired_count)
    if not gfam_recompute_storage_micro_limit_from_cache("equip", reason="装备应急拆解后本地缓存"):
        return False
    if gfam_equip_storage_tight_for_next_run():
        print("[夜战EPA] 装备应急拆解后空位仍不足下一轮安全估算，停止运行，避免在危险仓库状态下继续开战。")
        return False
    return True


# ===== GFAM: 夜战装备仓库与拆解兜底 =====
def gfam_set_last_equip_retire_count(count):
    try:
        CONFIG["EQUIP_LAST_RETIRE_COUNT"] = max(0, int(count or 0))
    except Exception:
        CONFIG["EQUIP_LAST_RETIRE_COUNT"] = 0


def gfam_get_last_equip_retire_count():
    try:
        return max(0, _gfam_storage_int(CONFIG.get("EQUIP_LAST_RETIRE_COUNT", 0), 0))
    except Exception:
        return 0


def gfam_equip_storage_info_snapshot():
    info = CONFIG.get("EQUIP_STORAGE_MICRO_INFO", {})
    return info if isinstance(info, dict) else {}


def gfam_equip_storage_tight_for_next_run():
    """仅使用本地缓存判断装备仓库是否已经不足以安全进入下一轮。"""
    try:
        if not gfam_is_night_equip_farm_mode():
            return False
    except Exception:
        if CONFIG.get("SELECTED_DIFFICULTY") != "夜战":
            return False
    info = gfam_equip_storage_info_snapshot()
    if not info:
        return False
    try:
        blocked = bool(CONFIG.get("EQUIP_STORAGE_MICRO_LIMIT_BLOCKED", False))
        free = _gfam_storage_int(info.get("free", 0), 0)
        usable_free = _gfam_storage_int(info.get("usable_free", info.get("free", 0)), 0)
        auto_limit = _gfam_storage_int(info.get("auto_limit", 0), 0)
        battles = max(1, _gfam_storage_int(info.get("battles_per_run", 0), 0) or gfam_estimate_drop_battles_per_run())
    except Exception:
        return False
    # blocked / 可用为 0 / 不足一轮理论最大装备掉落，均应先拆解，不再依赖“本轮是否记录到装备掉落”。
    return blocked or usable_free <= 0 or auto_limit <= 0 or free <= 0 or free < battles


def gfam_force_equip_cleanup_if_storage_tight(client, reason="Night EPA Macro End"):
    if not CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
        return True
    if not gfam_equip_storage_tight_for_next_run():
        return True
    info = gfam_equip_storage_info_snapshot()
    used = info.get("used", "?")
    max_equip = info.get("max_equip", info.get("max", "?"))
    free = info.get("free", "?")
    usable = info.get("usable_free", "?")
    battles = info.get("battles_per_run", gfam_estimate_drop_battles_per_run())
    print("[夜战EPA] 装备仓库空间不足或本地缓存已危险：%s/%s，空位 %s，可用空位 %s；每轮最多按 %s 件估算，开始装备应急拆解。" % (used, max_equip, free, usable, battles))
    recovered = emergency_retire_equips_from_index(client, reason=reason)
    if not recovered:
        print("[夜战EPA] 装备仓库应急拆解未能释放空间。")
        return False
    try:
        gfam_recompute_storage_micro_limit_from_cache("equip", reason="装备应急拆解后本地缓存")
    except Exception:
        pass
    if gfam_equip_storage_tight_for_next_run():
        print("[夜战EPA] 装备应急拆解后本地缓存仍不足下一轮安全估算，停止运行，避免继续堆高装备仓库。")
        return False
    return True
# ===== /GFAM: 夜战装备仓库与拆解兜底 =====

def gfam_refresh_dynamic_micro_limit_before_run(client):
    """运行前强制刷新仓库 Micro 上限。

    夜战装备打捞必须按装备仓库空位计算；普通/紧急打捞继续按人形仓库空位计算。
    这里每次 -r 前重新请求 Index/index，避免沿用上一次模式把 Micro 上限临时压低后的旧值。
    """
    if not CONFIG.get("DYNAMIC_MICRO_BY_STORAGE", True):
        return True
    payload = gfam_request_index_for_emergency(client)
    if not payload:
        print("[仓库] 运行前无法重新获取 Index/index，保留当前 Micro 上限：%s。" % CONFIG.get("MISSIONS_PER_RETIRE"))
        return not gfam_storage_micro_blocked()
    if gfam_is_night_equip_farm_mode():
        _payload, ok = gfam_apply_dynamic_equip_limit_with_emergency_retire(client, payload, reason="运行前 Index/index")
    else:
        _payload, ok = gfam_apply_dynamic_micro_limit_with_emergency_retire(client, payload, reason="运行前 Index/index")
    return ok


# === GFAM: 夜战装备仓库与装备应急拆解结束 ===

# === GFAM: 动态 Micro 上限结束 ===
def has_usable_dynamic_keys() -> bool:
    uid = str(CONFIG.get("USER_UID", "")).strip()
    sign = str(CONFIG.get("SIGN_KEY", "")).strip()
    if not uid or uid == "0":
        return False
    if not sign or sign == DEFAULT_SIGN:
        return False
    return True


def request_index_and_prepare_configs():
    CONFIG["LAST_INDEX_AUTH_ERROR"] = False
    if not has_usable_dynamic_keys():
        CONFIG["LAST_INDEX_AUTH_ERROR"] = True
        print("[!] UID/SIGN 或动态密钥未配置，本次不请求 Index/index。")
        print("[*] UID/SIGN 未就绪。请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN。")
        return False

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    print("[*] 正在主动请求 Index/index……")
    payload = {
        "time": int(time.time()),
        "furniture_data": False
    }

    response = client.send_request(API_INDEX_INDEX, payload)

    if isinstance(response, dict) and "error_local" in response:
        print("[-] Index/index 本地错误: %s" % response["error_local"])
        print("    原始响应：'%s'" % response.get("raw", "N/A"))
        raw_text = str(response.get("raw", "")).strip().lower()
        if raw_text in ("error:1", "1") or "error:1" in raw_text:
            CONFIG["LAST_INDEX_AUTH_ERROR"] = True
            print("[!] Index/index 返回 error:1，判定为 UID/SIGN 或动态密钥未就绪。")
        return False

    if isinstance(response, dict) and "error" in response:
        print("[-] Index/index 服务器错误: %s" % response["error"])
        if str(response.get("error", "")).strip() == "1":
            CONFIG["LAST_INDEX_AUTH_ERROR"] = True
            print("[!] Index/index 返回 error:1，判定为 UID/SIGN 或动态密钥未就绪。")
        return False

    if not isinstance(response, dict):
        print("[!] Index/index 返回格式异常。")
        return False

    gfam_write_debug_json("index_debug.json", response, "Index/index")

    update_fairy_cache_from_index_payload(response, source="smart 运行前 Index/index")

    if (CONFIG.get("MODE_NAME") == "smart_epa" or CONFIG.get("SMART_EPA_PLAN_MODE")) and smart_epa_is_equip_plan():
        response, _storage_ok = gfam_apply_dynamic_equip_limit_with_emergency_retire(client, response, reason="Index/index")
    elif CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
        response, _storage_ok = gfam_apply_dynamic_equip_limit_with_emergency_retire(client, response, reason="Index/index")
    else:
        response, _storage_ok = gfam_apply_dynamic_micro_limit_with_emergency_retire(client, response, reason="Index/index")
    if not _storage_ok:
        return False

    if CONFIG.get("MODE_NAME") == "smart_epa" or CONFIG.get("SMART_EPA_PLAN_MODE"):
        if not smart_epa_prepare_from_index(response):
            return False
        MENU_STATE["selection_unlocked"] = True
        reset_selection_menu()
        MENU_STATE["awaiting_stop_on_max"] = True
        print_main_menu()
        print_stop_on_max_menu()
        return True

    if not try_update_auto_capture_from_index_payload(response):
        print("[!] 已请求 Index/index，但未解析出有效梯队。")
        preview = str(response)[:300]
        print("    Parsed JSON preview: %s..." % preview)
        print("    如需继续排查，请设置 GFAM_SAVE_DEBUG_JSON=1 后重试，并把生成的 index_debug.json 发给我。")
        return False

    apply_auto_capture_to_config()
    if CONFIG.get("MODE_NAME") == "team":
        print("\n[AUTO] 已主动请求并解析 Index/index。")
        print("[AUTO] 共解析出 %d 个有效练级梯队：" % len(CAPTURED_TEAM_CONFIGS))
        for idx, team_cfg in enumerate(CAPTURED_TEAM_CONFIGS, start=1):
            print("[AUTO] 梯队%d -> TEAM_ID=%s | FAIRY_ID=%s | GUNS=%s" % (
                idx,
                team_cfg["team_id"],
                team_cfg["fairy_id"],
                team_cfg["guns"],
            ))
        print("[AUTO] 将默认从梯队一开始轮转。")
    else:
        print("\n[AUTO] 已主动请求并解析 Index/index。")
        print("[AUTO] TEAM_ID  = %s" % CONFIG["TEAM_ID"])
        print("[AUTO] FAIRY_ID = %s" % CONFIG["FAIRY_ID"])
        print("[AUTO] GUNS     = %s" % CONFIG["GUNS"])
        if not validate_captured_team_for_mode():
            return False

    MENU_STATE["selection_unlocked"] = True
    reset_selection_menu()
    print_main_menu()
    print_difficulty_menu()
    return True


def collect_keyed_values(obj, target_key: str):
    results = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k) == target_key:
                    results.append(v)
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)
    return results


def collect_gun_entries(obj):
    guns = []

    def walk(x):
        if isinstance(x, dict):
            if "id" in x and "life" in x:
                gun_id = x.get("id")
                life = x.get("life")
                if isinstance(gun_id, int) and isinstance(life, int):
                    guns.append({"id": gun_id, "life": life})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for gun in guns:
        key = (gun["id"], gun["life"])
        if key not in seen:
            seen.add(key)
            deduped.append(gun)
    return deduped


def try_update_auto_capture_from_payload(url: str, payload):
    # 新流程不再依赖被动抓取 TEAM_ID / FAIRY_ID / GUNS。
    # 这里只保留函数壳，避免旧调用报错。
    return False


def apply_auto_capture_to_config():
    if CONFIG.get("MODE_NAME") == "team":
        if CAPTURED_TEAM_CONFIGS:
            CONFIG["TEAM_ID"] = CAPTURED_TEAM_CONFIGS[0]["team_id"]
            CONFIG["FAIRY_ID"] = CAPTURED_TEAM_CONFIGS[0]["fairy_id"]
            CONFIG["GUNS"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0]["guns"])
    else:
        if AUTO_CAPTURE_STATE["team_id"] is not None:
            CONFIG["TEAM_ID"] = AUTO_CAPTURE_STATE["team_id"]
        if AUTO_CAPTURE_STATE["fairy_id"] is not None:
            CONFIG["FAIRY_ID"] = AUTO_CAPTURE_STATE["fairy_id"]
        if AUTO_CAPTURE_STATE["guns"]:
            CONFIG["GUNS"] = copy.deepcopy(AUTO_CAPTURE_STATE["guns"])


def stop_proxy_instance():
    global proxy_instance, worker_mode
    if proxy_instance:
        proxy_instance.stop()
        set_windows_proxy(False)
        proxy_instance = None
    worker_mode = None


def maybe_finish_auto_capture():
    return

def print_main_menu():
    print("\n================= SMART EPA MENU =================")

    if worker_mode == 'r':
        print(" 当前计划：%s" % smart_epa_plan_type_label())
        print(" -q : 当前 Macro 结束后安全停止")
        print(" -Q : 当前 Micro 结束后安全停止")
        print(" -E : 返回少女全自动 GFAM 主菜单")
    elif CONFIG.get("CONFIG_READY_FOR_INDEX", False) or CONFIG.get("INDEX_FETCH_READY", False):
        print(" 当前计划：%s" % smart_epa_plan_type_label())
        print(" -gun   : 选择人形一键打捞（普通/紧急）")
        print(" -equip : 选择装备一键打捞（夜战专属装备）")
        print(" -r     : 生成一键打捞计划并进入运行确认")
        print(" -E     : 返回少女全自动 GFAM 主菜单")
        print("----------------------------------------")
        if smart_epa_is_equip_plan():
            print("说明：装备一键打捞会扫描夜战 A-1～A-6 专属装备，按装备仓库空位计算 Micro。")
            print("说明：输入 -r 后会自动请求一次 Index/index，用于解析梯队1、妖精、装备仓库与计划状态。")
            print("说明：目标装备按已确认 equip_id 统计，并沿用装备拆解过滤/自动上锁保护。")
        else:
            print("说明：人形一键打捞会扫描 EPA 普通/紧急目标人形，按人形仓库空位计算 Micro。")
            print("说明：输入 -r 后会自动请求一次 Index/index，用于解析梯队1、妖精、人形仓库与计划状态。")
    elif MENU_STATE.get("awaiting_run_confirm") or MENU_STATE.get("awaiting_stop_on_max") or MENU_STATE.get("awaiting_target_drop_stop") or MENU_STATE.get("awaiting_equip_auto_lock") or MENU_STATE.get("awaiting_filter_protection"):
        print(" 当前正在进行运行前确认，请按上方提示输入。")
        print(" -back : 返回上一步")
        print(" -go   : 一键打捞（使用当前/默认选项直接开始）")
        print(" -m    : 返回打捞关卡选择")
        print(" -E    : 返回少女全自动 GFAM 主菜单")
    elif CONFIG.get("SELECTED_STAGE") and CONFIG.get("SELECTED_TARGET_LABEL") and not MENU_STATE.get("awaiting_run_confirm") and not MENU_STATE.get("awaiting_stop_on_max"):
        print(" -r  : 运行一键打捞计划")
        print(" -go : 一键打捞（跳过确认并直接运行当前目标）")
        print(" -m  : 返回打捞关卡选择")
        print(" -E  : 返回少女全自动 GFAM 主菜单")
    else:
        print(" 当前计划：%s" % smart_epa_plan_type_label())
        print(" -gun   : 选择人形一键打捞（普通/紧急）")
        print(" -equip : 选择装备一键打捞（夜战专属装备）")
        print(" -r     : 生成一键打捞计划并进入运行确认")
        print(" -E     : 返回少女全自动 GFAM 主菜单")

    if proxy_instance and worker_mode != 'r':
        print(" -s : 仅停止代理（调试/异常恢复用）")

    print("========================================\n")


def normalize_menu_input(cmd: str) -> str:
    raw = (cmd or "").strip()
    lower = raw.lower()

    alias_map = {
        "b": "-back",
        "back": "-back",

        "p": "普通",
        "普": "普通",
        "normal": "普通",

        "j": "紧急",
        "紧": "紧急",
        "urgent": "紧急",
        "em": "紧急",

        "y": "夜战",
        "夜": "夜战",
        "night": "夜战",

        "team": "-team",
        "t": "-team",
        "single": "-single",
        "s1": "-single",
        "9": "-smart",
        "-9": "-smart",
        "smart": "-smart",
        "coach": "-smart",
        "一键打捞": "-smart",
        "教练": "-smart",
        "妙妙小巧思": "-smart",
        "教练の妙妙小巧思": "-smart",

        "full": "-full",
        "f": "-full",
        "equal": "-equal",
        "e": "-equal",

        "protecton": "-protecton",
        "on": "-protecton",
        "po": "-protecton",

        "protectoff": "-protectoff",
        "off": "-protectoff",
        "pf": "-protectoff",

        "stopmax": "-stopmax",
        "sm": "-stopmax",
        "stop": "-stopmax",

        "keepmax": "-keepmax",
        "km": "-keepmax",
        "keep": "-keepmax",

        "stopdrop": "-stopdrop",
        "sd": "-stopdrop",
        "keepdrop": "-keepdrop",
        "kd": "-keepdrop",

        "lockequip": "-lockequip",
        "lockon": "-lockequip",
        "le": "-lockequip",
        "keepequipunlocked": "-keepequipunlocked",
        "unlockequip": "-keepequipunlocked",
        "lockoff": "-keepequipunlocked",
    }

    if lower in alias_map:
        return alias_map[lower]

    # A1 / a1 -> A-1
    if re.fullmatch(r"[aA]\d{1,2}", raw):
        return "A-" + raw[1:]

    # 1 / 2 / 3 / 4 / 5 -> -1 / -2 / ...
    if re.fullmatch(r"\d+", raw):
        return "-" + raw

    return raw


def print_difficulty_menu():
    print("\n=========== 打捞关卡菜单 ===========")
    print("请选择你要打捞的关卡难度：")
    print("  普通   （别名：普 / p）")
    print("  紧急   （别名：紧 / j）")
    print("  夜战   （别名：夜 / y）")
    print("------------------------------------")
    print("提示：输入名称或别名并回车，例如：普通 / p / 夜")
    print("====================================\n")


def print_stage_menu(difficulty: str):
    if difficulty == "普通":
        options = NORMAL_STAGE_OPTIONS
    elif difficulty == "紧急":
        options = EMERGENCY_STAGE_OPTIONS
    else:
        options = NIGHT_STAGE_OPTIONS

    print("\n=========== %s 关卡列表 ===========" % difficulty)
    print("请选择关卡：")
    print("  " + "  ".join(options))
    print("------------------------------------")
    print("提示：输入选项名称并回车，例如：A-10")
    print("提示：也可输入别名，例如：a10 / A10")
    print("提示：输入 -back 或 b 返回难度选择菜单")
    print("====================================\n")


def print_placeholder_menu(difficulty: str, stage: str):
    print("\n[!] %s %s 菜单暂未实现，当前先占位。" % (difficulty, stage))
    if difficulty == "夜战":
        print("[!] 夜战已接入装备掉落统计逻辑，但当前尚未写入该关的 MISSION_ID / START_SPOT / ROUTE / 目标装备。")
    else:
        print("[!] 你可以重新选择其他关卡，或等待后续继续补全。")


def print_target_menu(difficulty: str, stage: str):
    options = get_stage_options(difficulty, stage)
    print("\n=========== %s %s ===========" % (difficulty, stage))
    print("请选择你要打捞的目标：")
    if difficulty == "夜战":
        print("（夜战目标为装备）")
        print("（说明：夜战已接入装备掉落统计与自动装备拆解）")
    for key, item in options.items():
        print("  %s : %s" % (key, item["label"]))
    print("---------------------------------")
    print("提示：输入对应编号并回车，例如：-1")
    print("提示：也可直接输入数字，例如：1")
    print("提示：选定目标后可输入 -go，使用默认设置直接开始一键打捞")
    print("提示：输入 -back 或 b 返回上一级菜单")
    print("=================================\n")


def print_ready_to_run_hint():
    print("[*] 选择已完成，请确认后开始运行。")
    print("[*] 快捷：输入 -go 可使用当前/默认设置直接开始一键打捞。")



def print_filter_protection_menu():
    print("\n=========== 过滤保护 ===========")
    print("  -protecton  : 开启（默认）")
    print("  -protectoff : 关闭")
    print("--------------------------------")
    print("提示：练级模式下关闭后，可减少目标掉落占仓导致的中断。")
    print("快捷：输入 -go 可跳过后续设置，按当前/默认配置直接运行")
    print("================================")


def print_run_confirm_menu():
    print("\n=========== 运行前确认 ===========")
    print("关卡：%s %s -> %s" % (
        CONFIG["SELECTED_DIFFICULTY"],
        CONFIG["SELECTED_STAGE"],
        CONFIG["SELECTED_TARGET_LABEL"],
    ))
    print("模式：%s" % ("打捞单人模式" if CONFIG.get("SINGLE_GUN_MODE") else "练级五人模式"))
    if CONFIG.get("MODE_NAME") == "team":
        schedule_label = "整队满级后切换" if CONFIG.get("TRAIN_SCHEDULE_MODE") == "full" else "均等练级轮转"
        print("调度：%s" % schedule_label)
    print("满级停机：%s" % ("开启" if CONFIG.get("STOP_ON_MAX_LEVEL") else "关闭"))
    if CONFIG.get("MODE_NAME") == "single":
        target_word = "目标装备" if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "目标人形"
        print("%s达成停机：%s" % (target_word, "开启" if CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED") else "关闭"))
    if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
        print("目标装备自动上锁：%s" % ("开启" if CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True) else "关闭"))
    print("----------------------------------")
    print("输入 -y 确认，输入 -go 一键打捞，输入 -back 返回")
    print("==================================\n")


def print_stop_on_max_menu():
    print("\n=========== 满级停机设置 ===========")
    print("请选择当检测到人形 EXP 为 0（满级）后的行为：")
    print("  -stopmax : 停止程序")
    print("  -keepmax : 不停止程序（默认）")
    print("------------------------------------")
    print("提示：输入 -stopmax / -keepmax，回车默认 -keepmax")
    print("快捷：输入 -go 可跳过后续设置，按当前/默认配置直接运行")
    print("====================================\n")



def print_target_drop_stop_menu():
    target_word = "目标装备" if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "目标人形"
    print("\n=========== 目标达成停机 ===========")
    print("请选择%s至少各掉落 1 个后的行为：" % target_word)
    print("  -stopdrop : 停止打捞")
    print("  -keepdrop : 继续打捞（默认）")
    print("------------------------------------")
    print("说明：仅对打捞单人模式生效；夜战按目标装备统计，普通/紧急按目标人形统计。")
    print("提示：输入 -stopdrop / -keepdrop，回车默认 -keepdrop")
    print("快捷：输入 -go 可跳过后续设置，按当前/默认配置直接运行")
    print("====================================\n")


def print_equip_auto_lock_menu():
    print("\n=========== 目标装备自动上锁 ===========")
    print("请选择夜战目标装备掉落后的处理方式：")
    print("  -lockequip          : 自动上锁（默认，推荐）")
    print("  -keepequipunlocked  : 不自动上锁，仅依赖拆解过滤保护")
    print("----------------------------------------")
    print("说明：自动上锁只会尝试给当前目标装备上锁；无论接口是否成功，都会先加入本轮 UID 保护，避免被自动拆解。")
    print("提示：输入 -lockequip / -keepequipunlocked，回车默认 -lockequip")
    print("快捷：输入 -go 可跳过后续设置，按当前/默认配置直接运行")
    print("========================================\n")


def get_selected_protected_gun_ids():
    if not CONFIG.get("ENABLE_FILTER_PROTECTION", True):
        return set()

    protected_ids = set(CONFIG.get("PROTECTED_DROP_GUN_IDS", []))
    if CONFIG.get("SMART_EPA_PLAN_MODE") or CONFIG.get("MODE_NAME") == "smart_epa":
        for item in CONFIG.get("SMART_EPA_PLAN", []) or []:
            for gid in item.get("target_gun_ids", []) or []:
                try: protected_ids.add(int(gid))
                except Exception: pass
        return protected_ids

    label = CONFIG.get("SELECTED_TARGET_LABEL")
    if label:
        for name in split_target_label(label):
            gun_id = resolve_gun_id_by_name(name)
            if gun_id is not None:
                protected_ids.add(gun_id)
    return protected_ids


def get_selected_target_equip_ids():
    protected_ids = set()
    if not CONFIG.get("ENABLE_FILTER_PROTECTION", True):
        return protected_ids

    for value in CONFIG.get("PROTECTED_DROP_EQUIP_IDS", []):
        try:
            value = int(value)
            if value > 0:
                protected_ids.add(value)
        except Exception:
            pass

    label = CONFIG.get("SELECTED_TARGET_LABEL")
    if label:
        for name in split_target_label(label):
            equip_id = resolve_equip_id_by_name(name)
            if equip_id is not None:
                protected_ids.add(int(equip_id))

    # 正确拆解过滤：除当前目标外，全部已确认的 EPA 夜战专属装备也一律保护。
    # 这样即使 Index/index 或掉落包没有星级字段，也不会把专属装备当作低星装备误拆。
    protected_ids.update(gfam_get_all_known_epa_night_equip_ids())
    protected_ids.update(RUNTIME_PROTECTED_EQUIP_IDS)
    return protected_ids


def gfam_is_protected_equip_for_retire(uid, equip_id):
    try:
        uid = int(uid)
    except Exception:
        uid = 0
    try:
        equip_id = int(equip_id)
    except Exception:
        equip_id = 0
    protected_equip_ids = get_selected_target_equip_ids()
    if uid > 0 and uid in RUNTIME_PROTECTED_EQUIP_UIDS:
        return True
    if equip_id > 0 and equip_id in protected_equip_ids:
        return True
    return False


def gfam_should_auto_retire_equip_by_rules(uid, equip_id, rank=0, raw=None, source=""):
    """装备自动拆解的统一 AND 规则：低星、未上锁、未装备、非目标/非专属、非运行期保护。"""
    try:
        uid = int(uid)
    except Exception:
        uid = 0
    try:
        equip_id = int(equip_id)
    except Exception:
        equip_id = 0
    if uid <= 0:
        return False, "UID无效"
    if gfam_is_protected_equip_for_retire(uid, equip_id):
        return False, "受保护目标/专属装备"

    strict = bool(CONFIG.get("EQUIP_AUTO_RETIRE_STRICT_AND", True))
    raw_is_dict = isinstance(raw, dict)
    if raw_is_dict:
        lock_keys = ("if_locked", "is_locked", "locked", "lock", "is_lock")
        equip_state_keys = ("gun_with_user_id", "gun_id", "team_id", "squad_id", "slot", "position", "location", "equip_position", "equip_slot")
        if strict and not any(k in raw for k in lock_keys):
            return False, "缺少锁定字段，无法确认未上锁"
        if strict and not any(k in raw for k in equip_state_keys):
            return False, "缺少装备状态字段，无法确认未装备"
        if gfam_is_equip_locked_for_emergency(raw):
            return False, "已上锁"
        if gfam_is_equip_equipped_for_emergency(raw):
            return False, "已装备"
        if not rank:
            rank = gfam_extract_equip_rank(raw) or gfam_get_equip_rank_for_emergency(raw)
    elif strict:
        return False, "缺少原始字段，无法确认未上锁/未装备"

    try:
        rank = int(rank or 0)
    except Exception:
        rank = 0
    max_rank = _gfam_storage_int(CONFIG.get("EQUIP_AUTO_RETIRE_MAX_RANK", 4), 4)
    if rank <= 0 and not CONFIG.get("EQUIP_AUTO_RETIRE_ALLOW_UNKNOWN_RANK", False):
        return False, "星级未知，严格模式不拆"
    if rank > max_rank:
        return False, "高星装备"
    if rank <= 0:
        return True, "星级未知但未命中专属保护，满足自动拆解规则"
    return True, "满足自动拆解规则"


def gfam_lock_response_ok(resp):
    """判断上锁接口是否明确成功。装备上锁曾经被错误地把“无 error 的返回”当成功，
    但实际上部分错误端点/错误 payload 也可能返回空 dict，导致游戏内没有真正上锁。
    这里尽量只接受明确成功字段；最终仍可通过 Index/index 稀有校验确认。
    """
    if not isinstance(resp, dict):
        return False
    if resp.get("error") or resp.get("error_local"):
        return False
    for key in ("success", "ok", "result"):
        if key in resp:
            val = str(resp.get(key)).strip().lower()
            if val in ("1", "true", "ok", "success", "done"):
                return True
    # 少前部分接口成功时可能只返回空 dict；不直接认定成功，但允许后续 Index 校验确认。
    return not resp


def gfam_find_equip_in_index_payload(payload, equip_uid):
    try:
        equip_uid = int(equip_uid)
    except Exception:
        return None
    info = payload.get("equip_with_user_info") if isinstance(payload, dict) else None
    if isinstance(info, dict):
        item = info.get(str(equip_uid)) or info.get(equip_uid)
        if isinstance(item, dict):
            return item
        for v in info.values():
            if isinstance(v, dict):
                try:
                    if int(v.get("id", 0) or 0) == equip_uid:
                        return v
                except Exception:
                    pass
    elif isinstance(info, list):
        for v in info:
            if isinstance(v, dict):
                try:
                    if int(v.get("id", 0) or 0) == equip_uid:
                        return v
                except Exception:
                    pass
    return None


def gfam_verify_equip_locked_by_index(client, equip_uid):
    """目标专属装备掉落很少，自动上锁又是安全关键动作。
    因此只在触发自动上锁后请求一次 Index/index 进行校验，平时不增加 Index 频率。
    """
    if client is None:
        return None
    try:
        payload = {"time": int(time.time()), "furniture_data": False}
        idx = client.send_request(API_INDEX_INDEX, payload)
        if not isinstance(idx, dict) or idx.get("error") or idx.get("error_local"):
            return None
        update_fairy_cache_from_index_payload(idx, source="装备上锁校验 Index/index")
        item = gfam_find_equip_in_index_payload(idx, equip_uid)
        if not isinstance(item, dict):
            return None
        return gfam_is_equip_locked_for_emergency(item)
    except Exception:
        return None


def gfam_mark_equip_locked_locally(equip_uid):
    try:
        equip_uid = int(equip_uid)
    except Exception:
        return
    raw = DROPPED_UID_TO_EQUIP_RAW.get(equip_uid)
    if isinstance(raw, dict):
        raw["is_locked"] = "1"
        raw["if_locked"] = "1"
        raw["locked"] = "1"


def gfam_try_lock_equip(client, equip_uid):
    try:
        equip_uid = int(equip_uid)
    except Exception:
        equip_uid = 0
    if equip_uid <= 0 or client is None:
        return False

    # 无论接口是否成功，都先加入本轮保护，避免目标装备被当前脚本自动拆解。
    RUNTIME_PROTECTED_EQUIP_UIDS.add(equip_uid)

    # 已按用户抓到的真实 C2S 包固定：Equip/changeLock
    # payload: {"lock": [equip_uid], "unlock": []}
    # 不再尝试多种端点/字段，避免误调用导致异常或误判。
    payload = {"lock": [equip_uid], "unlock": []}
    try:
        resp = client.send_request(API_EQUIP_LOCK, payload)
    except Exception as exc:
        print("[装备上锁] 自动上锁请求异常，已加入本轮保护但游戏内可能仍未上锁：UID=%s | error=%s" % (equip_uid, str(exc)))
        return False

    if isinstance(resp, dict) and (resp.get("error") or resp.get("error_local")):
        print("[装备上锁] 自动上锁失败，已加入本轮保护但游戏内可能仍未上锁：UID=%s | 返回=%s" % (equip_uid, resp))
        return False

    gfam_mark_equip_locked_locally(equip_uid)
    print("[装备上锁] 已发送 Equip/changeLock 自动上锁请求：UID=%s" % equip_uid)
    return True

def gfam_auto_lock_target_equip_if_needed(client, equip_id, equip_uid, source="", spot_id=None):
    if not CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True):
        return False
    if CONFIG.get("SELECTED_DIFFICULTY") != "夜战":
        return False
    try:
        equip_id = int(equip_id)
        equip_uid = int(equip_uid)
    except Exception:
        return False
    if equip_id <= 0 or equip_uid <= 0:
        return False
    if equip_id not in get_selected_target_equip_ids():
        return False
    if equip_uid in RUNTIME_LOCKED_TARGET_EQUIP_UIDS:
        return True
    print("[装备上锁] 检测到目标装备掉落，准备自动上锁：equip_id=%s | UID=%s | 来源=%s" % (equip_id, equip_uid, source or "unknown"))
    ok = gfam_try_lock_equip(client, equip_uid)
    RUNTIME_LOCKED_TARGET_EQUIP_UIDS.add(equip_uid)
    return ok


def is_no_space_retire_failure(resp) -> bool:
    text_blob = str(resp).lower()
    keywords = [
        "full", "space", "capacity", "inventory",
        "仓库", "满", "空间", "容量", "上限", "空位"
    ]
    return any(k in text_blob for k in keywords)


def reset_run_stats():
    RUN_STATS["start_time"] = None
    RUN_STATS["end_time"] = None
    RUN_STATS["target_counts"] = {}
    RUN_STATS["target_type"] = "gun"
    RUN_STATS["current_macro"] = 0
    RUN_STATS["current_micro"] = 0
    RUN_STATS["current_step"] = 0
    RUN_STATS["current_team_no"] = 1
    RUN_STATS["macro_drop_names"] = []
    RUN_STATS["last_micro_exp_lines"] = []
    RUN_STATS["panel_enabled"] = True
    RUN_STATS["recent_logs"] = []
    RUN_STATS["drop_marquee_offset"] = 0
    RUN_STATS["drop_marquee_last_key"] = ""
    RUN_STATS["panel_last_refresh_at"] = 0.0
    RUNTIME_LOCKED_TARGET_EQUIP_UIDS.clear()


def get_selected_target_pairs():
    label = CONFIG.get("SELECTED_TARGET_LABEL", "")
    pairs = []
    if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
        for name in split_target_label(label):
            # 夜战专属装备 ID 仍在校对中：没有确认 ID 的目标也要显示统计项，
            # 但 item_id=None 不会参与自动计数/自动保护，避免误把普通装备计为目标。
            equip_id = resolve_equip_id_by_name(name)
            pairs.append((name, equip_id))
        return pairs

    for name in split_target_label(label):
        gun_id = resolve_gun_id_by_name(name)
        if gun_id is not None:
            pairs.append((name, gun_id))
    return pairs


def init_run_target_counts():
    RUN_STATS["target_counts"] = {}
    RUN_STATS["target_type"] = "equip" if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "gun"
    for name, item_id in get_selected_target_pairs():
        RUN_STATS["target_counts"][name] = {"item_id": item_id, "count": 0}


def record_target_drop(item_id, drop_type="gun"):
    try:
        item_id = int(item_id)
    except Exception:
        return

    if RUN_STATS.get("target_type") != drop_type:
        return

    for name, item in RUN_STATS["target_counts"].items():
        if item["item_id"] == item_id:
            item["count"] += 1




def has_each_target_dropped_once():
    if not RUN_STATS.get("target_counts"):
        return False
    return all(int(item.get("count", 0)) >= 1 for item in RUN_STATS["target_counts"].values())


def get_target_drop_progress_text():
    if not RUN_STATS.get("target_counts"):
        return "未配置"
    parts = []
    for name, item in RUN_STATS["target_counts"].items():
        parts.append("%s×%d" % (name, int(item.get("count", 0))))
    return "，".join(parts)


def should_stop_after_each_target_dropped():
    if not CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED", False):
        return False
    if CONFIG.get("MODE_NAME") != "single":
        return False
    if RUN_STATS.get("target_type") not in ("gun", "equip"):
        return False
    return has_each_target_dropped_once()


def get_target_type_label():
    return "目标装备" if RUN_STATS.get("target_type") == "equip" or CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "目标人形"


def get_terminal_width(default=120):
    try:
        import shutil
        return max(60, shutil.get_terminal_size(fallback=(default, 30)).columns)
    except Exception:
        return default


def strip_ansi(text):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", str(text))


def trim_ansi_line(text, max_width):
    s = str(text)
    if len(strip_ansi(s)) <= max_width:
        return s
    plain = strip_ansi(s)
    keep = max(10, max_width - 3)
    return plain[:keep] + "..."


def build_drop_marquee_segment(items, visible_width):
    if not items:
        return "无"

    parts = [format_drop_name_for_display(x) for x in items]
    plain_parts = [strip_ansi(x) for x in parts]
    joined_plain = "   ".join(plain_parts)
    if len(joined_plain) <= visible_width:
        return "   ".join(parts)

    key = "|".join(plain_parts)
    if RUN_STATS.get("drop_marquee_last_key") != key:
        RUN_STATS["drop_marquee_last_key"] = key
        RUN_STATS["drop_marquee_offset"] = 0

    count = len(parts)
    offset = RUN_STATS.get("drop_marquee_offset", 0) % max(1, count)
    RUN_STATS["drop_marquee_offset"] = (offset + 1) % max(1, count)

    ordered = parts[offset:] + parts[:offset]
    rendered = []
    used = 0
    for idx, part in enumerate(ordered):
        plain = strip_ansi(part)
        sep = "   " if idx > 0 else ""
        extra = len(sep) + len(plain)
        if rendered and used + extra > visible_width:
            break
        if not rendered and len(plain) > visible_width:
            return trim_ansi_line(part, visible_width)
        if sep:
            rendered.append(sep)
            used += len(sep)
        rendered.append(part)
        used += len(plain)

    if not rendered:
        return trim_ansi_line(ordered[0], visible_width)
    return "".join(rendered)



GUN_EXP_1_TO_100 = {
    1:100,2:200,3:300,4:400,5:500,6:600,7:700,8:800,9:900,10:1000,
    11:1100,12:1200,13:1300,14:1400,15:1500,16:1600,17:1700,18:1800,19:1900,20:2000,
    21:2100,22:2200,23:2300,24:2400,25:2500,26:2600,27:2800,28:3100,29:3400,30:4200,
    31:4600,32:5000,33:5400,34:5800,35:6300,36:6700,37:7200,38:7700,39:8200,40:8800,
    41:9300,42:9900,43:10500,44:11100,45:11800,46:12500,47:13100,48:13900,49:14600,50:15400,
    51:16100,52:16900,53:17800,54:18600,55:19500,56:20400,57:21300,58:22300,59:23300,60:24300,
    61:25300,62:26300,63:27400,64:28500,65:29600,66:30800,67:32000,68:33200,69:34400,70:45100,
    71:46800,72:48600,73:50400,74:52200,75:54000,76:55900,77:57900,78:59800,79:61800,80:63900,
    81:66000,82:68100,83:70300,84:72600,85:74800,86:77100,87:79500,88:81900,89:84300,90:112600,
    91:116100,92:119500,93:123100,94:126700,95:130400,96:134100,97:137900,98:141800,99:145700,
}
GUN_EXP_100_TO_120 = {
    100:100000,101:120000,102:140000,103:160000,104:180000,
    105:200000,106:220000,107:240000,108:280000,109:360000,
    110:480000,111:640000,112:900000,113:1200000,114:1600000,
    115:2200000,116:3000000,117:4000000,118:5000000,119:6000000,
}
FAIRY_EXP_1_TO_100 = {
    1:300,2:600,3:900,4:1200,5:1500,6:1800,7:2100,8:2400,9:2700,10:3000,
    11:3300,12:3600,13:3900,14:4200,15:4500,16:4800,17:5100,18:5500,19:6000,20:6500,
    21:7100,22:8000,23:9000,24:10000,25:11000,26:12200,27:13400,28:14700,29:16000,30:17500,
    31:18900,32:20500,33:22200,34:23900,35:25700,36:27600,37:29500,38:31600,39:33700,40:35900,
    41:38200,42:40500,43:43000,44:45500,45:48200,46:50900,47:53700,48:56600,49:59600,50:62700,
    51:65900,52:69200,53:72600,54:76000,55:79600,56:83300,57:87000,58:90900,59:94900,60:99000,
    61:103100,62:107400,63:111800,64:116300,65:120900,66:125600,67:130400,68:135300,69:140400,70:145500,
    71:150800,72:156100,73:161600,74:167200,75:172900,76:178700,77:184700,78:190700,79:196900,80:203200,
    81:209600,82:216100,83:222800,84:229600,85:236500,86:243500,87:250600,88:257900,89:265300,90:272800,
    91:280400,92:288200,93:296100,94:304100,95:312300,96:320600,97:329000,98:337500,99:357000,
}

def sum_exp_range(table, start_level, end_level_exclusive):
    total = 0
    for lv in range(start_level, end_level_exclusive):
        total += int(table.get(lv, 0))
    return total

def gun_total_exp_for_level(level, intra_exp=0):
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        intra_exp = int(intra_exp)
    except Exception:
        intra_exp = 0
    total = 0
    upper = min(level, 100)
    total += sum_exp_range(GUN_EXP_1_TO_100, 1, upper)
    if level > 100:
        total += sum_exp_range(GUN_EXP_100_TO_120, 100, min(level, 120))
    return total + max(0, intra_exp)

def gun_next_level_required_exp(level):
    try:
        level = int(level)
    except Exception:
        return 0
    if 1 <= level < 100:
        return int(GUN_EXP_1_TO_100.get(level, 0) or 0)
    if 100 <= level < 120:
        return int(GUN_EXP_100_TO_120.get(level, 0) or 0)
    return 0


def gun_base_total_exp_from_index(level, raw_exp):
    """
    Index/index 里的 gun_exp 在实际返回中更接近“累计总经验”，
    而不是“当前等级内经验”。如果继续把它当作等级内经验相加，
    99 级人形会被错误算到 100%。
    这里做兼容：
    - raw_exp 大于当前等级升下一级所需经验时，按累计总经验处理；
    - 否则按当前等级内经验处理。
    """
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        raw_exp = int(raw_exp)
    except Exception:
        raw_exp = 0

    next_need = gun_next_level_required_exp(level)
    total_1_to_100 = sum_exp_range(GUN_EXP_1_TO_100, 1, 100)
    if raw_exp > next_need or raw_exp >= total_1_to_100:
        return max(0, raw_exp)

    return gun_total_exp_for_level(level, raw_exp)


def fairy_total_exp_for_level(level, intra_exp=0):
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        intra_exp = int(intra_exp)
    except Exception:
        intra_exp = 0
    total = sum_exp_range(FAIRY_EXP_1_TO_100, 1, min(level, 100))
    return total + max(0, intra_exp)

def fairy_next_level_required_exp(level):
    try:
        level = int(level)
    except Exception:
        return 0
    if 1 <= level < 100:
        return int(FAIRY_EXP_1_TO_100.get(level, 0) or 0)
    return 0


def fairy_base_total_exp_from_index(level, raw_exp):
    """
    Index/index 里的 fairy_exp 可能是“累计总经验”，也可能是“当前等级内经验”。
    妖精等级已知时，累计总经验必须落在：
        当前等级累计下限 <= fairy_exp < 下一等级累计下限
    如果 raw_exp 超出该等级可能范围，不直接拿来当累计值，避免 92 级妖精被算成 100%。
    """
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        raw_exp = int(raw_exp)
    except Exception:
        raw_exp = 0

    total_1_to_100 = sum_exp_range(FAIRY_EXP_1_TO_100, 1, 100)
    level = max(1, min(level, 100))
    level_floor = sum_exp_range(FAIRY_EXP_1_TO_100, 1, level)

    if level >= 100:
        return total_1_to_100

    next_need = fairy_next_level_required_exp(level)
    next_floor = min(total_1_to_100, level_floor + next_need)

    # 形态一：fairy_exp 是累计总经验。
    if level_floor <= raw_exp < next_floor:
        return raw_exp

    # 形态二：fairy_exp 是当前等级内经验。
    if 0 <= raw_exp <= next_need:
        return level_floor + raw_exp

    # 超出当前等级可能范围时，保守使用当前等级下限，避免异常满进度。
    return level_floor


def infer_gun_target_level(gun):
    # Best-effort: if current level already passed a mind-update cap, preserve that cap family.
    level = int(gun.get("level", gun.get("gun_level", 1)) or 1)
    explicit = gun.get("target_level") or gun.get("max_level")
    if explicit:
        try:
            explicit = int(explicit)
            if explicit in (100,110,115,120):
                return explicit
        except Exception:
            pass
    if level > 115:
        return 120
    if level > 110:
        return 115
    if level > 100:
        return 110
    return 100

def infer_fairy_target_level(fairy):
    return 100

def init_team_progress_runtime_fields(team_cfg):
    for gun in team_cfg.get("guns", []):
        level = int(gun.get("level", gun.get("gun_level", 1)) or 1)
        exp = int(gun.get("exp", gun.get("gun_exp", 0)) or 0)
        target_level = infer_gun_target_level(gun)
        gun["level"] = level
        gun["exp"] = exp
        gun["target_level"] = target_level
        gun["base_total_exp"] = gun_base_total_exp_from_index(level, exp)
        gun["runtime_gained_exp"] = int(gun.get("runtime_gained_exp", 0) or 0)
        gun["target_total_exp"] = gun_total_exp_for_level(target_level, 0)
    fairy = team_cfg.get("fairy")
    if isinstance(fairy, dict):
        level = int(fairy.get("level", fairy.get("fairy_lv", 1)) or 1)
        exp = int(fairy.get("exp", fairy.get("fairy_exp", 0)) or 0)
        fairy["level"] = level
        fairy["exp"] = exp
        fairy["target_level"] = infer_fairy_target_level(fairy)
        fairy["base_total_exp"] = fairy_base_total_exp_from_index(level, exp)
        fairy["runtime_gained_exp"] = int(fairy.get("runtime_gained_exp", 0) or 0)
        fairy["target_total_exp"] = fairy_total_exp_for_level(fairy["target_level"], 0)
        fairy["last_total_exp_seen"] = int(fairy.get("last_total_exp_seen", fairy["base_total_exp"]) or fairy["base_total_exp"])
    team_cfg.setdefault("runtime_seconds", 0.0)
    team_cfg.setdefault("completed", False)
    team_cfg.setdefault("maxed_member_uids", set())
    team_cfg.setdefault("warned_max_member_uids", set())

def initialize_all_team_progress():
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        init_team_progress_runtime_fields(team_cfg)
    if not CAPTURED_TEAM_CONFIGS:
        init_team_progress_runtime_fields({"guns": CONFIG.get("GUNS", []), "fairy": CONFIG.get("FAIRY")})

def pause_current_team_runtime():
    team_id = TEAM_PROGRESS_STATE.get("current_active_team_id")
    started_at = TEAM_PROGRESS_STATE.get("current_active_started_at")
    if not team_id or not started_at:
        return
    cfg = get_team_config_by_team_id(team_id)
    if cfg is not None:
        cfg["runtime_seconds"] = float(cfg.get("runtime_seconds", 0.0)) + max(0.0, time.time() - started_at)
    TEAM_PROGRESS_STATE["current_active_started_at"] = None
    TEAM_PROGRESS_STATE["current_active_team_id"] = None

def activate_team_runtime(team_id):
    pause_current_team_runtime()
    TEAM_PROGRESS_STATE["current_active_team_id"] = team_id
    TEAM_PROGRESS_STATE["current_active_started_at"] = time.time()

def get_team_config_by_team_id(team_id):
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        if int(team_cfg.get("team_id", 0)) == int(team_id):
            return team_cfg
    if int(CONFIG.get("TEAM_ID", 0) or 0) == int(team_id):
        return {"team_id": CONFIG.get("TEAM_ID"), "guns": CONFIG.get("GUNS", []), "fairy": CONFIG.get("FAIRY")}
    return None

def get_team_runtime_seconds(team_cfg):
    total = float(team_cfg.get("runtime_seconds", 0.0))
    if TEAM_PROGRESS_STATE.get("current_active_team_id") == int(team_cfg.get("team_id", 0) or 0):
        started = TEAM_PROGRESS_STATE.get("current_active_started_at")
        if started:
            total += max(0.0, time.time() - started)
    return total

def get_team_member_progress(team_cfg):
    guns = team_cfg.get("guns", [])
    maxed_uids = set(str(x) for x in team_cfg.get("maxed_member_uids", set()))

    current_total = 0
    base_total = 0
    target_total = 0

    for g in guns:
        target = int(g.get("target_total_exp", 0))
        base = int(g.get("base_total_exp", 0))
        gained = int(g.get("runtime_gained_exp", 0))
        uid = str(g.get("id", ""))

        base_total += base
        target_total += target

        cur = min(target, base + gained)

        # 服务器返回 EXP=0 才是当前流程里最可靠的“该人形已满级”信号。
        # 如果累计经验已经达到表格上限，但该 UID 仍然在获得 EXP，
        # 说明表格进度已到理论上限，但实际还不能视为满级。
        # 因此未收到 EXP=0 的成员最多显示到 target-1，避免整队提前显示 100%。
        if uid not in maxed_uids and target > 0 and cur >= target:
            cur = target - 1

        current_total += max(0, cur)

    gained_total = max(0, current_total - base_total)
    percent = (current_total / target_total * 100.0) if target_total > 0 else 0.0
    return current_total, target_total, gained_total, percent

def get_team_fairy_progress(team_cfg):
    fairy = team_cfg.get("fairy")
    if not isinstance(fairy, dict):
        return 0, 0, 0.0
    current_total = min(int(fairy.get("target_total_exp",0)), int(fairy.get("base_total_exp",0)) + int(fairy.get("runtime_gained_exp",0)))
    target_total = int(fairy.get("target_total_exp",0))
    percent = (current_total / target_total * 100.0) if target_total > 0 else 0.0
    return current_total, target_total, percent

def estimate_team_eta_seconds(team_cfg):
    current_total, target_total, gained_total, _ = get_team_member_progress(team_cfg)
    runtime_seconds = get_team_runtime_seconds(team_cfg)
    remaining = max(0, target_total - current_total)
    if gained_total <= 0 or runtime_seconds <= 1:
        return None
    exp_per_sec = gained_total / runtime_seconds
    if exp_per_sec <= 0:
        return None
    return remaining / exp_per_sec

def format_percent(value):
    return "%.2f%%" % float(value)

def format_clock_time(ts):
    if ts is None:
        return "-"
    try:
        return time.strftime("%H:%M:%S", time.localtime(ts))
    except Exception:
        return "-"

def format_duration(seconds):
    seconds = int(max(0, seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}小时{m}分{s}秒"
    if m > 0:
        return f"{m}分{s}秒"
    return f"{s}秒"

def enable_console_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass



ANSI = {
    "reset": "\033[0m",
    "panel_border": "\033[96m",
    "panel_label": "\033[97m",
    "target": "\033[93m",
    "success": "\033[92m",
    "warn": "\033[91m",
    "dim": "\033[90m",
}

GUN_ID_NAME_CACHE = None

def colorize(text, color_key=None):
    s = str(text)
    if not color_key or color_key not in ANSI:
        return s
    return ANSI[color_key] + s + ANSI["reset"]


def get_gun_id_name_map():
    global GUN_ID_NAME_CACHE
    if GUN_ID_NAME_CACHE is not None:
        return GUN_ID_NAME_CACHE

    mapping = {}
    catalog = load_gun_catalog()
    if not catalog:
        GUN_ID_NAME_CACHE = mapping
        return mapping

    for gun in catalog:
        try:
            gid = int(gun.get("id"))
        except Exception:
            continue
        name = gun.get("en_name") or gun.get("code") or gun.get("name") or str(gid)
        if isinstance(name, str) and name.startswith("gun-"):
            name = gun.get("code") or gun.get("en_name") or name
        mapping[gid] = str(name)
    GUN_ID_NAME_CACHE = mapping
    return mapping


def resolve_gun_name_by_id(gun_id):
    try:
        gun_id = int(gun_id)
    except Exception:
        return str(gun_id)
    return get_gun_id_name_map().get(gun_id, str(gun_id))


def get_target_name_set():
    return set(split_target_label(CONFIG.get("SELECTED_TARGET_LABEL", "")))


def is_target_gun_name(name: str) -> bool:
    if not name:
        return False

    # 不使用子串匹配，避免 G3 被 SSG3000 误判为目标。
    # 优先按 gun_id 判断，其次按名称/别名精确匹配。
    try:
        drop_id = resolve_gun_id_by_name(name)
    except Exception:
        drop_id = None

    target_ids = set()
    for item in RUN_STATS.get("target_counts", {}).values():
        try:
            target_ids.add(int(item.get("item_id")))
        except Exception:
            pass

    if drop_id is not None and int(drop_id) in target_ids:
        return True

    n = normalize_gun_name(name)
    for target in get_target_name_set():
        if n == normalize_gun_name(target):
            return True
        alias = GUN_NAME_ALIAS.get(target)
        if alias and n == normalize_gun_name(alias):
            return True

    return False


def format_drop_name_for_display(name: str):
    if is_target_gun_name(name):
        return colorize(name, "target")
    return str(name)

def _safe_panel_text(value):
    try:
        return str(value)
    except Exception:
        return ""


def get_micro_limit_basis_text():
    if gfam_is_night_equip_farm_mode():
        info = CONFIG.get("EQUIP_STORAGE_MICRO_INFO") or {}
        if not info:
            return "装备仓库：等待运行前刷新"
        return "装备仓库 %s/%s，空位 %s，可安全轮数 %s；每轮按最多 %s 件装备仓库占用估算；不足一整轮时先拆解，不直接开跑" % (
            info.get("used", "?"),
            info.get("max_equip", "?"),
            info.get("free", "?"),
            info.get("auto_limit", CONFIG.get("MISSIONS_PER_RETIRE", "?")),
            info.get("battles_per_run", "?"),
        )
    info = CONFIG.get("STORAGE_MICRO_INFO") or {}
    if not info:
        return "人形仓库：等待运行前刷新"
    return "人形仓库 %s/%s，空位 %s，可安全轮数 %s；每轮按最多 %s 个人形仓库占用估算；不足一整轮时先拆解/停止" % (
        info.get("used", "?"),
        info.get("max_gun", "?"),
        info.get("free", "?"),
        info.get("usable_free", "?"),
        info.get("battles_per_run", "?"),
    )



def build_runtime_panel_lines():
    if not RUN_STATS.get("panel_enabled", True):
        return []

    term_width = get_terminal_width(120)
    inner_width = max(40, term_width - 2)

    mode_label = "练级五人模式" if CONFIG.get("MODE_NAME") == "team" else "打捞单人模式"
    stage_label = "%s %s -> %s" % (
        CONFIG.get("SELECTED_DIFFICULTY") or "-",
        CONFIG.get("SELECTED_STAGE") or "-",
        CONFIG.get("SELECTED_TARGET_LABEL") or "-",
    )
    server_label = CONFIG.get("SERVER_NAME", "SOP")
    elapsed = 0
    if RUN_STATS.get("start_time") is not None:
        elapsed = time.time() - RUN_STATS["start_time"]

    drop_text = "无"
    if RUN_STATS.get("macro_drop_names"):
        drop_text = build_drop_marquee_segment(RUN_STATS["macro_drop_names"], max(20, inner_width - 12))

    exp_text = "无"
    if RUN_STATS.get("last_micro_exp_lines"):
        exp_text = " | ".join(RUN_STATS["last_micro_exp_lines"])

    current_cfg = get_current_team_config()
    member_cur, member_target, member_gained, member_pct = get_team_member_progress(current_cfg)
    fairy_cur, fairy_target, fairy_pct = get_team_fairy_progress(current_cfg)
    team_runtime = get_team_runtime_seconds(current_cfg)
    eta_seconds = estimate_team_eta_seconds(current_cfg)
    eta_text = "-"
    eta_clock = "-"
    if eta_seconds is not None:
        eta_text = format_duration(eta_seconds)
        eta_clock = format_clock_time(time.time() + eta_seconds)

    if CONFIG.get("MODE_NAME") == "team":
        team_label = "%d / %d" % (CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0) + 1, max(1, len(CAPTURED_TEAM_CONFIGS)))
        macro_text = "当前 MACRO：%s / 直到全部梯队满级" % RUN_STATS.get("current_macro", 0)
    else:
        team_label = "1"
        macro_text = "当前 MACRO：%s / 直到手动停止或触发停止条件" % RUN_STATS.get("current_macro", 0)

    raw_lines = [
        colorize("============= EPA 运行状态 =============", "panel_border"),
        "%s%s    %s%s" % (colorize("服务器：", "panel_label"), server_label, colorize("模式：", "panel_label"), mode_label),
        "%s%s" % (colorize("关卡：", "panel_label"), stage_label),
        "%s%s" % (colorize("当前梯队：", "panel_label"), team_label),
        colorize(macro_text, "panel_label"),
        "%s%s / %s | %s%s / 5" % (
            colorize("当前 MICRO：", "panel_label"),
            RUN_STATS.get("current_micro", 0),
            CONFIG.get("MISSIONS_PER_RETIRE", 8),
            colorize("当前 Step：", "panel_label"),
            RUN_STATS.get("current_step", 0),
        ),
        "%s%s" % (colorize("Micro依据：", "panel_label"), get_micro_limit_basis_text()),
        "%s%s" % (colorize("本轮掉落：", "panel_label"), drop_text),
        "%s%s" % (colorize("目标统计：", "panel_label"), get_target_drop_progress_text()),
        "%s%s" % (colorize("最近一轮经验：", "panel_label"), exp_text),
        "%s%s (%s / %s)" % (colorize("人形进度：", "panel_label"), format_percent(member_pct), f"{member_cur:,}", f"{member_target:,}"),
        "%s%s (%s / %s)" % (colorize("妖精进度：", "panel_label"), format_percent(fairy_pct), f"{fairy_cur:,}", f"{fairy_target:,}"),
        "%s%s" % (colorize("本梯队已运行：", "panel_label"), format_duration(team_runtime)),
        "%s%s 后（%s）" % (colorize("预计完成：", "panel_label"), eta_text, eta_clock),
        "%s%s" % (colorize("总运行时间：", "panel_label"), format_duration(elapsed)),
        colorize("停止：-q 当前 Macro 后停 / -Q 当前 Micro 后停", "dim"),
        colorize("=" * min(inner_width, 37), "panel_border"),
    ]
    fairy_auto_line = fairy_runtime_status_line()
    if fairy_auto_line:
        raw_lines.insert(12, fairy_auto_line)
    lines = [trim_ansi_line(line, inner_width) for line in raw_lines]
    return lines


def clear_runtime_panel():
    try:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        try:
            os.system("cls" if os.name == "nt" else "clear")
        except Exception:
            pass


def refresh_runtime_panel(force=False):
    now = time.time()
    min_interval = float(RUN_STATS.get("panel_min_refresh_interval", 0.75) or 0.75)
    if not force and RUN_STATS.get("panel_last_refresh_at") and now - RUN_STATS.get("panel_last_refresh_at", 0.0) < min_interval:
        return
    RUN_STATS["panel_last_refresh_at"] = now
    lines = build_runtime_panel_lines()
    if not lines:
        return
    clear_runtime_panel()
    recent_logs = RUN_STATS.get("recent_logs", [])[-22:]
    if recent_logs:
        for line in recent_logs:
            print(line)
        print()
    for line in lines:
        print(line)


def panel_safe_print(*args, **kwargs):
    if not RUN_STATS.get("panel_enabled", True):
        print(*args, **kwargs)
        return

    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    msg = sep.join(str(a) for a in args)
    if end != "\n":
        msg = msg + end
    lines = msg.splitlines() or [msg]
    buf = RUN_STATS.setdefault("recent_logs", [])
    buf.extend(lines)
    max_logs = 10
    if len(buf) > max_logs:
        RUN_STATS["recent_logs"] = buf[-max_logs:]
    refresh_runtime_panel()


def print_run_summary():
    if RUN_STATS["start_time"] is None or RUN_STATS["end_time"] is None:
        return

    duration = RUN_STATS["end_time"] - RUN_STATS["start_time"]
    print("\n=========== 本次运行统计 ===========")
    print("运行总时长：%s" % format_duration(duration))
    title = "目标装备掉落" if RUN_STATS.get("target_type") == "equip" else "目标人形掉落"
    if RUN_STATS["target_counts"]:
        print("%s：" % title)
        for name, item in RUN_STATS["target_counts"].items():
            print("  %-12s %d" % (name + "：", item["count"]))
    else:
        print("%s：未配置" % title)
    print_fairy_summary(RUN_STATS.get("fairy_auto_start_snapshot"))
    print("================================\n")


SERVER_MENU_OPTIONS = {
    "-1": "SOP",
    "-2": "RO635",
    "-3": "M4A1",
    "-4": "M16",
    "-5": "AR-15",
}

SERVER_KEY_ALIASES = {
    "SOP": ["SOP"],
    "RO635": ["RO635"],
    "M4A1": ["M4A1"],
    "M16": ["M16"],
    "AR-15": ["AR-15", "AR15"],
}




def get_default_server_from_env():
    value = str(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP").strip().upper().replace("_", "-")
    if value in ("SOP", "RO635", "M4A1", "M16", "AR-15", "AR15"):
        return "AR-15" if value == "AR15" else value
    return "SOP"

def launched_from_gfam_main():
    return bool(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or os.environ.get("GFAM_SKIP_SERVER_MENU"))

def print_server_menu():
    print("\n=========== 服务器选择 ===========")
    print("请选择服务器：")
    print("  -1 : SOP")
    print("  -2 : RO635")
    print("  -3 : M4A1")
    print("  -4 : M16")
    print("  -5 : AR-15")
    print("----------------------------------")
    print("提示：可输入编号或服务器名，直接回车默认 %s" % get_default_server_from_env())
    print("==================================\n")


def normalize_server_input(cmd: str):
    cmd = str(cmd or "").strip()
    if not cmd:
        return get_default_server_from_env()
    cmd_norm = cmd.upper().replace("_", "-")
    if cmd_norm in ("1", "-1", "SOP"):
        return "SOP"
    if cmd_norm in ("2", "-2", "RO635"):
        return "RO635"
    if cmd_norm in ("3", "-3", "M4A1"):
        return "M4A1"
    if cmd_norm in ("4", "-4", "M16"):
        return "M16"
    if cmd_norm in ("5", "-5", "AR15", "AR-15"):
        return "AR-15"
    return None


def apply_server_selection(server_name: str) -> bool:
    server_name = normalize_server_input(server_name)
    if not server_name:
        return False

    candidates = SERVER_KEY_ALIASES.get(server_name, [server_name])
    for key in candidates:
        if key in SERVERS:
            CONFIG["SERVER_NAME"] = server_name
            CONFIG["BASE_URL"] = SERVERS[key]
            print("[+] 已选择服务器：%s" % server_name)
            return True

    print("[!] 当前 gflzirc 未找到服务器配置：%s" % server_name)
    print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
    return False



def print_gun_mode_menu():
    print("\n=========== 编队模式 ===========")
    print("  -team   : 练级五人模式（默认）")
    print("  -single : 打捞单人模式（仅使用梯队1）")
    print("  -smart  : 第6项一键打捞 / 教练の妙妙小巧思（固定使用梯队1）")
    print("--------------------------------")
    print("提示：先在游戏内配好编队，再开始抓取。")
    print("提示：回车默认选择 -team；输入 9 / -smart 可进入第6项一键打捞")
    print("提示：第6项内可输入 -gun / -equip 切换人形一键打捞或装备一键打捞")
    print("================================\n")


def reset_selection_menu():
    MENU_STATE["difficulty"] = None
    MENU_STATE["stage"] = None
    MENU_STATE["awaiting_gun_mode"] = False
    MENU_STATE["awaiting_stop_on_max"] = False
    MENU_STATE["awaiting_target_drop_stop"] = False
    MENU_STATE["awaiting_equip_auto_lock"] = False
    MENU_STATE["awaiting_filter_protection"] = False
    MENU_STATE["awaiting_run_confirm"] = False


def clear_selected_stage_config():
    """只清空关卡/目标选择，保留 UID/SIGN、服务器、编队模式与已解析梯队。"""
    CONFIG["SELECTED_DIFFICULTY"] = None
    CONFIG["SELECTED_STAGE"] = None
    CONFIG["SELECTED_TARGET"] = None
    CONFIG["SELECTED_TARGET_LABEL"] = None
    CONFIG["SELECTED_BATTLE_TEMPLATE"] = None


def reopen_stage_selection_menu():
    MENU_STATE["selection_unlocked"] = True
    reset_selection_menu()
    clear_selected_stage_config()
    print("[*] 已返回打捞关卡选择。当前 UID/SIGN、服务器、编队模式与梯队配置会继续沿用。")
    print_main_menu()
    print_difficulty_menu()


def validate_captured_team_for_mode() -> bool:
    guns = CONFIG.get("GUNS", []) or []
    if CONFIG.get("MODE_NAME") == "smart_epa":
        if not guns:
            print("[!] 第6项一键打捞需要梯队1至少存在 1 名人形。")
            return False
        print("[*] 第6项一键打捞校验通过：固定使用梯队1，实际出战使用第1名人形。")
        return True

    if CONFIG.get("MODE_NAME") == "single":
        if len(guns) != 1:
            print("[!] 当前为 single 打捞模式，但本次 Index/index 解析到的梯队人数为 %d 人。" % len(guns))
            print("[!] single 模式要求仅使用梯队1，且梯队1必须配置为单人编队。")
            print("[!] 请前往游戏编队界面，将梯队1调整为仅 1 名人形后，再重新输入 -r 生成计划。")
            print("[*] 提示：程序会保留你当前选择的 single 模式。调整好梯队1后，可直接再次输入 -r。")
            return False
        print("[*] single 模式校验通过。")
    return True


def handle_selection_input(cmd: str) -> bool:
    """Returns True if the input was consumed by the selection menu."""
    if not MENU_STATE["selection_unlocked"]:
        return False

    cmd = normalize_menu_input(cmd)

    if MENU_STATE["awaiting_filter_protection"]:
        if not cmd:
            cmd = "-protecton"
        if cmd == "-back":
            MENU_STATE["awaiting_filter_protection"] = False
            print("[*] 已返回上一级。")
            stage_data = get_stage_data(CONFIG.get("SELECTED_DIFFICULTY"), CONFIG.get("SELECTED_STAGE"))
            if stage_data:
                print_target_menu(CONFIG["SELECTED_DIFFICULTY"], CONFIG["SELECTED_STAGE"])
            return True
        if cmd == "-protecton":
            MENU_STATE["awaiting_filter_protection"] = False
            MENU_STATE["awaiting_stop_on_max"] = True
            CONFIG["ENABLE_FILTER_PROTECTION"] = True
            print("[+] 已选择：过滤保护开启。")
            print_stop_on_max_menu()
            return True
        if cmd == "-protectoff":
            MENU_STATE["awaiting_filter_protection"] = False
            MENU_STATE["awaiting_stop_on_max"] = True
            CONFIG["ENABLE_FILTER_PROTECTION"] = False
            print("[+] 已选择：过滤保护关闭。")
            print("[!] 提示：关闭后目标掉落也不会被保护，适合练级避免仓库被占满。")
            print_stop_on_max_menu()
            return True
        return False

    if MENU_STATE["awaiting_stop_on_max"]:
        if not cmd:
            cmd = "-keepmax"
        if cmd == "-back":
            MENU_STATE["awaiting_stop_on_max"] = False
            if CONFIG.get("MODE_NAME") == "team":
                MENU_STATE["awaiting_filter_protection"] = True
                print("[*] 已返回过滤保护设置菜单。")
                print_filter_protection_menu()
            else:
                print("[*] 已返回上一级。")
                stage_data = get_stage_data(CONFIG.get("SELECTED_DIFFICULTY"), CONFIG.get("SELECTED_STAGE"))
                if stage_data:
                    print_target_menu(CONFIG["SELECTED_DIFFICULTY"], CONFIG["SELECTED_STAGE"])
            return True
        if cmd == "-stopmax":
            MENU_STATE["awaiting_stop_on_max"] = False
            CONFIG["STOP_ON_MAX_LEVEL"] = True
            print("[+] 已选择：检测到满级后停止程序。")
            if CONFIG.get("MODE_NAME") == "single":
                MENU_STATE["awaiting_target_drop_stop"] = True
                print_target_drop_stop_menu()
            else:
                MENU_STATE["awaiting_run_confirm"] = True
                print_run_confirm_menu()
            return True
        if cmd == "-keepmax":
            MENU_STATE["awaiting_stop_on_max"] = False
            CONFIG["STOP_ON_MAX_LEVEL"] = False
            print("[+] 已选择：检测到满级后不停止程序。")
            if CONFIG.get("MODE_NAME") == "single":
                MENU_STATE["awaiting_target_drop_stop"] = True
                print_target_drop_stop_menu()
            else:
                MENU_STATE["awaiting_run_confirm"] = True
                print_run_confirm_menu()
            return True
        return False

    if MENU_STATE["awaiting_target_drop_stop"]:
        if not cmd:
            cmd = "-keepdrop"
        if cmd == "-back":
            MENU_STATE["awaiting_target_drop_stop"] = False
            MENU_STATE["awaiting_stop_on_max"] = True
            print("[*] 已返回满级停机设置。")
            print_stop_on_max_menu()
            return True
        if cmd == "-stopdrop":
            MENU_STATE["awaiting_target_drop_stop"] = False
            CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = True
            print("[+] 已选择：%s至少各掉落 1 个后停止打捞。" % ("目标装备" if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "目标人形"))
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                MENU_STATE["awaiting_equip_auto_lock"] = True
                print_equip_auto_lock_menu()
            else:
                MENU_STATE["awaiting_run_confirm"] = True
                print_run_confirm_menu()
            return True
        if cmd == "-keepdrop":
            MENU_STATE["awaiting_target_drop_stop"] = False
            CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = False
            print("[+] 已选择：目标达成后继续打捞。")
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                MENU_STATE["awaiting_equip_auto_lock"] = True
                print_equip_auto_lock_menu()
            else:
                MENU_STATE["awaiting_run_confirm"] = True
                print_run_confirm_menu()
            return True
        return False

    if MENU_STATE["awaiting_equip_auto_lock"]:
        if not cmd:
            cmd = "-lockequip"
        if cmd == "-back":
            MENU_STATE["awaiting_equip_auto_lock"] = False
            MENU_STATE["awaiting_target_drop_stop"] = True
            print("[*] 已返回目标达成停机设置。")
            print_target_drop_stop_menu()
            return True
        if cmd == "-lockequip":
            MENU_STATE["awaiting_equip_auto_lock"] = False
            MENU_STATE["awaiting_run_confirm"] = True
            CONFIG["AUTO_LOCK_TARGET_EQUIP"] = True
            print("[+] 已选择：目标装备掉落后自动上锁。")
            print_run_confirm_menu()
            return True
        if cmd == "-keepequipunlocked":
            MENU_STATE["awaiting_equip_auto_lock"] = False
            MENU_STATE["awaiting_run_confirm"] = True
            CONFIG["AUTO_LOCK_TARGET_EQUIP"] = False
            print("[+] 已选择：目标装备不自动上锁，仅依赖拆解过滤保护。")
            print_run_confirm_menu()
            return True
        return False

    if MENU_STATE["awaiting_run_confirm"]:
        if cmd == "-back":
            MENU_STATE["awaiting_run_confirm"] = False
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                MENU_STATE["awaiting_equip_auto_lock"] = True
                print("[*] 已返回目标装备自动上锁设置。")
                print_equip_auto_lock_menu()
            elif CONFIG.get("MODE_NAME") == "single":
                MENU_STATE["awaiting_target_drop_stop"] = True
                print("[*] 已返回目标达成停机设置。")
                print_target_drop_stop_menu()
            else:
                MENU_STATE["awaiting_stop_on_max"] = True
                print("[*] 已返回满级停机设置。")
                print_stop_on_max_menu()
            return True
        if cmd == "-y":
            MENU_STATE["awaiting_run_confirm"] = False
            print("[+] 配置已确认。")
            
            print("[+] 当前模式：%s" % ("打捞单人模式" if CONFIG.get("SINGLE_GUN_MODE") else "练级五人模式"))
            if CONFIG.get("MODE_NAME") == "team":
                schedule_label = "整队满级后切换" if CONFIG.get("TRAIN_SCHEDULE_MODE") == "full" else "均等练级轮转"
                
                print("[+] 练级调度模式：%s" % schedule_label)
                
                if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                    print("[!] 提示：夜战装备打捞已支持装备拆解过滤；练级模式仍不建议用于夜战。")
            print("[+] 满级停机设置：%s" % ("开启" if CONFIG.get("STOP_ON_MAX_LEVEL") else "关闭"))
            if CONFIG.get("MODE_NAME") == "single":
                print("[+] %s达成停机：%s" % ("目标装备" if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "目标人形", "开启" if CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED") else "关闭"))
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                print("[+] 目标装备自动上锁：%s" % ("开启" if CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True) else "关闭"))
            if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                # 夜战打捞目标是装备：这里不能加载 gun.json，也不能显示 gun_id 保护。
                # 直接使用已确认的 EPA 夜战专属装备 ID 表作为拆解过滤依据。
                current_target_equip_ids = []
                for _name in split_target_label(CONFIG.get("SELECTED_TARGET_LABEL", "")):
                    _eid = resolve_equip_id_by_name(_name)
                    if _eid is not None:
                        current_target_equip_ids.append(int(_eid))
                current_target_equip_ids = sorted(set(current_target_equip_ids))
                all_protected_equip_ids = sorted(get_selected_target_equip_ids())
                print("[+] 当前目标装备 equip_id：%s" % (current_target_equip_ids if current_target_equip_ids else "当前未配置"))
                print("[+] 装备自动拆解保护 equip_id：已保护全部 EPA 夜战专属装备，共 %d 个：%s" % (len(all_protected_equip_ids), all_protected_equip_ids if all_protected_equip_ids else "当前未配置"))
                print("[+] 说明：夜战关卡已启用装备掉落统计、Macro 后装备拆解与装备仓库应急恢复。")
            else:
                protected_ids = sorted(get_selected_protected_gun_ids())
                print("[+] 自动拆解保护 gun_id：%s" % (protected_ids if protected_ids else "当前未配置"))
            print("[*] 输入 -r 开始运行。")
            return True
        return False

    if MENU_STATE["difficulty"] is None:
        if cmd in ("普通", "紧急", "夜战"):
            MENU_STATE["difficulty"] = cmd
            CONFIG["SELECTED_DIFFICULTY"] = cmd
            CONFIG["SELECTED_STAGE"] = None
            CONFIG["SELECTED_TARGET"] = None
            CONFIG["SELECTED_TARGET_LABEL"] = None
            CONFIG["SELECTED_BATTLE_TEMPLATE"] = None
            print_stage_menu(cmd)
            return True
        return False

    if MENU_STATE["stage"] is None:
        if cmd == "-back":
            reset_selection_menu()
            print("[*] 当前已返回到难度选择菜单。")
            print_difficulty_menu()
            return True

        difficulty = MENU_STATE["difficulty"]
        valid_options = {
            "普通": NORMAL_STAGE_OPTIONS,
            "紧急": EMERGENCY_STAGE_OPTIONS,
            "夜战": NIGHT_STAGE_OPTIONS,
        }[difficulty]

        if cmd in valid_options:
            MENU_STATE["stage"] = cmd
            CONFIG["SELECTED_STAGE"] = cmd
            CONFIG["SELECTED_TARGET"] = None
            CONFIG["SELECTED_TARGET_LABEL"] = None
            CONFIG["SELECTED_BATTLE_TEMPLATE"] = None

            stage_data = get_stage_data(difficulty, cmd)
            if stage_data:
                print_target_menu(difficulty, cmd)
            else:
                print_placeholder_menu(difficulty, cmd)
                MENU_STATE["stage"] = None
                CONFIG["SELECTED_STAGE"] = None
                print_stage_menu(difficulty)
            return True
        return False

    stage_data = get_stage_data(CONFIG.get("SELECTED_DIFFICULTY"), CONFIG.get("SELECTED_STAGE"))
    if stage_data:
        if cmd == "-back":
            MENU_STATE["stage"] = None
            CONFIG["SELECTED_STAGE"] = None
            CONFIG["SELECTED_TARGET"] = None
            CONFIG["SELECTED_TARGET_LABEL"] = None
            CONFIG["SELECTED_BATTLE_TEMPLATE"] = None
            MENU_STATE["awaiting_stop_on_max"] = False
            MENU_STATE["awaiting_target_drop_stop"] = False
            MENU_STATE["awaiting_equip_auto_lock"] = False
            MENU_STATE["awaiting_run_confirm"] = False
            print("[*] 已返回%s难度关卡列表。" % CONFIG["SELECTED_DIFFICULTY"])
            print_stage_menu(CONFIG["SELECTED_DIFFICULTY"])
            return True

        options = stage_data.get("OPTIONS", {})
        if cmd in options:
            item = options[cmd]
            CONFIG["SELECTED_TARGET"] = cmd
            CONFIG["SELECTED_TARGET_LABEL"] = item["label"]
            CONFIG["MISSION_ID"] = stage_data["MISSION_ID"]
            if "start_spot" in item:
                CONFIG["START_SPOT"] = item["start_spot"]
            else:
                CONFIG["START_SPOT"] = stage_data["START_SPOTS"][cmd]
            CONFIG["ROUTE"] = item["route"]

            if CONFIG["SELECTED_DIFFICULTY"] == "普通" and CONFIG["SELECTED_STAGE"] == "A-10":
                CONFIG["SELECTED_BATTLE_TEMPLATE"] = A10_SINGLE_BATTLE_TEMPLATE
            else:
                CONFIG["SELECTED_BATTLE_TEMPLATE"] = None

            print("[+] 已选择：%s %s -> %s" % (
                CONFIG["SELECTED_DIFFICULTY"],
                CONFIG["SELECTED_STAGE"],
                CONFIG["SELECTED_TARGET_LABEL"],
            ))
            print("[+] 当前关卡配置已写入：MISSION_ID=%s, START_SPOT=%s, ROUTE=%s" % (
                CONFIG["MISSION_ID"],
                CONFIG["START_SPOT"],
                CONFIG["ROUTE"],
            ))
            print("[+] 当前模式已在抓包前确定：%s" % ("打捞单人模式" if CONFIG.get("SINGLE_GUN_MODE") else "练级五人模式"))
            if CONFIG.get("MODE_NAME") == "team" and CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                print("[!] 提示：夜战装备打捞已支持装备拆解过滤；练级模式仍不建议用于夜战。")
            print("[+] 当前战斗将自动调用已抓取的 TEAM_ID / FAIRY_ID / GUNS。")
            print("[+] 1002 将根据当前梯队配置自动生成，无需为每个任务单独修改。")
            print_ready_to_run_hint()
            if CONFIG.get("MODE_NAME") == "team":
                MENU_STATE["awaiting_filter_protection"] = True
                print_filter_protection_menu()
            else:
                MENU_STATE["awaiting_stop_on_max"] = True
                print_stop_on_max_menu()
            return True
        return False

    return False


def on_traffic(event_type: str, url: str, data: dict):
    event_upper = str(event_type).upper()

    if event_upper == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        CONFIG["INDEX_FETCH_READY"] = True
        print("\n[+] 成功！密钥已自动配置：")
        print("    UID  : %s" % CONFIG['USER_UID'])
        print("    SIGN : %s" % CONFIG['SIGN_KEY'])

        if CONFIG.get("AUTO_MONITOR_MODE"):
            print("[AUTO] 动态密钥已更新。")
            print("[AUTO] 请等待游戏完全进入指挥官主界面，然后再次输入 -r。")
            print("[AUTO] 程序将停止代理并主动请求 Index/index 解析梯队。")
        else:
            print("\n[!] CRITICAL: 请等待游戏完全加载到指挥官主界面！")
            print("[!] 然后输入 '-r' 自动停止代理并开始打捞。")


def gfam_resp_text(resp) -> str:
    try:
        if isinstance(resp, dict):
            parts = []
            for k in ("error_local", "error", "raw", "message", "msg"):
                if k in resp:
                    parts.append("%s=%s" % (k, resp.get(k)))
            return " | ".join(parts) or str(resp)
        return str(resp)
    except Exception:
        return ""


def gfam_remember_error(resp, step_name: str):
    global LAST_GFL_ERROR
    LAST_GFL_ERROR = {"step": step_name, "resp": resp, "text": gfam_resp_text(resp), "time": time.time()}


def gfam_is_plaintext_or_error300(resp) -> bool:
    """请求层/服务器偶发 plaintext 或 error:300。

    这类错误在实测中更常见于战斗接口短暂返回异常、仓库/关卡状态不同步、
    或本地解析到明文错误包；不能直接等同于 UID/SIGN 失效。
    """
    text = gfam_resp_text(resp).lower()
    return "unexpected plaintext response" in text or "error:300" in text




ADAPTIVE_TIMING_STATE = {
    "level": 0,
    "timing_errors": 0,
    "stable_success": 0,
    "last_error_time": 0.0,
}


def gfam_is_timing_sync_error(resp) -> bool:
    """识别更像“服务器状态未同步/接口推进过快”的错误。"""
    text = gfam_resp_text(resp).lower()
    if gfam_is_plaintext_or_error300(resp):
        return True
    return (
        "unexpected plaintext response" in text
        or "raw=error:2" in text or "error:2" in text or "error=2" in text
        or "raw=error:3" in text or "error:3" in text or "error=3" in text
    )


def gfam_adaptive_level() -> int:
    try:
        return max(0, int(ADAPTIVE_TIMING_STATE.get("level", 0) or 0))
    except Exception:
        return 0


def gfam_adaptive_extra(kind: str) -> float:
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True):
        return 0.0
    level = gfam_adaptive_level()
    if level <= 0:
        return 0.0
    kind = str(kind or "step").lower()
    if kind in ("sync", "abort", "start", "comb", "state", "move", "teammove", "battle", "finish", "endturn"):
        unit = float(CONFIG.get("ADAPTIVE_TIMING_STATE_EXTRA", 0.60) or 0.60)
    elif kind in ("repair", "retire"):
        unit = float(CONFIG.get("ADAPTIVE_TIMING_REPAIR_EXTRA", 1.00) or 1.00)
    elif kind in ("micro", "macro"):
        unit = float(CONFIG.get("ADAPTIVE_TIMING_STATE_EXTRA", 0.60) or 0.60)
    else:
        unit = float(CONFIG.get("ADAPTIVE_TIMING_STEP_EXTRA", 0.25) or 0.25)
    return max(0.0, level * unit)


def gfam_adaptive_sleep(kind: str = "step", base: float = 0.0):
    """按当前自适应等级等待；level=0 时保持原有间隔不变。"""
    try:
        total = max(0.0, float(base or 0.0) + gfam_adaptive_extra(kind))
    except Exception:
        total = float(base or 0.0)
    if total > 0:
        time.sleep(total)


def gfam_get_float_setting(name: str, default: float) -> float:
    """读取可被环境变量覆盖的节奏参数。"""
    try:
        env_name = "GFAM_" + str(name or "").upper()
        if env_name in os.environ:
            return max(0.0, float(os.environ.get(env_name) or default))
        return max(0.0, float(CONFIG.get(name, default) or default))
    except Exception:
        return max(0.0, float(default or 0.0))


def gfam_sync_sleep(kind: str, setting_name: str, default: float):
    gfam_adaptive_sleep(kind, gfam_get_float_setting(setting_name, default))


def gfam_send_request_with_timing_retry(client, endpoint, payload, step_name, attempts=None, sleep_seconds=None):
    """对 teamMove 这类容易因服务器同步未完成而返回 error:300 的接口做原地重试。

    以前一遇到 error:300 就直接放弃关卡并进入自修复；这会导致每几十秒异常一次。
    这里先等待并重试同一个请求，只有多次仍失败才交给原有异常恢复逻辑。
    """
    try:
        attempts = int(attempts if attempts is not None else CONFIG.get("TEAM_MOVE_RETRY_ATTEMPTS", 3))
    except Exception:
        attempts = 3
    attempts = max(1, attempts)
    base_sleep = gfam_get_float_setting("TEAM_MOVE_RETRY_SLEEP_SECONDS", 0.5) if sleep_seconds is None else float(sleep_seconds or 0)

    resp = client.send_request(endpoint, payload)
    if not gfam_is_timing_sync_error(resp) or attempts <= 1:
        return resp

    for i in range(2, attempts + 1):
        gfam_adaptive_note_timing_error(resp, step_name)
        wait_s = max(0.2, base_sleep * (i - 1))
        print("[同步重试] %s 返回状态同步类错误，等待 %.1f 秒后重试 %d/%d。" % (step_name, wait_s, i, attempts))
        gfam_adaptive_sleep("move", wait_s)
        resp = client.send_request(endpoint, payload)
        if not gfam_is_timing_sync_error(resp):
            if i > 1:
                print("[同步重试] %s 重试成功。" % step_name)
            return resp
    return resp


def gfam_adaptive_note_timing_error(resp, step_name: str = ""):
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True):
        return
    if not gfam_is_timing_sync_error(resp):
        return
    max_level = max(0, int(CONFIG.get("ADAPTIVE_TIMING_MAX_LEVEL", 5) or 5))
    trigger = max(1, int(CONFIG.get("ADAPTIVE_TIMING_TRIGGER_ERRORS", 2) or 2))
    ADAPTIVE_TIMING_STATE["timing_errors"] = int(ADAPTIVE_TIMING_STATE.get("timing_errors", 0) or 0) + 1
    ADAPTIVE_TIMING_STATE["stable_success"] = 0
    ADAPTIVE_TIMING_STATE["last_error_time"] = time.time()
    err_count = int(ADAPTIVE_TIMING_STATE.get("timing_errors", 0) or 0)
    old_level = gfam_adaptive_level()
    if err_count % trigger == 0 and old_level < max_level:
        ADAPTIVE_TIMING_STATE["level"] = old_level + 1
        new_level = old_level + 1
        print("[自适应间隔] 检测到状态同步类错误 %d 次，间隔等级提升为 %d/%d。" % (err_count, new_level, max_level))
        print("[自适应间隔] 当前额外等待：Step +%.2fs，状态同步/进出图 +%.2fs，拆解恢复 +%.2fs。" % (
            gfam_adaptive_extra("step"), gfam_adaptive_extra("state"), gfam_adaptive_extra("repair")
        ))


def gfam_adaptive_note_success():
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True):
        return
    level = gfam_adaptive_level()
    if level <= 0:
        return
    ADAPTIVE_TIMING_STATE["stable_success"] = int(ADAPTIVE_TIMING_STATE.get("stable_success", 0) or 0) + 1
    decay = max(1, int(CONFIG.get("ADAPTIVE_TIMING_DECAY_SUCCESSES", 80) or 80))
    if int(ADAPTIVE_TIMING_STATE.get("stable_success", 0) or 0) >= decay:
        ADAPTIVE_TIMING_STATE["level"] = max(0, level - 1)
        ADAPTIVE_TIMING_STATE["stable_success"] = 0
        ADAPTIVE_TIMING_STATE["timing_errors"] = 0
        print("[自适应间隔] 已连续稳定 %d 个关键接口，间隔等级降低为 %d/%d。" % (
            decay, gfam_adaptive_level(), int(CONFIG.get("ADAPTIVE_TIMING_MAX_LEVEL", 5) or 5)
        ))


def get_adaptive_timing_status_text():
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True):
        return "关闭"
    try:
        level = gfam_adaptive_level()
    except Exception:
        level = 0
    try:
        max_level = int(CONFIG.get("ADAPTIVE_TIMING_MAX_LEVEL", 8) or 8)
    except Exception:
        max_level = 8
    if level <= 0:
        return "等级 0/%s，当前使用默认间隔；遇到 error:300/plaintext 后自动放慢" % max_level
    return "等级 %s/%s，额外等待：Step +%.2fs，状态同步/进出图 +%.2fs，拆解恢复 +%.2fs" % (
        level, max_level,
        gfam_adaptive_extra("step"),
        gfam_adaptive_extra("state"),
        gfam_adaptive_extra("repair"),
    )

def gfam_is_auth_or_plaintext_error(resp) -> bool:
    """仅识别明确登录/签名失效。

    UID/SIGN 正常情况下不会在运行中频繁失效；除非用户重新登录获取了新的会话，
    否则 error:300 / Unexpected plaintext response 不再按 UID/SIGN 失效处理，
    而是交给异常自修复流程先尝试拆解恢复。
    """
    text = gfam_resp_text(resp).lower()
    if gfam_is_plaintext_or_error300(resp):
        return False
    strict_keywords = [
        "invalid sign", "sign invalid", "sign expired", "sign error",
        "uid/sign", "login expired", "session expired",
        "not login", "not logged in", "auth expired", "token expired",
    ]
    return any(k in text for k in strict_keywords)


def gfam_last_error_is_auth() -> bool:
    if not LAST_GFL_ERROR:
        return False
    return gfam_is_auth_or_plaintext_error(LAST_GFL_ERROR.get("resp"))


def gfam_pre_run_abort_once(client, reason="正式运行前状态清理"):
    """运行前轻量 abortMission 一次，清理上次异常残留的同关卡状态。

    只发送 abortMission，不额外请求 Index/index；异常静默降级，避免影响正常开跑。
    """
    if not CONFIG.get("ENABLE_PRE_RUN_ABORT", True):
        return False
    mission_id = CONFIG.get("MISSION_ID")
    if not mission_id:
        return False
    try:
        print("[状态清理] %s：尝试 abortMission mission_id=%s。" % (reason, mission_id))
        client.send_request(API_MISSION_ABORT, {"mission_id": int(mission_id)})
        return True
    except Exception:
        return False


def gfam_last_error_is_start_state_conflict() -> bool:
    """startMission 返回 error:2 通常表示服务器仍认为上一轮战役状态未完全结束。"""
    if not LAST_GFL_ERROR:
        return False
    step = str(LAST_GFL_ERROR.get("step") or "").lower().replace(" ", "")
    text = str(LAST_GFL_ERROR.get("text") or gfam_resp_text(LAST_GFL_ERROR.get("resp"))).lower()
    return "startmission" in step and ("error:2" in text or "error=2" in text or "raw=error:2" in text)


def gfam_safe_abort_and_sync(client, reason="状态同步", attempts=2, sleep_seconds=1.2):
    """异常恢复前后强制放弃当前战役并请求一次 Index/index，同步服务器状态与仓库上限。"""
    mission_id = CONFIG.get("MISSION_ID")
    print("[状态同步] %s：正在确认放弃当前战役并同步 Index/index。" % reason)
    for _ in range(max(1, int(attempts or 1))):
        try:
            client.send_request(API_MISSION_ABORT, {"mission_id": mission_id})
        except Exception:
            pass
        gfam_adaptive_sleep("sync", float(sleep_seconds or 1.0))
    try:
        payload = {"time": int(time.time()), "furniture_data": False}
        idx = client.send_request(API_INDEX_INDEX, payload)
        if isinstance(idx, dict) and "error" not in idx and "error_local" not in idx:
            update_fairy_cache_from_index_payload(idx, source="smart 状态同步 Index/index")
            try:
                if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                    gfam_apply_dynamic_equip_limit_from_index_payload(idx, reason="异常恢复状态同步 Index/index")
                else:
                    gfam_apply_dynamic_micro_limit_from_index_payload(idx, reason="异常恢复状态同步 Index/index")
            except Exception:
                pass
            return True
    except Exception as exc:
        print("[状态同步] Index/index 同步失败：%s" % exc)
    return False


def gfam_clear_runtime_auth_state():
    CONFIG["SIGN_KEY"] = DEFAULT_SIGN
    CONFIG["INDEX_FETCH_READY"] = False
    try:
        os.environ.pop("GFAM_USER_UID", None)
        os.environ.pop("GFAM_SIGN_KEY", None)
    except Exception:
        pass


def check_step_error(resp: dict, step_name: str) -> bool:
    if resp is None:
        gfam_remember_error(resp, step_name)
        gfam_adaptive_note_timing_error(resp, step_name)
        print("[-] %s 错误：服务器空响应。" % step_name)
        return True
    # Mission/combinationInfo 在部分夜战/部分服务器上可能正常返回 [] 或列表。
    # 该接口在本脚本中只作为进入战斗前的同步/预热请求，实际不依赖其内容；
    # 因此列表响应不应被当作致命错误，否则夜战 A-1 等关卡会在 Step 0 直接中止。
    step_key = str(step_name or "").lower().replace(" ", "")
    if isinstance(resp, list) and ("combinfo" in step_key or "combinationinfo" in step_key):
        if len(resp) == 0:
            gfam_debug_log("[*] %s 返回空列表，已按正常预热响应继续。" % step_name)
        else:
            gfam_debug_log("[*] %s 返回列表响应，已按正常预热响应继续。" % step_name)
        gfam_adaptive_note_success()
        return False
    if not isinstance(resp, dict):
        gfam_remember_error(resp, step_name)
        gfam_adaptive_note_timing_error(resp, step_name)
        print("[-] %s 错误：返回格式异常：%s" % (step_name, str(resp)))
        return True
    if "error_local" in resp:
        gfam_remember_error(resp, step_name)
        gfam_adaptive_note_timing_error(resp, step_name)
        print("[-] %s 本地错误: %s" % (step_name, resp.get('error_local')))
        if "raw" in resp:
            print("    原始响应：'%s'" % resp.get("raw"))
        if gfam_is_auth_or_plaintext_error(resp):
            print("[!] 检测到明确 UID/SIGN 失效，需要重新获取会话。")
        elif gfam_is_timing_sync_error(resp):
            print("[!] 检测到 plaintext/error 响应，按普通运行异常处理，优先尝试自修复。")
        return True
    if "error" in resp:
        gfam_remember_error(resp, step_name)
        gfam_adaptive_note_timing_error(resp, step_name)
        print("[-] %s 服务器错误: %s" % (step_name, resp.get('error')))
        if gfam_is_auth_or_plaintext_error(resp):
            print("[!] 检测到明确 UID/SIGN 失效，需要重新获取会话。")
        elif gfam_is_timing_sync_error(resp):
            print("[!] 检测到 plaintext/error 响应，按普通运行异常处理，优先尝试自修复。")
        return True
    gfam_adaptive_note_success()
    return False


def check_battle_drop(resp_data: dict, spot_id: int) -> list:
    collected = []
    bg = resp_data.get("battle_get_gun", [])
    if bg:
        for gun in bg:
            gun_id = int(gun.get("gun_id"))
            gun_uid = int(gun.get("gun_with_user_id"))
            # 详细掉落已汇总到状态面板，本处不再逐条打印。
            refresh_runtime_panel()
            DROPPED_UID_TO_GUN_ID[gun_uid] = gun_id
            record_target_drop(gun_id, "gun")
            RUN_STATS["macro_drop_names"].append(resolve_gun_name_by_id(gun_id))
            collected.append(gun_uid)
    return collected


def check_battle_equip_drop(resp_data: dict, spot_id: int, client=None):
    collected = []
    be = resp_data.get("battle_get_equip", [])
    if be:
        for equip in be:
            equip_id = gfam_extract_equip_id(equip)
            equip_uid = gfam_extract_equip_uid(equip)
            equip_rank = gfam_extract_equip_rank(equip)
            if equip_id <= 0 or equip_uid <= 0:
                print("[装备掉落] 无法解析装备掉落字段，已跳过自动记录：%s" % str(equip))
                continue
            refresh_runtime_panel()
            DROPPED_UID_TO_EQUIP_ID[equip_uid] = equip_id
            DROPPED_UID_TO_EQUIP_RANK[equip_uid] = equip_rank
            DROPPED_UID_TO_EQUIP_RAW[equip_uid] = dict(equip)
            record_target_drop(equip_id, "equip")
            gfam_auto_lock_target_equip_if_needed(client, equip_id, equip_uid, source="battle_get_equip", spot_id=spot_id)
            RUN_STATS["macro_drop_names"].append(resolve_equip_name_by_id(equip_id))
            collected.append({"equip_id": equip_id, "equip_uid": equip_uid, "rank": equip_rank})
    return collected



def extract_fairy_exp_candidates_from_resp(resp_data: dict):
    """
    从 battleFinish/endTurn/startTurn 响应中提取妖精经验候选值。

    兼容三种形态：
    1) 本次获得经验；2) 当前等级内经验；3) 累计总经验。
    """
    current_cfg = get_current_team_config()
    fairy = current_cfg.get("fairy")
    if not isinstance(fairy, dict):
        return []

    fairy_uid = str(fairy.get("id", ""))
    fairy_type_id = str(fairy.get("fairy_id", ""))
    candidates = []

    exp_keys = (
        "fairy_exp", "fairyExp", "fairyexp",
        "fairy_add_exp", "fairyAddExp", "add_fairy_exp", "addFairyExp",
        "fairy_gain_exp", "fairyGainExp", "fairy_exp_add", "fairyExpAdd",
    )
    generic_delta_keys = ("add_exp", "exp_add", "gain_exp", "get_exp")

    def identity_matches(node):
        if not isinstance(node, dict):
            return False
        if fairy_uid:
            for id_key in ("id", "fairy_with_user_id", "fairy_uid"):
                if str(node.get(id_key, "")) == fairy_uid:
                    return True
        if fairy_type_id:
            for id_key in ("fairy_id", "type_id"):
                if str(node.get(id_key, "")) == fairy_type_id:
                    return True
        return False

    def has_identity(node):
        return isinstance(node, dict) and any(k in node for k in ("id", "fairy_with_user_id", "fairy_uid", "fairy_id", "type_id"))

    def add_candidate(value, key, node):
        try:
            val = int(value or 0)
        except Exception:
            return
        if val <= 0:
            return
        key_l = str(key or "").lower()
        if any(bad in key_l for bad in ("quality", "skill", "grow", "develop", "mod")):
            return
        if identity_matches(node) or not has_identity(node):
            candidates.append(val)

    def walk(node):
        if isinstance(node, dict):
            for k in exp_keys:
                if k in node:
                    add_candidate(node.get(k), k, node)
            if identity_matches(node):
                for k in generic_delta_keys:
                    if k in node:
                        add_candidate(node.get(k), k, node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(resp_data)
    return sorted(set(candidates))


def extract_fairy_exp_gain_from_resp(resp_data: dict) -> int:
    vals = extract_fairy_exp_candidates_from_resp(resp_data)
    return max(vals) if vals else 0


def apply_fairy_exp_gain_from_resp(resp_data: dict):
    current_cfg = get_current_team_config()
    fairy = current_cfg.get("fairy")
    if not isinstance(fairy, dict):
        return 0

    candidates = extract_fairy_exp_candidates_from_resp(resp_data)
    if not candidates:
        return 0

    base_total = int(fairy.get("base_total_exp", 0) or 0)
    target_total = int(fairy.get("target_total_exp", 0) or 0)
    current_runtime = int(fairy.get("runtime_gained_exp", 0) or 0)
    current_total = min(target_total, base_total + current_runtime)

    level = int(fairy.get("level", fairy.get("fairy_lv", 1)) or 1)
    next_need = fairy_next_level_required_exp(level)
    level_floor = sum_exp_range(FAIRY_EXP_1_TO_100, 1, min(level, 100))
    max_reasonable_jump = max(500000, next_need * 2)
    max_reasonable_delta = max(50000, next_need)

    possible_deltas = []
    for raw_val in candidates:
        # 形态一：累计总经验。
        if current_total <= raw_val <= target_total:
            delta = raw_val - current_total
            if 0 < delta <= max_reasonable_jump:
                possible_deltas.append((delta, raw_val))

        # 形态二：当前等级内经验。Index 初始化也使用同一套转换逻辑。
        if 0 <= raw_val <= max(0, next_need):
            converted_total = level_floor + raw_val
            if current_total < converted_total <= target_total:
                delta = converted_total - current_total
                if 0 < delta <= max_reasonable_jump:
                    possible_deltas.append((delta, converted_total))

        # 形态三：本次获得经验。
        if 0 < raw_val <= max_reasonable_delta:
            possible_deltas.append((raw_val, current_total + raw_val))

    if not possible_deltas:
        return 0

    # 优先选择最小的合理增量，避免把“当前等级内经验”误当成“本次获得经验”。
    delta, seen_total = min(possible_deltas, key=lambda x: x[0])
    fairy["runtime_gained_exp"] = current_runtime + int(delta)
    fairy["last_total_exp_seen"] = int(min(target_total, seen_total))
    refresh_runtime_panel()
    return int(delta)


def check_battle_exp(resp_data: dict, spot_id: int):
    """Returns (any_zero, all_zero)."""
    gun_exp_list = resp_data.get("gun_exp", [])
    any_zero = False
    all_zero = False

    if gun_exp_list:
        exp_details = []
        zero_flags = []
        current_cfg = get_current_team_config()
        gun_map = {str(g.get("id")): g for g in current_cfg.get("guns", [])}

        for item in gun_exp_list:
            gun_uid = str(item.get("gun_with_user_id", "unknown"))
            exp_val = str(item.get("exp", "0"))
            exp_int = int(exp_val) if str(exp_val).isdigit() else 0
            exp_details.append("%s: +%s" % (gun_uid[-4:], exp_val))

            maxed_set = current_cfg.setdefault("maxed_member_uids", set())
            warned_set = current_cfg.setdefault("warned_max_member_uids", set())

            if gun_uid in gun_map and exp_int > 0:
                gun_map[gun_uid]["runtime_gained_exp"] = int(gun_map[gun_uid].get("runtime_gained_exp", 0)) + exp_int
                # 如果仍能获得经验，则不把它视为满级。
                maxed_set.discard(gun_uid)

            is_zero = (exp_val == "0")
            zero_flags.append(is_zero)
            if is_zero:
                maxed_set.add(gun_uid)
                if gun_uid not in warned_set:
                    panel_safe_print("    [满级检测] 人形 %s EXP 为 0，已标记为满级。" % gun_uid)
                    warned_set.add(gun_uid)
                any_zero = True

        all_zero = all(zero_flags) if zero_flags else False
        RUN_STATS["last_micro_exp_lines"] = exp_details
        apply_fairy_exp_gain_from_resp(resp_data)
        refresh_runtime_panel()

    return any_zero, all_zero


def check_win_drop(resp_data: dict) -> list:
    collected = []
    win_result = resp_data.get("mission_win_result", {})
    if win_result:
        rg = win_result.get("reward_gun", [])
        for gun in rg:
            gun_id = int(gun.get("gun_id"))
            gun_uid = int(gun.get("gun_with_user_id"))
            refresh_runtime_panel()
            DROPPED_UID_TO_GUN_ID[gun_uid] = gun_id
            record_target_drop(gun_id, "gun")
            RUN_STATS["macro_drop_names"].append(resolve_gun_name_by_id(gun_id))
            collected.append(gun_uid)
    return collected


def check_win_equip_drop(resp_data: dict, client=None):
    collected = []
    win_result = resp_data.get("mission_win_result", {})
    if win_result:
        re_list = win_result.get("reward_equip", [])
        for equip in re_list:
            equip_id = gfam_extract_equip_id(equip)
            equip_uid = gfam_extract_equip_uid(equip)
            equip_rank = gfam_extract_equip_rank(equip)
            if equip_id <= 0 or equip_uid <= 0:
                print("[装备掉落] 无法解析胜利奖励装备字段，已跳过自动记录：%s" % str(equip))
                continue
            refresh_runtime_panel()
            DROPPED_UID_TO_EQUIP_ID[equip_uid] = equip_id
            DROPPED_UID_TO_EQUIP_RANK[equip_uid] = equip_rank
            DROPPED_UID_TO_EQUIP_RAW[equip_uid] = dict(equip)
            record_target_drop(equip_id, "equip")
            gfam_auto_lock_target_equip_if_needed(client, equip_id, equip_uid, source="mission_win_result.reward_equip", spot_id=None)
            RUN_STATS["macro_drop_names"].append(resolve_equip_name_by_id(equip_id))
            collected.append({"equip_id": equip_id, "equip_uid": equip_uid, "rank": equip_rank})
    return collected


def get_mvp_generator():
    idx = 0
    while True:
        guns = get_active_guns()
        if not guns:
            yield 0
            continue
        yield guns[idx % len(guns)]["id"]
        idx = (idx + 1) % len(guns)


def get_active_guns():
    guns = get_current_team_config()["guns"]
    if CONFIG.get("SINGLE_GUN_MODE"):
        idx = CONFIG.get("SINGLE_GUN_INDEX", 0)
        if 0 <= idx < len(guns):
            return [guns[idx]]
        return []
    return guns


def build_battle_guns():
    return [{"id": g["id"], "life": g["life"]} for g in get_active_guns()]


def build_battle_1002():
    """
    与原版风格尽量保持一致：
    - 单人编队时，使用抓包里验证过的座位值 1
    - 多人编队时，按原版自动生成，不需要为每个任务单独写死
    """
    result = {}
    guns = get_active_guns()

    if len(guns) == 1:
        result[str(guns[0]["id"])] = {"47": 1}
        return result

    for gun in guns:
        result[str(gun["id"])] = {"47": 0}
    return result


def farm_mission_epa(client: GFLClient, team_id: int, mvp_gen):
    global stop_macro_flag, stop_micro_flag, TEAM_SWITCH_PENDING

    mission_id = CONFIG["MISSION_ID"]
    start_spot = CONFIG["START_SPOT"]
    route = CONFIG["ROUTE"]

    dropped_uids = []
    dropped_equip_uids = []
    current_spots_state = {}

    def update_seeds(resp):
        if isinstance(resp, dict) and "spot_act_info" in resp:
            for s in resp["spot_act_info"]:
                current_spots_state[str(s.get("spot_id"))] = int(s.get("seed", 0))

    refresh_runtime_panel()
    gfam_adaptive_sleep("comb", 0.0)
    if check_step_error(client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id}), "combInfo"):
        return None

    refresh_runtime_panel()
    start_payload = {
        "mission_id": mission_id,
        "spots": [{"spot_id": start_spot, "team_id": team_id}],
        "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [],
        "ally_spots": [], "mission_ally_spots": [],
        "ally_id": int(time.time())
    }
    gfam_adaptive_sleep("start", 0.0)
    start_resp = client.send_request(API_MISSION_START, start_payload)
    if check_step_error(start_resp, "startMission"):
        return None
    update_seeds(start_resp)

    curr_spot = start_spot
    for step, next_spot in enumerate(route, 1):
        RUN_STATS["current_step"] = step
        refresh_runtime_panel()
        refresh_runtime_panel()
        move_payload = {
            "person_type": 1, "person_id": team_id,
            "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
        }
        gfam_sync_sleep("move", "BASE_MOVE_DELAY_SECONDS", 0.20)
        move_step_name = "teamMove(%d->%d)" % (curr_spot, next_spot)
        move_resp = gfam_send_request_with_timing_retry(
            client, API_MISSION_TEAM_MOVE, move_payload, move_step_name,
            attempts=CONFIG.get("TEAM_MOVE_RETRY_ATTEMPTS", 3),
            sleep_seconds=CONFIG.get("TEAM_MOVE_RETRY_SLEEP_SECONDS", 0.5),
        )
        if check_step_error(move_resp, move_step_name):
            return None
        update_seeds(move_resp)

        gfam_sync_sleep("move", "AFTER_MOVE_DELAY_SECONDS", 0.20)
        client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id})
        gfam_sync_sleep("battle", "BASE_BATTLE_DELAY_SECONDS", 0.20)

        seed = current_spots_state.get(str(next_spot), 0)
        current_mvp = next(mvp_gen)
        refresh_runtime_panel()

        selected_template = CONFIG.get("SELECTED_BATTLE_TEMPLATE")

        if selected_template:
            fairy_dict = {}
            current_fairy_id = get_current_fairy_id()
            if current_fairy_id:
                fairy_dict = {
                    str(current_fairy_id): {
                        "9": 1,
                        "68": 0
                    }
                }

            battle_payload = {
                "spot_id": next_spot,
                "if_enemy_die": True,
                "current_time": int(time.time()),
                "boss_hp": 0,
                "mvp": current_mvp,
                "last_battle_info": "",
                "use_skill_squads": [],
                "use_skill_ally_spots": [],
                "use_skill_vehicle_spots": [],
                "guns": build_battle_guns(),
                "user_rec": '{"seed":%d,"record":[]}' % seed,
                "1000": selected_template.get("1000", {}),
                "1001": selected_template.get("1001", {}),
                "1002": build_battle_1002(),
                "1003": fairy_dict,
                "1005": selected_template.get("1005", {}),
                "1007": selected_template.get("1007", {}),
                "1008": selected_template.get("1008", {}),
                "1009": selected_template.get("1009", {}),
                "battle_damage": {},
                "micalog": {
                    "user_device": CONFIG["USER_DEVICE"],
                    "user_ip": ""
                }
            }
        else:
            fairy_dict = {}
            current_fairy_id = get_current_fairy_id()
            if current_fairy_id:
                fairy_dict = {
                    str(current_fairy_id): {
                        "9": 1,
                        "68": 0
                    }
                }

            battle_payload = {
                "spot_id": next_spot,
                "if_enemy_die": True,
                "current_time": int(time.time()),
                "boss_hp": 0,
                "mvp": current_mvp,
                "last_battle_info": "",
                "use_skill_squads": [],
                "use_skill_ally_spots": [],
                "use_skill_vehicle_spots": [],
                "guns": build_battle_guns(),
                "user_rec": '{"seed":%d,"record":[]}' % seed,

                "1000": {"10": 18473, "11": 18473, "12": 18473, "13": 18473, "15": 27550, "16": 0, "17": 98, "33": 10017, "40": 50, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 25975, "25": 0, "26": 25975, "27": 4, "34": 63, "35": 63, "41": 519, "42": 0, "43": 0, "44": 0},
                "1001": {},
                "1002": build_battle_1002(),
                "1003": fairy_dict,
                "1005": {}, "1007": {}, "1008": {}, "1009": {},
                "battle_damage": {},
                "micalog": {
                    "user_device": CONFIG["USER_DEVICE"],
                    "user_ip": ""
                }
            }

        battle_resp = client.send_request(API_MISSION_BATTLE_FINISH, battle_payload)
        if check_step_error(battle_resp, "battleFinish(%d)" % next_spot):
            return None

        dropped_uids.extend(check_battle_drop(battle_resp, next_spot))
        battle_equip_drops = check_battle_equip_drop(battle_resp, next_spot, client=client)
        dropped_equip_uids.extend([x["equip_uid"] for x in battle_equip_drops])

        any_zero, all_zero = check_battle_exp(battle_resp, next_spot)
        if CONFIG.get("MODE_NAME") == "team":
            if all_zero:
                TEAM_SWITCH_PENDING = True
                mark_current_training_team_completed()
                print("    [*] 当前五人编队成员 EXP 均为 0，该梯队已完成。")
        else:
            if any_zero:
                if CONFIG.get("STOP_ON_MAX_LEVEL", True):
                    stop_macro_flag = True
                    stop_micro_flag = True
                    print("    [*] 为避免浪费 EXP，已触发自动停机。本轮结束后将安全停止。")
                else:
                    print("    [*] 检测到满级，但已关闭满级停机，程序将继续运行。")

        curr_spot = next_spot
        gfam_adaptive_sleep("step", 0.2)

    refresh_runtime_panel()
    if check_step_error(client.send_request(API_MISSION_END_TURN, {}), "endTurn"):
        return None
    gfam_adaptive_sleep("step", 0.2)
    if check_step_error(client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"):
        return None
    gfam_adaptive_sleep("step", 0.2)
    if check_step_error(client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    win_resp = client.send_request(API_MISSION_START_TURN, {})
    if check_step_error(win_resp, "startTurn"):
        return None

    apply_fairy_exp_gain_from_resp(win_resp)
    dropped_uids.extend(check_win_drop(win_resp))
    win_equip_drops = check_win_equip_drop(win_resp, client=client)
    dropped_equip_uids.extend([x["equip_uid"] for x in win_equip_drops])

    return {"guns": dropped_uids, "equips": dropped_equip_uids}



def gfam_retry_mission_after_repair(client, team_id, mvp_gen, label="自修复"):
    """自修复完成后重试当前 Micro。

    若重试一开始 startMission 返回 error:2，通常不是仓库计算错误，
    而是上一轮失败/放弃后服务器状态还没完全同步；此时再做一次
    abort + Index/index 同步后允许二次重试一次，避免误判为修复失败。
    """
    gfam_safe_abort_and_sync(client, reason="%s 重试前状态同步" % label)
    gfam_adaptive_sleep("repair", 0.0)
    retry_result = farm_mission_epa(client, team_id, mvp_gen)
    if retry_result is None and gfam_last_error_is_start_state_conflict():
        print("[%s] startMission 返回 error:2，判断为战役状态未完全同步；执行二次状态同步后再重试一次。" % label)
        gfam_safe_abort_and_sync(client, reason="%s startMission error:2 二次同步" % label, attempts=3, sleep_seconds=1.5)
        gfam_adaptive_sleep("repair", 0.0)
        retry_result = farm_mission_epa(client, team_id, mvp_gen)
    return retry_result

def retire_guns(client: GFLClient, gun_uids: list, update_cache=False, cache_reason="Macro 后人形拆解成功"):
    global stop_macro_flag, stop_micro_flag, RETIRE_NO_SPACE_COUNT

    if not gun_uids:
        return 0

    protected_ids = get_selected_protected_gun_ids()
    filtered_uids = []

    for gun_uid in gun_uids:
        gun_id = DROPPED_UID_TO_GUN_ID.get(gun_uid)
        if gun_id is not None:
            try:
                gun_id = int(gun_id)
            except Exception:
                pass
        if gun_id in protected_ids:
            print("[*] 已保留受保护掉落。Gun ID: %s | UID: %s" % (gun_id, gun_uid))
            continue
        filtered_uids.append(gun_uid)

    if protected_ids:
        print("[*] 已启用自动拆解保护，受保护 gun_id：%s" % sorted(protected_ids))

    if not filtered_uids:
        print("[*] 过滤后没有可自动拆解的人形。")
        return 0

    result_count = 0
    print("[*] 正在提交 %d 名人形进行自动拆解……" % len(filtered_uids))
    resp = client.send_request(API_GUN_RETIRE, filtered_uids)
    if resp.get("success"):
        RETIRE_NO_SPACE_COUNT = 0
        print("[+] 自动拆解成功！")
        result_count = len(filtered_uids)
        if update_cache and result_count > 0:
            # 普通/紧急 EPA 的人形自动拆解在这里立即更新本地仓库缓存。
            # 之前只在外层 Macro 结束处尝试更新，普通 EPA 的某些路径会漏掉或面板刷新不及时。
            gfam_note_storage_recovered_after_retire("gun", result_count)
            gfam_recompute_storage_micro_limit_from_cache("gun", reason=cache_reason)
    else:
        print("[-] 拆解失败：%s" % str(resp))
        if is_no_space_retire_failure(resp):
            RETIRE_NO_SPACE_COUNT += 1
            print("[!] 检测到疑似仓库无空位导致的拆解失败次数：%d / %d" % (
                RETIRE_NO_SPACE_COUNT,
                CONFIG.get("STOP_AFTER_RETIRE_NO_SPACE_TIMES", 2),
            ))
            if RETIRE_NO_SPACE_COUNT >= CONFIG.get("STOP_AFTER_RETIRE_NO_SPACE_TIMES", 2):
                stop_macro_flag = True
                stop_micro_flag = True
                print("[!] 已触发自动停机：多次自动拆解后仓库似乎仍无空位。")
        else:
            RETIRE_NO_SPACE_COUNT = 0

    for gun_uid in gun_uids:
        if gun_uid in DROPPED_UID_TO_GUN_ID:
            del DROPPED_UID_TO_GUN_ID[gun_uid]
    gfam_final_cleanup_mark_retired("gun", gun_uids)
    return result_count


def retire_equips(client: GFLClient, equip_uids: list):
    gfam_set_last_equip_retire_count(0)
    if not CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
        print("[装备拆解] 已关闭装备自动拆解；本轮装备将保留在仓库中用于 ID 确认。")
        gfam_final_cleanup_mark_retired("equip", equip_uids)
        return True
    if not equip_uids:
        return True
    clean_uids = []
    for uid in equip_uids:
        try:
            uid = int(uid)
            if uid > 0:
                clean_uids.append(uid)
        except Exception:
            pass
    clean_uids = list(dict.fromkeys(clean_uids))
    filtered_uids = []
    for uid in clean_uids:
        rank = DROPPED_UID_TO_EQUIP_RANK.get(uid, 0)
        equip_id = DROPPED_UID_TO_EQUIP_ID.get(uid, "?")
        raw = DROPPED_UID_TO_EQUIP_RAW.get(uid)
        ok, reason = gfam_should_auto_retire_equip_by_rules(uid, equip_id, rank=rank, raw=raw, source="macro-drop")
        if not ok:
            print("[装备拆解] 已跳过：equip_id=%s | UID=%s | 星级=%s | 原因=%s" % (equip_id, uid, rank if rank else "未知", reason))
            continue
        filtered_uids.append(uid)
    clean_uids = filtered_uids
    if not clean_uids:
        gfam_set_last_equip_retire_count(0)
        print("[装备拆解] 过滤后没有可拆解的低星装备。")
        return True
    payload = {"equips": clean_uids}
    print("[装备拆解] 正在提交 %d 件装备进行自动拆解……" % len(clean_uids))
    resp = client.send_request(API_EQUIP_RETIRE, payload)
    if not isinstance(resp, dict):
        resp = {"error_local": "Equip/retire returned non-dict", "raw": str(resp)}
    if resp.get("success") or ("error" not in resp and "error_local" not in resp):
        gfam_set_last_equip_retire_count(len(clean_uids))
        print("[+] 装备拆解完成，实际拆解 %d 件。" % len(clean_uids))
        for uid in clean_uids:
            DROPPED_UID_TO_EQUIP_ID.pop(uid, None)
            DROPPED_UID_TO_EQUIP_RANK.pop(uid, None)
            DROPPED_UID_TO_EQUIP_RAW.pop(uid, None)
        gfam_final_cleanup_mark_retired("equip", equip_uids)
        return True
    print("[-] 装备拆解失败：%s" % str(resp))
    if gfam_is_auth_or_plaintext_error(resp):
        gfam_remember_error(resp, "Equip/retire")
        print("[!] 装备拆解接口返回明确 UID/SIGN 失效。")
        print("[!] 请返回 GFAM 主菜单重新获取 UID/SIGN 后再启动。")
    return False


def perform_deferred_night_recovery():
    return


# v47：运行结束收尾拆解兜底。
# 原则：只处理本次运行期间已经记录到的掉落 UID；不主动全仓库扫描，不额外请求 Index/index。
GFAM_FINAL_CLEANUP_PENDING_GUNS = []
GFAM_FINAL_CLEANUP_PENDING_EQUIPS = []


def gfam_final_cleanup_note_guns(uids):
    try:
        for uid in uids or []:
            try:
                uid = int(uid)
            except Exception:
                continue
            if uid > 0 and uid not in GFAM_FINAL_CLEANUP_PENDING_GUNS:
                GFAM_FINAL_CLEANUP_PENDING_GUNS.append(uid)
    except Exception:
        pass


def gfam_final_cleanup_note_equips(uids):
    try:
        for uid in uids or []:
            try:
                uid = int(uid)
            except Exception:
                continue
            if uid > 0 and uid not in GFAM_FINAL_CLEANUP_PENDING_EQUIPS:
                GFAM_FINAL_CLEANUP_PENDING_EQUIPS.append(uid)
    except Exception:
        pass


def gfam_final_cleanup_mark_retired(kind, uids):
    try:
        target = GFAM_FINAL_CLEANUP_PENDING_EQUIPS if kind == "equip" else GFAM_FINAL_CLEANUP_PENDING_GUNS
        for uid in uids or []:
            try:
                uid = int(uid)
            except Exception:
                continue
            while uid in target:
                target.remove(uid)
    except Exception:
        pass


def gfam_run_final_cleanup(client, label="运行结束"):
    guns = list(dict.fromkeys(GFAM_FINAL_CLEANUP_PENDING_GUNS))
    equips = list(dict.fromkeys(GFAM_FINAL_CLEANUP_PENDING_EQUIPS))
    if not guns and not equips:
        return
    print("[收尾拆解] %s：检测到本次运行仍有未处理掉落，人形 %d / 装备 %d；将尝试最后整理一次。" % (label, len(guns), len(equips)))

    if equips:
        if CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
            ok = retire_equips(client, equips)
            retired_count = 0
            try:
                retired_count = gfam_get_last_equip_retire_count()
            except Exception:
                retired_count = 0
            if ok and retired_count > 0:
                try:
                    gfam_note_storage_recovered_after_retire("equip", retired_count)
                    gfam_recompute_storage_micro_limit_from_cache("equip", reason="运行结束收尾装备拆解成功")
                except Exception:
                    pass
                print("[收尾拆解] 已收尾拆解装备 %d 件。" % retired_count)
            elif ok:
                print("[收尾拆解] 装备遗留已处理，但保护/过滤后实际拆解 0 件。")
            else:
                print("[收尾拆解] 装备遗留拆解失败，已保留在仓库，请手动检查。")
        else:
            print("[收尾拆解] 装备自动拆解已关闭，遗留装备保留在仓库。")
            gfam_final_cleanup_mark_retired("equip", equips)

    if guns:
        retired_count = retire_guns(client, guns)
        if retired_count and retired_count > 0:
            try:
                gfam_note_storage_recovered_after_retire("gun", retired_count)
                gfam_recompute_storage_micro_limit_from_cache("gun", reason="运行结束收尾人形拆解成功")
            except Exception:
                pass
            print("[收尾拆解] 已收尾拆解人形 %d 名。" % retired_count)
        else:
            print("[收尾拆解] 人形遗留经过保护/过滤或拆解失败后未产生实际拆解，请手动检查仓库。")




def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread
    try:
        _farm_worker_impl()
    except Exception:
        stop_macro_flag = True
        stop_micro_flag = True
        worker_mode = None
        current_worker_thread = None
        try:
            RUN_STATS["end_time"] = time.time()
        except Exception:
            pass
        print("\n[异常保护] 运行线程发生未处理异常，已自动终止当前运行，避免异常进程继续执行。")
        print(traceback.format_exc())
        try:
            print_run_summary()
        except Exception:
            pass
        try:
            print_main_menu()
        except Exception:
            pass

def _farm_worker_impl():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread, TEAM_SWITCH_PENDING

    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY 为默认值，请先通过 GFAM 主菜单获取 UID / SIGN。")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    gfam_pre_run_abort_once(client, reason="运行前状态清理")
    if not gfam_refresh_dynamic_micro_limit_before_run(client):
        if gfam_is_night_equip_farm_mode():
            print("[装备仓库] 当前可安全执行的 Micro 上限仍为 0，已取消运行。装备应急拆解未能释放足够装备仓库空位，请先手动整理装备仓库后再试。")
        else:
            print("[仓库] 当前可安全执行的 Micro 上限仍为 0，已取消运行。应急拆解未能释放足够人形仓库空位，请先手动整理人形仓库后再试。")
        worker_mode, current_worker_thread = None, None
        return
    if gfam_storage_micro_blocked():
        if gfam_is_night_equip_farm_mode():
            print("[装备仓库] 当前可安全执行的 Micro 上限仍为 0，已取消运行。请先手动整理装备仓库后再试。")
        else:
            print("[仓库] 当前可安全执行的 Micro 上限仍为 0，已取消运行。请先手动整理人形仓库后再试。")
        worker_mode, current_worker_thread = None, None
        return
    mvp_gen = get_mvp_generator()

    reset_run_stats()
    RUN_STATS["start_time"] = time.time()
    RUN_STATS["fairy_auto_start_snapshot"] = read_fairy_snapshot()
    init_run_target_counts()
    initialize_all_team_progress()

    if CONFIG.get("MODE_NAME") == "team":
        schedule_label = "整队满级后切换" if CONFIG.get("TRAIN_SCHEDULE_MODE") == "full" else "均等练级轮转"
        print("[*] 练级模式已启用，共 %d 个梯队参与轮转。" % len(CAPTURED_TEAM_CONFIGS))
        print("[*] 练级调度：%s" % schedule_label)
        print("[*] 将持续运行到全部梯队满级或你手动停止。")
        reset_training_progress()
        if CAPTURED_TEAM_CONFIGS:
            activate_team_runtime(CAPTURED_TEAM_CONFIGS[0]["team_id"])
    elif CONFIG.get("MODE_NAME") == "smart_epa":
        print("[*] 第6项一键打捞已启用：教练の妙妙小巧思。")
        print("[*] 当前计划：%s。" % smart_epa_plan_type_label())
        print("[*] 计划路线数：%d；当前路线：%d。" % (len(CONFIG.get("SMART_EPA_PLAN", []) or []), int(CONFIG.get("SMART_EPA_INDEX", 0) or 0) + 1))
        if smart_epa_is_equip_plan() or CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
            print("[*] 自动拆解将保护整个计划内的目标 equip_id，并保护全部已确认 EPA 夜战专属装备。")
            print("[*] 目标装备自动上锁：%s" % ("开启" if CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True) else "关闭"))
        else:
            print("[*] 自动拆解将保护整个计划内的目标 gun_id。")
        activate_team_runtime(get_current_team_id())
    else:
        if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
            print("[*] 夜战 EPA 装备打捞模式已启用。")
            if CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
                print("[*] 已启用装备掉落统计、Macro 后严格装备拆解与装备仓库应急恢复。")
            else:
                print("[*] 装备自动拆解与装备仓库应急恢复当前关闭；掉落将保留在仓库。")
            print("[*] 目标装备自动上锁：%s" % ("开启" if CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True) else "关闭"))
        else:
            print("[*] 打捞模式已启用。")
        if CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED"):
            print("[*] 目标达成停机已开启：%s至少各掉落 1 个后停止。" % ("目标装备" if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "目标人形"))
        print("[*] 将持续运行到你手动停止或触发其他停止条件。")
        activate_team_runtime(get_current_team_id())
    print("=== GFL Protocol Auto-Farming Started (EPA) ===")
    macro = 1
    consecutive_failures = 0
    max_consecutive_failures = max(1, int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 10) or 10))
    while True:
        if stop_macro_flag:
            break

        # v46：防止仓库 Micro 上限为 0 时进入空转 Macro。
        # 之前在人形/装备仓库满或本地缓存判定不可运行后，for micro range(1, 0 + 1)
        # 会完全跳过战役，却继续执行 Macro 结算、打印和 macro += 1，表现为“没有打战役也不报错”。
        if CONFIG.get("DYNAMIC_MICRO_BY_STORAGE", True):
            try:
                _macro_limit_now = int(CONFIG.get("MISSIONS_PER_RETIRE", 0) or 0)
            except Exception:
                _macro_limit_now = 0
            if _macro_limit_now <= 0 or gfam_storage_micro_blocked():
                _storage_kind = "equip" if gfam_is_night_equip_farm_mode() else "gun"
                gfam_recompute_storage_micro_limit_from_cache(_storage_kind, reason="Macro 开始前本地缓存复核")
                try:
                    _macro_limit_now = int(CONFIG.get("MISSIONS_PER_RETIRE", 0) or 0)
                except Exception:
                    _macro_limit_now = 0

            if _macro_limit_now <= 0 or gfam_storage_micro_blocked():
                if gfam_is_night_equip_farm_mode():
                    print("[装备仓库] 当前 Micro 上限为 0，先执行装备仓库应急恢复，不进入空转 Macro。")
                    recovered = gfam_force_equip_cleanup_if_storage_tight(client, reason="Macro 开始前装备仓库不足")
                else:
                    print("[仓库] 当前 Micro 上限为 0，先执行人形仓库应急恢复，不进入空转 Macro。")
                    recovered = emergency_retire_guns_from_index(client, reason="Macro 开始前人形仓库不足")
                    if recovered:
                        recovered = gfam_recompute_storage_micro_limit_from_cache("gun", reason="Macro 开始前应急拆解后本地缓存")
                try:
                    _macro_limit_now = int(CONFIG.get("MISSIONS_PER_RETIRE", 0) or 0)
                except Exception:
                    _macro_limit_now = 0
                if (not recovered) or _macro_limit_now <= 0 or gfam_storage_micro_blocked():
                    print("[仓库] 仓库恢复后仍无法安全开始下一轮，已停止运行，避免只增长 Macro 但不进行战役。")
                    stop_macro_flag = True
                    stop_micro_flag = True
                    break

        if CONFIG.get("MODE_NAME") == "team":
            panel_safe_print("=== MACRO %d / 直到全部梯队满级 ===" % macro)
        else:
            panel_safe_print("=== MACRO %d / 直到手动停止或触发停止条件 ===" % macro)

        RUN_STATS["current_macro"] = macro
        RUN_STATS["current_team_no"] = (CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0) + 1) if CONFIG.get("MODE_NAME") == "team" else get_current_team_id()
        RUN_STATS["macro_drop_names"] = []
        RUN_STATS["last_micro_exp_lines"] = []
        batch_guns = []
        batch_equips = []
        night_retire_attempted_after_failure = False
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag:
                break

            RUN_STATS["current_micro"] = micro
            RUN_STATS["current_step"] = 0
            refresh_runtime_panel()
            dropped = farm_mission_epa(client, get_current_team_id(), mvp_gen)

            if dropped is None:
                print("[-] 本轮失败或中止，正在放弃关卡……")
                client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                time.sleep(3)

                if gfam_last_error_is_auth():
                    print("[!] 最近错误明确为 UID/SIGN 失效。")
                    print("[!] 已停止当前模块，请返回 GFAM 主菜单重新获取 UID/SIGN。")
                    gfam_clear_runtime_auth_state()
                    stop_macro_flag = True
                    stop_micro_flag = True
                    break

                consecutive_failures += 1
                print("[异常保护] 当前 Micro 失败，连续失败 %d / %d。" % (consecutive_failures, max_consecutive_failures))
                failure_limit_reached = consecutive_failures >= max_consecutive_failures
                if failure_limit_reached:
                    print("[异常保护] 连续失败已达到上限，但会先执行本次自修复；若自修复成功将重新计数。")

                if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                    if not CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
                        print("[夜战EPA] 当前 Micro 失败；装备自动/应急拆解已关闭，程序将停止以便你检查装备仓库。")
                        print("[夜战EPA] 如果仓库中出现目标装备，请手动拆解该装备并抓包确认真实 equip_id。")
                        stop_macro_flag = True
                        stop_micro_flag = True
                        break
                    print("[夜战EPA] 当前 Micro 失败，尝试装备仓库恢复。")
                    recovered = False
                    if batch_equips:
                        print("[夜战EPA] 先尝试拆解当前 Macro 已记录装备。")
                        recovered = retire_equips(client, batch_equips)
                        if recovered:
                            retired_count = gfam_get_last_equip_retire_count()
                            if retired_count > 0:
                                gfam_note_storage_recovered_after_retire("equip", retired_count)
                                gfam_recompute_storage_micro_limit_from_cache("equip", reason="Micro 失败后装备拆解成功")
                                print("[夜战EPA] 已拆解当前 Macro 装备掉落 %d 件，并已本地更新装备仓库缓存。" % retired_count)
                            else:
                                print("[夜战EPA] 当前 Macro 装备掉落经过保护过滤后实际拆解 0 件，本地缓存不扣减。")
                            batch_equips = []
                    if not recovered:
                        print("[夜战EPA] 当前 Macro 装备不足以恢复，尝试从装备仓库应急拆解。")
                        recovered = emergency_retire_equips_from_index(client, reason="Night EPA Micro Error Before Retry")
                    if not recovered:
                        print("[夜战EPA] 装备仓库恢复失败，停止运行，避免异常循环。")
                        stop_macro_flag = True
                        stop_micro_flag = True
                        break
                    print("[夜战EPA] 装备仓库恢复完成，重试当前 Micro 一次。")
                    retry_result = gfam_retry_mission_after_repair(client, get_current_team_id(), mvp_gen, "夜战EPA")
                    if retry_result is None:
                        client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                        print("[夜战EPA] 当前 Micro 重试后仍失败，停止运行。")
                        stop_macro_flag = True
                        stop_micro_flag = True
                        break
                    consecutive_failures = 0
                    dropped = retry_result
                else:
                    if CONFIG.get("ENABLE_GUN_EXCEPTION_SELF_REPAIR", True):
                        print("[EPA自修复] 当前 Micro 失败，尝试人形应急拆解后重试当前 Micro 一次。")
                        recovered = emergency_retire_guns_from_index(client, reason="EPA Micro Error Before Retry")
                        if recovered:
                            print("[EPA自修复] 人形应急拆解完成，重试当前 Micro。")
                            retry_result = gfam_retry_mission_after_repair(client, get_current_team_id(), mvp_gen, "EPA自修复")
                            if retry_result is None:
                                try:
                                    client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                                except Exception:
                                    pass
                                print("[EPA自修复] 当前 Micro 重试后仍失败，停止运行，避免异常循环。")
                                stop_macro_flag = True
                                stop_micro_flag = True
                                break
                            consecutive_failures = 0
                            dropped = retry_result
                        else:
                            if failure_limit_reached:
                                print("[EPA自修复] 连续失败达到上限且本次未能完成自修复，已自动终止当前运行。")
                                stop_macro_flag = True
                                stop_micro_flag = True
                                break
                            print("[EPA自修复] 人形应急拆解未完成，本次 Micro 跳过，继续观察后续运行。")
                            time.sleep(3)
                            continue
                    else:
                        if failure_limit_reached:
                            print("[Smart自修复] 连续失败达到上限且自修复已关闭，已自动终止当前运行。")
                            stop_macro_flag = True
                            stop_micro_flag = True
                            break
                        continue

            if CONFIG.get("MODE_NAME") == "smart_epa" and smart_epa_current_target_done():
                panel_safe_print(colorize("[教练の妙妙小巧思] 当前路线目标已达成：%s" % get_target_drop_progress_text(), "success"))
                batch_guns.extend(dropped.get("guns", []))
                gfam_final_cleanup_note_guns(dropped.get("guns", []))
                if "batch_equips" not in locals(): batch_equips = []
                batch_equips.extend(dropped.get("equips", []))
                gfam_final_cleanup_note_equips(dropped.get("equips", []))
                # 目标达成会立刻切换下一条路线并结束当前 Macro。这里必须先按
                # 实际掉落扣减本地仓库缓存，再在路线切换时按缓存重新计算 Micro。
                # 否则装备一键打捞可能继续显示/沿用默认 8。
                gfam_note_storage_usage_after_micro(dropped)
                smart_epa_advance_if_needed()
                break

            if consecutive_failures:
                consecutive_failures = 0

            if should_stop_after_each_target_dropped():
                stop_macro_flag = True
                stop_micro_flag = True
                panel_safe_print(colorize("[目标达成] 当前%s已至少各掉落 1 个：%s，程序将安全停止。" % (get_target_type_label(), get_target_drop_progress_text()), "success"))
                break

            batch_guns.extend(dropped.get("guns", []))
            gfam_final_cleanup_note_guns(dropped.get("guns", []))
            if "batch_equips" not in locals():
                batch_equips = []
            new_equips = dropped.get("equips", [])
            batch_equips.extend(new_equips)
            gfam_final_cleanup_note_equips(new_equips)
            storage_enough_for_next_micro = gfam_note_storage_usage_after_micro(dropped)

            night_retire_attempted_after_failure = False
            gfam_adaptive_sleep("micro", 1)
            if not storage_enough_for_next_micro:
                break

            if CONFIG.get("MODE_NAME") == "team" and TEAM_SWITCH_PENDING:
                advance_to_next_training_team()
                break

            if CONFIG.get("MODE_NAME") == "team" and CONFIG.get("TRAIN_SCHEDULE_MODE") == "equal":
                switch_to_next_available_training_team("当前梯队已练级一轮")
                break

        if (stop_micro_flag or stop_macro_flag) and (batch_guns or batch_equips):
            panel_safe_print("[安全停止] 已收到 -q/-Q，将先自动拆解本轮已记录掉落，再结束当前运行。")

        if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
            if not CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
                if batch_equips:
                    print("[夜战EPA] 本轮 Macro 记录到 %d 件装备掉落；装备自动拆解已关闭，已全部保留在仓库。" % len(batch_equips))
                    batch_equips = []
                else:
                    print("[夜战EPA] 本轮 Macro 未记录到装备掉落。装备自动拆解当前关闭。")
            elif batch_equips:
                print("[夜战EPA] 本轮 Macro 记录到 %d 件装备掉落，开始自动装备拆解。" % len(batch_equips))
                ok = retire_equips(client, batch_equips)
                if ok:
                    retired_count = gfam_get_last_equip_retire_count()
                    if retired_count > 0:
                        gfam_note_storage_recovered_after_retire("equip", retired_count)
                        gfam_recompute_storage_micro_limit_from_cache("equip", reason="Macro 后装备拆解成功")
                        print("[夜战EPA] 本轮实际拆解装备 %d 件，已更新本地装备仓库缓存。" % retired_count)
                    else:
                        print("[夜战EPA] 本轮装备经过保护过滤后实际拆解 0 件，本地装备仓库缓存不扣减。")
                    batch_equips = []
                    if not gfam_force_equip_cleanup_if_storage_tight(client, reason="Night EPA Macro After Recorded Drops Storage Tight"):
                        print("[夜战EPA] 记录掉落处理后仓库仍不足且应急拆解失败，停止运行。")
                        stop_macro_flag = True
                        stop_micro_flag = True
                        break
                else:
                    print("[夜战EPA] 本轮装备拆解失败，尝试从仓库执行装备应急拆解。")
                    recovered = emergency_retire_equips_from_index(client, reason="Night EPA Macro Retire Failed")
                    if not recovered:
                        print("[夜战EPA] 装备拆解失败且应急拆解失败，停止运行。")
                        stop_macro_flag = True
                        stop_micro_flag = True
                        break
            else:
                gfam_debug_log("[夜战EPA] 本轮 Macro 未记录到装备掉落；正在检查装备仓库容量是否仍需拆解……")
                if not gfam_force_equip_cleanup_if_storage_tight(client, reason="Night EPA Macro Empty Drop But Storage Tight"):
                    print("[夜战EPA] 装备仓库空间不足且应急拆解失败，停止运行。")
                    stop_macro_flag = True
                    stop_micro_flag = True
                    break
                if not gfam_equip_storage_tight_for_next_run():
                    gfam_debug_log("[夜战EPA] 装备仓库本地缓存仍足够，跳过装备拆解。")
        else:
            retired_count = retire_guns(client, batch_guns, update_cache=True, cache_reason="普通/紧急 Macro 后人形拆解成功")
            if retired_count <= 0 and batch_guns:
                print("[人形仓库缓存] 本轮有人形掉落但没有成功拆解对象，缓存保持不变；受保护目标或拆解失败会导致这种情况。")

        drop_summary = "无"
        if RUN_STATS.get("macro_drop_names"):
            shown = [format_drop_name_for_display(x) for x in RUN_STATS["macro_drop_names"][:8]]
            drop_summary = ", ".join(shown)
            if len(RUN_STATS["macro_drop_names"]) > 8:
                drop_summary += colorize(" ...", "dim")
        elapsed_now = 0
        if RUN_STATS.get("start_time") is not None:
            elapsed_now = time.time() - RUN_STATS["start_time"]
        panel_safe_print("[MACRO %d] 梯队 %s | 掉落：%s | 用时：%s" % (
            macro,
            RUN_STATS.get("current_team_no", 1),
            drop_summary,
            format_duration(elapsed_now),
        ))

        time.sleep(2)
        if stop_micro_flag:
            break

        if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" and not CONFIG.get("ENABLE_EQUIP_AUTO_RETIRE", True):
            print("[装备仓库] 自动拆解关闭，准备进入下一轮 Macro 前重新计算装备仓库空位。")
            if not gfam_refresh_dynamic_micro_limit_before_run(client):
                print("[装备仓库] 当前装备仓库空位不足以继续夜战打捞，已停止运行。")
                print("[装备仓库] 请检查仓库；如果找到目标装备，请手动拆解该装备并抓包确认 equip_id。")
                break

        macro += 1

    gfam_run_final_cleanup(client, label="运行结束前")
    RUN_STATS["end_time"] = time.time()
    panel_safe_print(colorize("\n[*] 本次运行结束。", "success"))
    print_run_summary()
    worker_mode, current_worker_thread = None, None

    # GFAM 模块化版本：运行结束后统一回到当前模块主菜单。
    print_main_menu()


if __name__ == '__main__':
    enable_console_ansi()
    # 从 GFAM 主菜单启动时，必须先套用当前服务器，再沿用 UID/SIGN。
    # 否则非 SOP 服务器会用默认 SOP BASE_URL 请求 Index/index，导致有效 SIGN 被误判为 error:1。
    if launched_from_gfam_main():
        apply_server_selection(get_default_server_from_env())
    _gfam_auth_ready = apply_gfam_auth_from_env()

    if launched_from_gfam_main() and _gfam_auth_ready and CONFIG.get("INDEX_FETCH_READY", False):
        CONFIG["MODE_NAME"] = "smart_epa"
        CONFIG["SMART_EPA_PLAN_MODE"] = True
        CONFIG["SINGLE_GUN_MODE"] = True
        CONFIG["SINGLE_GUN_INDEX"] = 0
        CONFIG["MODE_SELECTED_EARLY"] = True
        CONFIG["TRAIN_TEAM_COUNT"] = 1
        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 1
        reset_captured_team_configs()
        CONFIG["INDEX_FETCH_READY"] = False
        CONFIG["CONFIG_READY_FOR_INDEX"] = True
        print("")
        print("[*] 已检测到 GFAM 主菜单提供的 UID/SIGN。")
        print("[*] 第6项一键打捞配置已保存：固定使用梯队1。")
        print_smart_epa_plan_type_hint()
        print("[*] 请确认游戏停留在指挥官主界面，并确认梯队1已按当前计划配置。")
        print("[*] 输入 -r 生成一键打捞计划并进入运行确认；运行前会自动请求一次 Index/index。")

    print_main_menu()
    while True:
        try:
            cmd = input("GFL-EPA> ").strip()
            if not cmd:
                # 选择流程中部分菜单带有“回车默认”选项。
                # 旧逻辑在这里直接 continue，导致 handle_selection_input() 无法收到空输入，
                # 例如满级停机设置的“回车默认 -keepmax”不会生效。
                if handle_selection_input(cmd):
                    continue
                continue
            cmd_prefix = cmd.split()[0]

            if handle_selection_input(cmd):
                continue

            normalized_cmd_prefix = normalize_menu_input(cmd_prefix)
            cmd_prefix_lower = cmd_prefix.lower()
            one_key_requested = cmd_prefix_lower in ('-go', 'go', '-one', 'one', '-onekey', 'onekey', '一键', '一键打捞')
            if one_key_requested:
                cmd_prefix = '-r'

            if cmd_prefix_lower in ('-m', 'm', '-menu', 'menu', '-stage', 'stage', '-select', 'select'):
                if worker_mode == 'r':
                    print("[!] 当前正在运行，不能切换关卡。请先输入 -q 或 -Q 等待安全停止。")
                    continue
                if not MENU_STATE.get("selection_unlocked", False):
                    print("[!] 当前还未完成登录抓取和 Index/index 解析，请先输入 -r 生成计划。")
                    continue
                reopen_stage_selection_menu()
                continue

            if normalized_cmd_prefix == "-smart":
                CONFIG["MODE_NAME"] = "smart_epa"; CONFIG["SMART_EPA_PLAN_MODE"] = True; CONFIG["SINGLE_GUN_MODE"] = True; CONFIG["SINGLE_GUN_INDEX"] = 0; CONFIG["MODE_SELECTED_EARLY"] = True
                CONFIG["TRAIN_TEAM_COUNT"] = 1; CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 1
                reset_captured_team_configs()
                print("[*] 已预选第6项一键打捞。请继续输入 -r 生成计划；如未获取 UID/SIGN，程序会提示重新抓取。")
                print_smart_epa_plan_type_hint()
                continue

            if cmd_prefix_lower in ("-equip", "equip", "-eq", "eq", "装备", "装备一键", "装备一键打捞", "夜战装备", "夜战装备一键打捞"):
                if worker_mode == 'r':
                    print("[!] 当前正在运行，不能切换计划类型。请先输入 -q 或 -Q 等待安全停止。")
                    continue
                smart_epa_set_plan_type("equip")
                print_main_menu()
                continue

            if cmd_prefix_lower in ("-gun", "gun", "-doll", "doll", "人形", "人形一键", "人形一键打捞", "普通紧急", "普通/紧急"):
                if worker_mode == 'r':
                    print("[!] 当前正在运行，不能切换计划类型。请先输入 -q 或 -Q 等待安全停止。")
                    continue
                smart_epa_set_plan_type("gun")
                print_main_menu()
                continue

            if cmd_prefix in ('-r', 'run') and CONFIG.get("MODE_NAME") == "smart_epa" and not MENU_STATE.get("selection_unlocked", False):
                cmd_prefix = '-a'

            if cmd_prefix == '-a':
                # Phase 3: 已确认第6项配置，并且用户已在游戏内调整好梯队1；此时才请求 Index/index。
                if CONFIG.get("CONFIG_READY_FOR_INDEX", False) and not proxy_instance:
                    if not has_usable_dynamic_keys():
                        CONFIG["CONFIG_READY_FOR_INDEX"] = False
                        CONFIG["INDEX_FETCH_READY"] = False
                        print("[!] UID/SIGN 或动态密钥未配置，本次不请求 Index/index。")
                        print("[*] 将直接进入 UID/SIGN 抓取流程，避免先撞一次 error:1。")
                    else:
                        CONFIG["CONFIG_READY_FOR_INDEX"] = False
                        print("[*] 已确认配置完成，正在请求 Index/index 并生成%s。" % smart_epa_plan_type_label())
                        ok = request_index_and_prepare_configs()
                        if not ok and CONFIG.get("LAST_INDEX_AUTH_ERROR", False):
                            print("[*] 已清理失效的 UID/SIGN 状态，将重新进入抓取流程。")
                            gfam_clear_runtime_auth_state()
                            CONFIG["CONFIG_READY_FOR_INDEX"] = False
                            CONFIG["INDEX_FETCH_READY"] = False
                        else:
                            continue

                # Phase 1: standalone fallback only. GFAM 主菜单已统一获取 UID/SIGN，
                # 从 GFAM 启动时本模块不再启动代理。
                if not CONFIG.get("INDEX_FETCH_READY", False) and not proxy_instance:
                    if launched_from_gfam_main():
                        print("[!] UID/SIGN 未就绪，本模块不会自行启动代理。")
                        print("[*] 请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN 后，再进入第6项一键打捞。")
                        continue
                    print_server_menu()
                    server_cmd = input("GFL-SMART(服务器, 默认%s)> " % get_default_server_from_env()).strip()
                    if not apply_server_selection(server_cmd):
                        print("[!] 服务器选择无效，请重新输入 -r 后选择服务器。")
                        continue

                    print("[*] 已完成服务器选择。")
                    print("[*] 单独运行模式：现在启动代理抓取 UID / SIGN。")
                    print("[*] 第6项一键打捞计划会在 UID / SIGN 就绪并确认配置后生成。")

                    reset_auto_capture_state()
                    CONFIG["AUTO_MONITOR_MODE"] = True
                    CONFIG["INDEX_FETCH_READY"] = False
                    CONFIG["CONFIG_READY_FOR_INDEX"] = False
                    proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                    proxy_instance.start()
                    set_windows_proxy(True, "127.0.0.1:%d" % CONFIG['PROXY_PORT'])
                    worker_mode = 'a'
                    print("[*] 一体化代理已启动，端口 %d。Windows 代理已设置。" % CONFIG['PROXY_PORT'])
                    print("[*] 当前服务器：%s" % CONFIG.get("SERVER_NAME", "SOP"))
                    print("[*] 请在游戏内登录，程序会先自动获取 UID / SIGN。")
                    print("[*] 获取成功后，请等待游戏完全进入指挥官主界面。")
                    print("[*] 然后再次输入 -r，确认第6项配置并生成计划。")
                    continue

                # Phase 2: UID/SIGN 已抓取；先停止代理并确认第6项配置，暂不请求 Index/index。
                if CONFIG.get("INDEX_FETCH_READY", False):
                    if proxy_instance:
                        print("[*] UID/SIGN 已获取，正在停止代理……")
                        stop_proxy_instance()
                        gfam_adaptive_sleep("micro", 1)
                    CONFIG["AUTO_MONITOR_MODE"] = False
                    CONFIG["INDEX_FETCH_READY"] = False
                    if not CONFIG.get("MODE_SELECTED_EARLY"):
                        CONFIG["MODE_NAME"] = "smart_epa"
                        CONFIG["SMART_EPA_PLAN_MODE"] = True
                        CONFIG["SINGLE_GUN_MODE"] = True
                        CONFIG["SINGLE_GUN_INDEX"] = 0
                        CONFIG["MODE_SELECTED_EARLY"] = True
                        CONFIG["TRAIN_TEAM_COUNT"] = 1
                        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 1
                        reset_captured_team_configs()
                    CONFIG["CONFIG_READY_FOR_INDEX"] = True
                    print("")
                    print("[*] 第6项一键打捞配置已保存：固定使用梯队1。")
                    print_smart_epa_plan_type_hint()
                    print("[*] 请确认游戏停留在指挥官主界面，并确保梯队1符合当前一键打捞计划。")
                    print("[*] 调整完成并停留在指挥官主界面后，再次输入 -r。")
                    print("[*] 再次输入 -r 生成一键打捞计划并进入运行确认。")
                    continue

                if proxy_instance:
                    print("[!] 代理已在运行！ 请先完成登录并等待 UID/SIGN 抓取。")
                    continue

                print("[!] 尚未抓取到有效 UID/SIGN，请返回 GFAM 主菜单获取 UID/SIGN，或重新输入 -r 按提示处理。")

            elif cmd_prefix == '-r':
                if MENU_STATE["selection_unlocked"]:
                    if CONFIG["SELECTED_DIFFICULTY"] is None or CONFIG["SELECTED_STAGE"] is None or CONFIG["SELECTED_TARGET_LABEL"] is None:
                        print("[!] 请先完成打捞菜单选择。")
                        continue
                    if MENU_STATE["awaiting_run_confirm"] or MENU_STATE["awaiting_stop_on_max"] or MENU_STATE["awaiting_target_drop_stop"] or MENU_STATE["awaiting_equip_auto_lock"] or MENU_STATE.get("awaiting_filter_protection", False):
                        if one_key_requested:
                            # -go 应在第一次选择目标后的任意运行前设置阶段都可用，
                            # 不应只出现在运行结束后的 EPA MENU 里。
                            MENU_STATE["awaiting_filter_protection"] = False
                            MENU_STATE["awaiting_stop_on_max"] = False
                            MENU_STATE["awaiting_target_drop_stop"] = False
                            MENU_STATE["awaiting_equip_auto_lock"] = False
                            MENU_STATE["awaiting_run_confirm"] = False
                            # -go 是“使用当前/默认选项直接开始”。默认值必须与菜单提示保持一致：
                            # 满级停机默认 -keepmax（关闭），目标达成停机默认 -keepdrop（关闭）。
                            # 避免 GHA / 本地快捷运行时因为 CONFIG 初始值或旧状态而误触发满级停机。
                            CONFIG["STOP_ON_MAX_LEVEL"] = False
                            CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = False
                            if CONFIG.get("MODE_NAME") == "team":
                                CONFIG["ENABLE_FILTER_PROTECTION"] = CONFIG.get("ENABLE_FILTER_PROTECTION", True)
                            if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                                CONFIG["AUTO_LOCK_TARGET_EQUIP"] = CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True)
                            print("[一键打捞] 已使用当前/默认选项直接开始：满级停机=%s，目标达成停机=%s，目标装备自动上锁=%s。" % (
                                "开启" if CONFIG.get("STOP_ON_MAX_LEVEL") else "关闭",
                                "开启" if CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED") else "关闭",
                                "开启" if CONFIG.get("AUTO_LOCK_TARGET_EQUIP", True) else "关闭",
                            ))
                        else:
                            print("[!] 请先完成满级停机、目标达成停机/装备上锁设置与运行前确认，或输入 -go 一键打捞。")
                            continue
                    if CONFIG.get("MODE_NAME") == "team" and not CAPTURED_TEAM_CONFIGS:
                        print("[!] 练级模式尚未抓取到有效梯队配置。请先输入 -r 生成计划。")
                        continue

                if worker_mode == 'c' and proxy_instance:
                    print("[*] Stopping Proxy to begin farming...")
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    proxy_instance = None
                    gfam_adaptive_sleep("micro", 1)

                stop_macro_flag, stop_micro_flag = False, False
                worker_mode = 'r'
                current_worker_thread = threading.Thread(target=farm_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()

            elif cmd_prefix == '-q':
                stop_macro_flag = True
                print("[*] 将在当前 MACRO 批次结束后停止……")
            elif cmd_prefix == '-Q':
                stop_micro_flag = True
                print("[*] 将在当前 MICRO 轮次结束后停止……")
            elif cmd_prefix == '-s':
                if proxy_instance:
                    CONFIG["AUTO_MONITOR_MODE"] = False
                    stop_proxy_instance()
                    print("[*] 代理已安全停止。")
                else:
                    print("[!] 代理未在运行。")
            elif cmd_prefix == '-E':
                if proxy_instance:
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    print("[*] 已安全退出，Windows 代理已恢复。")
                else:
                    print("[*] 已安全退出，未启动本模块代理。")
                CONFIG["AUTO_MONITOR_MODE"] = False
                stop_macro_flag, stop_micro_flag = True, True
                sys.exit(0)
            else:
                if MENU_STATE["selection_unlocked"]:
                    if MENU_STATE["difficulty"] is None:
                        print("[!] 无效输入，请输入：普通 / 紧急 / 夜战，也可输入：p / j / y")
                    elif MENU_STATE["stage"] is None:
                        print("[!] 无效输入，请输入对应关卡名称，例如：A-10，也可输入 a10，或输入 -back / b 返回难度菜单")
                    elif MENU_STATE["awaiting_filter_protection"]:
                        print("[!] 无效输入，请输入 -protecton / -protectoff，或 on / off，或输入 -back / b 返回上一级菜单")
                    elif MENU_STATE["awaiting_stop_on_max"]:
                        print("[!] 无效输入，请输入 -stopmax / -keepmax，或 sm / km，或输入 -back / b 返回上一级菜单")
                    elif MENU_STATE["awaiting_run_confirm"]:
                        print("[!] 无效输入，请输入 -y 确认运行，或输入 -back 返回上一级菜单")
                    elif MENU_STATE["stage"] is not None and get_stage_data(MENU_STATE["difficulty"], MENU_STATE["stage"]):
                        opt_keys = list(get_stage_options(MENU_STATE["difficulty"], MENU_STATE["stage"]).keys())
                        print("[!] 无效输入，请输入 %s，也可直接输入数字 1/2/3...，或输入 -back / b 返回上一级菜单" % " / ".join(opt_keys))
                    else:
                        print("[!] 当前菜单暂未实现。")
                else:
                    print("[!] 未知命令: %s" % cmd)

        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")
