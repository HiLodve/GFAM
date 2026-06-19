# -*- coding: utf-8 -*-
"""GFAM 人形/装备自动制造后台循环。

已实装：
- 人形自动制造：Gun/developMultiGun / Gun/finishAllDevelop / Gun/retireGun
- 装备自动制造：Equip/developMulti / Equip/finishAllDevelop / Equip/retire

原则：
- 优先复用 GFAM 主菜单阶段写入的共享 Index 缓存，不重复请求 Index。
- 提交制造成功后，按返回的 gun_id/equip_id + slot 更新本地制造栏缓存。
- 默认不使用快速制造。
- 非保护产物进入 pending 队列并批量拆解。
- 人形/装备仓库至少保留 1 个空位给其它模块，避免仓库满导致新关卡无法开始。
"""
import os
import sys
import time
import json
import traceback
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parents[1]
GFLZIRC_CORE_DIR = ROOT_DIR / "libs" / "ZIRC" / "src" / "core"
if str(GFLZIRC_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(GFLZIRC_CORE_DIR))

try:
    from gflzirc import GFLClient, SERVERS, DEFAULT_SIGN, API_GUN_RETIRE
except Exception:
    GFLClient = None
    SERVERS = {}
    DEFAULT_SIGN = ""
    API_GUN_RETIRE = "Gun/retireGun"

try:
    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()
except Exception:
    pass

try:
    from gflzirc import API_INDEX_INDEX
except Exception:
    API_INDEX_INDEX = "Index/index"

try:
    from gfam_crossprocess_lock import RetireLock
except ImportError:
    RetireLock = None

API_GUN_DEVELOP_MULTI = "Gun/developMultiGun"
API_GUN_FINISH_ALL_DEVELOP = "Gun/finishAllDevelop"
API_EQUIP_DEVELOP_MULTI = "Equip/developMulti"
API_EQUIP_FINISH_ALL_DEVELOP = "Equip/finishAllDevelop"

READY_FLAG_KEYS = (
    "is_finish", "is_finished", "finished", "finish",
    "is_complete", "is_completed", "complete", "completed",
    "is_ready", "ready", "can_finish", "can_get", "is_get",
)
STATUS_KEYS = ("status", "state", "build_status", "develop_status")
REMAIN_KEYS = ("remain_time", "remaining_time", "left_time", "time_left")
FINISH_TIME_KEYS = ("finish_time", "end_time", "build_finish_time", "complete_time", "finished_at")

API_EQUIP_RETIRE = "Equip/retire"

STATE_FILE = ROOT_DIR / ".gfam_factory_state.json"
CACHE_FILE = ROOT_DIR / ".gfam_factory_auto_cache.json"
SHARED_INDEX_FILE = ROOT_DIR / ".gfam_index_cache.json"
WAREHOUSE_CACHE_FILE = ROOT_DIR / ".gfam_factory_warehouse_cache.json"
LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "gfam_factory_auto.log"
DATA_DIR = ROOT_DIR / "data"

RESOURCE_KEYS = ("mp", "ammo", "mre", "part")
RESOURCE_LABELS = {"mp": "人力", "ammo": "弹药", "mre": "口粮", "part": "零件"}

DOLL_FORMULAS = {
    "handgun": {"name": "手枪", "type": 1, "resources": {"mp": 130, "ammo": 130, "mre": 130, "part": 30}, "recommended": {233: "Px4 Storm / Px4风暴"}},
    "smg": {"name": "冲锋枪", "type": 2, "resources": {"mp": 400, "ammo": 400, "mre": 100, "part": 200}, "recommended": {115: "Suomi / 索米"}},
    "rifle": {"name": "步枪", "type": 3, "resources": {"mp": 400, "ammo": 100, "mre": 400, "part": 200}, "recommended": {}},
    "ar": {"name": "突击步枪", "type": 4, "resources": {"mp": 100, "ammo": 400, "mre": 400, "part": 200}, "recommended": {}},
    "mg": {"name": "机枪", "type": 5, "resources": {"mp": 800, "ammo": 800, "mre": 100, "part": 400}, "recommended": {}},
}

