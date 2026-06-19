# -*- coding: utf-8 -*-
"""
少女全自动（GFAM）妖精自动建造 / 自动强化后台循环。

已根据实测抓包适配：
- 领取妖精建造：Fairy/finishAllDevelop，payload={"if_quick": 0}
- 开始妖精建造：Fairy/develop，payload 使用最低公式 500/500/500/500
- 妖精强化：Fairy/eatFairy，payload={"fairy_with_user_id": 目标UID, "food": [材料UID...]}

运行方式：
- 由 GFAM 主菜单 fairy 开关控制。
- 功能模块运行期间，run_windows.bat 会在后台启动本脚本。
- 主功能模块退出时，后台妖精循环会一并停止。
"""

import os
import sys
import time
import json
import traceback
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GFLZIRC_CORE_DIR = os.path.join(ROOT_DIR, "libs", "ZIRC", "src", "core")
if GFLZIRC_CORE_DIR not in sys.path:
    sys.path.insert(0, GFLZIRC_CORE_DIR)

try:
    from gflzirc import GFLClient, SERVERS, DEFAULT_SIGN
except Exception:
    GFLClient = None
    SERVERS = {}
    DEFAULT_SIGN = ""

try:
    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()
except Exception:
    pass

try:
    from gflzirc import API_INDEX_INDEX
except Exception:
    API_INDEX_INDEX = "Index/index"


# === 基础配置 ===
FAIRY_BUILD_RESOURCE = 500
DEFAULT_INTERVAL_SECONDS = 45
MAX_CONSECUTIVE_FAIRY_ERRORS = 5
INDEX_REFRESH_INTERVAL_SECONDS = int(os.environ.get("GFAM_FAIRY_INDEX_REFRESH_INTERVAL", "1800"))
FINISH_POLL_INTERVAL_SECONDS = int(os.environ.get("GFAM_FAIRY_FINISH_POLL_INTERVAL", str(DEFAULT_INTERVAL_SECONDS)))
STRENGTHEN_ALWAYS = os.environ.get("GFAM_FAIRY_AUTO_STRENGTHEN_ALWAYS", "1") not in ("0", "false", "False", "off", "no")

# 抓包中的 develop_fairy_act_info 只有 start_time，没有 finish_time / remain_time。
# 500x4 最低妖精建造通常按 5 小时处理；若后续 Index 出现 finish_time/remain_time，会优先使用真实字段。
DEFAULT_FAIRY_BUILD_SECONDS = int(os.environ.get("GFAM_FAIRY_BUILD_SECONDS", str(5 * 3600)))

# 500x4 妖精建造在 Index/index 中通常只有 start_time，没有 finish_time/remain_time。
# 根据用户提供的“2 建造中 + 2 待领取”Index 校准：fairy_id=2 的最低公式建造时间为 3小时30分。
# 其他妖精暂按默认 5 小时；后续如有新样本，只需要继续补这个表。
FAIRY_BUILD_SECONDS_BY_ID = {
    2: int(os.environ.get("GFAM_FAIRY_BUILD_SECONDS_ID_2", str(3 * 3600 + 30 * 60))),
}

def fairy_build_seconds_for(fairy_id):
    try:
        fairy_id = int(fairy_id)
    except Exception:
        fairy_id = 0
    return int(FAIRY_BUILD_SECONDS_BY_ID.get(fairy_id, DEFAULT_FAIRY_BUILD_SECONDS))

# 如果妖精仓库空位小于一次可批量建造数量，则先强化腾位置。
CACHE_FILE = os.path.join(ROOT_DIR, ".gfam_fairy_auto_cache.json")
LOG_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "gfam_fairy_auto.log")

# 缓存文件同时承担两类用途：
# 1) 后台循环的操作计数/冷却状态；
# 2) 前台模块状态面板显示的妖精仓库、建造栏位等快照。
# 注意：后台循环不能用“只有计数字段的 state”直接覆盖整个缓存，否则会把前台刚从 Index/index
# 写入的仓库/栏位快照清空，导致面板显示 0/0、未更新。
FAIRY_STATE_KEYS = {
    "build_attempts",
    "build_success",
    "finish_attempts",
    "finish_success",
    "strengthen_attempts",
    "strengthen_success",
    "last_finish_poll_at",
    "finish_disabled_until",
    "strengthen_disabled_until",
    "build_disabled_until",
    "last_loop_at",
    "last_loop_ok",
    "last_index_refresh_at",
}

API_FAIRY_FINISH_ALL_DEVELOP = "Fairy/finishAllDevelop"
API_FAIRY_DEVELOP = "Fairy/develop"
API_FAIRY_EAT_FAIRY = "Fairy/eatFairy"

READY_FLAG_KEYS = (
    "is_finish", "is_finished", "finished", "finish",
    "is_complete", "is_completed", "complete", "completed",
    "is_ready", "ready", "can_finish", "can_get", "is_get",
)
STATUS_KEYS = ("status", "state", "build_status", "develop_status")
REMAIN_KEYS = ("remain_time", "remaining_time", "left_time", "time_left")
FINISH_TIME_KEYS = ("finish_time", "end_time", "build_finish_time", "complete_time", "finished_at")


def truthy_flag(value):
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "ready", "finish", "finished", "complete", "completed", "done", "get", "can_get"):
        return True
    if text in ("0", "false", "no", "n", "building", "running", "developing", "pending", "none", ""):
        return False
    try:
        return int(float(text)) > 0
    except Exception:
        return False


