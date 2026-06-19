# -*- coding: utf-8 -*-
# ===== GFAM project-local dependency loader =====
# 优先加载项目内 ZIRC submodule 的 src/core，避免依赖 PyPI 或系统环境里的旧版本。
import os as _gfam_os
import sys as _gfam_sys
_gfam_root = _gfam_os.path.abspath(_gfam_os.path.join(_gfam_os.path.dirname(__file__), ".."))
_gfam_zirc_core = _gfam_os.path.join(_gfam_root, "libs", "ZIRC", "src", "core")
if _gfam_zirc_core not in _gfam_sys.path:
    _gfam_sys.path.insert(0, _gfam_zirc_core)
# ===============================================

"""GFAM 灰域自动彩蛋模块。

基于用户提供的 greyzone_halloween.py 接入 GFAM 主菜单：
- 沿用主菜单已经抓取的 UID/SIGN，不再启动代理。
- 新增灰域彩蛋专用接口 BuildingSkillPerformOnDeath。
- 保留原始 580001~580006 路线与彩蛋点数解析。
- 运行结束只收尾拆解本次运行记录到、但未成功拆解的人形 UID；不扫仓库，不请求 Index/index。
"""

import os
import sys
import time
import json
import threading
import traceback
from gflzirc import (
    GFLClient,
    SERVERS, DEFAULT_SIGN,
    API_DAILY_RESET_MAP, API_INDEX_INDEX, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_ALLY_MYSIDE_MOVE,
    API_MISSION_END_TURN, API_MISSION_START_ENEMY_TURN,
    API_MISSION_END_ENEMY_TURN, API_MISSION_START_TURN,
    API_MISSION_ABORT, API_GUN_RETIRE, API_MISSION_BATTLE_FINISH,
    API_MISSION_BUILDING_SKILL_PERFORM_ON_DEATH,
)

try:
    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()
except Exception:
    pass

try:
    from gfam_common import gfam_debug_log, gfam_debug_enabled
except Exception:
    def gfam_debug_log(message):
        return None
    def gfam_debug_enabled():
        return False

try:
    from gfam_fairy_stats import (
        read_fairy_snapshot,
        fairy_runtime_status_line,
        print_fairy_summary,
        update_fairy_cache_from_index_payload,
    )
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
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "SERVER_NAME": "M4A1",
    "BASE_URL": SERVERS.get("M4A1"),
    # 0：限时免费；1：探查点数；2：四项。默认沿用原脚本四项。
    "TICKET_TYPE": 2,
    # 默认占位设备号，避免用户版包内写入真实设备信息。
    "USER_DEVICE": "1145141919810",
    "RESET_DIFFICULTY": 3,
    "MAX_CONSECUTIVE_FAILURES": 8,
    "RESET_RETRY_DELAY": 0.2,
    "AFTER_MISSION_DELAY": 1.0,
    # 正式运行前先尝试 abort 灰域旧关卡，避免上次异常后卡在灰域关导致 startMission/code3。
    "ABORT_BEFORE_RUN": True,
    # 限时活动免费模式：服务器活动期间灰域彩蛋不消耗探查许可证/四项资源。
    # 该开关只影响本地缓存扣减与仪表盘显示；实际是否消耗仍由服务器活动规则决定。
    "FREE_EVENT_MODE": str(os.environ.get("GFAM_GREYZONE_FREE_EVENT") or "").strip().lower() in ("1", "true", "yes", "on", "free"),
}
if CONFIG.get("FREE_EVENT_MODE"):
    # 限时免费活动模式下，进入灰域彩蛋时 daily_param.ticket_type 应传 0。
    CONFIG["TICKET_TYPE"] = 0

# ==========================================
# GreyZone Static Data
# ==========================================
from gfam_greyzone_data import MISSION_CONFIGS, GREYZONE_RESPAWN_MAP


# ==========================================
# Global State
# ==========================================
current_worker_thread = None
worker_mode = None
stop_macro_flag = False
total_halloween_points = 0
run_start_time = 0
macro_count = 0
# 本次运行按“运行前一次 Index + 本地推算”维护：
# - run_completed_rounds：本次运行跨过 6000 积分阈值的次数。
# - run_entry_count：本次运行实际进入彩蛋关次数，用于本地扣减票券/四项。
run_completed_rounds = 0
run_entry_count = 0
run_ticket_cost = 0
run_resource_cost = {"mp": 0, "ammo": 0, "mre": 0, "part": 0}
fairy_auto_start_snapshot = {}
pending_gun_uids = []
pending_gun_uid_set = set()
pending_lock = threading.Lock()

status_lock = threading.Lock()
last_status_print_time = 0.0
runtime_panel_active = False
runtime_recent_logs = []
runtime_recent_logs_max = 12
runtime_panel_min_interval = 0.75
run_status = {
    "running": False,
    "stop_requested": False,
    "phase": "待机",
    "reset_attempts": 0,
    "consecutive_failures": 0,
    "mission_id": None,
    "map_spot_id": None,
    "mission_type": "-",
    "current_step": 0,
    "total_steps": 0,
    "current_from": None,
    "current_to": None,
    "battle_done": 0,
    "battle_total": 0,
    "last_points": 0,
    "last_drops": [],
}

# 灰域积分缓存：正式运行前请求一次 Index/index 写入基准，运行中只按服务器动作结果做本地推算。
CACHE_DIR = os.path.join(_gfam_root, "cache")
GREYZONE_CACHE_PATH = os.path.join(CACHE_DIR, "greyzone_halloween_cache.json")
# 已确认：彩蛋点数道具为 10736。
# 已根据用户提供的 Index/index 与游戏内数量确认：探查许可证 item_id 为 10702。
# 10735 等相邻道具不是探查许可证，不能再作为候选；如后续服端变更，可用环境变量覆盖。
#   set GFAM_GREYZONE_TICKET_ITEM_IDS=真实item_id
GREYZONE_POINT_ITEM_IDS = (10736,)
DEFAULT_GREYZONE_TICKET_ITEM_IDS = (10702,)
GREYZONE_TICKET_SANITY_MAX = int(os.environ.get("GFAM_GREYZONE_TICKET_SANITY_MAX") or "50000")
greyzone_cache_lock = threading.RLock()
greyzone_progress_cache = {
    "server": "M4A1",
    "ticket_type": 2,
    "current_points": None,   # 当前轮进度，范围通常为 0~5999
    "current_rounds": None,   # 当前官方轮次/已完成轮次，来自运行前 Index；运行中按本地跨轮推算递增。
    "ticket1": None,          # 探查票券数量。四项模式下若探查票券 >=6，服务器会优先消耗探查票券。
    "ticket2": None,          # 历史兼容字段：当前逻辑不再显示“资源票券”，四项模式主要扣减 resources。
    "resources": {"mp": None, "ammo": None, "mre": None, "part": None},
    "source": "未缓存",
    "updated_at": 0,
}

SERVER_KEY_ALIASES = {
    "SOP": ["SOP"],
    "RO635": ["RO635"],
    "M4A1": ["M4A1"],
    "M16": ["M16"],
    "AR-15": ["AR-15", "AR15"],
}


def normalize_server_name(value):
    value = str(value or "M4A1").strip().upper().replace("_", "-")
    if value == "AR15":
        value = "AR-15"
    if value in SERVER_KEY_ALIASES:
        return value
    return "M4A1"


def apply_gfam_selected_server():
    server = normalize_server_name(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "M4A1")
    for key in SERVER_KEY_ALIASES.get(server, [server]):
        if key in SERVERS:
            CONFIG["SERVER_NAME"] = server
            CONFIG["BASE_URL"] = SERVERS[key]
            print("[+] 已选择服务器：%s" % server)
            return True
    print("[!] 当前 gflzirc 未找到服务器配置：%s" % server)
    print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
    return False


def apply_gfam_auth_from_env():
    uid = str(os.environ.get("GFAM_USER_UID") or "").strip()
    sign = str(os.environ.get("GFAM_SIGN_KEY") or "").strip()
    if uid and sign and sign != DEFAULT_SIGN:
        CONFIG["USER_UID"] = uid
        CONFIG["SIGN_KEY"] = sign
        print("[+] 已沿用 GFAM 主菜单获取的 UID/SIGN。")
        return True
    return False


def greyzone_free_event_enabled():
    return bool(CONFIG.get("FREE_EVENT_MODE"))


def current_ticket_type(default=2):
    """读取当前灰域票券类型。0=限时免费，1=探查点数，2=四项资源。"""
    try:
        val = CONFIG.get("TICKET_TYPE", default)
        if val is None or str(val).strip() == "":
            return default
        return int(val)
    except Exception:
        return default


def free_event_label():
    return "开启" if greyzone_free_event_enabled() else "关闭"


def ticket_type_label():
    mode = current_ticket_type()
    if mode == 0 or greyzone_free_event_enabled():
        return "活动特殊"
    if mode == 1:
        return "探查点数"
    return "四项资源"