EQUIP_FORMULAS = {
    "optic": {"name": "光学瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}},
    "holo": {"name": "全息瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}},
    "red_dot": {"name": "红点瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}},
    "night": {"name": "夜战装备", "resources": {"mp": 70, "ammo": 10, "mre": 150, "part": 30}},
    "suppressor": {"name": "消音器", "resources": {"mp": 150, "ammo": 50, "mre": 50, "part": 50}},
    "ap": {"name": "穿甲弹", "resources": {"mp": 10, "ammo": 150, "mre": 90, "part": 100}},
    "status": {"name": "状态弹", "resources": {"mp": 180, "ammo": 180, "mre": 10, "part": 50}},
    "hv": {"name": "高速弹", "resources": {"mp": 10, "ammo": 230, "mre": 120, "part": 80}},
    "shotgun": {"name": "散弹", "resources": {"mp": 30, "ammo": 150, "mre": 30, "part": 130}},
    "exo": {"name": "外骨骼", "resources": {"mp": 100, "ammo": 80, "mre": 10, "part": 100}},
    "armor": {"name": "防弹插板", "resources": {"mp": 50, "ammo": 50, "mre": 100, "part": 100}},
    "ammo_box": {"name": "弹链箱", "resources": {"mp": 30, "ammo": 30, "mre": 30, "part": 200}},
    "cape": {"name": "伪装披风", "resources": {"mp": 180, "ammo": 20, "mre": 200, "part": 20}},
    "mixed": {"name": "装备混合", "resources": {"mp": 150, "ammo": 150, "mre": 150, "part": 150}},
    "backup_sight": {"name": "备用瞄具", "resources": {"mp": 180, "ammo": 65, "mre": 65, "part": 65}},
    "chip": {"name": "芯片", "resources": {"mp": 170, "ammo": 120, "mre": 50, "part": 50}},
    "special_ap": {"name": "特殊穿甲弹", "resources": {"mp": 10, "ammo": 300, "mre": 10, "part": 10}},
    "bipod": {"name": "固定脚架", "resources": {"mp": 300, "ammo": 10, "mre": 10, "part": 200}},
    "tube": {"name": "收缩管", "resources": {"mp": 80, "ammo": 220, "mre": 80, "part": 80}},
    "rangefinder": {"name": "测距仪", "resources": {"mp": 100, "ammo": 250, "mre": 150, "part": 170}},
}

INTERVAL_SECONDS = max(10, int(os.environ.get("GFAM_FACTORY_AUTO_INTERVAL", "45") or "45"))
FINISH_POLL_SECONDS = max(10, int(os.environ.get("GFAM_FACTORY_FINISH_POLL_INTERVAL", "45") or "45"))
SHARED_INDEX_TTL_SECONDS = int(os.environ.get("GFAM_SHARED_INDEX_TTL", "300") or "300")
MAX_CONSECUTIVE_ERRORS = 5
RESERVED_GUN_SLOTS = max(1, int(os.environ.get("GFAM_FACTORY_RESERVED_GUN_SLOTS", "1") or "1"))
RESERVED_EQUIP_SLOTS = max(1, int(os.environ.get("GFAM_FACTORY_RESERVED_EQUIP_SLOTS", "1") or "1"))
EQUIP_FALLBACK_DURATION = max(60, int(os.environ.get("GFAM_FACTORY_EQUIP_FALLBACK_DURATION", "1800") or "1800"))

# Large retire requests can take too long on the official server and may be
# reported locally as plaintext/timeout errors even when the request is still
# being processed.  Keep batches conservative to avoid false failure judgement.
RETIRE_BATCH_SIZE = max(20, int(os.environ.get("GFAM_FACTORY_RETIRE_BATCH_SIZE", "80") or "80"))
RETIRE_BATCH_DELAY = max(0.0, float(os.environ.get("GFAM_FACTORY_RETIRE_BATCH_DELAY", "0.25") or "0.25"))
RETIRE_UNKNOWN_KEYWORDS = (
    "unexpected plaintext response", "plaintext response", "timed out", "timeout",
    "read timed", "connection aborted", "remote end closed", "temporarily unavailable",
)


def chunked_list(values, size):
    size = max(1, int_safe(size, 80))
    for i in range(0, len(values), size):
        yield values[i:i + size]


def retire_response_unknown(resp):
    text = compact_error(resp).lower()
    return any(k in text for k in RETIRE_UNKNOWN_KEYWORDS)


def now_ts():
    return int(time.time())


def ts_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def int_safe(v, default=0):
    try:
        if v is None:
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    """Atomic JSON write: write to temp file then rename."""
    import tempfile
    path = Path(path)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".gfam_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        print("[工厂] 写入 JSON 失败：%s" % e)


def log(msg):
    line = "[%s] %s" % (ts_text(), msg)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if os.environ.get("GFAM_FACTORY_AUTO_VERBOSE", "0") == "1":
        print(line)


def default_state():
    return {
        "doll_enabled": False,
        "doll_formula": "handgun",
        "doll_protect_mode": "retire_all_outputs",
        "doll_protect_ids": [],
        "doll_target_count": 1,
        "doll_target_scope": "total_outputs",
        "doll_retire_non_protected": True,
        "equip_enabled": False,
        "equip_formula": "optic",
        "equip_protect_mode": "auto_5star_outputs",
        "equip_protect_ids": [],
        "equip_protect_holo_red_dot": False,
        "equip_target_count": 1,
        "equip_target_scope": "total_outputs",
        "equip_retire_non_protected": True,
        "updated_at": 0,
    }


def load_state():
    st = default_state()
    raw = read_json(STATE_FILE, {})
    if isinstance(raw, dict):
        st.update(raw)
    env = str(os.environ.get("GFAM_DOLL_FACTORY_AUTO_ENABLED", "")).strip().lower()
    if env in ("1", "true", "yes", "on"):
        st["doll_enabled"] = True
    elif env in ("0", "false", "no", "off"):
        st["doll_enabled"] = False
    env = str(os.environ.get("GFAM_EQUIP_FACTORY_AUTO_ENABLED", "")).strip().lower()
    if env in ("1", "true", "yes", "on"):
        st["equip_enabled"] = True
    elif env in ("0", "false", "no", "off"):
        st["equip_enabled"] = False
    return st


def load_catalog(filenames):
    merged = {}
    for fn in filenames:
        arr = read_json(DATA_DIR / fn, [])
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                cid = int_safe(item.get("id", item.get("equip_id", 0)), 0)
                if cid <= 0:
                    continue
                old = merged.get(cid, {})
                old.update(item)
                merged[cid] = old
    return merged


GUN_CATALOG = load_catalog(("gun.json", "gun1.json"))
EQUIP_CATALOG = load_catalog(("equip.json", "equip1.json", "equipment.json"))


def gun_name(gun_id):
    item = GUN_CATALOG.get(int_safe(gun_id))
    if not item:
        return "gun-%s" % gun_id
    for key in ("en_name", "code", "name"):
        val = str(item.get(key) or "").strip()
        if val and not val.startswith("gun-"):
            return val
    return str(item.get("name") or item.get("code") or item.get("en_name") or ("gun-%s" % gun_id))


def equip_name(equip_id):
    item = EQUIP_CATALOG.get(int_safe(equip_id))
    if not item:
        return "equip-%s" % equip_id
    for key in ("name", "en_name", "code"):
        val = str(item.get(key) or "").strip()
        if val and not val.startswith("equip-"):
            return val
    return str(item.get("name") or item.get("code") or item.get("en_name") or ("equip-%s" % equip_id))


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


def explicit_ready_flag(item):
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
    return False


def first_present_int(item, keys, default=0):
    for key in keys:
        if isinstance(item, dict) and key in item:
            return int_safe(item.get(key), default)
    return default


def develop_duration_for(gun_id):
    item = GUN_CATALOG.get(int_safe(gun_id), {})
    return max(60, int_safe(item.get("develop_duration"), 20 * 60))


def equip_duration_for(equip_id):
    item = EQUIP_CATALOG.get(int_safe(equip_id), {})
    for key in ("develop_duration", "build_time", "develop_time", "time"):
        val = int_safe(item.get(key), 0)
        if val > 0:
            return max(60, val)
    return EQUIP_FALLBACK_DURATION


def identity_from_env():
    server = str(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP").strip().upper().replace("_", "-")
    if server in ("AR15",):
        server = "AR-15"
    uid = str(os.environ.get("GFAM_USER_UID") or "").strip()
    sign = str(os.environ.get("GFAM_SIGN_KEY") or DEFAULT_SIGN or "").strip()
    base_url = SERVERS.get(server) or SERVERS.get("SOP")
    return server, uid, sign, base_url


def make_client():
    if GFLClient is None:
        return None
    server, uid, sign, base_url = identity_from_env()
    if not uid or not sign or sign == DEFAULT_SIGN or not base_url:
        log("UID/SIGN 未就绪，制造自动化后台不启动。")
        return None
    return GFLClient(uid, sign, base_url)


def is_error(resp):
    return (not isinstance(resp, dict)) or bool(resp.get("error") or resp.get("error_local"))


def compact_error(resp):
    if isinstance(resp, dict):
        return str(resp.get("error_local") or resp.get("error") or resp)[:500]
    return str(resp)[:500]


def request_index(client):
    shared = read_json(SHARED_INDEX_FILE, None)
    if isinstance(shared, dict):
        payload = shared.get("payload") if isinstance(shared.get("payload"), dict) else None
        if payload is None and isinstance(shared.get("user_info"), dict):
            payload = shared
        ts = int_safe(shared.get("saved_at") or shared.get("time") or shared.get("created_at"), 0)
        age = now_ts() - ts if ts else 0
        if isinstance(payload, dict) and (not ts or age <= SHARED_INDEX_TTL_SECONDS):
            ensure_local_warehouse_snapshot(payload, source="factory_auto_reuse_shared_index")
            log("已复用 GFAM 共享 Index 缓存初始化制造后台%s；仓库判断使用本地缓存。" % (("，缓存年龄 %ss" % max(age, 0)) if ts else ""))
            return payload
        if isinstance(payload, dict):
            log("共享 Index 缓存已过期或不可信，年龄 %ss；将兜底请求一次 Index/index。" % max(age, 0))
    payload = {"time": now_ts(), "furniture_data": False}
    resp = client.send_request(API_INDEX_INDEX, payload)
    if is_error(resp):
        log("Index/index 请求失败：%s" % compact_error(resp))
        return None
    ensure_local_warehouse_snapshot(resp, source="factory_auto_fallback_Index/index")
    write_json(SHARED_INDEX_FILE, {
        "schema": "gfam_shared_index_cache_v1",
        "source": "factory_auto_fallback_Index/index",
        "server": identity_from_env()[0],
        "saved_at": now_ts(),
        "payload": resp,
    })
    log("未找到可复用的 GFAM 共享 Index 缓存，已兜底请求一次 Index/index 并写入共享缓存。")
    return resp


def normalize_list_or_dict(value):
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    return []


def _derive_factory_warehouse_snapshot(index_payload, source="index"):
    if not isinstance(index_payload, dict):
        return {}
    ui = index_payload.get("user_info") if isinstance(index_payload.get("user_info"), dict) else {}
    maxgun = int_safe(ui.get("maxgun"), 0)
    maxequip = int_safe(ui.get("maxequip"), 0)
    gun_count_value = len(normalize_list_or_dict(index_payload.get("gun_with_user_info", [])))
    equip_count_value = len(normalize_list_or_dict(index_payload.get("equip_with_user_info", [])))
    return {
        "schema": "gfam_factory_warehouse_cache_v1",
        "updated_at": now_ts(),
        "source": source,
        "gun_count": gun_count_value,
        "maxgun": maxgun,
        "gun_free": max(0, maxgun - gun_count_value) if maxgun > 0 else 0,
        "equip_count": equip_count_value,
        "maxequip": maxequip,
        "equip_free": max(0, maxequip - equip_count_value) if maxequip > 0 else 0,
    }


def _get_payload_warehouse_snapshot(index_payload):
    if isinstance(index_payload, dict):
        wh = index_payload.get("_gfam_local_warehouse")
        if isinstance(wh, dict):
            return wh
    wh = read_json(WAREHOUSE_CACHE_FILE, {})
    return wh if isinstance(wh, dict) else {}


def _save_payload_warehouse_snapshot(index_payload, snapshot):
    if not isinstance(snapshot, dict):
        return index_payload
    snapshot["updated_at"] = now_ts()
    if isinstance(index_payload, dict):
        index_payload["_gfam_local_warehouse"] = snapshot
    write_json(WAREHOUSE_CACHE_FILE, snapshot)
    return index_payload


def ensure_local_warehouse_snapshot(index_payload, source="index"):
    if not isinstance(index_payload, dict):
        return index_payload
    if not isinstance(index_payload.get("_gfam_local_warehouse"), dict):
        _save_payload_warehouse_snapshot(index_payload, _derive_factory_warehouse_snapshot(index_payload, source=source))
    return index_payload


def adjust_local_warehouse_snapshot(index_payload, kind, delta, source="local_action"):
    if not isinstance(index_payload, dict):
        return index_payload
    ensure_local_warehouse_snapshot(index_payload, source="before_" + source)
    wh = dict(_get_payload_warehouse_snapshot(index_payload))
    delta = int_safe(delta, 0)
    ui = index_payload.get("user_info") if isinstance(index_payload.get("user_info"), dict) else {}
    if kind == "equip":
        maxv = int_safe(wh.get("maxequip"), int_safe(ui.get("maxequip"), 0))
        cnt = max(0, int_safe(wh.get("equip_count"), len(normalize_list_or_dict(index_payload.get("equip_with_user_info", [])))) + delta)
        wh["equip_count"] = cnt; wh["maxequip"] = maxv; wh["equip_free"] = max(0, maxv - cnt) if maxv > 0 else 0
    else:
        maxv = int_safe(wh.get("maxgun"), int_safe(ui.get("maxgun"), 0))
        cnt = max(0, int_safe(wh.get("gun_count"), len(normalize_list_or_dict(index_payload.get("gun_with_user_info", [])))) + delta)
        wh["gun_count"] = cnt; wh["maxgun"] = maxv; wh["gun_free"] = max(0, maxv - cnt) if maxv > 0 else 0
    wh["schema"] = "gfam_factory_warehouse_cache_v1"; wh["source"] = source
    _save_payload_warehouse_snapshot(index_payload, wh)
    return index_payload


def item_count(index_payload, item_id):
    for item in normalize_list_or_dict(index_payload.get("item_with_user_info", [])):
        if int_safe(item.get("item_id"), -1) == int(item_id):
            return int_safe(item.get("number"), 0)
    return 0


def resource_snapshot(index_payload):
    ui = index_payload.get("user_info") or {}
    return {k: int_safe(ui.get(k), 0) for k in RESOURCE_KEYS}


def build_slot_count_from_raw(max_build_slot):
    """
    GFL Index/user_info.max_build_slot is the total number of build slots
    (both normal and heavy).  For example max_build_slot=8 means 8 slots total:
    slots 1/3/5/7 are normal (普通) and slots 2/4/6/8 are heavy (重型).
    """
    raw = int_safe(max_build_slot, 0)
    if raw <= 0:
        return 0
    return raw


def slot_numbers(max_build_slot):
    """Return all valid slot numbers (1 .. max_build_slot)."""
    count = build_slot_count_from_raw(max_build_slot)
    return list(range(1, count + 1))


def normal_slot_numbers(max_build_slot):
    """Return only normal (普通) build slot numbers: odd slots 1, 3, 5, 7, ..."""
    count = build_slot_count_from_raw(max_build_slot)
    return [s for s in range(1, count + 1) if s % 2 == 1]


def heavy_slot_numbers(max_build_slot):
    """Return only heavy (重型) build slot numbers: even slots 2, 4, 6, 8, ..."""
    count = build_slot_count_from_raw(max_build_slot)
    return [s for s in range(1, count + 1) if s % 2 == 0]


def is_heavy_slot(slot_number):
    """Check if a slot number is a heavy (重型) build slot."""
    return int_safe(slot_number, 0) % 2 == 0


def gun_count(index_payload):
    wh = _get_payload_warehouse_snapshot(index_payload)
    if isinstance(wh, dict) and "gun_count" in wh:
        return int_safe(wh.get("gun_count"), 0)
    return len(normalize_list_or_dict(index_payload.get("gun_with_user_info", [])))


def gun_max(index_payload):
    return int_safe((index_payload.get("user_info") or {}).get("maxgun"), 0)


def equip_count(index_payload):
    wh = _get_payload_warehouse_snapshot(index_payload)
    if isinstance(wh, dict) and "equip_count" in wh:
        return int_safe(wh.get("equip_count"), 0)
    return len(normalize_list_or_dict(index_payload.get("equip_with_user_info", [])))


def equip_max(index_payload):
    return int_safe((index_payload.get("user_info") or {}).get("maxequip"), 0)


def _slot_time_state(item, result_id, kind):
    now = now_ts()
    start = int_safe(item.get("start_time"), 0)
    explicit_ready = explicit_ready_flag(item)
    finish_time = first_present_int(item, FINISH_TIME_KEYS, 0)
    remain = first_present_int(item, REMAIN_KEYS, 0)
    status_source = "estimated"
    if explicit_ready:
        remain = 0
        expected_finish = now
        status_source = "explicit_ready"
    elif finish_time > 0:
        remain = max(0, finish_time - now)
        expected_finish = finish_time
        status_source = "finish_time"
    elif remain > 0:
        expected_finish = now + remain
        status_source = "remain_time"
    else:
        if start > 0:
            duration = develop_duration_for(result_id) if kind == "doll" else equip_duration_for(result_id)
            expected_finish = start + duration
            remain = max(0, expected_finish - now)
            status_source = "start_time_estimated"
        else:
            expected_finish = now
            remain = 0
            status_source = "no_time_ready"
    return start, expected_finish, remain, status_source


def build_slots_from_index(index_payload):
    slots = {}
    for item in normalize_list_or_dict(index_payload.get("develop_act_info", [])):
        if not isinstance(item, dict):
            continue
        slot = int_safe(item.get("build_slot") or item.get("slot"), 0)
        gid = int_safe(item.get("gun_id") or item.get("id"), 0)
        if slot <= 0 or gid <= 0:
            continue
        start, finish, remain, source = _slot_time_state(item, gid, "doll")
        slots[slot] = {"slot": slot, "gun_id": gid, "start_time": start, "finish_time": finish, "remain": remain, "status_source": source}
    return slots


def equip_build_slots_from_index(index_payload):
    slots = {}
    for item in normalize_list_or_dict(index_payload.get("develop_equip_act_info", [])):
        if not isinstance(item, dict):
            continue
        slot = int_safe(item.get("build_slot") or item.get("slot"), 0)
        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        eid = int_safe(info.get("equip_id") or item.get("equip_id") or item.get("id"), 0)
        if slot <= 0 or eid <= 0:
            continue
        start, finish, remain, source = _slot_time_state(item, eid, "equip")
        slots[slot] = {"slot": slot, "equip_id": eid, "start_time": start, "finish_time": finish, "remain": remain, "status_source": source}
    return slots


def is_gun_locked(gun):
    for key in ("if_locked", "is_locked", "locked", "lock", "is_lock"):
        if key in gun and str(gun.get(key)).strip().lower() in ("1", "true", "yes", "y"):
            return True
    return False


def gun_team_id(gun):
    for key in ("team_id", "team", "location"):
        if key in gun:
            return int_safe(gun.get(key), 0)
    return 0


def gun_uid(gun):
    for key in ("gun_with_user_id", "id", "uid"):
        if key in gun:
            return int_safe(gun.get(key), 0)
    return 0


def gun_id_of(gun):
    return int_safe(gun.get("gun_id", gun.get("gun", 0)), 0)


def equip_uid(equip):
    for key in ("equip_with_user_id", "id", "uid"):
        if key in equip:
            return int_safe(equip.get(key), 0)
    return 0


def equip_id_of(equip):
    return int_safe(equip.get("equip_id", equip.get("equip", 0)), 0)


def is_equip_locked(equip):
    for key in ("is_locked", "if_locked", "locked", "lock", "is_lock"):
        if key in equip and str(equip.get(key)).strip().lower() in ("1", "true", "yes", "y"):
            return True
    return False


def equip_on_gun(equip):
    return int_safe(equip.get("gun_with_user_id"), 0) > 0


def equip_rank(equip):
    for key in ("rank", "star", "quality", "quality_lv"):
        v = int_safe(equip.get(key), 0)
        if v > 0:
            return v
    item = EQUIP_CATALOG.get(equip_id_of(equip), {})
    for key in ("rank", "star", "quality", "quality_lv"):
        v = int_safe(item.get(key), 0)
        if v > 0:
            return v
    return 0


def equip_rank_by_id(equip_id):
    item = EQUIP_CATALOG.get(int_safe(equip_id, 0), {})
    for key in ("rank", "star", "quality", "quality_lv"):
        v = int_safe(item.get(key), 0)
        if v > 0:
            return v
    return 0


def equip_is_five_star_id(equip_id):
    return equip_rank_by_id(equip_id) >= 5


def equip_is_holo_or_red_dot_id(equip_id):
    """Identify normal holographic / red-dot sight families.

    Normal holo/red-dot sights are represented by type 2/3 or auto_select_id
    2001/3001 in the catalog.  Exclusive gear can contain words such as 全息
    or ACOG, but type 18 is intentionally not treated as disposable factory
    sight equipment here.
    """
    item = EQUIP_CATALOG.get(int_safe(equip_id, 0), {})
    if not isinstance(item, dict) or not item:
        return False
    etype = int_safe(item.get("type"), 0)
    auto_id = int_safe(item.get("auto_select_id"), 0)
    if etype in (2, 3) or auto_id in (2001, 3001):
        return True
    code = str(item.get("code") or item.get("name") or item.get("en_name") or "")
    category = int_safe(item.get("category"), 0)
    if category == 1 and etype != 18 and ("全息" in code or "红点" in code or "ACOG" in code.upper()):
        return True
    return False


def collect_emergency_retire_uids(index_payload, protected_ids, max_count=30):
    protected_ids = set(int_safe(x) for x in protected_ids)
    result = []
    for gun in normalize_list_or_dict(index_payload.get("gun_with_user_info", [])):
        if not isinstance(gun, dict):
            continue
        if is_gun_locked(gun) or gun_team_id(gun) != 0:
            continue
        gid = gun_id_of(gun)
        if gid in protected_ids:
            continue
        uid = gun_uid(gun)
        if uid > 0:
            result.append(uid)
        if len(result) >= max_count:
            break
    return result


def collect_emergency_retire_equips(index_payload, protected_ids, max_count=30, protect_holo_red_dot=False):
    """保守装备应急拆解：只拆未上锁、未装备、非保护且可确认为 4 星及以下的装备。

    如果缺少 equip.json 导致星级无法确认，则不主动全仓库拆解，避免误拆高价值装备。
    """
    protected_ids = set(int_safe(x) for x in protected_ids)
    result = []
    for eq in normalize_list_or_dict(index_payload.get("equip_with_user_info", [])):
        if not isinstance(eq, dict):
            continue
        if is_equip_locked(eq) or equip_on_gun(eq):
            continue
        eid = equip_id_of(eq)
        if eid in protected_ids:
            continue
        rank = equip_rank(eq)
        if equip_is_holo_or_red_dot_id(eid):
            if protect_holo_red_dot:
                continue
            # 默认：普通全息/红点瞄具所有已知星级均不保护；星级未知仍保守保留。
            if rank <= 0:
                continue
        else:
            if rank <= 0 or rank >= 5:
                continue
        uid = equip_uid(eq)
        if uid > 0:
            result.append(uid)
        if len(result) >= max_count:
            break
    return result


class BaseFactoryService:
    cache_key = "base"
    name = "制造"
    object_name = "产物"
    reserved_slots = 1

    def __init__(self, client, state, index_payload, shared_resources):
        self.client = client
        self.state = state
        self.resources = shared_resources
        self.index_payload = index_payload
        self.stop_after_current = False
        self.last_finish_poll = 0
        self.disabled = False
        self.disabled_reason = ""
        self.last_retire_response_unknown = False

    def quota_reached(self):
        if self.target_count <= 0:
            return False
        if self.target_scope == "protected_hits":
            return int(self.stats.get("target_kept", 0)) >= self.target_count
        return int(self.stats.get("build_success", 0)) >= self.target_count

    def quota_remaining_for_start(self):
        if self.target_count <= 0:
            return 10 ** 9
        if self.target_scope == "protected_hits":
            return 10 ** 9
        return max(0, self.target_count - int(self.stats.get("build_success", 0)))

    def persist_disabled_state(self):
        try:
            st = read_json(STATE_FILE, {})
            if not isinstance(st, dict):
                st = {}
            st[self.cache_key + "_enabled"] = False
            st[self.cache_key + "_disabled_reason"] = self.disabled_reason
            write_json(STATE_FILE, st)
        except Exception:
            pass

    def can_afford_count(self, n):
        n = int(n)
        if n <= 0:
            return False
        if self.contracts < n:
            return False
        for k, v in self.formula["resources"].items():
            if self.resources.get(k, 0) < int(v) * n:
                return False
        return True

    def free_build_slots(self):
        # Only return normal (odd) slots for standard builds (build_heavy=0)
        all_normal = normal_slot_numbers(self.max_build_slot)
        return [s for s in all_normal if s not in self.slots]

    def normal_slot_count(self):
        """Number of normal (普通) build slots (odd slots only)."""
        return len(normal_slot_numbers(self.max_build_slot))

    def check_completion(self):
        if self.quota_reached():
            self.stop_after_current = True
        if self.stop_after_current and not self.slots and not self.pending_retire:
            self.disabled = True
            if self.target_scope == "protected_hits":
                self.disabled_reason = "已达到目标%s保留数量 %s，自动停止%s自动制造" % (self.object_name, self.target_count, self.object_name)
            else:
                self.disabled_reason = "已达到本次总制造数量上限 %s，自动停止%s自动制造" % (self.target_count, self.object_name)
            log("[*] %s。" % self.disabled_reason)
            self.persist_disabled_state()
            self.write_cache()

    def loop_once(self):
        if self.disabled:
            return
        self.finish_ready_builds()
        self.start_new_builds()
        self.check_completion()


class DollFactoryService(BaseFactoryService):
    cache_key = "doll"
    name = "人形自动制造"
    object_name = "人形"
    reserved_slots = RESERVED_GUN_SLOTS

    def __init__(self, client, state, index_payload, shared_resources):
        super().__init__(client, state, index_payload, shared_resources)
        self.formula_key = str(state.get("doll_formula") or "handgun")
        if self.formula_key not in DOLL_FORMULAS:
            self.formula_key = "handgun"
        self.formula = DOLL_FORMULAS[self.formula_key]
        self.protected_ids = set(int_safe(x) for x in state.get("doll_protect_ids", []) if int_safe(x) > 0)
        self.target_count = max(0, int_safe(state.get("doll_target_count", 1), 1))
        self.target_scope = str(state.get("doll_target_scope") or ("protected_hits" if self.protected_ids else "total_outputs"))
        self.max_build_slot = int_safe((index_payload.get("user_info") or {}).get("max_build_slot"), 0)
        self.maxgun = gun_max(index_payload)
        self.gun_count = gun_count(index_payload)
        self.contracts = item_count(index_payload, 1)
        self.slots = build_slots_from_index(index_payload)
        self.pending_retire = []
        self.stats = {"build_attempts": 0, "build_success": 0, "finish_attempts": 0, "finish_success": 0, "retire_attempts": 0, "retire_success": 0, "target_kept": 0, "total_outputs": 0}
        log("人形自动制造初始化：公式=%s，栏位=%s，占用=%s，仓库=%s/%s，契约=%s，保护=%s，目标数量=%s/%s" % (
            self.formula["name"], self.normal_slot_count(), len(self.slots), self.gun_count, self.maxgun, self.contracts, sorted(self.protected_ids), self.target_count, self.target_scope
        ))
        self.write_cache()

    def free_gun_slots(self):
        if self.maxgun <= 0:
            return 0  # was 9999 - unsafe default
        return max(0, self.maxgun - self.gun_count)

    def write_cache(self):
        data = read_json(CACHE_FILE, {})
        if not isinstance(data, dict):
            data = {}
        data.update({
            "updated_at": now_ts(),
            "doll_enabled": not self.disabled,
            "doll_disabled_reason": self.disabled_reason,
            "doll_formula": self.formula_key,
            "doll_formula_name": self.formula["name"],
            "resources": self.resources,
            "doll_max_build_slot": self.normal_slot_count(),
            "doll_max_build_slot_raw": self.max_build_slot,
            "doll_busy_slots": len(self.slots),
            "doll_free_build_slots": len(self.free_build_slots()),
            "gun_count": self.gun_count,
            "maxgun": self.maxgun,
            "gun_free": self.free_gun_slots(),
            "doll_contracts": self.contracts,
            "doll_pending_retire": len(self.pending_retire),
            "doll_protected_ids": sorted(self.protected_ids),
            "doll_target_count": self.target_count,
            "doll_target_scope": self.target_scope,
            "doll_stats": dict(self.stats),
        })
        write_json(CACHE_FILE, data)

    def _update_from_index(self, index_payload):
        """Refresh service state from a fresh Index payload (periodic TTL refresh)."""
        self.index_payload = index_payload
        self.max_build_slot = int_safe((index_payload.get("user_info") or {}).get("max_build_slot"), 0)
        self.maxgun = gun_max(index_payload)
        self.gun_count = gun_count(index_payload)
        self.contracts = item_count(index_payload, 1)
        self.slots = build_slots_from_index(index_payload)

    def retire_uids(self, uids, reason="非保护产物拆解"):
        clean = []
        seen = set()
        for uid in uids:
            uid = int_safe(uid, 0)
            if uid > 0 and uid not in seen:
                clean.append(uid); seen.add(uid)
        if not clean:
            return 0
        self.last_retire_response_unknown = False
        total_ok = 0
        total = len(clean)
        self.stats["retire_attempts"] += total
        log("%s：准备拆解 %d 名人形；按每批最多 %d 分批提交，避免大批量响应超时误判。" % (reason, total, RETIRE_BATCH_SIZE))
        # Acquire cross-process lock to avoid concurrent Gun/retireGun with A-10
        _lock = RetireLock() if RetireLock else None
        if _lock and not _lock.acquire(timeout=12):
            log("[!] 未能获取跨进程拆解锁（A-10 可能正在拆解），本轮跳过人形拆解。")
            self.last_retire_response_unknown = True
            return 0
        try:
            for batch_no, batch in enumerate(chunked_list(clean, RETIRE_BATCH_SIZE), start=1):
                batch_seen = set(batch)
                log("%s：提交人形拆解批次 %d，数量 %d/%d。" % (reason, batch_no, len(batch), total))
                resp = self.client.send_request(API_GUN_RETIRE, batch)
                if isinstance(resp, dict) and resp.get("success"):
                    self.stats["retire_success"] += len(batch)
                    total_ok += len(batch)
                    self.gun_count = max(0, self.gun_count - len(batch))
                    self.pending_retire = [x for x in self.pending_retire if int_safe(x) not in batch_seen]
                    adjust_local_warehouse_snapshot(self.index_payload, "gun", -len(batch), source="factory_auto_after_gun_retire_batch")
                    log("人形拆解批次成功：%d。仓库缓存 %s/%s，空位 %s。" % (len(batch), self.gun_count, self.maxgun, self.free_gun_slots()))
                    self.write_cache()
                    if RETIRE_BATCH_DELAY > 0:
                        time.sleep(RETIRE_BATCH_DELAY)
                    continue
                if retire_response_unknown(resp):
                    self.last_retire_response_unknown = True
                    log("[!] 人形拆解批次响应状态未知：%s" % compact_error(resp))
                    log("[!] 已停止后续拆解批次，保留未确认 UID，不把本次判为明确失败；下一轮可重新校准/重试。")
                    self.write_cache(); return total_ok
                log("人形拆解失败：%s" % compact_error(resp))
                self.write_cache(); return total_ok
        finally:
            if _lock:
                _lock.release()
        log("人形拆解完成：%d/%d。仓库缓存 %s/%s，空位 %s。" % (total_ok, total, self.gun_count, self.maxgun, self.free_gun_slots()))
        self.write_cache(); return total_ok

    def ensure_storage_for_factory(self):
        if self.free_gun_slots() > RESERVED_GUN_SLOTS:
            return True
        if self.pending_retire:
            self.retire_uids(list(self.pending_retire), reason="人形仓库空位不足，先拆 pending 非保护制造产物")
        if getattr(self, "last_retire_response_unknown", False):
            log("[!] 人形拆解响应状态未知，暂不禁用人形自动制造；本轮暂停提交新制造，避免重复/误判。")
            self.write_cache(); return False
        if self.free_gun_slots() > RESERVED_GUN_SLOTS:
            return True
        emergency = collect_emergency_retire_uids(self.index_payload, self.protected_ids, max_count=20)
        if emergency:
            self.retire_uids(emergency, reason="人形仓库空位不足，应急拆解未上锁未编队非保护人形")
        if getattr(self, "last_retire_response_unknown", False):
            log("[!] 人形应急拆解响应状态未知，暂不禁用人形自动制造；本轮暂停提交新制造。")
            self.write_cache(); return False
        if self.free_gun_slots() > RESERVED_GUN_SLOTS:
            return True
        self.disabled = True
        self.disabled_reason = "人形仓库仅剩 %d 个空位，已保留给其它模块，停止人形自动制造" % self.free_gun_slots()
        log("[!] %s。" % self.disabled_reason)
        self.persist_disabled_state(); self.write_cache(); return False

    def finish_ready_builds(self, force=False):
        if now_ts() - self.last_finish_poll < FINISH_POLL_SECONDS:
            return
        self.last_finish_poll = now_ts()
        ready_slots = [slot for slot, info in self.slots.items() if int_safe(info.get("finish_time"), 0) <= now_ts()]
        if not ready_slots and not force:
            return
        if not self.slots:
            return
        self.stats["finish_attempts"] += 1
        resp = self.client.send_request(API_GUN_FINISH_ALL_DEVELOP, {"is_cost_item3": 0})
        if is_error(resp):
            log("领取人形制造完成失败：%s" % compact_error(resp)); self.write_cache(); return
        add_list = resp.get("gun_with_user_add_list") or []
        if not isinstance(add_list, list):
            add_list = []
        if not add_list:
            if force:
                log("已尝试领取人形制造完成，但服务器未返回可领取人形；栏位仍按占用处理。")
            else:
                log("已请求领取人形制造完成，但返回未包含新增人形。")
            self.write_cache(); return
        old_slots = set(self.slots.keys())
        popped_slots = set()
        self.stats["finish_success"] += len(add_list)
        for item in add_list:
            slot = int_safe(item.get("build_slot"), 0)
            uid = int_safe(item.get("gun_with_user_id"), 0)
            gid = int_safe(item.get("gun_id"), 0)
            if slot > 0:
                self.slots.pop(slot, None); popped_slots.add(slot)
            self.gun_count += 1
            self.stats["total_outputs"] = int(self.stats.get("total_outputs", 0)) + 1
            if gid in self.protected_ids:
                self.stats["target_kept"] = int(self.stats.get("target_kept", 0)) + 1
                log("领取人形制造：%s(%s) UID %s，命中保护目标，已保留（目标进度 %s/%s）。" % (gun_name(gid), gid, uid, self.stats.get("target_kept", 0), self.target_count if self.target_count > 0 else "不限"))
            else:
                if uid > 0:
                    self.pending_retire.append(uid)
                log("领取人形制造：%s(%s) UID %s，非保护目标，加入待拆解队列。" % (gun_name(gid), gid, uid))
        # 有些 finishAllDevelop 返回项不带 build_slot。此时按 ready/force 语义释放本地栏位，
        # 避免“已领取但本地仍认为满栏”导致只收不建。
        if not popped_slots:
            fallback_slots = ready_slots or sorted(old_slots)[:len(add_list)]
            for slot in fallback_slots[:len(add_list)]:
                self.slots.pop(slot, None)
            if fallback_slots:
                log("人形制造领取返回未带栏位号，已按本地完成队列释放栏位：%s" % sorted(fallback_slots[:len(add_list)]))
        if self.pending_retire:
            self.retire_uids(list(self.pending_retire), reason="领取后非保护制造产物拆解")
        self.check_completion(); self.write_cache()

    def start_new_builds(self):
        if self.disabled:
            return
        if self.stop_after_current or self.quota_reached():
            self.stop_after_current = True; self.check_completion(); return
        if not self.ensure_storage_for_factory():
            return
        free_slots = self.free_build_slots()
        if not free_slots:
            # 满栏时先尝试普通领取已完成制造；若领取成功会释放本地栏位并继续提交新制造。
            self.finish_ready_builds(force=True)
            free_slots = self.free_build_slots()
            if not free_slots:
                return
        count = min(len(free_slots), max(0, self.free_gun_slots() - RESERVED_GUN_SLOTS), self.contracts, self.quota_remaining_for_start())
        for k, v in self.formula["resources"].items():
            if int(v) > 0:
                count = min(count, self.resources.get(k, 0) // int(v))
        if count <= 0:
            return
        payload = dict(self.formula["resources"])
        payload.update({"input_level": 0, "build_quick": 0, "build_multi": int(count), "build_heavy": 0})
        self.stats["build_attempts"] += int(count)
        resp = self.client.send_request(API_GUN_DEVELOP_MULTI, payload)
        if is_error(resp):
            log("提交人形制造失败：%s" % compact_error(resp)); self.write_cache(); return
        gun_ids = resp.get("gun_ids") or []
        if not isinstance(gun_ids, list) or not gun_ids:
            log("提交人形制造返回异常：未包含 gun_ids。"); self.write_cache(); return
        started = 0; t = now_ts()
        for item in gun_ids:
            gid = int_safe(item.get("id"), 0); slot = int_safe(item.get("slot"), 0)
            if gid <= 0 or slot <= 0:
                continue
            self.slots[slot] = {"slot": slot, "gun_id": gid, "start_time": t, "finish_time": t + develop_duration_for(gid)}
            started += 1
        if started:
            self.stats["build_success"] += started
            self.contracts = max(0, self.contracts - started)
            for k, v in self.formula["resources"].items():
                self.resources[k] = max(0, self.resources.get(k, 0) - int(v) * started)
            log("已启动人形制造 %d 个，公式=%s；栏位占用 %d/%d。" % (started, self.formula["name"], len(self.slots), self.normal_slot_count()))
        if self.quota_reached() and not self.protected_ids:
            self.stop_after_current = True
        self.write_cache()


class EquipFactoryService(BaseFactoryService):
    cache_key = "equip"
    name = "装备自动制造"
    object_name = "装备"
    reserved_slots = RESERVED_EQUIP_SLOTS

    def __init__(self, client, state, index_payload, shared_resources):
        super().__init__(client, state, index_payload, shared_resources)
        self.formula_key = str(state.get("equip_formula") or "optic")
        if self.formula_key not in EQUIP_FORMULAS:
            self.formula_key = "optic"
        self.formula = EQUIP_FORMULAS[self.formula_key]
        self.protected_ids = set(int_safe(x) for x in state.get("equip_protect_ids", []) if int_safe(x) > 0)
        self.protect_all_5star = True
        self.protect_holo_red_dot = bool(state.get("equip_protect_holo_red_dot", False))
        self.protect_mode = str(state.get("equip_protect_mode") or "auto_5star_outputs")
        self.target_count = max(0, int_safe(state.get("equip_target_count", 1), 1))
        self.target_scope = str(state.get("equip_target_scope") or "total_outputs")
        self.max_build_slot = int_safe((index_payload.get("user_info") or {}).get("max_equip_build_slot"), 0)
        self.maxequip = equip_max(index_payload)
        self.equip_count = equip_count(index_payload)
        self.contracts = item_count(index_payload, 2)
        self.slots = equip_build_slots_from_index(index_payload)
        self.pending_retire = []
        self.stats = {"build_attempts": 0, "build_success": 0, "finish_attempts": 0, "finish_success": 0, "retire_attempts": 0, "retire_success": 0, "target_kept": 0, "five_star_kept": 0, "unknown_rank_kept": 0, "total_outputs": 0}
        protect_text = "所有五星装备（默认排除全息/红点瞄具）"
        if self.protect_holo_red_dot:
            protect_text += " + 全息/红点瞄具"
        if self.protected_ids:
            protect_text += " + 额外ID %s" % sorted(self.protected_ids)
        log("装备自动制造初始化：公式=%s，栏位=%s，占用=%s，仓库=%s/%s，契约=%s，保护=%s，目标数量=%s/%s" % (
            self.formula["name"], self.normal_slot_count(), len(self.slots), self.equip_count, self.maxequip, self.contracts, protect_text, self.target_count, self.target_scope
        ))
        self.write_cache()

    def free_equip_slots(self):
        if self.maxequip <= 0:
            return 0  # was 9999 - unsafe default
        return max(0, self.maxequip - self.equip_count)

    def write_cache(self):
        data = read_json(CACHE_FILE, {})
        if not isinstance(data, dict):
            data = {}
        data.update({
            "updated_at": now_ts(),
            "equip_enabled": not self.disabled,
            "equip_disabled_reason": self.disabled_reason,
            "equip_formula": self.formula_key,
            "equip_formula_name": self.formula["name"],
            "resources": self.resources,
            "equip_max_build_slot": self.normal_slot_count(),
            "equip_max_build_slot_raw": self.max_build_slot,
            "equip_busy_slots": len(self.slots),
            "equip_free_build_slots": len(self.free_build_slots()),
            "equip_count": self.equip_count,
            "maxequip": self.maxequip,
            "equip_free": self.free_equip_slots(),
            "equip_contracts": self.contracts,
            "equip_pending_retire": len(self.pending_retire),
            "equip_protected_ids": sorted(self.protected_ids),
            "equip_protect_mode": "auto_5star_outputs",
            "equip_protect_all_5star": True,
            "equip_protect_holo_red_dot": bool(self.protect_holo_red_dot),
            "equip_target_count": self.target_count,
            "equip_target_scope": self.target_scope,
            "equip_stats": dict(self.stats),
        })
        write_json(CACHE_FILE, data)

    def _update_from_index(self, index_payload):
        """Refresh service state from a fresh Index payload (periodic TTL refresh)."""
        self.index_payload = index_payload
        self.max_build_slot = int_safe((index_payload.get("user_info") or {}).get("max_equip_build_slot"), 0)
        self.maxequip = equip_max(index_payload)
        self.equip_count = equip_count(index_payload)
        self.contracts = item_count(index_payload, 2)
        self.slots = equip_build_slots_from_index(index_payload)

    def is_output_protected(self, equip_id):
        eid = int_safe(equip_id, 0)
        if eid in self.protected_ids:
            return True, "额外保护ID"
        rank = equip_rank_by_id(eid)
        if equip_is_holo_or_red_dot_id(eid):
            if self.protect_holo_red_dot:
                return True, "全息/红点瞄具保护开关已开启"
            if rank > 0:
                return False, "%s星全息/红点瞄具默认不保护" % rank
            return True, "星级未知，保守保留"
        if rank >= 5:
            return True, "五星装备"
        if rank <= 0:
            return True, "星级未知，保守保留"
        return False, "%s星非保护" % rank

    def retire_uids(self, uids, reason="非保护装备拆解"):
        clean = []
        seen = set()
        for uid in uids:
            uid = int_safe(uid, 0)
            if uid > 0 and uid not in seen:
                clean.append(uid); seen.add(uid)
        if not clean:
            return 0
        self.last_retire_response_unknown = False
        total_ok = 0
        total = len(clean)
        self.stats["retire_attempts"] += total
        log("%s：准备拆解 %d 件装备；按每批最多 %d 分批提交，避免大批量响应超时误判。" % (reason, total, RETIRE_BATCH_SIZE))
        # Acquire cross-process lock to avoid concurrent retire calls with A-10
        _lock = RetireLock() if RetireLock else None
        if _lock and not _lock.acquire(timeout=12):
            log("[!] 未能获取跨进程拆解锁（A-10 可能正在拆解），本轮跳过装备拆解。")
            self.last_retire_response_unknown = True
            return 0
        try:
            for batch_no, batch in enumerate(chunked_list(clean, RETIRE_BATCH_SIZE), start=1):
                batch_seen = set(batch)
                log("%s：提交装备拆解批次 %d，数量 %d/%d。" % (reason, batch_no, len(batch), total))
                resp = self.client.send_request(API_EQUIP_RETIRE, {"equips": batch})
                if isinstance(resp, dict) and (resp.get("success") or ("error" not in resp and "error_local" not in resp)):
                    self.stats["retire_success"] += len(batch)
                    total_ok += len(batch)
                    self.equip_count = max(0, self.equip_count - len(batch))
                    self.pending_retire = [x for x in self.pending_retire if int_safe(x) not in batch_seen]
                    adjust_local_warehouse_snapshot(self.index_payload, "equip", -len(batch), source="factory_auto_after_equip_retire_batch")
                    log("装备拆解批次成功：%d。仓库缓存 %s/%s，空位 %s。" % (len(batch), self.equip_count, self.maxequip, self.free_equip_slots()))
                    self.write_cache()
                    if RETIRE_BATCH_DELAY > 0:
                        time.sleep(RETIRE_BATCH_DELAY)
                    continue
                if retire_response_unknown(resp):
                    self.last_retire_response_unknown = True
                    log("[!] 装备拆解批次响应状态未知：%s" % compact_error(resp))
                    log("[!] 已停止后续拆解批次，保留未确认 UID，不把本次判为明确失败；下一轮可重新校准/重试。")
                    self.write_cache(); return total_ok
                log("装备拆解失败：%s" % compact_error(resp))
                self.write_cache(); return total_ok
        finally:
            if _lock:
                _lock.release()
        log("装备拆解完成：%d/%d。仓库缓存 %s/%s，空位 %s。" % (total_ok, total, self.equip_count, self.maxequip, self.free_equip_slots()))
        self.write_cache(); return total_ok

    def ensure_storage_for_factory(self):
        if self.free_equip_slots() > RESERVED_EQUIP_SLOTS:
            return True
        if self.pending_retire:
            self.retire_uids(list(self.pending_retire), reason="装备仓库空位不足，先拆 pending 非保护制造产物")
        if getattr(self, "last_retire_response_unknown", False):
            log("[!] 装备拆解响应状态未知，暂不禁用装备自动制造；本轮暂停提交新制造，避免重复/误判。")
            self.write_cache(); return False
        if self.free_equip_slots() > RESERVED_EQUIP_SLOTS:
            return True
        emergency = collect_emergency_retire_equips(self.index_payload, self.protected_ids, max_count=20, protect_holo_red_dot=self.protect_holo_red_dot)
        if emergency:
            self.retire_uids(emergency, reason="装备仓库空位不足，应急拆解未上锁未装备低星非保护装备/默认不保护瞄具")
        if getattr(self, "last_retire_response_unknown", False):
            log("[!] 装备应急拆解响应状态未知，暂不禁用装备自动制造；本轮暂停提交新制造。")
            self.write_cache(); return False
        if self.free_equip_slots() > RESERVED_EQUIP_SLOTS:
            return True
        self.disabled = True
        self.disabled_reason = "装备仓库仅剩 %d 个空位，已保留给其它模块，停止装备自动制造" % self.free_equip_slots()
        log("[!] %s。" % self.disabled_reason)
        self.persist_disabled_state(); self.write_cache(); return False

    def finish_ready_builds(self, force=False):
        if now_ts() - self.last_finish_poll < FINISH_POLL_SECONDS:
            return
        self.last_finish_poll = now_ts()
        ready_slots = [slot for slot, info in self.slots.items() if int_safe(info.get("finish_time"), 0) <= now_ts()]
        if not ready_slots and not force:
            return
        if not self.slots:
            return
        self.stats["finish_attempts"] += 1
        resp = self.client.send_request(API_EQUIP_FINISH_ALL_DEVELOP, {"is_cost_item3": 0})
        if is_error(resp):
            log("领取装备制造完成失败：%s" % compact_error(resp)); self.write_cache(); return
        add_list = resp.get("equip_with_user_add_list") or []
        if not isinstance(add_list, list):
            add_list = []
        if not add_list:
            if force:
                log("已尝试领取装备制造完成，但服务器未返回可领取装备；栏位仍按占用处理。")
            else:
                log("已请求领取装备制造完成，但返回未包含新增装备。")
            self.write_cache(); return
        old_slots = set(self.slots.keys())
        popped_slots = set()
        self.stats["finish_success"] += len(add_list)
        for item in add_list:
            slot = int_safe(item.get("build_slot"), 0)
            eid = int_safe(item.get("equip_id"), 0)
            ew = item.get("equip_with_user") if isinstance(item.get("equip_with_user"), dict) else {}
            uid = int_safe(ew.get("id") or item.get("equip_with_user_id") or item.get("id"), 0)
            if slot > 0:
                self.slots.pop(slot, None); popped_slots.add(slot)
            self.equip_count += 1
            self.stats["total_outputs"] = int(self.stats.get("total_outputs", 0)) + 1
            protected, protect_reason = self.is_output_protected(eid)
            if protected:
                self.stats["target_kept"] = int(self.stats.get("target_kept", 0)) + 1
                rank = equip_rank_by_id(eid)
                if rank >= 5:
                    self.stats["five_star_kept"] = int(self.stats.get("five_star_kept", 0)) + 1
                elif rank <= 0:
                    self.stats["unknown_rank_kept"] = int(self.stats.get("unknown_rank_kept", 0)) + 1
                log("领取装备制造：%s(%s) UID %s，%s，已保留。" % (equip_name(eid), eid, uid, protect_reason))
            else:
                if uid > 0:
                    self.pending_retire.append(uid)
                log("领取装备制造：%s(%s) UID %s，%s，加入待拆解队列。" % (equip_name(eid), eid, uid, protect_reason))
        # 有些 finishAllDevelop 返回项不带 build_slot。此时按 ready/force 语义释放本地栏位，
        # 避免“已领取但本地仍认为满栏”导致只收不建。
        if not popped_slots:
            fallback_slots = ready_slots or sorted(old_slots)[:len(add_list)]
            for slot in fallback_slots[:len(add_list)]:
                self.slots.pop(slot, None)
            if fallback_slots:
                log("装备制造领取返回未带栏位号，已按本地完成队列释放栏位：%s" % sorted(fallback_slots[:len(add_list)]))
        if self.pending_retire:
            self.retire_uids(list(self.pending_retire), reason="领取后非保护制造产物拆解")
        self.check_completion(); self.write_cache()

    def start_new_builds(self):
        if self.disabled:
            return
        if self.stop_after_current or self.quota_reached():
            self.stop_after_current = True; self.check_completion(); return
        if not self.ensure_storage_for_factory():
            return
        free_slots = self.free_build_slots()
        if not free_slots:
            # 满栏时先尝试普通领取已完成制造；若领取成功会释放本地栏位并继续提交新制造。
            self.finish_ready_builds(force=True)
            free_slots = self.free_build_slots()
            if not free_slots:
                return
        count = min(len(free_slots), max(0, self.free_equip_slots() - RESERVED_EQUIP_SLOTS), self.contracts, self.quota_remaining_for_start())
        for k, v in self.formula["resources"].items():
            if int(v) > 0:
                count = min(count, self.resources.get(k, 0) // int(v))
        if count <= 0:
            return
        payload = dict(self.formula["resources"])
        payload.update({"input_level": 0, "build_quick": 0, "build_multi": int(count), "build_heavy": 0})
        self.stats["build_attempts"] += int(count)
        resp = self.client.send_request(API_EQUIP_DEVELOP_MULTI, payload)
        if is_error(resp):
            log("提交装备制造失败：%s" % compact_error(resp)); self.write_cache(); return
        equip_ids = resp.get("equip_ids") or []
        if not isinstance(equip_ids, list) or not equip_ids:
            log("提交装备制造返回异常：未包含 equip_ids。"); self.write_cache(); return
        started = 0; t = now_ts()
        for item in equip_ids:
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            eid = int_safe(info.get("equip_id") or item.get("equip_id"), 0)
            slot = int_safe(item.get("slot"), 0)
            if eid <= 0 or slot <= 0:
                continue
            self.slots[slot] = {"slot": slot, "equip_id": eid, "start_time": t, "finish_time": t + equip_duration_for(eid)}
            started += 1
        if started:
            self.stats["build_success"] += started
            self.contracts = max(0, self.contracts - started)
            for k, v in self.formula["resources"].items():
                self.resources[k] = max(0, self.resources.get(k, 0) - int(v) * started)
            log("已启动装备制造 %d 个，公式=%s；栏位占用 %d/%d。" % (started, self.formula["name"], len(self.slots), self.normal_slot_count()))
        if self.quota_reached() and not self.protected_ids:
            self.stop_after_current = True
        self.write_cache()


def main():
    state = load_state()
    if not state.get("doll_enabled") and not state.get("equip_enabled"):
        log("制造自动化未开启，后台退出。")
        return 0
    client = make_client()
    if client is None:
        return 1
    index_payload = request_index(client)
    _index_fetched_at = time.time()
    if not isinstance(index_payload, dict):
        log("无法初始化 Index 缓存，制造自动化后台退出。")
        return 2
    shared_resources = resource_snapshot(index_payload)
    doll_service = DollFactoryService(client, state, index_payload, shared_resources) if state.get("doll_enabled") else None
    equip_service = EquipFactoryService(client, state, index_payload, shared_resources) if state.get("equip_enabled") else None
    errors = 0
    log("制造自动化后台已启动。")
    while True:
        try:
            state = load_state()
            if not state.get("doll_enabled") and not state.get("equip_enabled"):
                log("制造自动化已关闭，后台退出。")
                return 0
            # Refresh Index/index every 300 seconds (5 minutes)
            if time.time() - _index_fetched_at > 300:
                new_payload = request_index(client)
                if new_payload:
                    index_payload = new_payload
                    _index_fetched_at = time.time()
                    if doll_service:
                        doll_service._update_from_index(index_payload)
                    if equip_service:
                        equip_service._update_from_index(index_payload)
                    shared_resources.clear()
                    shared_resources.update(resource_snapshot(index_payload))
                    log("已刷新 Index/index 缓存（周期 300s）。")
            if doll_service and state.get("doll_enabled"):
                doll_service.loop_once()
            if equip_service and state.get("equip_enabled"):
                equip_service.loop_once()
            errors = 0
        except KeyboardInterrupt:
            log("制造自动化后台收到中断，退出。")
            return 0
        except Exception:
            errors += 1
            log("制造自动化后台异常：%s" % traceback.format_exc())
            if errors >= MAX_CONSECUTIVE_ERRORS:
                log("连续异常过多，制造自动化后台退出。")
                return 3
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