def explicit_ready_flag(item, source_key):
    if not isinstance(item, dict):
        return False
    for key in READY_FLAG_KEYS:
        if key in item and truthy_flag(item.get(key)):
            return True
    for key in STATUS_KEYS:
        if key in item:
            text = str(item.get(key)).strip().lower()
            if text in ("ready", "finish", "finished", "complete", "completed", "done", "can_get"):
                return True
    # 注意：实测 Index/index 中，妖精仍在建造时 develop_fairy_act_info 也会预先包含
    # fairy_id/passive_skill/quality_lv 等结果字段；这些字段不能作为“待领取”依据。
    # 只有明确完成标记、明确完成状态、remain_time<=0、finish_time<=now，或估算时间已到，
    # 才能判定为待领取。
    return False


def first_present_int(item, keys, default=0):
    for key in keys:
        if isinstance(item, dict) and key in item:
            return int_safe(item.get(key), default)
    return default


def _now_ts():
    return int(time.time())


def _ts_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    line = "[%s] %s" % (_ts_text(), msg)
    try:
        _ensure_log_dir()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if os.environ.get("GFAM_FAIRY_AUTO_VERBOSE", "0") == "1":
        print(line)


def int_safe(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def merge_state_to_cache(state):
    """只把后台循环计数/冷却状态写回缓存，保留当前账号的 Index 快照。"""
    try:
        cache = read_json(CACHE_FILE, {})
        if not isinstance(cache, dict) or not cache_matches_current_identity(cache):
            cache = {}
            stamp_cache_identity(cache)
        if isinstance(state, dict):
            for key in FAIRY_STATE_KEYS:
                if key in state:
                    cache[key] = state[key]
        write_json(CACHE_FILE, cache)
    except Exception:
        try:
            write_json(CACHE_FILE, state if isinstance(state, dict) else {})
        except Exception:
            pass


def load_loop_state():
    """从缓存中只抽取当前账号后台循环需要维护的字段。"""
    cache = read_json(CACHE_FILE, {})
    if not isinstance(cache, dict) or not cache_matches_current_identity(cache):
        return {}
    return {k: cache.get(k) for k in FAIRY_STATE_KEYS if k in cache}


def is_error_response(resp):
    if not isinstance(resp, dict):
        return True
    return bool(resp.get("error") or resp.get("error_local"))


def compact_error(resp):
    if isinstance(resp, dict):
        return str(resp.get("error_local") or resp.get("error") or resp)[:300]
    return str(resp)[:300]


def request_index(client):
    payload = {"time": _now_ts(), "furniture_data": False}
    resp = client.send_request(API_INDEX_INDEX, payload)
    if is_error_response(resp):
        log("Index/index 请求失败：%s" % compact_error(resp))
        return None
    return resp


def refresh_cache_from_index_after_action(client, state, reason="妖精动作后本地更新"):
    """妖精动作成功后不再立即请求 Index/index。

    领取/建造/强化成功后，优先依赖动作返回结果与本地缓存更新：
    - 领取成功：apply_local_finish_to_cache() 已移除待领取栏位并增加妖精仓库数量；
    - 建造成功：apply_local_start_build_to_cache() 已写入本地 start/expected_finish_time；
    - 强化成功：apply_local_strengthen_to_cache() 已按材料数量扣减本地仓库。

    Index/index 只保留给低频校准、缓存缺失、切账号/切服务器、或明显不可信的异常恢复。
    """
    if isinstance(state, dict):
        state["last_local_action_at"] = _now_ts()
    log("%s：已按本地缓存更新，未请求 Index/index。" % reason)
    return None

def user_info(payload):
    return payload.get("user_info", {}) if isinstance(payload, dict) else {}


def payload_uid(payload):
    ui = user_info(payload)
    return str(ui.get("user_id") or ui.get("id") or "").strip()


def current_uid():
    return str(os.environ.get("GFAM_USER_UID") or os.environ.get("USER_UID") or "").strip()


def current_server():
    return str(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "").strip()


def cache_matches_current_identity(cache):
    if not isinstance(cache, dict):
        return False
    uid = current_uid()
    server = current_server()
    cache_uid = str(cache.get("cache_uid") or "").strip()
    cache_server = str(cache.get("cache_server") or "").strip()
    if uid and cache_uid and uid != cache_uid:
        return False
    if server and cache_server and server != cache_server:
        return False
    return True


def stamp_cache_identity(cache, payload=None):
    if not isinstance(cache, dict):
        cache = {}
    uid = payload_uid(payload) if payload is not None else current_uid()
    if uid:
        cache["cache_uid"] = uid
    server = current_server()
    if server:
        cache["cache_server"] = server
    return cache


def get_resources(payload):
    ui = user_info(payload)
    return {
        "mp": int_safe(ui.get("mp"), 0),
        "ammo": int_safe(ui.get("ammo"), 0),
        "mre": int_safe(ui.get("mre"), 0),
        "part": int_safe(ui.get("part"), 0),
    }


def iter_fairies(payload):
    data = payload.get("fairy_with_user_info", {}) if isinstance(payload, dict) else {}
    if isinstance(data, dict):
        iterable = data.values()
    elif isinstance(data, list):
        iterable = data
    else:
        iterable = []
    for item in iterable:
        if isinstance(item, dict):
            yield item


def get_fairy_inventory(payload):
    fairies = list(iter_fairies(payload))
    max_fairy = int_safe(user_info(payload).get("max_fairy"), 0)
    if max_fairy <= 0:
        max_fairy = len(fairies)
    return {
        "count": len(fairies),
        "max": max_fairy,
        "free": max(0, max_fairy - len(fairies)),
    }


def get_unlocked_fairy_build_slot_count(payload):
    """
    Index/user_info.max_equip_build_slot 是装备/妖精建造偶数栏位上限。
    你的抓包中 max_equip_build_slot=8，对应妖精建造栏位 2/4/6/8，共 4 个。
    基础 2 栏时通常对应 max_equip_build_slot=4。
    """
    ui = user_info(payload)
    raw = int_safe(ui.get("max_equip_build_slot", ui.get("max_build_slot", 4)), 4)
    if raw <= 0:
        return 2
    return max(1, raw // 2)


def get_fairy_slot_numbers(payload):
    count = get_unlocked_fairy_build_slot_count(payload)
    return [2 * i for i in range(1, count + 1)]


def has_active_fairy_build_payload(item):
    """判断 develop_fairy_act_info 中某个栏位是否真的有妖精建造任务。"""
    if not isinstance(item, dict) or not item:
        return False
    if int_safe(item.get("start_time"), 0) > 0:
        return True
    # remain_time>0 可确认正在建造；remain_time=0 单独出现时可能只是空栏位占位，
    # 不能作为待领取依据，除非同时有 fairy_id/passive_skill/完成标记等结果字段。
    if first_present_int(item, REMAIN_KEYS, -1) > 0:
        return True
    if first_present_int(item, FINISH_TIME_KEYS, 0) > 0:
        return True
    if explicit_ready_flag(item, "develop_fairy_act_info"):
        return True
    # 注意：fairy_id/passive_skill 在建造中、甚至空栏位占位记录里都可能存在，
    # 不能单独作为“占用/待领取”依据。必须依赖 start_time、remain_time、finish_time、
    # 明确完成标记，或最低公式资源字段。
    if int_safe(item.get("input_level"), 0) == 1 and all(int_safe(item.get(k), 0) >= FAIRY_BUILD_RESOURCE for k in ("mp", "ammo", "mre", "part")):
        return True
    return False


def looks_like_fairy_build(item, source_key):
    """只把真实妖精建造任务计入妖精栏位，避免空栏位/装备建造误判。"""
    if not isinstance(item, dict):
        return False
    if source_key == "develop_fairy_act_info":
        return has_active_fairy_build_payload(item)
    if source_key == "develop_equip_act_info":
        return False
    return False


def iter_fairy_build_records(payload):
    if not isinstance(payload, dict):
        return
    for source_key in ("develop_fairy_act_info", "develop_equip_act_info"):
        info = payload.get(source_key, {})
        if isinstance(info, dict):
            pairs = info.items()
        elif isinstance(info, list):
            pairs = enumerate(info, start=1)
        else:
            pairs = []
        for fallback_slot, item in pairs:
            if not isinstance(item, dict):
                continue
            if not looks_like_fairy_build(item, source_key):
                continue
            yield source_key, fallback_slot, item


def get_active_fairy_builds(payload):
    now = _now_ts()
    result = []
    for source_key, fallback_slot, item in iter_fairy_build_records(payload) or []:
        slot = int_safe(item.get("build_slot", item.get("slot", fallback_slot)), int_safe(fallback_slot, 0))

        explicit_ready = explicit_ready_flag(item, source_key)
        finish_time = first_present_int(item, FINISH_TIME_KEYS, 0)
        remain = first_present_int(item, REMAIN_KEYS, 0)
        status_source = "estimated"

        if explicit_ready:
            remain = 0
            expected_finish_time = now
            status_source = "explicit_ready"
        elif finish_time > 0:
            remain = max(0, finish_time - now)
            expected_finish_time = finish_time
            status_source = "finish_time"
        elif remain > 0:
            expected_finish_time = now + remain
            status_source = "remain_time"
        else:
            start_time = int_safe(item.get("start_time"), 0)
            if start_time > 0:
                expected_finish_time = start_time + fairy_build_seconds_for(item.get("fairy_id", 0))
                remain = max(0, expected_finish_time - now)
                status_source = "start_time_estimated"
            else:
                expected_finish_time = now
                remain = 0
                status_source = "no_time_ready"

        result.append({
            "slot": slot,
            "source": source_key,
            "remain": remain,
            "is_ready": remain <= 0,
            "status_source": status_source,
            "expected_finish_time": expected_finish_time,
            "fairy_id": int_safe(item.get("fairy_id"), 0),
            "passive_skill": int_safe(item.get("passive_skill"), 0),
            "quality_lv": int_safe(item.get("quality_lv"), 0),
            "raw": item,
        })

    seen = set()
    unique = []
    for b in result:
        key = (b.get("slot"), b.get("expected_finish_time"), b.get("fairy_id"), b.get("passive_skill"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)
    return unique


def build_status_counts(builds):
    ready = sum(1 for b in builds if int_safe(b.get("remain"), 1) <= 0)
    building = max(0, len(builds) - ready)
    return building, ready, len(builds)


def recompute_builds_by_local_timer(builds):
    """仅按缓存中的 expected_finish_time 本地倒计时，不请求 Index/index。"""
    now = _now_ts()
    result = []
    for item in builds or []:
        if not isinstance(item, dict):
            continue
        b = dict(item)
        expected = int_safe(b.get("expected_finish_time"), 0)
        if expected > 0:
            remain = max(0, expected - now)
        else:
            remain = max(0, int_safe(b.get("remain"), 0))
            if remain > 0:
                expected = now + remain
        b["expected_finish_time"] = expected
        b["remain"] = remain
        b["is_ready"] = remain <= 0
        if b.get("status_source") in ("", None):
            b["status_source"] = "local_timer"
        result.append(b)
    return result


def normalize_cache_local_timer(cache):
    """刷新当前账号缓存中的建造中/待领取统计，只使用本地时间。"""
    if not isinstance(cache, dict) or not cache_matches_current_identity(cache):
        cache = {}
        stamp_cache_identity(cache)
    builds = recompute_builds_by_local_timer(cache.get("active_builds", []))
    building_count, ready_count, occupied_count = build_status_counts(builds)
    cache["active_builds"] = builds
    cache["ready_builds"] = ready_count
    cache["building_builds"] = building_count
    cache["occupied_builds"] = occupied_count
    cache["local_timer_updated_at"] = _now_ts()
    return cache


def write_cache_local_timer(cache):
    cache = normalize_cache_local_timer(cache)
    write_json(CACHE_FILE, cache)
    return cache


def get_cached_resources(cache):
    res = cache.get("resources") if isinstance(cache, dict) else {}
    if not isinstance(res, dict):
        res = {}
    return {
        "mp": int_safe(res.get("mp"), 0),
        "ammo": int_safe(res.get("ammo"), 0),
        "mre": int_safe(res.get("mre"), 0),
        "part": int_safe(res.get("part"), 0),
    }


def calc_resource_batches_from_cache(cache):
    res = get_cached_resources(cache)
    return min(res[k] // FAIRY_BUILD_RESOURCE for k in ("mp", "ammo", "mre", "part"))


def calc_build_count_from_cache(cache):
    cache = normalize_cache_local_timer(cache)
    slots = int_safe(cache.get("build_slots"), 0)
    if slots <= 0:
        return 0, {"reason": "no_build_slots"}
    slot_numbers = cache.get("slot_numbers") if isinstance(cache.get("slot_numbers"), list) else [2 * i for i in range(1, slots + 1)]
    active = cache.get("active_builds", []) if isinstance(cache.get("active_builds"), list) else []
    occupied = len(active)
    free_slots = max(0, slots - occupied)
    inv = cache.get("fairy_inventory") if isinstance(cache.get("fairy_inventory"), dict) else {}
    fairy_free = max(0, int_safe(inv.get("free"), 0))
    resource_batches = calc_resource_batches_from_cache(cache)
    count = max(0, min(free_slots, fairy_free, resource_batches))
    return count, {
        "slots": slots,
        "slot_numbers": slot_numbers,
        "active": int_safe(cache.get("building_builds"), 0),
        "ready": int_safe(cache.get("ready_builds"), 0),
        "occupied": occupied,
        "free_slots": free_slots,
        "fairy_free": fairy_free,
        "resource_batches": resource_batches,
    }


def apply_local_finish_to_cache(added_count):
    """领取成功后本地更新缓存：移除待领取栏位，妖精仓库数量增加。"""
    cache = write_cache_local_timer(read_json(CACHE_FILE, {}))
    added_count = max(0, int_safe(added_count, 0))
    if added_count <= 0:
        return cache
    builds = cache.get("active_builds", []) if isinstance(cache.get("active_builds"), list) else []
    ready = [b for b in builds if int_safe(b.get("remain"), 1) <= 0]
    ready_to_remove = min(len(ready), added_count)
    removed = 0
    new_builds = []
    for b in builds:
        if int_safe(b.get("remain"), 1) <= 0 and removed < ready_to_remove:
            removed += 1
            continue
        new_builds.append(b)
    cache["active_builds"] = new_builds
    inv = cache.get("fairy_inventory") if isinstance(cache.get("fairy_inventory"), dict) else {}
    max_fairy = int_safe(inv.get("max"), 0)
    count = int_safe(inv.get("count"), 0) + added_count
    if max_fairy > 0:
        count = min(count, max_fairy)
    inv["count"] = count
    inv["free"] = max(0, max_fairy - count) if max_fairy > 0 else max(0, int_safe(inv.get("free"), 0) - added_count)
    cache["fairy_inventory"] = inv
    cache["local_action_at"] = _now_ts()
    return write_cache_local_timer(cache)


def apply_local_strengthen_to_cache(material_count):
    """强化成功后本地更新妖精仓库数量，避免为此请求 Index/index。"""
    cache = write_cache_local_timer(read_json(CACHE_FILE, {}))
    material_count = max(0, int_safe(material_count, 0))
    if material_count <= 0:
        return cache
    inv = cache.get("fairy_inventory") if isinstance(cache.get("fairy_inventory"), dict) else {}
    max_fairy = int_safe(inv.get("max"), 0)
    count = max(0, int_safe(inv.get("count"), 0) - material_count)
    inv["count"] = count
    inv["free"] = max(0, max_fairy - count) if max_fairy > 0 else int_safe(inv.get("free"), 0) + material_count
    cache["fairy_inventory"] = inv
    cache["local_action_at"] = _now_ts()
    return write_cache_local_timer(cache)


def apply_local_start_build_to_cache(build_count):
    """开始建造成功后，用本地时间生成虚拟建造栏位，避免立刻请求 Index/index。"""
    cache = write_cache_local_timer(read_json(CACHE_FILE, {}))
    build_count = max(0, int_safe(build_count, 0))
    if build_count <= 0:
        return cache
    slots = int_safe(cache.get("build_slots"), 0)
    if slots <= 0:
        return cache
    slot_numbers = cache.get("slot_numbers") if isinstance(cache.get("slot_numbers"), list) else [2 * i for i in range(1, slots + 1)]
    builds = cache.get("active_builds", []) if isinstance(cache.get("active_builds"), list) else []
    occupied_slots = {int_safe(b.get("slot"), 0) for b in builds if isinstance(b, dict)}
    free_slot_numbers = [s for s in slot_numbers if int_safe(s, 0) not in occupied_slots]
    now = _now_ts()
    for slot in free_slot_numbers[:build_count]:
        builds.append({
            "slot": int_safe(slot, 0),
            "source": "local_start_build",
            "fairy_id": 0,
            "passive_skill": 0,
            "remain": DEFAULT_FAIRY_BUILD_SECONDS,
            "is_ready": False,
            "status_source": "local_started_estimated",
            "expected_finish_time": now + DEFAULT_FAIRY_BUILD_SECONDS,
        })
    cache["active_builds"] = builds
    res = get_cached_resources(cache)
    for k in ("mp", "ammo", "mre", "part"):
        res[k] = max(0, res[k] - build_count * FAIRY_BUILD_RESOURCE)
    cache["resources"] = res
    cache["local_action_at"] = now
    return write_cache_local_timer(cache)

def calc_resource_batches(payload):
    res = get_resources(payload)
    return min(res[k] // FAIRY_BUILD_RESOURCE for k in ("mp", "ammo", "mre", "part"))


def calc_build_count(payload):
    active = get_active_fairy_builds(payload)
    building_count, ready_count, occupied_count = build_status_counts(active)
    slots = get_unlocked_fairy_build_slot_count(payload)
    # 待领取栏位仍然占用建造栏，不能算作空栏。
    free_slots = max(0, slots - occupied_count)
    inv = get_fairy_inventory(payload)
    resource_batches = calc_resource_batches(payload)
    count = max(0, min(free_slots, inv["free"], resource_batches))
    return count, {
        "slots": slots,
        "slot_numbers": get_fairy_slot_numbers(payload),
        "active": building_count,
        "ready": ready_count,
        "occupied": occupied_count,
        "free_slots": free_slots,
        "fairy_free": inv["free"],
        "resource_batches": resource_batches,
    }


def save_cache_from_index(payload):
    builds = get_active_fairy_builds(payload)
    building_count, ready_count, occupied_count = build_status_counts(builds)
    cache = read_json(CACHE_FILE, {})
    if not isinstance(cache, dict) or not cache_matches_current_identity(cache):
        cache = {k: cache.get(k, 0) for k in FAIRY_STATE_KEYS} if isinstance(cache, dict) else {}
    stamp_cache_identity(cache, payload)
    build_slots = get_unlocked_fairy_build_slot_count(payload)
    cache.update({
        "updated_at": _now_ts(),
        "last_index_at": _now_ts(),
        "fairy_inventory": get_fairy_inventory(payload),
        "resources": get_resources(payload),
        "build_slots": build_slots,
        "slot_numbers": get_fairy_slot_numbers(payload),
        "active_builds": [
            {
                "slot": b["slot"],
                "source": b.get("source", ""),
                "fairy_id": b.get("fairy_id", 0),
                "passive_skill": b.get("passive_skill", 0),
                "remain": b["remain"],
                "is_ready": int_safe(b.get("remain"), 1) <= 0,
                "status_source": b.get("status_source", ""),
                "expected_finish_time": b["expected_finish_time"],
            }
            for b in builds
        ],
        "ready_builds": ready_count,
        "building_builds": building_count,
        "occupied_builds": occupied_count,
    })
    write_cache_local_timer(cache)

def send_request(client, endpoint, payload, action_name):
    try:
        resp = client.send_request(endpoint, payload)
    except Exception as e:
        resp = {"error_local": str(e)}

    if is_error_response(resp):
        log("%s 失败：endpoint=%s payload=%s error=%s" % (action_name, endpoint, payload, compact_error(resp)))
        return False, resp

    log("%s 成功：endpoint=%s payload=%s resp=%s" % (action_name, endpoint, payload, str(resp)[:500]))
    return True, resp


def finish_all_fairy_develop(client, if_quick=0):
    # 正常等待倒计时结束后领取，if_quick=0；保留 if_quick 参数仅用于兼容接口。
    if_quick = 1 if int_safe(if_quick, 0) else 0
    action = "快速领取全部妖精建造" if if_quick else "领取全部已完成妖精建造"
    return send_request(client, API_FAIRY_FINISH_ALL_DEVELOP, {"if_quick": if_quick}, action)


def start_fairy_develop(client, build_multi, build_quick=0):
    build_multi = max(1, int_safe(build_multi, 1))
    payload = {
        "build_slot": 0,
        "build_multi": build_multi,
        "mp": FAIRY_BUILD_RESOURCE,
        "ammo": FAIRY_BUILD_RESOURCE,
        "mre": FAIRY_BUILD_RESOURCE,
        "part": FAIRY_BUILD_RESOURCE,
        "input_level": 1,
        "build_heavy": 1,
        "build_quick": 1 if int_safe(build_quick, 0) else 0,
    }
    return send_request(client, API_FAIRY_DEVELOP, payload, "开始妖精建造")


def fairy_uid(fairy):
    return int_safe(fairy.get("id", fairy.get("fairy_with_user_id")), 0)


def fairy_type_id(fairy):
    return int_safe(fairy.get("fairy_id", fairy.get("type_id")), 0)


def is_material_fairy(fairy):
    if fairy_uid(fairy) <= 0:
        return False
    if str(fairy.get("is_locked", "0")) == "1":
        return False
    if int_safe(fairy.get("team_id"), 0) > 0:
        return False
    return True


def is_strengthenable_target(fairy):
    if fairy_uid(fairy) <= 0:
        return False
    # 不把编入梯队的妖精作为强化目标，避免影响当前作战配置。
    if int_safe(fairy.get("team_id"), 0) > 0:
        return False
    qlv = int_safe(fairy.get("quality_lv"), 0)
    qexp = int_safe(fairy.get("quality_exp"), 0)
    # 可建造妖精 5星满开发值通常为 quality_lv=5 且 quality_exp>=3000。
    if qlv >= 5 and qexp >= 3000:
        return False
    return True


def material_score(material, target):
    """
    仅用于排序材料提交顺序：
    同名妖精倍率最高，其次同天赋，再按低等级低星优先吃。
    是否实际获得倍率由服务器计算。
    """
    score = 0
    if fairy_type_id(material) == fairy_type_id(target):
        score += 100000
    if int_safe(material.get("passive_skill"), 0) == int_safe(target.get("passive_skill"), 0):
        score += 10000
    # 原型妖精字段在当前抓包未确认；如果后续明确 fairy_id，可在这里加权。
    score -= int_safe(material.get("fairy_lv"), 0) * 10
    score -= int_safe(material.get("quality_lv"), 0) * 100
    score -= fairy_uid(material) % 1000
    return score


def choose_strengthen_target_and_materials(payload):
    fairies = list(iter_fairies(payload))

    targets = [f for f in fairies if is_strengthenable_target(f)]
    if not targets:
        return None, []

    # 优先强化 fairy_id=11 的空降妖精；没有可强化空降时，按等级从高到低选择其他可强化妖精。
    para_targets = [f for f in targets if fairy_type_id(f) == 11]
    para_targets.sort(
        key=lambda f: (
            int_safe(f.get("fairy_lv"), 0),
            int_safe(f.get("quality_lv"), 0),
            int_safe(f.get("quality_exp"), 0),
            fairy_uid(f),
        ),
        reverse=True,
    )
    if para_targets:
        target = para_targets[0]
    else:
        targets.sort(
            key=lambda f: (
                int_safe(f.get("fairy_lv"), 0),
                int_safe(f.get("quality_lv"), 0),
                int_safe(f.get("quality_exp"), 0),
                fairy_uid(f),
            ),
            reverse=True,
        )
        target = targets[0]

    target_uid = fairy_uid(target)
    materials = [f for f in fairies if is_material_fairy(f) and fairy_uid(f) != target_uid]
    materials.sort(key=lambda f: material_score(f, target), reverse=True)

    # 接口可接受较长 food 列表；为降低风险，每次最多吃 30 只，和你抓包里的 29 只规模接近。
    mat_uids = [fairy_uid(f) for f in materials if fairy_uid(f) > 0][:30]
    return target, mat_uids


def strengthen_fairy(client, target, mat_uids):
    if not target or not mat_uids:
        return False, {"error_local": "没有可强化目标或材料"}
    payload = {
        "fairy_with_user_id": fairy_uid(target),
        "food": [int(x) for x in mat_uids],
    }
    return send_request(client, API_FAIRY_EAT_FAIRY, payload, "妖精强化")


def should_strengthen_before_build(payload):
    inv = get_fairy_inventory(payload)
    slot_count = get_unlocked_fairy_build_slot_count(payload)
    # 空位不足以进行一次完整批量建造时，先强化腾空位。
    return inv["free"] < slot_count


def run_once(client, state):
    payload = request_index(client)
    if not payload:
        return False

    save_cache_from_index(payload)
    state["last_index_refresh_at"] = _now_ts()
    inv = get_fairy_inventory(payload)
    active = get_active_fairy_builds(payload)
    build_count, build_meta = calc_build_count(payload)

    log("状态：妖精仓库 %s/%s，空位 %s；妖精建造栏 %s 个 %s，占用 %s（建造中 %s / 待领取 %s），可建造 %s" % (
        inv["count"],
        inv["max"],
        inv["free"],
        build_meta["slots"],
        build_meta["slot_numbers"],
        build_meta["occupied"],
        build_meta["active"],
        build_meta["ready"],
        build_count,
    ))

    # 1. 已完成则一次性领取全部完成的妖精建造。
    # 说明：部分服务器 Index 只有 start_time，没有准确 finish_time/remain_time；因此即使估算未完成，
    # 也会按较低频率轮询一次领取接口，避免游戏内已经完成但面板仍显示“建造中”。
    building_count, ready_count, occupied_count = build_status_counts(active)
    should_poll_finish = occupied_count > 0 and (_now_ts() - int_safe(state.get("last_finish_poll_at"), 0) >= FINISH_POLL_INTERVAL_SECONDS)
    if (ready_count > 0 or should_poll_finish) and _now_ts() >= int_safe(state.get("finish_disabled_until"), 0):
        state["last_finish_poll_at"] = _now_ts()
        ok, resp = finish_all_fairy_develop(client)
        state["finish_attempts"] = state.get("finish_attempts", 0) + 1
        added = resp.get("fairy_with_user_add_list", []) if isinstance(resp, dict) else []
        added_count = len(added) if isinstance(added, list) else 0
        if ok and added_count > 0:
            state["finish_success"] = state.get("finish_success", 0) + 1
            log("领取妖精建造结果：%s 个。%s" % (added_count, added))
        elif ok:
            # 接口成功但没有新增妖精，多半只是当前没有真正完成的栏位；不记为成功，也不长时间禁用。
            log("领取妖精建造检查完成：当前没有可领取妖精。")
        else:
            # 领取失败通常是暂未完成或服务端同步中，只短暂降频，避免一旦有栏位完成仍长时间不领取。
            state["finish_disabled_until"] = _now_ts() + max(30, FINISH_POLL_INTERVAL_SECONDS)
            log("领取妖精建造失败，短暂降频后再试。")
        if added_count > 0:
            apply_local_finish_to_cache(added_count)
            refreshed = refresh_cache_from_index_after_action(client, state, reason="妖精领取成功后本地更新")
            if refreshed:
                payload = refreshed

    # 2. 自动强化：默认每轮最多尝试一次；若你想只在仓库紧张时强化，可设置 GFAM_FAIRY_AUTO_STRENGTHEN_ALWAYS=0。
    if (STRENGTHEN_ALWAYS or should_strengthen_before_build(payload)) and _now_ts() >= int_safe(state.get("strengthen_disabled_until"), 0):
        target, materials = choose_strengthen_target_and_materials(payload)
        if target and materials:
            ok, resp = strengthen_fairy(client, target, materials)
            state["strengthen_attempts"] = state.get("strengthen_attempts", 0) + 1
            if ok:
                state["strengthen_success"] = state.get("strengthen_success", 0) + 1
                log("妖精强化成功：目标 UID=%s fairy_id=%s Lv.%s 星级=%s，材料=%s只，返回=%s" % (
                    fairy_uid(target),
                    fairy_type_id(target),
                    target.get("fairy_lv", "-"),
                    target.get("quality_lv", "-"),
                    len(materials),
                    resp,
                ))
                apply_local_strengthen_to_cache(len(materials))
                refreshed = refresh_cache_from_index_after_action(client, state, reason="妖精强化成功后本地更新")
                if refreshed:
                    payload = refreshed
            else:
                state["strengthen_disabled_until"] = _now_ts() + 600
                log("妖精强化失败，暂停强化动作 10 分钟。")
        else:
            log("当前没有可强化目标或未上锁材料。")

    # 3. 如果有空建造栏、资源和妖精仓库空位，按最低公式批量建造。
    build_count, build_meta = calc_build_count(payload)
    if build_count > 0 and _now_ts() >= int_safe(state.get("build_disabled_until"), 0):
        ok, resp = start_fairy_develop(client, build_count)
        state["build_attempts"] = state.get("build_attempts", 0) + 1
        if ok:
            state["build_success"] = state.get("build_success", 0) + 1
            equip_ids = resp.get("equip_ids", []) if isinstance(resp, dict) else []
            log("已开始妖精建造：build_multi=%s，返回预览=%s" % (build_count, equip_ids))
            apply_local_start_build_to_cache(build_count)
            refreshed = refresh_cache_from_index_after_action(client, state, reason="妖精建造启动成功后本地更新")
            if refreshed:
                payload = refreshed
        else:
            state["build_disabled_until"] = _now_ts() + 600
            log("开始妖精建造失败，暂停建造动作 10 分钟。")
    else:
        if build_count <= 0:
            log("当前不满足继续妖精建造条件：%s" % build_meta)

    return True



def run_once_from_cache(client, state):
    """不请求 Index/index，只使用本地缓存计时处理妖精领取/继续建造。"""
    cache = write_cache_local_timer(read_json(CACHE_FILE, {}))
    if not cache.get("updated_at"):
        return False

    active = cache.get("active_builds", []) if isinstance(cache.get("active_builds"), list) else []
    building_count, ready_count, occupied_count = build_status_counts(active)

    # 1. 本地倒计时显示已完成时才尝试领取；未完成时不反复请求 Index/index。
    if ready_count > 0 and _now_ts() >= int_safe(state.get("finish_disabled_until"), 0):
        ok, resp = finish_all_fairy_develop(client)
        state["finish_attempts"] = state.get("finish_attempts", 0) + 1
        added = resp.get("fairy_with_user_add_list", []) if isinstance(resp, dict) else []
        added_count = len(added) if isinstance(added, list) else 0
        if ok and added_count > 0:
            state["finish_success"] = state.get("finish_success", 0) + 1
            log("本地计时触发领取：%s 个。%s" % (added_count, added))
            cache = apply_local_finish_to_cache(added_count)
            refreshed = refresh_cache_from_index_after_action(client, state, reason="本地倒计时领取成功后本地更新")
            if refreshed:
                cache = write_cache_local_timer(read_json(CACHE_FILE, {}))
        elif ok:
            # 本地估算可能略早，短暂延后，仍不请求 Index。
            state["finish_disabled_until"] = _now_ts() + 300
            log("本地计时触发领取，但当前没有可领取妖精；延后 5 分钟再试。")
        else:
            state["finish_disabled_until"] = _now_ts() + 600
            log("本地计时领取失败，延后 10 分钟再试：%s" % compact_error(resp))

    # 2. 领取后如果本地缓存显示有空栏、仓库空位和资源，直接建造并本地写入预计完成时间。
    cache = write_cache_local_timer(read_json(CACHE_FILE, {}))
    build_count, build_meta = calc_build_count_from_cache(cache)
    if build_count > 0 and _now_ts() >= int_safe(state.get("build_disabled_until"), 0):
        ok, resp = start_fairy_develop(client, build_count)
        state["build_attempts"] = state.get("build_attempts", 0) + 1
        if ok:
            state["build_success"] = state.get("build_success", 0) + 1
            log("本地缓存触发妖精建造：build_multi=%s，返回预览=%s" % (build_count, str(resp)[:300]))
            apply_local_start_build_to_cache(build_count)
            refreshed = refresh_cache_from_index_after_action(client, state, reason="本地缓存建造启动成功后本地更新")
            if refreshed:
                cache = write_cache_local_timer(read_json(CACHE_FILE, {}))
        else:
            state["build_disabled_until"] = _now_ts() + 600
            log("本地缓存触发建造失败，暂停建造动作 10 分钟：%s" % compact_error(resp))
    return True


def format_inv(inv):
    return "%s/%s，空位 %s" % (inv.get("count", 0), inv.get("max", 0), inv.get("free", 0))



def fairy_cache_requests_refresh(state):
    """决定本轮后台妖精循环是否需要请求 Index/index。

    主模块在 -a、运行前刷新、资源结算等位置已经会写妖精缓存；后台妖精循环只做低频校准。
    默认 1800 秒（30 分钟）请求一次 Index/index；如果想改成 1 小时，可设置：
        set GFAM_FAIRY_INDEX_REFRESH_INTERVAL=3600

    注意：即使缓存显示有待领取栏位，也不再每 45 秒强制拉 Index，避免后台妖精自动过于频繁
    打 Index/index。待领取/建造状态会在下一次低频校准或主模块请求 Index 时同步刷新。
    """
    now = _now_ts()
    cache = read_json(CACHE_FILE, {})
    if not isinstance(cache, dict) or not cache_matches_current_identity(cache) or not cache.get("updated_at"):
        return True
    last = int_safe(state.get("last_index_refresh_at"), 0)
    cache_updated = int_safe(cache.get("updated_at"), 0)
    last = max(last, cache_updated)
    return (now - last) >= max(1800, INDEX_REFRESH_INTERVAL_SECONDS)


def worker_loop():
    if GFLClient is None:
        log("无法导入 gflzirc，妖精自动循环未启动。")
        return 1

    uid = os.environ.get("GFAM_USER_UID") or os.environ.get("USER_UID")
    sign = os.environ.get("GFAM_SIGN_KEY") or os.environ.get("SIGN_KEY")
    server = os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP"

    if not uid or not sign or sign == DEFAULT_SIGN:
        log("缺少 UID/SIGN，妖精自动循环未启动。")
        return 1
    if server not in SERVERS:
        log("未知服务器 %s，妖精自动循环未启动。" % server)
        return 1

    interval = max(15, int_safe(os.environ.get("GFAM_FAIRY_AUTO_INTERVAL"), DEFAULT_INTERVAL_SECONDS))
    client = GFLClient(uid, sign, SERVERS[server])
    state = load_loop_state()
    log("妖精自动建造/强化循环启动：server=%s loop_interval=%ss index_refresh=%ss build_seconds=%ss" % (
        server,
        interval,
        INDEX_REFRESH_INTERVAL_SECONDS,
        DEFAULT_FAIRY_BUILD_SECONDS,
    ))

    consecutive_errors = 0
    try:
        while True:
            try:
                if fairy_cache_requests_refresh(state):
                    ok = run_once(client, state)
                else:
                    ok = run_once_from_cache(client, state)
                state["last_loop_at"] = _now_ts()
                state["last_loop_ok"] = bool(ok)
                merge_state_to_cache(state)
                consecutive_errors = 0
            except KeyboardInterrupt:
                break
            except Exception:
                consecutive_errors += 1
                log("妖精自动循环异常（%d / %d）：\n%s" % (consecutive_errors, MAX_CONSECUTIVE_FAIRY_ERRORS, traceback.format_exc()))
                if consecutive_errors >= MAX_CONSECUTIVE_FAIRY_ERRORS:
                    log("妖精自动循环连续异常达到上限，已自动终止后台妖精模块。")
                    break
            time.sleep(interval)
    finally:
        merge_state_to_cache(state)
        log("妖精自动建造/强化循环结束。")
    return 0


if __name__ == "__main__":
    sys.exit(worker_loop())