def _safe_int(value, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return default
        return int(float(text))
    except Exception:
        return default


def _safe_ticket_count(value):
    """探查许可证数量的安全过滤。

    旧版曾用宽松字段名把非票券字段误识别成几十万的票券数量；这里统一过滤。
    正常探查许可证数量一般远低于该上限，若未来确实超过，可用环境变量
    GFAM_GREYZONE_TICKET_SANITY_MAX 调整。
    """
    val = _safe_int(value, None)
    if val is None:
        return None
    if val < 0:
        return None
    if GREYZONE_TICKET_SANITY_MAX > 0 and val > GREYZONE_TICKET_SANITY_MAX:
        return None
    return val



def resolve_server_ticket_type_for_entry():
    """返回本次 startMission 应提交给服务器的 ticket_type。

    GFAM 菜单里的“四项资源”是用户选择的消耗策略；灰域实际进入彩蛋关时，
    如果本地缓存显示探查许可证不少于 6 张，服务器侧也应优先用探查许可证
    进入，避免出现本地按票券扣减、请求却仍传四项模式导致 startMission
    返回 error:2 的情况。
    """
    mode = current_ticket_type()
    if greyzone_free_event_enabled() or mode == 0:
        return 0
    if mode == 1:
        return 1
    ticket_val = None
    try:
        with greyzone_cache_lock:
            ticket_val = _safe_ticket_count(greyzone_progress_cache.get("ticket1"))
    except Exception:
        ticket_val = None
    if ticket_val is not None and int(ticket_val) >= 6:
        return 1
    return 2


def is_recoverable_startmission_error(resp):
    """startMission 返回 plaintext error:2 时，按当前灰域入口临时失效处理。

    这类响应可能出现在 resetMap 发现彩蛋后、真正 startMission 前，
    直接停止整轮会让模块看起来异常。更稳妥的做法是放弃当前候选，
    继续 resetMap/尝试下一个候选。
    """
    if not isinstance(resp, dict):
        return False
    values = [resp.get("error"), resp.get("raw"), resp.get("raw_preview")]
    for value in values:
        text = str(value or "").strip().lower().replace(" ", "")
        if text in ("2", "error:2", "error=2"):
            return True
    return False

def _cache_key(server=None, ticket_type=None):
    # 灰域积分、探查票券与四项资源是服务器维度数据，不应按当前选择的票券类型拆成两份缓存。
    # 兼容旧版缓存时会额外回退读取 "服务器:1" / "服务器:2"。
    return "%s" % (server or CONFIG.get("SERVER_NAME", "M4A1"))


def _normalize_progress(points, rounds=None):
    points = _safe_int(points, None)
    rounds = _safe_int(rounds, None)
    if points is None:
        return None, rounds
    if points < 0:
        points = 0
    if points >= 6000:
        auto_rounds, points = divmod(points, 6000)
        rounds = max(rounds or 0, auto_rounds)
    if rounds is not None and rounds < 0:
        rounds = 0
    return points, rounds


def load_greyzone_cache():
    key = _cache_key()
    with greyzone_cache_lock:
        greyzone_progress_cache.update({
            "server": CONFIG.get("SERVER_NAME", "M4A1"),
            "ticket_type": int(CONFIG.get("TICKET_TYPE", 2) or 2),
            "current_points": None,
            "current_rounds": None,
            "ticket1": None,
            "ticket2": None,
            "resources": {"mp": None, "ammo": None, "mre": None, "part": None},
            "source": "未缓存",
            "updated_at": 0,
        })
        try:
            if not os.path.exists(GREYZONE_CACHE_PATH):
                return False
            with open(GREYZONE_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            entry = data.get(key) if isinstance(data, dict) else None
            # 兼容 v52 之前按 ticket_type 分开的旧缓存键：M4A1:2 / M4A1:1
            if not isinstance(entry, dict) and isinstance(data, dict):
                server = CONFIG.get("SERVER_NAME", "M4A1")
                entry = data.get("%s:2" % server) or data.get("%s:1" % server)
            if not isinstance(entry, dict):
                return False
            points, rounds = _normalize_progress(entry.get("current_points"), entry.get("current_rounds"))
            resources = entry.get("resources") if isinstance(entry.get("resources"), dict) else {}
            greyzone_progress_cache.update({
                "server": CONFIG.get("SERVER_NAME", "M4A1"),
                "ticket_type": int(CONFIG.get("TICKET_TYPE", 2) or 2),
                "current_points": points,
                "current_rounds": rounds,
                "ticket1": _safe_ticket_count(entry.get("ticket1")),
                "ticket2": _safe_ticket_count(entry.get("ticket2")),
                "resources": {
                    "mp": _safe_int(resources.get("mp"), None),
                    "ammo": _safe_int(resources.get("ammo"), None),
                    "mre": _safe_int(resources.get("mre"), None),
                    "part": _safe_int(resources.get("part"), None),
                },
                "source": entry.get("source") or "本地缓存",
                "updated_at": _safe_int(entry.get("updated_at"), 0) or 0,
            })
            return points is not None or rounds is not None
        except Exception as exc:
            gfam_debug_log("灰域积分缓存读取失败：%s" % exc)
            return False


def save_greyzone_cache():
    key = _cache_key()
    with greyzone_cache_lock:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            data = {}
            if os.path.exists(GREYZONE_CACHE_PATH):
                try:
                    with open(GREYZONE_CACHE_PATH, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    if isinstance(old, dict):
                        data.update(old)
                except Exception:
                    data = {}
            data[key] = {
                "server": greyzone_progress_cache.get("server"),
                "ticket_type": greyzone_progress_cache.get("ticket_type"),
                "current_points": greyzone_progress_cache.get("current_points"),
                "current_rounds": greyzone_progress_cache.get("current_rounds"),
                "ticket1": greyzone_progress_cache.get("ticket1"),
                "ticket2": greyzone_progress_cache.get("ticket2"),
                "resources": greyzone_progress_cache.get("resources") or {},
                "source": greyzone_progress_cache.get("source"),
                "updated_at": greyzone_progress_cache.get("updated_at") or int(time.time()),
            }
            with open(GREYZONE_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            gfam_debug_log("灰域积分缓存写入失败：%s" % exc)
            return False


def get_greyzone_cache_snapshot():
    with greyzone_cache_lock:
        return dict(greyzone_progress_cache)


def _direct_lookup_int(container, keys):
    if not isinstance(container, dict):
        return None
    lower_map = {str(k).lower(): v for k, v in container.items()}
    for key in keys:
        if key in container:
            value = _safe_int(container.get(key), None)
            if value is not None:
                return value
        lk = str(key).lower()
        if lk in lower_map:
            value = _safe_int(lower_map.get(lk), None)
            if value is not None:
                return value
    return None


def _find_item_10736(obj, depth=0):
    # Index/item_with_user_info 常见格式是 [{"item_id": "10736", "number": "296"}]。
    if depth == 0:
        val = _find_item_count_by_ids(obj, GREYZONE_POINT_ITEM_IDS)
        if val is not None:
            return val
    if depth > 5:
        return None
    if isinstance(obj, dict):
        for key in ("10736", 10736, "item_10736", "halloween_point_item"):
            if key in obj:
                value = _safe_int(obj.get(key), None)
                if value is not None:
                    return value
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("item", "items", "user_item", "user_items", "mission_type5_drop", "type5_drop", "daily_item"):
                found = _find_item_10736(v, depth + 1)
                if found is not None:
                    return found
        for v in obj.values():
            found = _find_item_10736(v, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj[:80]:
            found = _find_item_10736(item, depth + 1)
            if found is not None:
                return found
    return None


def _parse_item_id_list_from_env():
    text = str(os.environ.get("GFAM_GREYZONE_TICKET_ITEM_IDS") or "").strip()
    result = []
    if text:
        for part in re.split(r"[,;，；\s]+", text):
            if not part:
                continue
            val = _safe_int(part, None)
            if val is not None and val not in result:
                result.append(val)
    if not result:
        result.extend(DEFAULT_GREYZONE_TICKET_ITEM_IDS)
    return tuple(result)


def _iter_item_entries(obj, depth=0, max_depth=6):
    """遍历 Index/item_with_user_info 这类道具列表，兼容 {item_id, number} 与嵌套 item 容器。"""
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        keys_lower = {str(k).lower() for k in obj.keys()}
        if keys_lower.intersection({"item_id", "itemid", "itemid", "id"}) and keys_lower.intersection({"number", "num", "count", "amount", "value"}):
            yield obj
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("item_with_user_info", "item", "items", "user_item", "user_items", "daily_item", "daily_items", "material", "materials") or isinstance(v, (dict, list)):
                yield from _iter_item_entries(v, depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj[:2000]:
            yield from _iter_item_entries(item, depth + 1, max_depth)


def _entry_item_id(entry):
    if not isinstance(entry, dict):
        return None
    for key in ("item_id", "itemId", "itemid", "id"):
        if key in entry:
            val = _safe_int(entry.get(key), None)
            if val is not None:
                return val
    return None


def _entry_item_count(entry):
    if not isinstance(entry, dict):
        return None
    for key in ("number", "num", "count", "amount", "value"):
        if key in entry:
            val = _safe_int(entry.get(key), None)
            if val is not None:
                return val
    return None


def _find_item_count_by_ids(payload, item_ids):
    ids = set(_safe_int(x, None) for x in (item_ids or []) if _safe_int(x, None) is not None)
    if not ids:
        return None
    # 先兼容 {"10736": 296} 这种字典形式。
    if isinstance(payload, dict):
        for item_id in ids:
            for key in (str(item_id), item_id, "item_%s" % item_id):
                if key in payload:
                    val = _safe_int(payload.get(key), None)
                    if val is not None:
                        return val
    total = None
    for entry in _iter_item_entries(payload):
        item_id = _entry_item_id(entry)
        if item_id in ids:
            count = _entry_item_count(entry)
            if count is not None:
                total = int(total or 0) + int(count)
    return total


def _iter_dicts(obj, depth=0, max_depth=6):
    """宽松遍历 Index 响应中的 dict，用于兼容不同服/不同字段名。"""
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value, depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj[:200]:
            yield from _iter_dicts(item, depth + 1, max_depth)


def extract_basic_resources_from_payload(payload):
    """从运行前 Index/index 中读取四项基础资源。"""
    resources = {"mp": None, "ammo": None, "mre": None, "part": None}
    if not isinstance(payload, dict):
        return resources
    user_info = payload.get("user_info") if isinstance(payload.get("user_info"), dict) else None
    roots = [user_info] if user_info else []
    roots.append(payload)
    key_alias = {
        "mp": ("mp", "manpower", "man_power", "human", "human_resource"),
        "ammo": ("ammo", "ammunition", "bullet"),
        "mre": ("mre", "ration", "rations", "food"),
        "part": ("part", "parts", "component", "components"),
    }
    for root in roots:
        if not isinstance(root, dict):
            continue
        for key, aliases in key_alias.items():
            if resources[key] is None:
                resources[key] = _direct_lookup_int(root, aliases)
    return resources


def extract_ticket_counts_from_payload(payload):
    """从 Index/index 中解析探查许可证数量。

    v59 之前这里为了兼容过宽，会扫描所有包含 ticket/daily/grey 的字段，
    结果可能把非探查许可证字段误识别成几十万的票券数量。v61 已确认探查许可证 item_id=10702：
    1. 优先读取 item_id=10702，或读取环境变量指定的显式 item_id 候选；
    2. 所有结果都会经过安全上限过滤；
    3. 解析不到时显示未知，不再用宽松字段猜测。
    """
    counts = {"ticket1": None, "ticket2": None}
    if not isinstance(payload, dict):
        return counts

    # 1) 显式 item_id：优先使用已确认的 10702；环境变量可覆盖/追加候选。
    ticket_item_ids = _parse_item_id_list_from_env()
    val = _find_item_count_by_ids(payload, ticket_item_ids)
    val = _safe_ticket_count(val)
    if val is not None:
        counts["ticket1"] = val
        return counts

    # 2) 如果 Index 项目中带名称字段，则按“探查许可证/探查許可證/探索许可证”等名称识别。
    name_keys = ("name", "item_name", "title", "cn_name", "zh_name", "description", "desc")
    name_tokens = ("探查许可证", "探查許可證", "探查许可", "探查許可", "探索许可证", "探索許可證", "grayzone", "greyzone")
    for entry in _iter_item_entries(payload, max_depth=7):
        if not isinstance(entry, dict):
            continue
        names = []
        for key in name_keys:
            if key in entry and entry.get(key) is not None:
                names.append(str(entry.get(key)))
        joined = " ".join(names)
        if joined and any(tok.lower() in joined.lower() for tok in name_tokens):
            cnt = _safe_ticket_count(_entry_item_count(entry))
            if cnt is not None:
                counts["ticket1"] = cnt
                return counts

    # 3) 不再宽松猜测 ticket_num/daily_ticket 等字段，避免显示明显错误数据。
    return counts

def format_optional_int(value):
    value = _safe_int(value, None)
    return "-" if value is None else str(value)


def format_resources(resources):
    resources = resources if isinstance(resources, dict) else {}
    return "人力 %s / 弹药 %s / 口粮 %s / 零件 %s" % (
        format_optional_int(resources.get("mp")),
        format_optional_int(resources.get("ammo")),
        format_optional_int(resources.get("mre")),
        format_optional_int(resources.get("part")),
    )


def format_resource_cost(cost):
    cost = cost if isinstance(cost, dict) else {}
    return "人力 -%d / 弹药 -%d / 口粮 -%d / 零件 -%d" % (
        int(cost.get("mp", 0) or 0),
        int(cost.get("ammo", 0) or 0),
        int(cost.get("mre", 0) or 0),
        int(cost.get("part", 0) or 0),
    )


def extract_greyzone_progress_from_payload(payload):
    """从 resetMap/Index 类响应中尽量解析当前灰域积分与轮次。

    不同服务端字段名可能不一致，因此这里只做保守解析：优先读取日常状态、
    灰域状态和道具 10736；解析不到时返回 (None, None)。
    """
    if not isinstance(payload, dict):
        return None, None
    roots = []
    for key in (
        "daily_status_with_user_info", "daily_status", "daily", "greyzone", "grey_zone",
        "grayzone", "gray_zone", "halloween", "halloween_info", "user_info"
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            roots.append(value)
    roots.append(payload)

    point_keys = (
        "halloween_points", "halloween_point", "current_halloween_points", "current_halloween_point",
        "greyzone_points", "grey_zone_points", "grayzone_points", "gray_zone_points",
        "event_points", "event_point", "daily_points", "daily_point",
        "current_points", "current_point", "point", "points", "score", "current_score",
    )
    round_keys = (
        "halloween_round", "halloween_rounds", "current_halloween_round", "current_halloween_rounds",
        "greyzone_round", "greyzone_rounds", "grey_zone_round", "grey_zone_rounds",
        "grayzone_round", "grayzone_rounds", "round", "rounds", "round_num", "current_round",
        "current_rounds", "finish_round", "finish_rounds", "completed_round", "completed_rounds",
    )
    points = None
    rounds = None
    for root in roots:
        if points is None:
            points = _direct_lookup_int(root, point_keys)
        if rounds is None:
            rounds = _direct_lookup_int(root, round_keys)
        if points is not None and rounds is not None:
            break
    if points is None:
        points = _find_item_10736(payload)
    points, rounds = _normalize_progress(points, rounds)
    if points is not None and rounds is None:
        # Index 不一定提供“当前轮次”字段；至少保证运行基准可显示为 0 轮起算。
        rounds = 0
    return points, rounds


def update_greyzone_cache_from_payload(payload, source="resetMap"):
    points, rounds = extract_greyzone_progress_from_payload(payload)
    if points is None and rounds is None:
        return False
    now = int(time.time())
    with greyzone_cache_lock:
        greyzone_progress_cache.update({
            "server": CONFIG.get("SERVER_NAME", "M4A1"),
            "ticket_type": int(CONFIG.get("TICKET_TYPE", 2) or 2),
            "source": source,
            "updated_at": now,
        })
        if points is not None:
            greyzone_progress_cache["current_points"] = points
        if rounds is not None:
            greyzone_progress_cache["current_rounds"] = rounds
    save_greyzone_cache()
    return True


def update_greyzone_cache_from_index_payload(payload, source="运行前 Index/index"):
    """正式运行前唯一一次 Index 基准写入。"""
    points, rounds = extract_greyzone_progress_from_payload(payload)
    tickets = extract_ticket_counts_from_payload(payload)
    resources = extract_basic_resources_from_payload(payload)
    parsed_any = (
        points is not None or rounds is not None or
        tickets.get("ticket1") is not None or tickets.get("ticket2") is not None or
        any(v is not None for v in resources.values())
    )
    now = int(time.time())
    with greyzone_cache_lock:
        greyzone_progress_cache.update({
            "server": CONFIG.get("SERVER_NAME", "M4A1"),
            "ticket_type": int(CONFIG.get("TICKET_TYPE", 2) or 2),
            "source": source,
            "updated_at": now,
        })
        if points is not None:
            greyzone_progress_cache["current_points"] = points
        if rounds is not None:
            greyzone_progress_cache["current_rounds"] = rounds
        if tickets.get("ticket1") is not None:
            greyzone_progress_cache["ticket1"] = tickets.get("ticket1")
        else:
            # 本次 Index 未能可靠识别探查许可证时，清除旧版可能留下的错误大数缓存。
            if _safe_ticket_count(greyzone_progress_cache.get("ticket1")) is None:
                greyzone_progress_cache["ticket1"] = None
        if tickets.get("ticket2") is not None:
            greyzone_progress_cache["ticket2"] = tickets.get("ticket2")
        old_resources = greyzone_progress_cache.get("resources") if isinstance(greyzone_progress_cache.get("resources"), dict) else {}
        merged_resources = dict(old_resources)
        for k, v in resources.items():
            if v is not None:
                merged_resources[k] = v
            elif k not in merged_resources:
                merged_resources[k] = None
        greyzone_progress_cache["resources"] = merged_resources
    save_greyzone_cache()
    return parsed_any


def request_initial_index_and_cache(client):
    """运行前申请一次 Index/index，写入积分、轮次、票券与四项基准。"""
    update_run_status(phase="运行前申请 Index/index")
    print_status_panel(force=True)
    runtime_log("[*] 正在运行前申请一次 Index/index，写入灰域积分、轮次、票券与四项基准……", force=True)
    payload = {"time": int(time.time()), "furniture_data": False}
    _max_retries = 5
    _retry_delay = 5
    resp = None
    for _attempt in range(1, _max_retries + 1):
        resp = client.send_request(API_INDEX_INDEX, payload)
        if not check_step_error(resp, "Index/index"):
            break
        if _attempt < _max_retries:
            runtime_log("[!] 运行前 Index/index 第 %d 次请求失败，%d 秒后重试……" % (_attempt, _retry_delay), force=True)
            time.sleep(_retry_delay)
        else:
            runtime_log("[!] 运行前 Index/index 失败（已重试 %d 次），已取消本次灰域自动彩蛋。" % _max_retries, force=True)
            return False
    parsed_any = update_greyzone_cache_from_index_payload(resp, source="运行前 Index/index")
    update_fairy_cache_from_index_payload(resp, source="灰域运行前 Index/index")
    cache = get_greyzone_cache_snapshot()
    runtime_log("[+] 运行前 Index/index 已完成。", force=True)
    runtime_log("    当前灰域积分：%s/6000；当前轮次：%s" % (
        format_optional_int(cache.get("current_points")),
        format_optional_int(cache.get("current_rounds")),
    ), force=True)
    runtime_log("    票券缓存：探查票券 %s" % format_optional_int(cache.get("ticket1")))
    runtime_log("    四项缓存：%s" % format_resources(cache.get("resources")))
    if not parsed_any:
        runtime_log("[!] 未能从 Index/index 解析到灰域进度/票券/四项字段；本次仍可运行，但仪表盘会显示未知项。", force=True)
    return True


def apply_greyzone_entry_cost_cache(reason="进入彩蛋关"):
    """每次成功进入彩蛋关后本地扣减固定消耗。

    规则：
    - 探查模式：固定消耗 6 张探查票券。
    - 四项模式：探查票券可抵扣四项消耗，1 张探查票券 = 四项各 10。
      例如探查票券为 4 时，进入彩蛋关本地扣 4 张票券 + 四项各 20；
      探查票券为 0 或未知时，按四项各 60 扣减。
    """
    global run_entry_count, run_ticket_cost, run_resource_cost
    ticket_type = current_ticket_type()
    now = int(time.time())
    cost_detail = reason + " / 本地消耗推算"
    display_source = "运行中本地缓存"
    with greyzone_cache_lock:
        run_entry_count += 1
        ticket_val = _safe_int(greyzone_progress_cache.get("ticket1"), None)
        resources = greyzone_progress_cache.get("resources") if isinstance(greyzone_progress_cache.get("resources"), dict) else {}
        resources = dict(resources)

        ticket_to_consume = 0
        resource_to_consume = 0

        if ticket_type == 0 or greyzone_free_event_enabled():
            # 限时免费活动模式下，进入灰域彩蛋时不扣减探查票券和四项资源。
            ticket_to_consume = 0
            resource_to_consume = 0
            cost_detail += "（ticket_type=0，不扣减探查许可证/四项资源本地缓存）"
            display_source = "运行中本地缓存"
        elif ticket_type == 1:
            # 探查点数模式仍按固定 6 张票券估算；若缓存不足，服务器侧会决定是否可进入。
            ticket_to_consume = 6
            resource_to_consume = 0
            cost_detail += "（探查模式：消耗 6 张探查票券）"
        else:
            # 四项模式下，服务器会优先用探查票券抵扣；1 张票券等价四项各 10。
            if ticket_val is None:
                ticket_to_consume = 0
                resource_to_consume = 60
                cost_detail += "（四项模式：探查票券未知，按四项各 60 估算）"
            else:
                ticket_to_consume = max(0, min(6, int(ticket_val)))
                resource_to_consume = max(0, 60 - ticket_to_consume * 10)
                if ticket_to_consume >= 6:
                    cost_detail += "（四项模式：探查票券足够，消耗 6 张票券）"
                elif ticket_to_consume > 0:
                    cost_detail += "（四项模式：%d 张票券 + 四项各 %d）" % (ticket_to_consume, resource_to_consume)
                else:
                    cost_detail += "（四项模式：无探查票券，消耗四项各 60）"

        if ticket_to_consume > 0:
            run_ticket_cost += ticket_to_consume
            if ticket_val is not None:
                greyzone_progress_cache["ticket1"] = max(0, int(ticket_val) - ticket_to_consume)

        if resource_to_consume > 0:
            for key in ("mp", "ammo", "mre", "part"):
                run_resource_cost[key] = int(run_resource_cost.get(key, 0) or 0) + resource_to_consume
                val = _safe_int(resources.get(key), None)
                if val is not None:
                    resources[key] = max(0, val - resource_to_consume)
            greyzone_progress_cache["resources"] = resources

        greyzone_progress_cache.update({
            "server": CONFIG.get("SERVER_NAME", "M4A1"),
            "ticket_type": ticket_type,
            "source": display_source,
            "last_cost_detail": cost_detail,
            "updated_at": now,
        })
    save_greyzone_cache()

def add_greyzone_points_to_cache(points, source="本次运行推算"):
    global run_completed_rounds
    points = _safe_int(points, 0) or 0
    if points <= 0:
        return
    now = int(time.time())
    with greyzone_cache_lock:
        cur_points = greyzone_progress_cache.get("current_points")
        cur_rounds = greyzone_progress_cache.get("current_rounds")
        if cur_points is None:
            cur_points = 0
        if cur_rounds is None:
            cur_rounds = 0
        cur_points += points
        add_rounds, cur_points = divmod(max(0, cur_points), 6000)
        run_completed_rounds += int(add_rounds or 0)
        cur_rounds = max(0, int(cur_rounds or 0)) + add_rounds
        greyzone_progress_cache.update({
            "server": CONFIG.get("SERVER_NAME", "M4A1"),
            "ticket_type": int(CONFIG.get("TICKET_TYPE", 2) or 2),
            "current_points": cur_points,
            "current_rounds": cur_rounds,
            "source": source,
            "updated_at": now,
        })
    save_greyzone_cache()


def format_cache_age(updated_at):
    updated_at = _safe_int(updated_at, 0) or 0
    if updated_at <= 0:
        return "-"
    age = max(0, int(time.time()) - updated_at)
    if age < 60:
        return "%d秒前" % age
    if age < 3600:
        return "%d分钟前" % (age // 60)
    return "%d小时前" % (age // 3600)


def check_step_error(resp: dict, step_name: str) -> bool:
    if not isinstance(resp, dict):
        runtime_log("[-] %s 错误：服务器返回格式异常。" % step_name, force=True)
        return True
    if "error_local" in resp:
        runtime_log("[-] %s 本地错误：%s" % (step_name, resp.get("error_local")), force=True)
        preview = resp.get("raw_preview")
        if preview is None and isinstance(resp.get("raw"), str):
            raw = resp.get("raw") or ""
            preview = (raw[:120] + "...") if len(raw) > 120 else raw
        if preview not in (None, ""):
            runtime_log("    响应预览：%s" % preview, force=True)
        return True
    if "error" in resp:
        runtime_log("[-] %s 服务器错误：%s" % (step_name, resp.get("error")), force=True)
        return True
    return False



def _format_abort_response(resp):
    if not isinstance(resp, dict):
        return str(resp)
    if resp.get("success"):
        return "success"
    if "error" in resp:
        return "error:%s" % resp.get("error")
    if "error_local" in resp:
        preview = resp.get("raw_preview")
        if preview is None and isinstance(resp.get("raw"), str):
            raw = resp.get("raw") or ""
            preview = (raw[:80] + "...") if len(raw) > 80 else raw
        if preview not in (None, ""):
            return "%s（%s）" % (resp.get("error_local"), preview)
        return str(resp.get("error_local"))
    return str(resp)[:160]


def abort_greyzone_missions(client: GFLClient, mission_ids=None, reason="灰域卡关清理", quiet=False):
    """发送 Mission/abortMission 清理灰域卡关状态。

    只尝试灰域彩蛋配置中的 mission_id，不请求 Index/index，不扫描其他状态。
    若当前并不在对应关卡，服务器可能返回 error:2/error:3，这属于可忽略结果。
    """
    if client is None:
        return False
    ids = []
    for mid in mission_ids or []:
        mid = _safe_int(mid, None)
        if mid is not None and mid not in ids:
            ids.append(mid)
    status_mid = _safe_int(get_run_status_snapshot().get("mission_id"), None)
    if status_mid is not None and status_mid not in ids:
        ids.insert(0, status_mid)
    for mid in sorted(MISSION_CONFIGS.keys()):
        if mid not in ids:
            ids.append(mid)
    if not ids:
        return False
    if not quiet:
        runtime_log("[*] %s：尝试发送 abortMission 清理灰域当前关卡……" % reason, force=True)
    ok_any = False
    for mid in ids:
        try:
            resp = client.send_request(API_MISSION_ABORT, {"mission_id": int(mid)})
            ok = isinstance(resp, dict) and bool(resp.get("success"))
            ok_any = ok_any or ok
            # error:2/error:3 通常表示没有对应可退出战役/状态不匹配，不当作致命错误。
            if not quiet or ok or gfam_debug_enabled():
                runtime_log("    abortMission mission_id=%d -> %s" % (int(mid), _format_abort_response(resp)), force=ok)
            time.sleep(0.1)
        except Exception as exc:
            if not quiet or gfam_debug_enabled():
                runtime_log("    abortMission mission_id=%d 异常：%s" % (int(mid), exc), force=True)
    if not quiet:
        runtime_log("[*] abortMission 清理已完成；若游戏仍显示卡关，请回到主界面后重新进入灰域模块。", force=True)
    return ok_any


def manual_abort_current_greyzone():
    """菜单命令：手动退出当前灰域关卡。"""
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] 当前没有有效 UID/SIGN，无法发送 abortMission。请先从 GFAM 主菜单获取 UID/SIGN。")
        return False
    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    set_runtime_panel_active(True)
    update_run_status(running=False, phase="手动 abortMission 清理灰域卡关")
    print_status_panel(force=True)
    ok = abort_greyzone_missions(client, reason="手动退出当前灰域关卡", quiet=False)
    print_status_panel(force=True)
    set_runtime_panel_active(False)
    return ok

def record_pending_guns(gun_uids):
    if not gun_uids:
        return
    with pending_lock:
        for uid in gun_uids:
            try:
                uid = int(uid)
            except Exception:
                continue
            if uid not in pending_gun_uid_set:
                pending_gun_uid_set.add(uid)
                pending_gun_uids.append(uid)


def mark_pending_guns_retired(gun_uids):
    if not gun_uids:
        return
    gone = set()
    for uid in gun_uids:
        try:
            gone.add(int(uid))
        except Exception:
            pass
    if not gone:
        return
    with pending_lock:
        pending_gun_uid_set.difference_update(gone)
        pending_gun_uids[:] = [uid for uid in pending_gun_uids if uid not in gone]


def get_pending_guns_snapshot():
    with pending_lock:
        return list(pending_gun_uids)


def update_run_status(**kwargs):
    with status_lock:
        run_status.update(kwargs)


def reset_run_status():
    with status_lock:
        run_status.update({
            "running": False,
            "stop_requested": False,
            "phase": "待机",
            "reset_attempts": 0,
            "consecutive_failures": 0,
            "mission_id": None,
            "map_spot_id": None,
            "mission_type": "-",
            "current_step": 0,
            "total_steps": 0,
            "current_from": None,
            "current_to": None,
            "battle_done": 0,
            "battle_total": 0,
            "last_points": 0,
            "last_drops": [],
        })


def get_run_status_snapshot():
    with status_lock:
        return dict(run_status)


def format_gun_drop_list(gun_uids):
    if not gun_uids:
        return "无"
    labels = []
    for uid in gun_uids[:8]:
        try:
            labels.append("gun-%d" % int(uid))
        except Exception:
            labels.append(str(uid))
    if len(gun_uids) > 8:
        labels.append("等%d个" % len(gun_uids))
    return "   ".join(labels)


def get_terminal_width(default=120):
    try:
        import shutil
        return max(60, shutil.get_terminal_size(fallback=(default, 30)).columns)
    except Exception:
        return default


def strip_ansi(text):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", str(text))


def trim_line(text, max_width):
    text = str(text)
    if len(strip_ansi(text)) <= max_width:
        return text
    return strip_ansi(text)[:max(10, max_width - 3)] + "..."


def build_status_panel_lines():
    snap = get_run_status_snapshot()
    cache = get_greyzone_cache_snapshot()
    now = time.time()
    elapsed = int(now - run_start_time) if run_start_time else 0
    cached_points = cache.get("current_points")
    cached_rounds = cache.get("current_rounds")
    progress_text = "- / 6000"
    if cached_points is not None:
        progress_text = "%d / 6000" % int(cached_points or 0)
    round_text = str(int(cached_rounds or 0)) if cached_rounds is not None else "-"
    ticket_line = "探查票券 %s" % format_optional_int(cache.get("ticket1"))
    resource_line = format_resources(cache.get("resources"))
    cache_source = cache.get("source") or "未缓存"
    pending_count = len(get_pending_guns_snapshot())
    running_label = "运行中" if snap.get("running") else "待机"
    if snap.get("stop_requested"):
        running_label = "等待当前任务结束后停止"

    mission_id = snap.get("mission_id")
    spot_id = snap.get("map_spot_id")
    mission_text = "-"
    if mission_id:
        mission_text = "mission_id=%s spot=%s 类型=%s" % (mission_id, spot_id or "-", snap.get("mission_type") or "-")

    step_text = "%s / %s" % (snap.get("current_step", 0) or 0, snap.get("total_steps", 0) or 0)
    move_text = "-"
    if snap.get("current_from") is not None and snap.get("current_to") is not None:
        move_text = "%s -> %s" % (snap.get("current_from"), snap.get("current_to"))

    raw_lines = [
        "============= 灰域自动彩蛋运行状态 =============",
        "服务器：%s    票券：%s" % (CONFIG.get("SERVER_NAME"), ticket_type_label()),
        "状态：%s    当前阶段：%s" % (running_label, snap.get("phase") or "-"),
        "重置尝试：%d    连续失败：%d / %d" % (
            int(snap.get("reset_attempts", 0) or 0),
            int(snap.get("consecutive_failures", 0) or 0),
            int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 8) or 8),
        ),
        "当前任务：%s" % mission_text,
        "当前 Step：%s    当前移动：%s" % (step_text, move_text),
        "战斗触发：%d / %d" % (int(snap.get("battle_done", 0) or 0), int(snap.get("battle_total", 0) or 0)),
        "完成彩蛋任务：%d    本轮点数：%d" % (macro_count, int(snap.get("last_points", 0) or 0)),
        "当前灰域积分：%s    当前轮次：%s" % (progress_text, round_text),
        "票券缓存：%s    进入彩蛋关：%d 次" % (ticket_line, int(run_entry_count)),
        "四项缓存：%s" % resource_line,
        "本次消耗：探查票券 -%d；%s" % (int(run_ticket_cost), format_resource_cost(run_resource_cost)),
        "本次运行累计彩蛋点数：%d" % int(total_halloween_points),
        "进度：%s（本次运行已完成 %d 轮）" % (progress_text, int(run_completed_rounds)),
        "缓存：%s" % cache_source,
        fairy_runtime_status_line(),
        "本轮掉落：%s" % format_gun_drop_list(snap.get("last_drops") or []),
        "待收尾拆解：%d" % pending_count,
        "本次运行：%s" % format_duration(elapsed),
        "停止：-q 当前任务后停 / -E 返回 GFAM 主菜单",
        "==============================================",
    ]
    raw_lines = [line for line in raw_lines if str(line).strip()]
    width = max(60, get_terminal_width(120) - 2)
    return [trim_line(line, width) for line in raw_lines]


def clear_runtime_panel():
    try:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        try:
            os.system("cls" if os.name == "nt" else "clear")
        except Exception:
            pass


def refresh_status_panel(force=False):
    global last_status_print_time
    if not runtime_panel_active:
        return
    now = time.time()
    if not force and now - last_status_print_time < runtime_panel_min_interval:
        return
    last_status_print_time = now
    clear_runtime_panel()
    for line in runtime_recent_logs[-runtime_recent_logs_max:]:
        print(line)
    if runtime_recent_logs:
        print()
    for line in build_status_panel_lines():
        print(line)


def print_status_panel(force=False):
    refresh_status_panel(force=force)



def set_runtime_panel_active(active):
    global runtime_panel_active, last_status_print_time
    runtime_panel_active = bool(active)
    last_status_print_time = 0.0
    if active:
        runtime_recent_logs.clear()


def runtime_log(message="", force=False):
    text = str(message)
    if not runtime_panel_active:
        print(text)
        return
    lines = text.splitlines() or [""]
    runtime_recent_logs.extend(lines)
    if len(runtime_recent_logs) > runtime_recent_logs_max:
        del runtime_recent_logs[:-runtime_recent_logs_max]
    refresh_status_panel(force=force)


# ==========================================
# Class: MapParser
# ==========================================
class MapParser:
    SPAWN_MAP = GREYZONE_RESPAWN_MAP

    @classmethod
    def parse(cls, resp: dict) -> list:
        status = resp.get("daily_status_with_user_info", {}) if isinstance(resp, dict) else {}
        map_list = resp.get("daily_map_with_user_info", []) if isinstance(resp, dict) else []
        respawn_spot = str(status.get("spot_id"))
        spots = {str(spot.get("spot_id")): spot.get("mission", "") for spot in map_list if isinstance(spot, dict)}
        results = []
        if respawn_spot not in cls.SPAWN_MAP:
            return results
        for adj in cls.SPAWN_MAP[respawn_spot]:
            mission_str = spots.get(adj, "")
            if not mission_str:
                continue
            for part in str(mission_str).split(","):
                if part.startswith("1:58"):
                    try:
                        m_id = int(part.split(":", 1)[1])
                        results.append({"spot_id": int(adj), "mission_id": m_id})
                    except Exception:
                        pass
        return results


# ==========================================
# Class Hierarchy: MissionRunner
# ==========================================
class MissionRunner:
    def __init__(self, client: GFLClient, mission_id: int, map_spot_id: int):
        self.client = client
        self.mission_id = mission_id
        self.map_spot_id = map_spot_id
        cfg = MISSION_CONFIGS.get(mission_id, {})
        self.start_spot = int(cfg.get("start_spot", 0) or 0)
        self.route = list(cfg.get("route", []) or [])
        self.has_ally_move = bool(cfg.get("has_ally_move", False))
        self.last_error_kind = None

    def run(self):
        raise NotImplementedError("Base run() method must be overridden.")

    def start_payload(self):
        return {
            "mission_id": self.mission_id,
            "spots": [],
            "squad_spots": [],
            "sangvis_spots": [],
            "vehicle_spots": [],
            "ally_spots": [],
            "mission_ally_spots": [
                {
                    "spot_id": self.start_spot,
                    "ally_team_id": 78001,
                    "mission_myside_data": {
                        "sangvis": [],
                        "gun": {
                            "1": {"position": 8},
                            "2": {"position": 9},
                            "3": {"position": 7},
                            "4": {"position": 14},
                            "5": {"position": 13},
                        },
                    },
                }
            ],
            "ally_id": int(time.time()),
            "daily_param": {
                "spot_id": self.map_spot_id,
                "ticket_type": resolve_server_ticket_type_for_entry(),
            },
            "fight_environment_skill_info": {},
        }

    def process_win_result(self, resp: dict):
        # 必须显式区分三种情况：
        #   [uid, ...]：胜利结算且有人形掉落
        #   []        ：胜利结算正常，但没有人形掉落/捡垃圾，后续空发一次 retire
        #   None      ：没有拿到有效胜利结算，外层统一 abortMission，避免灰域关卡残留导致 code3
        dropped_guns = None
        points = 0

        if not isinstance(resp, dict):
            self.last_error_kind = "missing_win_result"
            runtime_log("[-] 灰域结算响应格式异常，未取得 mission_win_result。", force=True)
            return None

        win_result = resp.get("mission_win_result")
        if not isinstance(win_result, dict) or not win_result:
            self.last_error_kind = "missing_win_result"
            preview = str(resp)[:180].replace("\n", " ")
            runtime_log("[-] 灰域结算缺少 mission_win_result，视为任务未正常完成。", force=True)
            if preview:
                runtime_log("    响应预览：%s" % preview, force=True)
            return None

        # 只有确认拿到有效胜利结算后，才把 None 转为 []。
        # 这样正常捡垃圾/无掉落会空发 retire，而异常结算会触发 abortMission。
        dropped_guns = []

        reward_guns = win_result.get("reward_gun", []) or []
        for gun in reward_guns:
            try:
                gun_uid = int(gun.get("gun_with_user_id"))
            except Exception:
                continue
            dropped_guns.append(gun_uid)
            runtime_log("    [+] 掉落人形 UID：%d" % gun_uid)

        type5_drop = win_result.get("mission_type5_drop", {}) or {}
        item_dict = type5_drop.get("item", {}) or {}
        try:
            points = int(item_dict.get("10736", 0) or 0)
        except Exception:
            points = 0

        return dropped_guns, points

    def move_to(self, curr_spot, next_spot, step):
        update_run_status(
            phase="移动路线",
            current_step=step,
            total_steps=len(self.route),
            current_from=curr_spot,
            current_to=next_spot,
        )
        print_status_panel()
        runtime_log("[>] Step %d：移动 %d -> %d" % (step, curr_spot, next_spot))
        move_payload = {
            "person_type": 3,
            "person_id": 1,
            "from_spot_id": curr_spot,
            "to_spot_id": next_spot,
            "move_type": 1,
        }
        resp = self.client.send_request(API_MISSION_TEAM_MOVE, move_payload)
        if check_step_error(resp, "teamMove"):
            return None
        return resp

    def finish_turn_and_collect(self):
        update_run_status(phase="结束回合并结算", current_from=None, current_to=None)
        print_status_panel(force=True)
        runtime_log("[>] 结束回合并结算……", force=True)
        if check_step_error(self.client.send_request(API_MISSION_END_TURN, {}), "endTurn"):
            return None
        time.sleep(0.2)
        if check_step_error(self.client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"):
            return None
        time.sleep(0.2)
        if check_step_error(self.client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"):
            return None
        time.sleep(0.2)
        win_resp = self.client.send_request(API_MISSION_START_TURN, {})
        if check_step_error(win_resp, "startTurn"):
            return None
        return self.process_win_result(win_resp)


class MissionRunnerMove(MissionRunner):
    def run(self):
        update_run_status(
            phase="开始 MOVE 彩蛋任务",
            mission_id=self.mission_id,
            map_spot_id=self.map_spot_id,
            mission_type="MOVE",
            current_step=0,
            total_steps=len(self.route),
            current_from=None,
            current_to=None,
            battle_done=0,
            battle_total=0,
            last_points=0,
            last_drops=[],
        )
        print_status_panel(force=True)
        runtime_log("[>] 开始 MOVE 彩蛋任务 %d，地图点 %d。" % (self.mission_id, self.map_spot_id), force=True)
        if gfam_debug_enabled():
            gfam_debug_log(self.start_payload())
        self.last_error_kind = None
        start_resp = self.client.send_request(API_MISSION_START, self.start_payload())
        if check_step_error(start_resp, "startMission"):
            if is_recoverable_startmission_error(start_resp):
                self.last_error_kind = "start_error_2"
            return None
        apply_greyzone_entry_cost_cache(reason="进入 MOVE 彩蛋关")
        print_status_panel(force=True)

        curr_spot = self.start_spot
        for step, next_spot in enumerate(self.route, 1):
            if stop_macro_flag:
                return None
            move_resp = self.move_to(curr_spot, next_spot, step)
            if move_resp is None:
                return None
            curr_spot = next_spot
            time.sleep(0.1)

        if self.has_ally_move:
            runtime_log("[>] 触发友方移动……", force=True)
            if check_step_error(self.client.send_request(API_MISSION_ALLY_MYSIDE_MOVE, {}), "allyMove"):
                return None
            time.sleep(0.3)

        return self.finish_turn_and_collect()


class MissionRunnerBattle(MissionRunner):
    def run(self):
        current_spots_state = {}

        def update_seeds(resp_data):
            if isinstance(resp_data, dict) and "spot_act_info" in resp_data:
                for spot in resp_data["spot_act_info"]:
                    try:
                        current_spots_state[str(spot.get("spot_id"))] = int(spot.get("seed", 0) or 0)
                    except Exception:
                        pass

        update_run_status(
            phase="开始 BATTLE 彩蛋任务",
            mission_id=self.mission_id,
            map_spot_id=self.map_spot_id,
            mission_type="BATTLE",
            current_step=0,
            total_steps=len(self.route),
            current_from=None,
            current_to=None,
            battle_done=0,
            battle_total=len(MISSION_CONFIGS.get(self.mission_id, {}).get("on_battle", []) or []),
            last_points=0,
            last_drops=[],
        )
        print_status_panel(force=True)
        runtime_log("[>] 开始 BATTLE 彩蛋任务 %d，地图点 %d。" % (self.mission_id, self.map_spot_id), force=True)
        self.last_error_kind = None
        start_resp = self.client.send_request(API_MISSION_START, self.start_payload())
        if check_step_error(start_resp, "startMission"):
            if is_recoverable_startmission_error(start_resp):
                self.last_error_kind = "start_error_2"
            return None
        apply_greyzone_entry_cost_cache(reason="进入 BATTLE 彩蛋关")
        print_status_panel(force=True)
        update_seeds(start_resp)

        cfg = MISSION_CONFIGS.get(self.mission_id, {})
        on_battle_list = list(cfg.get("on_battle", []) or [])
        death_k_list = list(cfg.get("building_missionskills_on_death_k", []) or [])

        curr_spot = self.start_spot
        for step, next_spot in enumerate(self.route, 1):
            if stop_macro_flag:
                return None
            move_resp = self.move_to(curr_spot, next_spot, step)
            if move_resp is None:
                return None
            update_seeds(move_resp)
            curr_spot = next_spot
            time.sleep(0.1)

            if curr_spot in on_battle_list:
                battle_idx = on_battle_list.index(curr_spot)
                k_val = death_k_list[battle_idx] if battle_idx < len(death_k_list) else 0
                seed = current_spots_state.get(str(curr_spot), 0)
                update_run_status(phase="触发战斗", battle_done=battle_idx + 1, battle_total=len(on_battle_list))
                print_status_panel(force=True)
                runtime_log("    [!] 触发战斗：spot=%d seed=%d k=%d" % (curr_spot, seed, k_val), force=True)

                battle_payload = {
                    "spot_id": curr_spot,
                    "if_enemy_die": True,
                    "current_time": int(time.time()),
                    "boss_hp": 0,
                    "mvp": 1084,
                    "last_battle_info": "",
                    "use_skill_squads": [],
                    "use_skill_ally_spots": [],
                    "use_skill_vehicle_spots": [],
                    "guns": [
                        {"id": 1084, "life": 565},
                        {"id": 1085, "life": 540},
                        {"id": 1086, "life": 565},
                        {"id": 1087, "life": 605},
                        {"id": 1088, "life": 1040},
                    ],
                    "user_rec": '{"seed":%d,"record":[]}' % seed,
                    "1000": {"10": 32089, "11": 32089, "12": 32089, "13": 32089, "15": 531, "16": 0, "17": 43, "33": 10001, "40": 9, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 811, "25": 0, "26": 811, "27": 4, "34": 5, "35": 5, "41": 90, "42": 0, "43": 0, "44": 0},
                    "1001": {},
                    "1002": {"1084": {"47": 0}, "1085": {"47": 0}, "1086": {"47": 0}, "1087": {"47": 0}, "1088": {"47": 0}},
                    "1003": {},
                    "1005": {},
                    "1007": {},
                    "1008": {},
                    "1009": {},
                    "battle_damage": {},
                    "micalog": {"user_device": CONFIG["USER_DEVICE"], "user_ip": ""},
                }

                if check_step_error(self.client.send_request(API_MISSION_BATTLE_FINISH, battle_payload), "battleFinish"):
                    return None
                time.sleep(0.1)

                runtime_log("    [!] 执行 BuildingSkillPerformOnDeath：target=%d" % self.start_spot, force=True)
                building_payload = {
                    "building_missionskills_on_death_k": {
                        str(self.start_spot): [k_val]
                    }
                }
                if check_step_error(self.client.send_request(API_MISSION_BUILDING_SKILL_PERFORM_ON_DEATH, building_payload), "buildingSkillPerformOnDeath"):
                    return None
                time.sleep(0.1)

        if self.has_ally_move:
            runtime_log("[>] 触发友方移动……", force=True)
            if check_step_error(self.client.send_request(API_MISSION_ALLY_MYSIDE_MOVE, {}), "allyMove"):
                return None
            time.sleep(0.3)

        return self.finish_turn_and_collect()


# ==========================================
# Worker Logic
# ==========================================
def retire_guns(client: GFLClient, gun_uids: list, reason="自动拆解"):
    # 返回值语义：
    #   None  ：任务错误，外层不会调用本函数，而是先 abortMission。
    #   []    ：任务正常完成但没有掉落人形 / 捡垃圾，需要空发一次 retire 让流程闭合。
    #   [uid] ：任务正常完成且有人形掉落，提交对应 UID 拆解。
    if gun_uids is None:
        return 0

    uids = []
    seen = set()
    for uid in gun_uids or []:
        try:
            uid = int(uid)
        except Exception:
            continue
        if uid in seen:
            continue
        seen.add(uid)
        uids.append(uid)

    if not uids:
        runtime_log("[*] %s：本轮无掉落人形，空发一次 retire。" % reason)
        resp = client.send_request(API_GUN_RETIRE, [])
        if isinstance(resp, dict) and resp.get("success"):
            return 0
        runtime_log("[-] 空 retire 失败：%s" % str(resp), force=True)
        return 0

    runtime_log("[*] %s：提交 %d 名人形自动拆解……" % (reason, len(uids)), force=True)
    resp = client.send_request(API_GUN_RETIRE, uids)
    if isinstance(resp, dict) and resp.get("success"):
        runtime_log("[+] 自动拆解成功。", force=True)
        mark_pending_guns_retired(uids)
        return len(uids)
    runtime_log("[-] 自动拆解失败：%s" % str(resp), force=True)
    return 0


def final_cleanup(client: GFLClient):
    update_run_status(phase="运行结束收尾拆解")
    print_status_panel(force=True)
    uids = get_pending_guns_snapshot()
    if not uids:
        return
    runtime_log("[收尾拆解] 检测到本次运行仍有 %d 名掉落人形未成功拆解，正在收尾处理。" % len(uids), force=True)
    retired = retire_guns(client, uids, reason="运行结束收尾拆解")
    if retired > 0:
        runtime_log("[收尾拆解] 已收尾拆解人形 %d 名。" % retired, force=True)
    else:
        runtime_log("[收尾拆解] 未能成功拆解遗留人形，请手动检查仓库。", force=True)


def make_runner(client, mission_id, spot_id):
    mission_type = MISSION_CONFIGS.get(mission_id, {}).get("type")
    if mission_type == "MOVE":
        return MissionRunnerMove(client, mission_id, spot_id)
    if mission_type == "BATTLE":
        return MissionRunnerBattle(client, mission_id, spot_id)
    return None


def normalize_runner_result(result):
    """Normalize mission result semantics.

    Convention used by GFAM farm modules:
      - [uid, ...] : mission succeeded and returned T-Doll drops
      - []         : mission succeeded but no T-Doll drop / scavenging result
      - None       : protocol/server/local error; caller should abortMission

    Greyzone runners additionally return points, so the internal form is
    (dropped_guns, points). This helper keeps both forms compatible and makes
    sure an empty list is never treated as a failure.
    """
    if result is None:
        # runner 内部步骤出错时直接返回 None；这里统一转换成可解包的错误语义。
        return None, 0
    if isinstance(result, tuple):
        if len(result) >= 2:
            dropped, points = result[0], result[1]
        elif len(result) == 1:
            dropped, points = result[0], 0
        else:
            return None
    else:
        dropped, points = result, 0

    if dropped is None:
        return None, int(points or 0)
    if isinstance(dropped, list):
        return dropped, int(points or 0)

    try:
        return list(dropped), int(points or 0)
    except Exception:
        return None, int(points or 0)


def print_run_summary():
    elapsed = int(time.time() - run_start_time) if run_start_time else 0
    cache = get_greyzone_cache_snapshot()
    current_points = cache.get("current_points")
    current_rounds = cache.get("current_rounds")
    print() 
    print("=========== 灰域自动彩蛋统计 ===========")
    print("运行总时长：%s" % format_duration(elapsed))
    print("完成彩蛋任务：%d 次" % macro_count)
    print("本次运行累计彩蛋点数：%d" % total_halloween_points)
    print("本次进入彩蛋关：%d 次" % int(run_entry_count))
    print("本次本地消耗：探查票券 -%d；%s" % (int(run_ticket_cost), format_resource_cost(run_resource_cost)))
    if current_points is not None or current_rounds is not None:
        print("当前灰域进度：%s/6000（当前轮次 %s；本次运行已完成 %d 轮）" % (
            int(current_points or 0),
            int(current_rounds or 0),
            int(run_completed_rounds),
        ))
        print("积分缓存来源：%s" % (cache.get("source") or "-"))
    else:
        print("当前灰域进度：未从 Index/缓存解析到，已仅统计本次运行增量。")
    print("当前票券类型：%s" % ticket_type_label())
    if current_ticket_type() == 2:
        print("四项模式消耗规则：探查票券优先抵扣，1 张票券 = 四项各 10；不足 6 张时补扣剩余四项。")
    print_fairy_summary(fairy_auto_start_snapshot)
    print("====================================")
    print()

    # ---- Write JSON summary for GUI popup ----
    try:
        _rc = run_resource_cost if isinstance(run_resource_cost, dict) else {}
        _summary = {
            "kind": "greyzone",
            "title": "灰域自动彩蛋统计",
            "server": CONFIG.get("SERVER_NAME", ""),
            "elapsed_seconds": elapsed,
            "elapsed_text": format_duration(elapsed),
            "macro_count": int(macro_count),
            "halloween_points": int(total_halloween_points),
            "entry_count": int(run_entry_count),
            "ticket_cost": int(run_ticket_cost),
            "resource_cost": {
                "mp": int(_rc.get("mp", 0) or 0),
                "ammo": int(_rc.get("ammo", 0) or 0),
                "mre": int(_rc.get("mre", 0) or 0),
                "part": int(_rc.get("part", 0) or 0),
            },
            "greyzone_points": int(current_points or 0) if current_points is not None else None,
            "greyzone_rounds": int(current_rounds or 0) if current_rounds is not None else None,
            "completed_rounds": int(run_completed_rounds),
            "ticket_type": int(CONFIG.get("TICKET_TYPE", 2) or 2),
            "ticket_type_label": ticket_type_label(),
            "stats": [
                {"label": "完成彩蛋任务", "value": "%d 次" % int(macro_count)},
                {"label": "累计彩蛋点数", "value": "%d" % int(total_halloween_points)},
                {"label": "进入彩蛋关", "value": "%d 次" % int(run_entry_count)},
                {"label": "消耗探查票券", "value": "-%d" % int(run_ticket_cost)},
            ],
        }
        if current_points is not None:
            _summary["stats"].append({"label": "灰域进度", "value": "%d/6000" % int(current_points)})
            _summary["stats"].append({"label": "已完成轮次", "value": "%d" % int(run_completed_rounds)})
        try:
            _fs = read_fairy_snapshot()
            if _fs:
                _summary["fairy"] = _fs
        except Exception:
            pass
        # Follow-module factory stats (if active)
        try:
            _factory_cache_path = _gfam_os.path.join(_gfam_root, ".gfam_factory_auto_cache.json")
            if _gfam_os.path.exists(_factory_cache_path):
                with open(_factory_cache_path, "r", encoding="utf-8") as _fc:
                    _factory_cache = json.load(_fc)
                _factory_data = {}
                for _fk in ("doll", "equip"):
                    _fstats = _factory_cache.get("%s_stats" % _fk)
                    if not _fstats or not isinstance(_fstats, dict):
                        continue
                    _ba = int(_fstats.get("build_attempts", 0) or 0)
                    _to = int(_fstats.get("total_outputs", 0) or 0)
                    if _ba == 0 and _to == 0:
                        continue
                    _factory_data[_fk] = {
                        "formula_name": _factory_cache.get("%s_formula_name" % _fk, ""),
                        "stats": dict(_fstats),
                    }
                if _factory_data:
                    _summary["factory"] = _factory_data
        except Exception:
            pass
        _summary_file = _gfam_os.path.join(_gfam_root, ".gfam_greyzone_summary.json")
        with open(_summary_file, "w", encoding="utf-8") as _f:
            json.dump(_summary, _f, ensure_ascii=False, indent=2)
        print("[SUMMARY] 灰域自动彩蛋统计报告已生成。")
    except Exception:
        pass

def halloween_farm_worker():
    global stop_macro_flag, worker_mode, current_worker_thread, total_halloween_points, macro_count, run_start_time, fairy_auto_start_snapshot
    client = None
    consecutive_failures = 0
    try:
        if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
            runtime_log("[!] 当前没有有效 UID/SIGN。请从 GFAM 主菜单进入本模块，或先重新获取 UID/SIGN。", force=True)
            return

        client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
        fairy_auto_start_snapshot = read_fairy_snapshot()
        run_start_time = time.time()
        set_runtime_panel_active(True)
        update_run_status(running=True, stop_requested=False, phase="准备运行")
        print_status_panel(force=True)
        runtime_log("=== 灰域自动彩蛋 Started ===", force=True)
        runtime_log("[*] 服务器：%s | 票券类型：%s" % (CONFIG.get("SERVER_NAME"), ticket_type_label()))
        if bool(CONFIG.get("ABORT_BEFORE_RUN", True)):
            update_run_status(phase="运行前清理旧灰域关卡")
            print_status_panel(force=True)
            runtime_log("[*] 正式运行前先尝试 abortMission 清理旧灰域关卡，防止上次异常后卡关。")
            abort_greyzone_missions(client, reason="运行前清理旧灰域关卡", quiet=False)
            runtime_log("[*] abortMission 已完成，等待 2 秒后申请 Index/index……")
            time.sleep(2)
        runtime_log("[*] 将先申请一次 Index/index 作为基准，之后票券/四项/积分/轮次均按本地缓存推算。")
        if not request_initial_index_and_cache(client):
            return

        attempts = 0
        while not stop_macro_flag:
            attempts += 1
            update_run_status(
                phase="重置灰域地图",
                reset_attempts=attempts,
                consecutive_failures=consecutive_failures,
                mission_id=None,
                map_spot_id=None,
                mission_type="-",
                current_step=0,
                total_steps=0,
                current_from=None,
                current_to=None,
                battle_done=0,
                battle_total=0,
            )
            print_status_panel()
            runtime_log("[*] 重置灰域地图，尝试 %d ……" % attempts)
            resp = client.send_request(API_DAILY_RESET_MAP, {"difficulty": int(CONFIG.get("RESET_DIFFICULTY", 3) or 3)})
            if check_step_error(resp, "resetMap"):
                consecutive_failures += 1
                update_run_status(phase="重置失败，等待重试", consecutive_failures=consecutive_failures)
                print_status_panel(force=True)
                if consecutive_failures >= int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 8) or 8):
                    runtime_log("[!] 连续失败次数过多，已停止灰域自动彩蛋。", force=True)
                    break
                time.sleep(3)
                continue

            # 运行中不再用 resetMap 反复覆盖基准进度；只用它解析当前地图。
            targets = MapParser.parse(resp)
            if not targets:
                consecutive_failures = 0
                update_run_status(phase="未发现彩蛋，继续重置", consecutive_failures=0)
                print_status_panel()
                runtime_log("    [-] 当前地图未发现有效彩蛋，继续重置。")
                time.sleep(float(CONFIG.get("RESET_RETRY_DELAY", 0.2) or 0.2))
                continue

            for target in targets:
                if stop_macro_flag:
                    break
                mission_id = int(target["mission_id"])
                spot_id = int(target["spot_id"])
                update_run_status(phase="发现灰域彩蛋", mission_id=mission_id, map_spot_id=spot_id)
                print_status_panel(force=True)
                runtime_log("[+] 发现灰域彩蛋：spot=%d mission_id=%d" % (spot_id, mission_id), force=True)
                if mission_id not in MISSION_CONFIGS:
                    runtime_log("[!] mission_id=%d 未配置路线，已停止。" % mission_id, force=True)
                    stop_macro_flag = True
                    break

                runner = make_runner(client, mission_id, spot_id)
                if runner is None:
                    runtime_log("[!] mission_id=%d 类型未知，已停止。" % mission_id, force=True)
                    stop_macro_flag = True
                    break

                dropped_guns, points = normalize_runner_result(runner.run())
                if dropped_guns is None:
                    # 无论失败原因是什么，只要 runner.run() 没有正常返回掉落列表，
                    # 都先发送 abortMission 清理当前灰域关卡，避免游戏端残留在灰域关里，
                    # 下次进入时直接 code3 或 startMission 返回 error:2。
                    error_kind = getattr(runner, "last_error_kind", None)
                    consecutive_failures += 1
                    update_run_status(
                        phase="彩蛋任务失败，正在 abortMission 清理当前关卡",
                        consecutive_failures=consecutive_failures,
                    )
                    print_status_panel(force=True)
                    runtime_log("[-] 本次彩蛋任务失败或被中断，正在执行 abortMission 清理当前灰域关卡。", force=True)
                    abort_greyzone_missions(
                        client,
                        mission_ids=[mission_id],
                        reason="dropped_guns=None 后清理当前灰域关卡",
                        quiet=False,
                    )

                    if error_kind == "start_error_2":
                        if consecutive_failures >= int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 8) or 8):
                            runtime_log("[!] 连续 startMission 失败次数过多，已停止灰域自动彩蛋。", force=True)
                            stop_macro_flag = True
                            break
                        runtime_log("[!] 已 abort 当前异常灰域关卡；放弃当前彩蛋候选并继续重置灰域地图。", force=True)
                        time.sleep(float(CONFIG.get("RESET_RETRY_DELAY", 0.2) or 0.2))
                        continue

                    stop_macro_flag = True
                    break

                update_run_status(phase="彩蛋任务结算", last_drops=list(dropped_guns or []), last_points=int(points or 0))
                print_status_panel(force=True)
                record_pending_guns(dropped_guns)
                retire_guns(client, dropped_guns, reason="Macro 后人形拆解")

                macro_count += 1
                consecutive_failures = 0
                total_halloween_points += int(points or 0)
                add_greyzone_points_to_cache(int(points or 0), source="本次运行推算")
                update_run_status(phase="彩蛋任务完成", last_drops=list(dropped_guns or []), last_points=int(points or 0))
                print_status_panel(force=True)
                cache_after = get_greyzone_cache_snapshot()
                current_points = cache_after.get("current_points")
                current_rounds = cache_after.get("current_rounds")
                if current_points is None:
                    current_points = total_halloween_points % 6000
                if current_rounds is None:
                    current_rounds = total_halloween_points // 6000

                runtime_log("========================================", force=True)
                runtime_log("[+] 彩蛋任务完成：mission_id=%d" % mission_id)
                runtime_log("[+] 本轮彩蛋点数：%d" % int(points or 0))
                runtime_log("[+] 本次运行累计彩蛋点数：%d" % total_halloween_points)
                runtime_log("[+] 进度：%d/6000（本次运行已完成 %d 轮）" % (int(current_points or 0), int(run_completed_rounds)))
                runtime_log("========================================", force=True)
                time.sleep(float(CONFIG.get("AFTER_MISSION_DELAY", 1.0) or 1.0))

        runtime_log("[*] 灰域自动彩蛋已结束。", force=True)
    except Exception:
        stop_macro_flag = True
        runtime_log("[异常保护] 灰域自动彩蛋线程发生未处理异常，已自动终止。", force=True)
        runtime_log(traceback.format_exc(), force=True)
    finally:
        update_run_status(running=False, phase="准备结束")
        try:
            if client is not None:
                final_cleanup(client)
        except Exception:
            runtime_log("[收尾拆解] 收尾拆解时出现异常：", force=True)
            runtime_log(traceback.format_exc(), force=True)
        print_status_panel(force=True)
        set_runtime_panel_active(False)
        print_run_summary()
        worker_mode = None
        current_worker_thread = None


def format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h:
        parts.append("%d小时" % h)
    if m:
        parts.append("%d分" % m)
    parts.append("%d秒" % s)
    return "".join(parts)


def set_manual_ticket_count(count):
    """手动校准探查许可证数量。

    在尚未确认真实 item_id 前，可用 -ticketcount 2950 按游戏内道具栏数量写入本地缓存。
    后续运行会按本地消耗继续扣减。
    """
    count = _safe_ticket_count(count)
    if count is None:
        return False
    now = int(time.time())
    with greyzone_cache_lock:
        greyzone_progress_cache.update({
            "server": CONFIG.get("SERVER_NAME", "M4A1"),
            "ticket_type": int(CONFIG.get("TICKET_TYPE", 2) or 2),
            "ticket1": count,
            "source": "手动校准探查许可证",
            "updated_at": now,
        })
    save_greyzone_cache()
    return True


def print_menu():
    cache = get_greyzone_cache_snapshot()
    print()
    print("================= 灰域自动彩蛋 MENU =================")
    print(" 当前服务器：%s" % CONFIG.get("SERVER_NAME"))
    print(" 当前票券类型：%s" % ticket_type_label())
    if cache.get("current_points") is not None or cache.get("current_rounds") is not None:
        print(" 当前缓存进度：%s/6000（当前轮次 %s），来源：%s" % (
            int(cache.get("current_points") or 0),
            int(cache.get("current_rounds") or 0),
            cache.get("source") or "-",
        ))
        print(" 当前缓存票券：探查票券 %s" % format_optional_int(cache.get("ticket1")))
        print(" 当前缓存四项：%s" % format_resources(cache.get("resources")))
    else:
        print(" 当前缓存进度：暂无；输入 -r 正式运行前会先申请一次 Index/index 写入基准。")
    print(" -r        : 开始灰域自动彩蛋")
    print(" -q        : 当前执行结束后安全停止")
    print(" -ticket1  : 使用探查点数票券")
    print(" -ticket2  : 使用四项资源票券（默认）")
    print(" -ticketcount 数量 : 手动校准探查许可证数量（备用）")
    print(" -abort    : 发送 abortMission 退出当前灰域关卡/清理卡关")
    print(" -E        : 返回少女全自动 GFAM 主菜单")
    print("-----------------------------------------------------")
    print("说明：本模块沿用 GFAM 主菜单 UID/SIGN，不启动代理；正式运行前仅请求一次 Index/index 写入基准。")
    print("说明：运行中会显示灰域专用状态仪表盘；掉落人形会自动拆解；开启 fairy 时会显示妖精自动信息。")
    print("说明：彩蛋战斗使用 BuildingSkillPerformOnDeath 接口。")
    print("说明：运行中不反复请求 Index/index；四项模式会先按本地缓存消耗探查票券，1 张票券抵四项各 10，不足部分补扣四项。")
    print("说明：已确认探查许可证 item_id=10702；若后续服端变更或显示异常，可用 -ticketcount 数量 临时校准。")
    print("说明：如果游戏卡在灰域关或一进关就 code3，可先在本菜单输入 -abort 退出当前灰域关卡。")
    print("=====================================================")
    print()

def start_worker():
    global stop_macro_flag, worker_mode, current_worker_thread, total_halloween_points, macro_count
    global run_completed_rounds, run_entry_count, run_ticket_cost, run_resource_cost, fairy_auto_start_snapshot
    if current_worker_thread and current_worker_thread.is_alive():
        print("[!] 灰域自动彩蛋已经在运行。")
        return
    stop_macro_flag = False
    load_greyzone_cache()
    total_halloween_points = 0
    macro_count = 0
    run_completed_rounds = 0
    run_entry_count = 0
    run_ticket_cost = 0
    run_resource_cost = {"mp": 0, "ammo": 0, "mre": 0, "part": 0}
    fairy_auto_start_snapshot = {}
    reset_run_status()
    with pending_lock:
        pending_gun_uids.clear()
        pending_gun_uid_set.clear()
    worker_mode = "run"
    current_worker_thread = threading.Thread(target=halloween_farm_worker, daemon=True)
    current_worker_thread.start()


def request_stop():
    global stop_macro_flag
    stop_macro_flag = True
    update_run_status(stop_requested=True, phase="已请求停止，等待当前任务结束")
    print_status_panel(force=True)
    runtime_log("[*] 将在当前执行结束后停止……", force=True)


def main_loop():
    print_menu()
    while True:
        try:
            cmd = input("GFAM-灰域> ").strip()
        except KeyboardInterrupt:
            print("\n[!] 请使用 -E 安全返回 GFAM 主菜单。")
            continue
        if not cmd:
            continue
        cmd_prefix = cmd.split()[0].lower()
        if cmd_prefix == "-r":
            start_worker()
        elif cmd_prefix == "-q":
            request_stop()
        elif cmd_prefix in ("-ticket1", "-t1", "-point", "-points", "-探查"):
            if current_worker_thread and current_worker_thread.is_alive():
                print("[!] 运行中不能切换票券类型，请先 -q 停止。")
                continue
            CONFIG["TICKET_TYPE"] = 1
            load_greyzone_cache()
            print("[+] 已选择票券类型：探查点数。")
            print_menu()
        elif cmd_prefix in ("-ticket2", "-t2", "-resource", "-resources", "-四项"):
            if current_worker_thread and current_worker_thread.is_alive():
                print("[!] 运行中不能切换票券类型，请先 -q 停止。")
                continue
            CONFIG["TICKET_TYPE"] = 2
            load_greyzone_cache()
            print("[+] 已选择票券类型：四项资源。")
            print_menu()
        elif cmd_prefix in ("-freeon", "-free", "-freeevent", "-免费", "-限免", "-活动免费"):
            if current_worker_thread and current_worker_thread.is_alive():
                print("[!] 运行中不能切换模式，请先 -q 停止。")
                continue
            CONFIG["FREE_EVENT_MODE"] = True
            CONFIG["TICKET_TYPE"] = 0
            load_greyzone_cache()
            print("[+] 已切换票券模式：TICKET_TYPE=0。")
            print_menu()
        elif cmd_prefix in ("-freeoff", "-freeofff", "-关闭免费", "-关闭限免"):
            if current_worker_thread and current_worker_thread.is_alive():
                print("[!] 运行中不能切换模式，请先 -q 停止。")
                continue
            if current_ticket_type() == 0:
                CONFIG["TICKET_TYPE"] = 2
            CONFIG["FREE_EVENT_MODE"] = False
            load_greyzone_cache()
            print("[+] 已恢复默认票券模式。")
            print_menu()
        elif cmd_prefix in ("-ticketcount", "-ticketnum", "-tc", "-许可证数量", "-票券数量"):
            if current_worker_thread and current_worker_thread.is_alive():
                print("[!] 运行中不能手动校准票券数量，请先 -q 停止。")
                continue
            parts = cmd.split()
            if len(parts) < 2:
                print("[!] 用法：-ticketcount 2950")
                continue
            if set_manual_ticket_count(parts[1]):
                load_greyzone_cache()
                print("[+] 已手动校准探查许可证数量：%s" % format_optional_int(get_greyzone_cache_snapshot().get("ticket1")))
                print_menu()
            else:
                print("[!] 探查许可证数量无效或超过安全上限。")
        elif cmd_prefix in ("-abort", "abort", "-ab", "-clear", "-退关", "-退出关卡", "-清理卡关"):
            if current_worker_thread and current_worker_thread.is_alive():
                print("[!] 灰域自动彩蛋正在运行，已先请求停止并尝试清理当前灰域关卡。")
                request_stop()
            manual_abort_current_greyzone()
            print_menu()
        elif cmd_prefix in ("-e", "-exit", "exit", "quit"):
            request_stop()
            if current_worker_thread and current_worker_thread.is_alive():
                current_worker_thread.join(timeout=5)
                if current_worker_thread and current_worker_thread.is_alive():
                    print("[!] 当前彩蛋任务仍在执行，已请求停止，返回菜单前可能仍需等待游戏接口完成。")
            print("[*] 已返回少女全自动 GFAM 主菜单。")
            return 0
        else:
            print("[!] 未识别输入：%s" % cmd)
            print_menu()


if __name__ == "__main__":
    if not apply_gfam_selected_server():
        sys.exit(1)
    load_greyzone_cache()
    if apply_gfam_auth_from_env():
        print("[*] 灰域自动彩蛋配置已就绪。")
    else:
        print("[!] 未检测到 GFAM 主菜单提供的 UID/SIGN。请从 GFAM 主菜单进入本模块。")
    sys.exit(main_loop())
