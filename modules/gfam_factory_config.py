# -*- coding: utf-8 -*-
"""GFAM 制造自动化设置。

本模块只负责配置后台制造服务。实际后台循环在 gfam_factory_auto.py 中运行，
并由 run_windows.bat 在其它功能模块运行期间自动启动/停止。
"""
import os
import sys
import json
import time
import copy
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT_DIR / ".gfam_factory_state.json"
QUICK_BUILD_GUI_CONFIG_FILE = ROOT_DIR / ".gfam_quick_build_gui.json"
QUICK_BUILD_SUMMARY_FILE = ROOT_DIR / ".gfam_quick_build_summary.json"
_quick_stats = {}
_round_details = []
SHARED_INDEX_FILE = ROOT_DIR / ".gfam_index_cache.json"
WAREHOUSE_CACHE_FILE = ROOT_DIR / ".gfam_factory_warehouse_cache.json"
INDEX_CACHE_TTL_SECONDS = int(os.environ.get("GFAM_SHARED_INDEX_TTL", "300") or "300")
DATA_DIR = ROOT_DIR / "data"
GFLZIRC_CORE_DIR = ROOT_DIR / "libs" / "ZIRC" / "src" / "core"
if str(GFLZIRC_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(GFLZIRC_CORE_DIR))

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

API_INDEX_INDEX = "Index/index"
API_GUN_DEVELOP_MULTI = "Gun/developMultiGun"
API_GUN_FINISH_ALL_DEVELOP = "Gun/finishAllDevelop"
API_EQUIP_DEVELOP_MULTI = "Equip/developMulti"
API_EQUIP_FINISH_ALL_DEVELOP = "Equip/finishAllDevelop"
API_EQUIP_RETIRE = "Equip/retire"
API_GUN_RETIRE = "Gun/retireGun"

RESERVED_EQUIP_SLOTS = max(1, int(os.environ.get("GFAM_FACTORY_RESERVED_EQUIP_SLOTS", "1") or "1"))

RETIRE_BATCH_SIZE = max(20, int(os.environ.get("GFAM_FACTORY_RETIRE_BATCH_SIZE", "80") or "80"))
RETIRE_BATCH_DELAY = max(0.0, float(os.environ.get("GFAM_FACTORY_RETIRE_BATCH_DELAY", "0.25") or "0.25"))
RETIRE_UNKNOWN_KEYWORDS = (
    "unexpected plaintext response", "plaintext response", "timed out", "timeout",
    "read timed", "connection aborted", "remote end closed", "temporarily unavailable",
)

DOLL_FORMULAS = {
    "handgun": {"name": "手枪", "type": 1, "resources": {"mp": 130, "ammo": 130, "mre": 130, "part": 30}, "recommended": {233: "Px4 Storm / Px4风暴"}},
    "smg": {"name": "冲锋枪", "type": 2, "resources": {"mp": 400, "ammo": 400, "mre": 100, "part": 200}, "recommended": {115: "Suomi / 索米"}},
    "rifle": {"name": "步枪", "type": 3, "resources": {"mp": 400, "ammo": 100, "mre": 400, "part": 200}, "recommended": {}},
    "ar": {"name": "突击步枪", "type": 4, "resources": {"mp": 100, "ammo": 400, "mre": 400, "part": 200}, "recommended": {}},
    "mg": {"name": "机枪", "type": 5, "resources": {"mp": 800, "ammo": 800, "mre": 100, "part": 400}, "recommended": {}},
}

EQUIP_FORMULAS = {
    "optic": {"name": "光学瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}, "recommended": {}},
    "holo": {"name": "全息瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}, "recommended": {}},
    "red_dot": {"name": "红点瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}, "recommended": {}},
    "night": {"name": "夜战装备", "resources": {"mp": 70, "ammo": 10, "mre": 150, "part": 30}, "recommended": {}},
    "suppressor": {"name": "消音器", "resources": {"mp": 150, "ammo": 50, "mre": 50, "part": 50}, "recommended": {}},
    "ap": {"name": "穿甲弹", "resources": {"mp": 10, "ammo": 150, "mre": 90, "part": 100}, "recommended": {}},
    "status": {"name": "状态弹", "resources": {"mp": 180, "ammo": 180, "mre": 10, "part": 50}, "recommended": {}},
    "hv": {"name": "高速弹", "resources": {"mp": 10, "ammo": 230, "mre": 120, "part": 80}, "recommended": {}},
    "shotgun": {"name": "散弹", "resources": {"mp": 30, "ammo": 150, "mre": 30, "part": 130}, "recommended": {}},
    "exo": {"name": "外骨骼", "resources": {"mp": 100, "ammo": 80, "mre": 10, "part": 100}, "recommended": {}},
    "armor": {"name": "防弹插板", "resources": {"mp": 50, "ammo": 50, "mre": 100, "part": 100}, "recommended": {}},
    "ammo_box": {"name": "弹链箱", "resources": {"mp": 30, "ammo": 30, "mre": 30, "part": 200}, "recommended": {}},
    "cape": {"name": "伪装披风", "resources": {"mp": 180, "ammo": 20, "mre": 200, "part": 20}, "recommended": {}},
    "mixed": {"name": "装备混合", "resources": {"mp": 150, "ammo": 150, "mre": 150, "part": 150}, "recommended": {}},
    "backup_sight": {"name": "备用瞄具", "resources": {"mp": 180, "ammo": 65, "mre": 65, "part": 65}, "recommended": {}},
    "chip": {"name": "芯片", "resources": {"mp": 170, "ammo": 120, "mre": 50, "part": 50}, "recommended": {}},
    "special_ap": {"name": "特殊穿甲弹", "resources": {"mp": 10, "ammo": 300, "mre": 10, "part": 10}, "recommended": {}},
    "bipod": {"name": "固定脚架", "resources": {"mp": 300, "ammo": 10, "mre": 10, "part": 200}, "recommended": {}},
    "tube": {"name": "收缩管", "resources": {"mp": 80, "ammo": 220, "mre": 80, "part": 80}, "recommended": {}},
    "rangefinder": {"name": "测距仪", "resources": {"mp": 100, "ammo": 250, "mre": 150, "part": 170}, "recommended": {}},
}

RESOURCE_LABELS = {"mp": "人力", "ammo": "弹药", "mre": "口粮", "part": "零件"}


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
        print("[工厂配置] 写入 JSON 失败：%s" % e)
        raise


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


def save_state(st):
    import time
    st["updated_at"] = int(time.time())
    write_json(STATE_FILE, st)


def load_gun_catalog():
    merged = {}
    for fn in ("gun.json", "gun1.json"):
        arr = read_json(DATA_DIR / fn, [])
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                try:
                    gid = int(item.get("id"))
                except Exception:
                    continue
                old = merged.get(gid, {})
                old.update(item)
                merged[gid] = old
    return merged


def load_equip_catalog():
    merged = {}
    for fn in ("equip.json", "equip1.json", "equipment.json"):
        arr = read_json(DATA_DIR / fn, [])
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                try:
                    eid = int(item.get("id") or item.get("equip_id"))
                except Exception:
                    continue
                old = merged.get(eid, {})
                old.update(item)
                merged[eid] = old
    return merged


def gun_display_name(item):
    if not isinstance(item, dict):
        return "未知"
    for key in ("en_name", "code", "name"):
        val = str(item.get(key) or "").strip()
        if val and not val.startswith("gun-"):
            return val
    return str(item.get("name") or item.get("code") or item.get("en_name") or "未知")


def equip_display_name(item, equip_id=None):
    if not isinstance(item, dict):
        return "equip-%s" % equip_id if equip_id else "未知装备"
    for key in ("name", "en_name", "code"):
        val = str(item.get(key) or "").strip()
        if val and not val.startswith("equip-"):
            return val
    return str(item.get("name") or item.get("code") or item.get("en_name") or ("equip-%s" % equip_id))


def equip_rank_from_catalog_item(item):
    if not isinstance(item, dict):
        return 0
    for key in ("rank", "star", "quality", "quality_lv"):
        try:
            v = int(float(str(item.get(key, 0)).strip()))
        except Exception:
            v = 0
        if v > 0:
            return v
    return 0


def equip_rank_by_id(catalog, equip_id):
    try:
        equip_id = int(equip_id)
    except Exception:
        return 0
    return equip_rank_from_catalog_item(catalog.get(equip_id))


def equip_is_five_star(catalog, equip_id):
    return equip_rank_by_id(catalog, equip_id) >= 5


def equip_is_holo_or_red_dot(catalog, equip_id):
    """Identify normal holographic / red-dot sight families.

    Normal holo/red-dot sights are type 2/3 or auto_select_id 2001/3001.
    Type 18 exclusive equipment is intentionally excluded even if its code
    contains 全息 or ACOG.
    """
    try:
        equip_id = int(equip_id)
    except Exception:
        return False
    item = catalog.get(equip_id, {}) if isinstance(catalog, dict) else {}
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


def equip_protect_decision(catalog, equip_id, protect_holo_red_dot=False):
    rank = equip_rank_by_id(catalog, equip_id)
    if equip_is_holo_or_red_dot(catalog, equip_id):
        if protect_holo_red_dot:
            return True, "全息/红点瞄具保护开关已开启"
        if rank > 0:
            return False, "%s星全息/红点瞄具默认不保护" % rank
        return True, "星级未知，保守保留"
    if rank >= 5:
        return True, "五星装备，已自动保护/保留"
    if rank > 0:
        return False, "%s星装备，非保护，可进入后续拆解队列" % rank
    return True, "星级未知，保守保留，避免误拆"


def resource_text(res):
    return " / ".join("%s %s" % (RESOURCE_LABELS[k], res.get(k, 0)) for k in ("mp", "ammo", "mre", "part"))


def int_safe(v, default=0):
    try:
        if v is None:
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def normalize_list_or_dict(value):
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    return []


def item_count(index_payload, item_id):
    for item in normalize_list_or_dict(index_payload.get("item_with_user_info", [])):
        if int_safe(item.get("item_id"), -1) == int(item_id):
            return int_safe(item.get("number"), 0)
    return 0


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


def normal_slot_count(max_build_slot):
    """Number of normal (普通) build slots."""
    return len(normal_slot_numbers(max_build_slot))


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


_GUN_CATALOG_CACHE = None


def _get_gun_catalog_cached():
    global _GUN_CATALOG_CACHE
    if _GUN_CATALOG_CACHE is None:
        _GUN_CATALOG_CACHE = load_gun_catalog()
    return _GUN_CATALOG_CACHE


def develop_duration_for(gun_id):
    item = _get_gun_catalog_cached().get(int_safe(gun_id), {})
    return max(60, int_safe(item.get("develop_duration"), 20 * 60))


def equip_duration_for(equip_id):
    item = load_equip_catalog().get(int_safe(equip_id), {})
    for key in ("develop_duration", "build_time", "develop_time", "time"):
        val = int_safe(item.get(key), 0)
        if val > 0:
            return max(60, val)
    return 30 * 60


def format_seconds(sec):
    sec = max(0, int_safe(sec, 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)


def _record_result_id(item, kind):
    if kind == "doll":
        return int_safe(item.get("gun_id") or item.get("id"), 0)
    info = item.get("info") if isinstance(item.get("info"), dict) else {}
    return int_safe(info.get("equip_id") or item.get("equip_id") or item.get("id"), 0)


def _fallback_duration(kind, result_id):
    return develop_duration_for(result_id) if kind == "doll" else equip_duration_for(result_id)


def build_slot_states_from_index(index_payload, key, kind):
    """Return slot states parsed from Index/index with real remain/finish fields when present.

    This mirrors the fairy logic: prefer explicit ready flags, finish_time/end_time,
    remain_time/remaining_time, and only then fall back to start_time + catalog duration.
    """
    now = int(time.time())
    states = {}
    for item in normalize_list_or_dict(index_payload.get(key, [])):
        if not isinstance(item, dict):
            continue
        slot = int_safe(item.get("build_slot") or item.get("slot"), 0)
        if slot <= 0:
            continue
        result_id = _record_result_id(item, kind)
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
            start_time = int_safe(item.get("start_time"), 0)
            if start_time > 0:
                expected_finish = start_time + _fallback_duration(kind, result_id)
                remain = max(0, expected_finish - now)
                status_source = "start_time_estimated"
            else:
                expected_finish = now
                remain = 0
                status_source = "no_time_ready"
        states[slot] = {
            "slot": slot,
            "kind": kind,
            "result_id": result_id,
            "remain": remain,
            "is_ready": remain <= 0,
            "expected_finish_time": expected_finish,
            "status_source": status_source,
            "is_heavy": (slot % 2 == 0),
            "raw": item,
        }
    return states


def used_slots_from_index(index_payload, key):
    kind = "equip" if "equip" in str(key) else "doll"
    return set(build_slot_states_from_index(index_payload, key, kind).keys())


def print_slot_states(states, label):
    if not states:
        print("[*] 当前没有%s制造占用栏位。" % label)
        return
    for slot in sorted(states):
        st = states[slot]
        rid = st.get("result_id") or "?"
        heavy_tag = "（重型）" if st.get("is_heavy") else "（普通）"
        if st.get("is_ready"):
            print("    栏位 %s%s：已完成待领取，结果ID=%s，来源=%s" % (slot, heavy_tag, rid, st.get("status_source")))
        else:
            print("    栏位 %s%s：建造中，剩余 %s，结果ID=%s，来源=%s" % (slot, heavy_tag, format_seconds(st.get("remain", 0)), rid, st.get("status_source")))


def resource_snapshot(index_payload):
    ui = index_payload.get("user_info") or {}
    return {k: int_safe(ui.get(k), 0) for k in ("mp", "ammo", "mre", "part")}


def has_enough_resources(resources, formula):
    missing = []
    for k, need in formula.get("resources", {}).items():
        have = int_safe(resources.get(k), 0)
        need = int_safe(need, 0)
        if have < need:
            missing.append("%s不足：%s/%s" % (RESOURCE_LABELS.get(k, k), have, need))
    return missing


def _derive_factory_warehouse_snapshot(index_payload, source="index"):
    """Create a small local warehouse snapshot from an Index-like payload.

    This mirrors the fairy automation style: later factory actions update this
    counter locally, so warehouse-space checks do not need a fresh Index/index
    after every claim/build/retire action.
    """
    if not isinstance(index_payload, dict):
        return {}
    ui = index_payload.get("user_info") if isinstance(index_payload.get("user_info"), dict) else {}
    maxgun = int_safe(ui.get("maxgun"), 0)
    maxequip = int_safe(ui.get("maxequip"), 0)
    gun_count_value = len(normalize_list_or_dict(index_payload.get("gun_with_user_info", [])))
    equip_count_value = len(normalize_list_or_dict(index_payload.get("equip_with_user_info", [])))
    return {
        "schema": "gfam_factory_warehouse_cache_v1",
        "updated_at": int(time.time()),
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
    snapshot["updated_at"] = int(time.time())
    if isinstance(index_payload, dict):
        index_payload["_gfam_local_warehouse"] = snapshot
    try:
        write_json(WAREHOUSE_CACHE_FILE, snapshot)
    except Exception:
        pass
    return index_payload


def ensure_local_warehouse_snapshot(index_payload, source="index"):
    if not isinstance(index_payload, dict):
        return index_payload
    wh = index_payload.get("_gfam_local_warehouse")
    if not isinstance(wh, dict):
        wh = _derive_factory_warehouse_snapshot(index_payload, source=source)
        _save_payload_warehouse_snapshot(index_payload, wh)
    return index_payload


def adjust_local_warehouse_snapshot(index_payload, kind, delta, source="local_action"):
    """Update only local warehouse counters after a trusted server action.

    kind: "equip" or "gun".  This intentionally does not require a fresh Index.
    """
    if not isinstance(index_payload, dict):
        return index_payload
    ensure_local_warehouse_snapshot(index_payload, source="before_" + source)
    wh = dict(_get_payload_warehouse_snapshot(index_payload))
    delta = int_safe(delta, 0)
    if kind == "equip":
        maxv = int_safe(wh.get("maxequip"), equip_storage_max(index_payload))
        cnt = max(0, int_safe(wh.get("equip_count"), len(normalize_list_or_dict(index_payload.get("equip_with_user_info", [])))) + delta)
        wh["equip_count"] = cnt
        wh["maxequip"] = maxv
        wh["equip_free"] = max(0, maxv - cnt) if maxv > 0 else 0
    else:
        ui = index_payload.get("user_info") if isinstance(index_payload.get("user_info"), dict) else {}
        maxv = int_safe(wh.get("maxgun"), int_safe(ui.get("maxgun"), 0))
        cnt = max(0, int_safe(wh.get("gun_count"), len(normalize_list_or_dict(index_payload.get("gun_with_user_info", [])))) + delta)
        wh["gun_count"] = cnt
        wh["maxgun"] = maxv
        wh["gun_free"] = max(0, maxv - cnt) if maxv > 0 else 0
    wh["schema"] = "gfam_factory_warehouse_cache_v1"
    wh["source"] = source
    _save_payload_warehouse_snapshot(index_payload, wh)
    return index_payload


def gun_storage_count(index_payload):
    wh = _get_payload_warehouse_snapshot(index_payload)
    if isinstance(wh, dict) and "gun_count" in wh:
        return int_safe(wh.get("gun_count"), 0)
    return len(normalize_list_or_dict(index_payload.get("gun_with_user_info", [])))


def gun_storage_max(index_payload):
    return int_safe((index_payload.get("user_info") or {}).get("maxgun"), 0)


def gun_storage_free(index_payload):
    mx = gun_storage_max(index_payload)
    if mx <= 0:
        return 0
    return max(0, mx - gun_storage_count(index_payload))


def gun_uid_from_record(gun):
    if not isinstance(gun, dict):
        return 0
    for key in ("gun_with_user_id", "id", "uid"):
        if key in gun:
            return int_safe(gun.get(key), 0)
    return 0


def equip_storage_count(index_payload):
    wh = _get_payload_warehouse_snapshot(index_payload)
    if isinstance(wh, dict) and "equip_count" in wh:
        return int_safe(wh.get("equip_count"), 0)
    return len(normalize_list_or_dict(index_payload.get("equip_with_user_info", [])))


def equip_storage_max(index_payload):
    return int_safe((index_payload.get("user_info") or {}).get("maxequip"), 0)


def equip_storage_free(index_payload):
    mx = equip_storage_max(index_payload)
    if mx <= 0:
        return 0
    return max(0, mx - equip_storage_count(index_payload))


def equip_uid_from_record(equip):
    if not isinstance(equip, dict):
        return 0
    for key in ("equip_with_user_id", "id", "uid"):
        if key in equip:
            return int_safe(equip.get(key), 0)
    return 0


def equip_id_from_record(equip):
    if not isinstance(equip, dict):
        return 0
    return int_safe(equip.get("equip_id") or equip.get("equip") or equip.get("id"), 0)


def equip_locked_from_record(equip):
    if not isinstance(equip, dict):
        return False
    for key in ("is_locked", "locked", "lock", "is_lock"):
        if key in equip and str(equip.get(key)).strip().lower() in ("1", "true", "yes", "y"):
            return True
    return False


def equip_on_gun_from_record(equip):
    if not isinstance(equip, dict):
        return False
    return int_safe(equip.get("gun_with_user_id"), 0) > 0


def equip_rank_from_record(equip, catalog=None):
    if not isinstance(equip, dict):
        return 0
    for key in ("rank", "star", "quality", "quality_lv"):
        v = int_safe(equip.get(key), 0)
        if v > 0:
            return v
    if catalog is None:
        catalog = load_equip_catalog()
    return equip_rank_by_id(catalog, equip_id_from_record(equip))


def remove_equips_from_index_snapshot(index_payload, uids):
    """Remove retired equipment from current Index snapshot and write shared cache."""
    if not isinstance(index_payload, dict):
        return index_payload
    uids = set(int_safe(x, 0) for x in uids if int_safe(x, 0) > 0)
    if not uids:
        return index_payload
    new_payload = copy.deepcopy(index_payload)
    raw = new_payload.get("equip_with_user_info", [])
    def keep(item):
        return equip_uid_from_record(item) not in uids
    if isinstance(raw, list):
        new_payload["equip_with_user_info"] = [item for item in raw if keep(item)]
    elif isinstance(raw, dict):
        new_payload["equip_with_user_info"] = {k: v for k, v in raw.items() if keep(v)}
    adjust_local_warehouse_snapshot(new_payload, "equip", -len(uids), source="factory_test_local_after_equip_retire")
    write_shared_index_cache(new_payload, source="factory_test_local_after_equip_retire")
    return new_payload


def remove_guns_from_index_snapshot(index_payload, uids):
    """Remove retired dolls from current Index snapshot and write shared cache."""
    if not isinstance(index_payload, dict):
        return index_payload
    uids = set(int_safe(x, 0) for x in uids if int_safe(x, 0) > 0)
    if not uids:
        return index_payload
    new_payload = copy.deepcopy(index_payload)
    raw = new_payload.get("gun_with_user_info", [])
    def keep(item):
        return gun_uid_from_record(item) not in uids
    if isinstance(raw, list):
        new_payload["gun_with_user_info"] = [item for item in raw if keep(item)]
    elif isinstance(raw, dict):
        new_payload["gun_with_user_info"] = {k: v for k, v in raw.items() if keep(v)}
    adjust_local_warehouse_snapshot(new_payload, "gun", -len(uids), source="factory_test_local_after_gun_retire")
    write_shared_index_cache(new_payload, source="factory_test_local_after_gun_retire")
    return new_payload


def retire_dolls_for_test(client, index_payload, uids, reason="人形测试拆解"):
    """Retire (dismantle) specific dolls by UID for test flows."""
    clean = []
    seen = set()
    for x in uids:
        uid = int_safe(x, 0)
        if uid > 0 and uid not in seen:
            clean.append(uid); seen.add(uid)
    if not clean:
        return index_payload, 0
    total_ok = 0
    total = len(clean)
    print("[*] %s：准备拆解 %d 名人形；按每批最多 %d 分批提交。" % (reason, total, RETIRE_BATCH_SIZE))
    for batch_no, batch in enumerate(chunked_list(clean, RETIRE_BATCH_SIZE), start=1):
        print("[*] %s：提交人形拆解批次 %d，数量 %d/%d。" % (reason, batch_no, len(batch), total))
        resp = client.send_request(API_GUN_RETIRE, batch)
        if is_error(resp):
            if retire_response_unknown(resp):
                print("[!] 人形拆解批次响应状态未知：%s" % compact_error(resp))
                print("[!] 已停止后续批次，不把本次判定为明确拆解失败。")
                return index_payload, total_ok
            print("[!] 人形拆解失败：%s" % compact_error(resp))
            return index_payload, total_ok
        index_payload = remove_guns_from_index_snapshot(index_payload, batch)
        total_ok += len(batch)
        print("[+] 人形拆解批次成功：%d。当前人形仓库估算 %s/%s，空位 %s。" % (
            len(batch), gun_storage_count(index_payload), gun_storage_max(index_payload), gun_storage_free(index_payload)))
        if RETIRE_BATCH_DELAY > 0:
            time.sleep(RETIRE_BATCH_DELAY)
    print("[+] 人形拆解完成：%d/%d。当前人形仓库估算 %s/%s，空位 %s。" % (
        total_ok, total, gun_storage_count(index_payload), gun_storage_max(index_payload), gun_storage_free(index_payload)))
    return index_payload, total_ok


def retire_non_target_dolls_for_test(client, index_payload, finish_resp, protected_ids=None):
    """After test finishAllDevelop, retire non-protected doll outputs.

    Returns (index_payload, retired_count).
    Dolls whose gun_id is in protected_ids are kept; all others are retired.
    If protected_ids is empty/None, ALL claimed dolls are retired (test-only cleanup).
    """
    add_list = finish_resp.get("gun_with_user_add_list") if isinstance(finish_resp, dict) else None
    if not isinstance(add_list, list) or not add_list:
        return index_payload, 0
    protected = set(int_safe(x, 0) for x in (protected_ids or []) if int_safe(x, 0) > 0)
    catalog = load_gun_catalog()
    retire_uids = []
    kept_uids = []
    for item in add_list:
        gid = int_safe(item.get("gun_id"), 0)
        uid = int_safe(item.get("gun_with_user_id"), 0)
        if uid <= 0:
            continue
        if protected and gid in protected:
            kept_uids.append(uid)
        else:
            retire_uids.append(uid)
    if kept_uids:
        print("[*] 本次领取中 %d 名人形命中保护目标，已保留。" % len(kept_uids))
    retired_count = 0
    if retire_uids:
        print("[*] 本次领取中 %d 名人形为非目标产物，将自动拆解。" % len(retire_uids))
        index_payload, retired_count = retire_dolls_for_test(client, index_payload, retire_uids, reason="快速建造后非目标人形自动拆解")
    else:
        print("[*] 本次领取的所有人形均命中保护目标，无需拆解。")
    return index_payload, retired_count


def force_finish_builds_for_test(client, index_payload, kind, protected_ids=None, protect_holo_red_dot=False):
    """Force-complete ALL ongoing builds (costs quick contracts) and retire non-target outputs.

    Returns (index_payload, claimed_count, retired_count) or (index_payload, 0, 0) on failure.
    """
    if kind == "doll":
        api = API_GUN_FINISH_ALL_DEVELOP
        label = "人形"
    else:
        api = API_EQUIP_FINISH_ALL_DEVELOP
        label = "装备"
    print("[*] 正在强制完成所有%s制造栏位（消耗快速制造契约）..." % label)
    finish_payload = {"is_cost_item3": 1}
    resp = client.send_request(api, finish_payload)
    if is_error(resp):
        print("[!] 强制完成%s制造失败：%s" % (label, compact_error(resp)))
        return index_payload, 0, 0
    add_key = "gun_with_user_add_list" if kind == "doll" else "equip_with_user_add_list"
    add_list = resp.get(add_key)
    claimed = len(add_list) if isinstance(add_list, list) else 0
    print("[+] 强制完成并领取%s制造 %d 个。" % (label, claimed))
    # Apply to local snapshot
    index_payload = apply_finish_response_to_index_snapshot(index_payload, resp, kind, ready_slots=None, cost_quick=True) or index_payload
    # Retire non-target products
    retired = 0
    if kind == "doll":
        print_finish_doll_result(resp, protected_ids=protected_ids, protect_mode=None)
        index_payload, retired = retire_non_target_dolls_for_test(client, index_payload, resp, protected_ids=protected_ids)
    else:
        print_finish_equip_result(resp, protect_holo_red_dot=protect_holo_red_dot)
        index_payload, retired = retire_non_five_star_finished_equips_for_test(client, index_payload, resp, protect_holo_red_dot=protect_holo_red_dot)
    return index_payload, claimed, retired


def collect_low_star_retire_equips_for_test(index_payload, max_count=20, protect_holo_red_dot=False):
    """Safe emergency retire list for factory test: unlocked, unequipped, known 1-4 star only."""
    catalog = load_equip_catalog()
    result = []
    for eq in normalize_list_or_dict(index_payload.get("equip_with_user_info", [])):
        if not isinstance(eq, dict):
            continue
        if equip_locked_from_record(eq) or equip_on_gun_from_record(eq):
            continue
        uid = equip_uid_from_record(eq)
        if uid <= 0:
            continue
        eid = equip_id_from_record(eq)
        rank = equip_rank_from_record(eq, catalog)
        if equip_is_holo_or_red_dot(catalog, eid):
            if protect_holo_red_dot:
                continue
            # 默认：普通全息/红点瞄具所有已知星级均不保护。
            if rank > 0:
                result.append(uid)
        elif 0 < rank < 5:
            result.append(uid)
        if len(result) >= max_count:
            break
    return result


def retire_equips_for_test(client, index_payload, uids, reason="装备测试应急拆解"):
    clean = []
    seen = set()
    for x in uids:
        uid = int_safe(x, 0)
        if uid > 0 and uid not in seen:
            clean.append(uid); seen.add(uid)
    if not clean:
        return index_payload, 0
    total_ok = 0
    total = len(clean)
    print("[*] %s：准备拆解 %d 件低星装备；按每批最多 %d 分批提交。" % (reason, total, RETIRE_BATCH_SIZE))
    for batch_no, batch in enumerate(chunked_list(clean, RETIRE_BATCH_SIZE), start=1):
        print("[*] %s：提交装备拆解批次 %d，数量 %d/%d。" % (reason, batch_no, len(batch), total))
        resp = client.send_request(API_EQUIP_RETIRE, {"equips": batch})
        if is_error(resp):
            if retire_response_unknown(resp):
                print("[!] 装备拆解批次响应状态未知：%s" % compact_error(resp))
                print("[!] 已停止后续批次，不把本次判定为明确拆解失败；请等待下一轮或回游戏确认仓库状态。")
                return index_payload, total_ok
            print("[!] 装备拆解失败：%s" % compact_error(resp))
            return index_payload, total_ok
        index_payload = remove_equips_from_index_snapshot(index_payload, batch)
        total_ok += len(batch)
        print("[+] 装备拆解批次成功：%d。当前装备仓库估算 %s/%s，空位 %s。" % (
            len(batch), equip_storage_count(index_payload), equip_storage_max(index_payload), equip_storage_free(index_payload)))
        if RETIRE_BATCH_DELAY > 0:
            time.sleep(RETIRE_BATCH_DELAY)
    print("[+] 装备拆解完成：%d/%d。当前装备仓库估算 %s/%s，空位 %s。" % (
        total_ok, total, equip_storage_count(index_payload), equip_storage_max(index_payload), equip_storage_free(index_payload)))
    return index_payload, total_ok


def ensure_equip_storage_for_test(client, index_payload, protect_holo_red_dot=False):
    """Before test equip build, keep at least RESERVED_EQUIP_SLOTS free.

    如果装备仓库只剩 1 个空位（默认保留线）或更少，先执行成熟的低星应急拆解；
    拆解后仍然只剩 1 个空位则停止本次测试/自动制造，避免把最后空位占满。
    """
    free = equip_storage_free(index_payload)
    mx = equip_storage_max(index_payload)
    cnt = equip_storage_count(index_payload)
    print("[*] 装备仓库本地缓存：%s/%s，空位 %s；自动制造保留空位 %s。" % (cnt, mx, free, RESERVED_EQUIP_SLOTS))
    if free > RESERVED_EQUIP_SLOTS:
        return index_payload, True
    print("[!] 装备仓库空位仅剩 %s，先尝试拆解低星非保护装备。" % free)
    candidates = collect_low_star_retire_equips_for_test(index_payload, max_count=20, protect_holo_red_dot=protect_holo_red_dot)
    if not candidates:
        print("[!] 没有可安全拆解的低星装备；本次装备制造测试停止。")
        return index_payload, False
    index_payload, retired = retire_equips_for_test(client, index_payload, candidates, reason="装备仓库空位不足，测试前应急拆解低星/默认不保护瞄具")
    free = equip_storage_free(index_payload)
    if free > RESERVED_EQUIP_SLOTS:
        return index_payload, True
    print("[!] 拆解后装备仓库空位仍为 %s，未超过保留线 %s；本次装备制造测试停止。" % (free, RESERVED_EQUIP_SLOTS))
    return index_payload, False


def retire_non_five_star_finished_equips_for_test(client, index_payload, finish_resp, protect_holo_red_dot=False):
    """After test finishAllDevelop, retire non-protected outputs.

    Returns (index_payload, retired_count).
    Normal 5-star equipment is protected, but normal holo/red-dot sights of
    every known star level are not protected unless the manual switch is on.
    """
    add_list = finish_resp.get("equip_with_user_add_list") if isinstance(finish_resp, dict) else None
    if not isinstance(add_list, list) or not add_list:
        return index_payload, 0
    catalog = load_equip_catalog()
    retire_uids = []
    for item in add_list:
        eid = int_safe(item.get("equip_id"), 0)
        ew = item.get("equip_with_user") if isinstance(item.get("equip_with_user"), dict) else {}
        uid = int_safe(ew.get("id") or item.get("equip_with_user_id") or item.get("id"), 0)
        protected, _reason = equip_protect_decision(catalog, eid, protect_holo_red_dot=protect_holo_red_dot)
        if uid > 0 and not protected:
            retire_uids.append(uid)
    retired_count = 0
    if retire_uids:
        index_payload, retired_count = retire_equips_for_test(client, index_payload, retire_uids, reason="测试领取后非保护装备自动拆解")
    else:
        print("[*] 本次测试领取结果没有可自动拆解的非保护装备；保护/未知星级装备均已保留。")
    return index_payload, retired_count


def compact_error(resp):
    if isinstance(resp, dict):
        return str(resp.get("error_local") or resp.get("error") or resp)[:500]
    return str(resp)[:500]


def is_error(resp):
    return (not isinstance(resp, dict)) or bool(resp.get("error") or resp.get("error_local"))


def chunked_list(values, size):
    size = max(1, int_safe(size, 80))
    for i in range(0, len(values), size):
        yield values[i:i + size]


def retire_response_unknown(resp):
    text = compact_error(resp).lower()
    return any(k in text for k in RETIRE_UNKNOWN_KEYWORDS)


def identity_from_env_for_factory_test():
    server = str(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP").strip().upper().replace("_", "-")
    if server in ("AR15",):
        server = "AR-15"
    uid = str(os.environ.get("GFAM_USER_UID") or "").strip()
    sign = str(os.environ.get("GFAM_SIGN_KEY") or DEFAULT_SIGN or "").strip()
    base_url = SERVERS.get(server) or SERVERS.get("SOP")
    return server, uid, sign, base_url


def make_client_for_factory_test():
    if GFLClient is None:
        print("[!] gflzirc 未加载，无法执行制造请求测试。")
        return None
    server, uid, sign, base_url = identity_from_env_for_factory_test()
    if not uid or not sign or sign == DEFAULT_SIGN or not base_url:
        print("[!] UID/SIGN/服务器未就绪。请先从 GFAM 主菜单完成 UID/SIGN 获取后再进入 factory。")
        print("    server=%s uid=%s base_url=%s" % (server, "已填写" if uid else "空", base_url or "空"))
        return None
    print("[*] 当前服务器：%s" % server)
    print("[*] UID/SIGN：已读取（UID %s***）" % (uid[:-3] if len(uid) > 3 else uid))
    return GFLClient(uid, sign, base_url)


def _shared_index_server_matches(cache):
    if not isinstance(cache, dict):
        return False
    cache_server = str(cache.get("server") or "").strip().upper()
    if not cache_server:
        return True
    current_server = str(identity_from_env_for_factory_test()[0] or "").strip().upper()
    return cache_server == current_server


def read_shared_index_cache(max_age=INDEX_CACHE_TTL_SECONDS):
    cache = read_json(SHARED_INDEX_FILE, None)
    if not isinstance(cache, dict):
        return None, "missing"
    payload = cache.get("payload") if isinstance(cache.get("payload"), dict) else None
    if payload is None and isinstance(cache.get("user_info"), dict):
        payload = cache
    if not isinstance(payload, dict):
        return None, "invalid"
    if not _shared_index_server_matches(cache):
        return None, "server_mismatch"
    ts = int_safe(cache.get("saved_at") or cache.get("time") or cache.get("created_at"), 0)
    if max_age and ts > 0:
        age = int(time.time()) - ts
        if age > int(max_age):
            return None, "expired:%s" % age
        return payload, "cache:%ss" % max(age, 0)
    return payload, "cache"


def write_shared_index_cache(payload, source="factory_test_Index/index"):
    if not isinstance(payload, dict):
        return
    try:
        ensure_local_warehouse_snapshot(payload, source=source)
        server = identity_from_env_for_factory_test()[0]
        write_json(SHARED_INDEX_FILE, {
            "schema": "gfam_shared_index_cache_v1",
            "source": source,
            "server": server,
            "saved_at": int(time.time()),
            "payload": payload,
        })
    except Exception:
        pass


def _adjust_user_resource(payload, resources, multiplier=-1):
    """Best-effort local update of user_info resource fields after develop requests."""
    if not isinstance(payload, dict):
        return
    ui = payload.get("user_info")
    if not isinstance(ui, dict):
        return
    for k in ("mp", "ammo", "mre", "part"):
        delta = int_safe((resources or {}).get(k), 0) * int_safe(multiplier, -1)
        ui[k] = max(0, int_safe(ui.get(k), 0) + delta)


def _adjust_item_count(payload, item_id, delta):
    """Best-effort local update of item_with_user_info count."""
    if not isinstance(payload, dict):
        return
    items = payload.get("item_with_user_info")
    if isinstance(items, dict):
        for item in items.values():
            if isinstance(item, dict) and int_safe(item.get("item_id"), -1) == int(item_id):
                item["number"] = max(0, int_safe(item.get("number"), 0) + int_safe(delta, 0))
                return
        # Preserve dict shape if possible.
        key = str(item_id)
        items[key] = {"item_id": int(item_id), "number": max(0, int_safe(delta, 0))}
        return
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and int_safe(item.get("item_id"), -1) == int(item_id):
                item["number"] = max(0, int_safe(item.get("number"), 0) + int_safe(delta, 0))
                return
        items.append({"item_id": int(item_id), "number": max(0, int_safe(delta, 0))})
        return
    payload["item_with_user_info"] = [{"item_id": int(item_id), "number": max(0, int_safe(delta, 0))}]


def _append_build_records_to_index(payload, develop_resp, kind):
    """Append newly submitted build records to an Index snapshot locally.

    The server develop* response already contains the result id and slot. We only need a
    conservative record for later slot/resource decisions; start_time is enough for the
    existing build_slot_states_from_index fallback estimator.
    """
    if not isinstance(payload, dict) or not isinstance(develop_resp, dict):
        return []
    if kind == "doll":
        list_key = "gun_ids"
        act_key = "develop_act_info"
    else:
        list_key = "equip_ids"
        act_key = "develop_equip_act_info"
    started = develop_resp.get(list_key)
    if not isinstance(started, list) or not started:
        return []
    now = int(time.time())
    records = []
    for item in started:
        if not isinstance(item, dict):
            continue
        slot = int_safe(item.get("build_slot") or item.get("slot"), 0)
        if slot <= 0:
            continue
        if kind == "doll":
            rid = int_safe(item.get("gun_id") or item.get("id"), 0)
            rec = {"build_slot": slot, "gun_id": rid, "start_time": now}
        else:
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            rid = int_safe(info.get("equip_id") or item.get("equip_id") or item.get("id"), 0)
            rec = {"build_slot": slot, "equip_id": rid, "start_time": now}
            if info:
                rec["info"] = dict(info)
        records.append(rec)
    if not records:
        return []
    existing = payload.get(act_key)
    if isinstance(existing, list):
        existing.extend(records)
    elif isinstance(existing, dict):
        for rec in records:
            existing[str(rec.get("build_slot"))] = rec
    else:
        payload[act_key] = records
    return [int_safe(r.get("build_slot"), 0) for r in records if int_safe(r.get("build_slot"), 0) > 0]


def apply_develop_response_to_index_snapshot(index_payload, develop_resp, kind, formula):
    """Apply a successful develop request to the shared Index snapshot locally.

    This keeps the Index cache usable after submitting a manufacturing request, avoiding
    the old behavior of deleting the cache and forcing the next flow to request Index again.
    """
    if not isinstance(index_payload, dict) or not isinstance(develop_resp, dict):
        return None
    new_payload = copy.deepcopy(index_payload)
    slots = _append_build_records_to_index(new_payload, develop_resp, kind)
    if not slots:
        print("[*] 制造提交返回未包含可解析栏位，无法安全更新共享 Index 缓存；本次保留旧缓存但不用于强推。")
        return None
    _adjust_user_resource(new_payload, (formula or {}).get("resources", {}), multiplier=-1)
    _adjust_item_count(new_payload, 1 if kind == "doll" else 2, -1)
    write_shared_index_cache(new_payload, source="factory_test_local_after_develop_%s" % kind)
    print("[*] 已根据 develop 返回本地更新共享 Index 缓存：占用栏位 %s，已扣减资源与制造契约；未清除旧缓存。" % sorted(set(slots)))
    return new_payload


def invalidate_shared_index_cache(reason="state_changed"):
    try:
        if SHARED_INDEX_FILE.exists():
            SHARED_INDEX_FILE.unlink()
            print("[*] 已清除共享 Index 缓存：%s。" % reason)
    except Exception:
        pass


def request_index_for_factory_test(client, force_refresh=False, reason="检查资源、契约和制造栏位"):
    if not force_refresh:
        cached, status = read_shared_index_cache()
        if isinstance(cached, dict):
            ensure_local_warehouse_snapshot(cached, source="factory_test_reuse_shared_index")
            print("[*] 已复用 GFAM 共享 Index 缓存，用于%s（%s）；仓库判断使用本地缓存。" % (reason, status))
            return cached
        if status not in ("missing", "invalid"):
            print("[*] 共享 Index 缓存不可用：%s，将重新请求。" % status)
    payload = {"time": int(time.time()), "furniture_data": False}
    print("[*] 正在请求 Index/index，用于%s..." % reason)
    resp = client.send_request(API_INDEX_INDEX, payload)
    if is_error(resp):
        print("[!] Index/index 请求失败：%s" % compact_error(resp))
        return None
    write_shared_index_cache(resp, source="factory_test_%s" % reason)
    return resp


def print_started_doll_builds(gun_ids):
    if not isinstance(gun_ids, list):
        print("    gun_ids 返回格式异常：%s" % type(gun_ids).__name__)
        return
    for item in gun_ids:
        if not isinstance(item, dict):
            print("    %s" % item)
            continue
        gid = int_safe(item.get("id") or item.get("gun_id"), 0)
        slot = int_safe(item.get("slot") or item.get("build_slot"), 0)
        print("    栏位 %s -> %s(%s)" % (slot or "?", gun_display_name(load_gun_catalog().get(gid)), gid or "?"))


def print_started_equip_builds(equip_ids):
    if not isinstance(equip_ids, list):
        print("    equip_ids 返回格式异常：%s" % type(equip_ids).__name__)
        return
    catalog = load_equip_catalog()
    for item in equip_ids:
        if not isinstance(item, dict):
            print("    %s" % item)
            continue
        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        eid = int_safe(info.get("equip_id") or item.get("equip_id"), 0)
        slot = int_safe(item.get("slot") or item.get("build_slot"), 0)
        print("    栏位 %s -> %s(%s)" % (slot or "?", equip_display_name(catalog.get(eid), eid), eid or "?"))


def print_finish_doll_result(resp, protected_ids=None, protect_mode=None):
    add_list = resp.get("gun_with_user_add_list") if isinstance(resp, dict) else None
    if not isinstance(add_list, list):
        print("[*] 快速完成请求已返回，但未解析到 gun_with_user_add_list。返回摘要：%s" % compact_error(resp))
        return
    print("[+] 快速完成并领取人形制造返回 %d 名人形：" % len(add_list))
    catalog = load_gun_catalog()
    protected_ids = set(int_safe(x, 0) for x in (protected_ids or []) if int_safe(x, 0) > 0)
    for item in add_list:
        gid = int_safe(item.get("gun_id"), 0)
        uid = int_safe(item.get("gun_with_user_id"), 0)
        slot = int_safe(item.get("build_slot"), 0)
        note = ""
        if protected_ids:
            if gid in protected_ids:
                note = "；命中本次保护人形，已保留"
            else:
                note = "；非本次保护人形（快速建造仅提示，不会自动拆解人形）"
        elif protect_mode:
            note = "；本次未配置保护 ID"
        print("    栏位 %s -> %s(%s) UID %s%s" % (slot or "?", gun_display_name(catalog.get(gid)), gid or "?", uid or "?", note))


def print_finish_equip_result(resp, protect_holo_red_dot=False):
    add_list = resp.get("equip_with_user_add_list") if isinstance(resp, dict) else None
    if not isinstance(add_list, list):
        print("[*] 快速完成请求已返回，但未解析到 equip_with_user_add_list。返回摘要：%s" % compact_error(resp))
        return
    print("[+] 快速完成并领取装备制造返回 %d 件装备：" % len(add_list))
    catalog = load_equip_catalog()
    for item in add_list:
        eid = int_safe(item.get("equip_id"), 0)
        ew = item.get("equip_with_user") if isinstance(item.get("equip_with_user"), dict) else {}
        uid = int_safe(ew.get("id") or item.get("equip_with_user_id") or item.get("id"), 0)
        slot = int_safe(item.get("build_slot"), 0)
        protected, protect_note = equip_protect_decision(catalog, eid, protect_holo_red_dot=protect_holo_red_dot)
        if protected:
            if "保留" not in protect_note:
                protect_note += "，已保留"
        else:
            protect_note += "，将尝试自动拆解"
        print("    栏位 %s -> %s(%s) UID %s；%s" % (slot or "?", equip_display_name(catalog.get(eid), eid), eid or "?", uid or "?", protect_note))


def _filter_build_records_by_claimed_slots(raw_records, claimed_slots):
    """Return records with claimed build slots removed, preserving list/dict shape when possible."""
    claimed_slots = set(int_safe(x, 0) for x in claimed_slots if int_safe(x, 0) > 0)
    if not claimed_slots:
        return raw_records
    def keep_item(item):
        if not isinstance(item, dict):
            return True
        slot = int_safe(item.get("build_slot") or item.get("slot"), 0)
        return slot not in claimed_slots
    if isinstance(raw_records, list):
        return [item for item in raw_records if keep_item(item)]
    if isinstance(raw_records, dict):
        return {k: v for k, v in raw_records.items() if keep_item(v)}
    return raw_records


def _append_claimed_items_to_index(payload, add_list, kind):
    """Best-effort local storage update after finishAllDevelop, without requesting Index/index."""
    if not isinstance(payload, dict) or not isinstance(add_list, list):
        return
    key = "gun_with_user_info" if kind == "doll" else "equip_with_user_info"
    existing = payload.get(key)
    # Keep this conservative: only append when the original shape is list.
    # Dict-shaped Index chunks often use server-side UID keys, which are easy to corrupt locally.
    if isinstance(existing, list):
        existing.extend(add_list)


def apply_finish_response_to_index_snapshot(index_payload, finish_resp, kind, ready_slots=None, cost_quick=False):
    """Apply a normal finishAllDevelop result to the current Index snapshot locally.

    This avoids the extra Index/index immediately after ordinary claiming. The returned
    snapshot is not a perfect full Index, but it is enough for the factory test flow:
    it releases completed build slots and keeps the current resource/contract counts.
    """
    if not isinstance(index_payload, dict) or not isinstance(finish_resp, dict):
        return None
    if kind == "doll":
        add_key = "gun_with_user_add_list"
        act_key = "develop_act_info"
        label = "人形"
    else:
        add_key = "equip_with_user_add_list"
        act_key = "develop_equip_act_info"
        label = "装备"
    add_list = finish_resp.get(add_key)
    if not isinstance(add_list, list) or not add_list:
        print("[*] 领取返回未包含新增%s，无法仅凭返回值安全推导空闲栏位；本次不额外请求 Index。" % label)
        return None
    claimed_slots = []
    for item in add_list:
        if isinstance(item, dict):
            slot = int_safe(item.get("build_slot") or item.get("slot"), 0)
            if slot > 0:
                claimed_slots.append(slot)
    if not claimed_slots and ready_slots:
        claimed_slots = [int_safe(x, 0) for x in ready_slots[:len(add_list)] if int_safe(x, 0) > 0]
        if claimed_slots:
            print("[*] 领取返回未带栏位号，已按 Index 中已完成队列推导释放栏位：%s" % sorted(claimed_slots))
    if not claimed_slots:
        print("[*] 无法从领取返回推导释放栏位；本次不额外请求 Index。")
        return None
    new_payload = copy.deepcopy(index_payload)
    new_payload[act_key] = _filter_build_records_by_claimed_slots(new_payload.get(act_key, []), claimed_slots)
    _append_claimed_items_to_index(new_payload, add_list, kind)
    adjust_local_warehouse_snapshot(new_payload, "equip" if kind == "equip" else "gun", len(add_list), source="factory_test_local_after_finish_%s" % kind)
    if cost_quick:
        # finishAllDevelop with is_cost_item3=1 can finish several active slots at once.
        # Use returned item count as the safest local deduction estimate.
        _adjust_item_count(new_payload, 3, -len(add_list))
    write_shared_index_cache(new_payload, source="factory_test_local_after_finish_%s" % kind)
    extra = "，已按返回数量扣减快速制造契约" if cost_quick else ""
    print("[*] 已根据 finishAllDevelop 返回本地刷新%s制造栏位：释放 %s%s；未再次请求 Index/index。" % (label, sorted(set(claimed_slots)), extra))
    return new_payload



def try_claim_completed_builds_for_test(client, kind, index_payload=None, ready_slots=None):
    """测试功能辅助：当前没有空闲栏位时，先尝试领取已经完成的制造。

    这里使用 is_cost_item3=0，只领取已完成栏位，不消耗快速制造契约。
    领取成功后优先根据 finishAllDevelop 返回内容在本地释放栏位，避免紧接着
    再请求一次 Index/index；只有用户后续重新进入或缓存过期时才需要重新校准。
    """
    if kind == "doll":
        api = API_GUN_FINISH_ALL_DEVELOP
        label = "人形"
        print_func = print_finish_doll_result
    else:
        api = API_EQUIP_FINISH_ALL_DEVELOP
        label = "装备"
        print_func = print_finish_equip_result
    print("[*] 测试模式：当前没有%s制造空闲栏位，将自动尝试领取已完成%s制造。" % (label, label))
    payload = {"is_cost_item3": 0}
    print("[*] 正在发送 %s：%s（普通领取已完成栏位，不消耗快速制造契约）" % (api, payload))
    resp = client.send_request(api, payload)
    if is_error(resp):
        print("[!] 领取已完成%s制造失败：%s" % (label, compact_error(resp)))
        return None
    print_func(resp)
    updated = apply_finish_response_to_index_snapshot(index_payload, resp, kind, ready_slots=ready_slots)
    if isinstance(updated, dict):
        return updated
    print("[*] 未能安全本地推导栏位状态；为避免重复请求，本次测试到此停止。")
    return None

def run_one_doll_factory_test(st, batch_count=1, force_refresh_index=False):
    print("\n================ 人形制造快速建造 ================ ")
    formula_key = str(st.get("doll_formula") or "handgun")
    custom_formula = st.get("_custom_doll_formula")
    if isinstance(custom_formula, dict) and custom_formula.get("resources"):
        formula = custom_formula
        formula_key = "custom"
    elif formula_key not in DOLL_FORMULAS:
        formula_key = "handgun"
        formula = DOLL_FORMULAS[formula_key]
    else:
        formula = DOLL_FORMULAS[formula_key]
    print("[*] 将使用本次人形快速建造公式：%s（%s）" % (formula["name"], resource_text(formula["resources"])))
    print("[*] 自动快速建造流程：发送 Gun/developMultiGun（批量）；若快速制造契约足够，将自动调用 Gun/finishAllDevelop 快速完成并领取。")
    print("[!] 注意：finishAllDevelop 可能会快速完成/领取全部未完成人形制造栏位，不一定只影响刚刚测试提交的一栏。")
    protected_ids = set(int_safe(x, 0) for x in st.get("doll_protect_ids", []) if int_safe(x, 0) > 0)
    if protected_ids:
        mode_text = "手动保护" if st.get("doll_protect_mode") == "manual" else "默认五星保护"
        print("[*] 本次快速建造人形保护：%s；保护 ID 数量 %s。" % (mode_text, len(protected_ids)))
    else:
        print("[*] 本次快速建造未配置保护 ID；领取后非目标产物将自动拆解。")
    print("[*] 快速建造模式：不修改跟随模块制造设置。")
    global _quick_stats
    _quick_stats = {"retired": 0, "protected": 0}
    _quick_used = 0
    _detail_p = {}
    _detail_r = {}
    client = make_client_for_factory_test()
    if client is None:
        _quick_stats["quick_contracts_used"] = 0
        return 0
    index_payload = request_index_for_factory_test(client, force_refresh=force_refresh_index, reason="强制刷新（上轮异常后重新获取）" if force_refresh_index else "检查资源、契约和制造栏位")
    if not isinstance(index_payload, dict):
        _quick_stats["quick_contracts_used"] = 0
        return 0
    resources = resource_snapshot(index_payload)
    missing = has_enough_resources(resources, formula)
    if missing:
        print("[!] 当前资源不足，无法测试：%s" % "；".join(missing))
        _quick_stats["quick_contracts_used"] = 0
        return 0
    contracts = item_count(index_payload, 1)
    quick_contracts = item_count(index_payload, 3)
    max_slot = int_safe((index_payload.get("user_info") or {}).get("max_build_slot"), 0)
    states = build_slot_states_from_index(index_payload, "develop_act_info", "doll")
    busy = set(states.keys())
    ready_slots = [slot for slot, st2 in states.items() if st2.get("is_ready")]
    building_slots = [slot for slot, st2 in states.items() if not st2.get("is_ready")]
    free_slots = [slot for slot in normal_slot_numbers(max_slot) if slot not in busy]
    print("[*] 人形制造栏位：普通 %s 个（重型 %s 个），已完成待领 %s 个，建造中 %s 个，空闲 %s 个。" % (normal_slot_count(max_slot), len(heavy_slot_numbers(max_slot)), len(ready_slots), len(building_slots), len(free_slots)))
    print_slot_states(states, "人形")
    print("[*] 人形制造契约：%s；快速制造契约：%s。" % (contracts, quick_contracts))
    if contracts <= 0:
        print("[!] 人形制造契约不足。")
        _quick_stats["quick_contracts_used"] = 0
        return 0
    # ── Step 1: Clear occupied slots ──────────────────────────────────
    if busy:
        # Step 1a: 先普通领取已完成建造（不消耗快速契约），并拆解非目标产物
        if ready_slots:
            print("[*] 检测到 %d 个栏位已完成待领取，先普通领取（不消耗快速契约）..." % len(ready_slots))
            claim_payload = {"is_cost_item3": 0}
            print("[*] 正在发送 Gun/finishAllDevelop：%s" % claim_payload)
            claim_resp = client.send_request(API_GUN_FINISH_ALL_DEVELOP, claim_payload)
            if is_error(claim_resp):
                print("[!] 普通领取已完成人形失败：%s" % compact_error(claim_resp))
            else:
                print_finish_doll_result(claim_resp, protected_ids=list(protected_ids) if protected_ids else None, protect_mode=st.get("doll_protect_mode"))
                index_payload = apply_finish_response_to_index_snapshot(index_payload, claim_resp, "doll", ready_slots=ready_slots) or index_payload
                index_payload, _r = retire_non_target_dolls_for_test(client, index_payload, claim_resp, protected_ids=list(protected_ids) if protected_ids else None)
                _quick_stats["retired"] += _r
                # Collect detail from normal claim
                for _item in (claim_resp.get("gun_with_user_add_list") or []):
                    _uid = int_safe(_item.get("gun_with_user_id"), 0)
                    if _uid <= 0:
                        continue
                    _gid = int_safe(_item.get("gun_id"), 0)
                    if protected_ids and _gid in protected_ids:
                        _detail_p[_uid] = _gid
                    else:
                        _detail_r[_uid] = _gid
                resources = resource_snapshot(index_payload)
                contracts = item_count(index_payload, 1)
                quick_contracts = item_count(index_payload, 3)
                max_slot = int_safe((index_payload.get("user_info") or {}).get("max_build_slot"), 0)
                states = build_slot_states_from_index(index_payload, "develop_act_info", "doll")
                busy = set(states.keys())
                ready_slots = [slot for slot, st2 in states.items() if st2.get("is_ready")]
                building_slots = [slot for slot, st2 in states.items() if not st2.get("is_ready")]
                free_slots = [slot for slot in normal_slot_numbers(max_slot) if slot not in busy]
                print("[*] 普通领取后人形制造栏位：普通 %s 个（重型 %s 个），空闲 %s 个。" % (normal_slot_count(max_slot), len(heavy_slot_numbers(max_slot)), len(free_slots)))
        # Step 1b: 若仍有建造中的栏位，使用快速契约强制完成并拆解非目标产物
        if busy and quick_contracts > 0:
            print("[*] 仍有 %d 个栏位建造中，使用快速契约强制完成..." % len(busy))
            index_payload, force_claimed, _r = force_finish_builds_for_test(
                client, index_payload, "doll",
                protected_ids=list(protected_ids) if protected_ids else None)
            _quick_stats["retired"] += _r
            _quick_used += force_claimed
            if force_claimed > 0:
                resources = resource_snapshot(index_payload)
                contracts = item_count(index_payload, 1)
                quick_contracts = item_count(index_payload, 3)
                max_slot = int_safe((index_payload.get("user_info") or {}).get("max_build_slot"), 0)
                states = build_slot_states_from_index(index_payload, "develop_act_info", "doll")
                busy = set(states.keys())
                ready_slots = [slot for slot, st2 in states.items() if st2.get("is_ready")]
                building_slots = [slot for slot, st2 in states.items() if not st2.get("is_ready")]
                free_slots = [slot for slot in normal_slot_numbers(max_slot) if slot not in busy]
                print("[*] 强制完成后人形制造栏位：普通 %s 个（重型 %s 个），空闲 %s 个。" % (normal_slot_count(max_slot), len(heavy_slot_numbers(max_slot)), len(free_slots)))
                print("[*] 剩余快速制造契约：%s。" % quick_contracts)
    if not free_slots:
        print("[!] 清理后仍没有人形制造空闲栏位（建造中 %d 个无法快速完成）。" % len(building_slots))
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    if quick_contracts <= 0:
        print("[!] 快速制造契约不足，仍可发送制造请求，但无法执行后续快速完成。")
    # ── Step 2: Submit new batch ───────────────────────────────────────
    batch = min(batch_count, len(free_slots), contracts)
    for _rk, _rv in formula["resources"].items():
        if int(_rv) > 0:
            batch = min(batch, resources.get(_rk, 0) // int(_rv))
    if quick_contracts > 0:
        batch = min(batch, quick_contracts)
    if batch <= 0:
        print("[!] 资源/契约/栏位不足，本批无法建造。")
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    if batch > 1:
        print("[*] 本批次计划批量建造 %d 个（空闲栏位 %d，契约 %d，请求上限 %d）。" % (batch, len(free_slots), contracts, batch_count))
    payload = dict(formula["resources"])
    payload.update({"input_level": 0, "build_quick": 0, "build_multi": int(batch), "build_heavy": 0})
    print("[*] 正在发送 Gun/developMultiGun（build_multi=%d）：%s" % (batch, payload))
    resp = client.send_request(API_GUN_DEVELOP_MULTI, payload)
    if is_error(resp):
        print("[!] 人形制造请求失败：%s" % compact_error(resp))
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    gun_ids = resp.get("gun_ids") if isinstance(resp, dict) else None
    if not gun_ids:
        print("[!] 人形制造请求返回异常：未包含 gun_ids。返回摘要：%s" % compact_error(resp))
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    started = len(gun_ids) if isinstance(gun_ids, list) else 0
    index_payload = apply_develop_response_to_index_snapshot(index_payload, resp, "doll", formula) or index_payload
    print("[+] 人形制造请求已成功提交（%d 个）：" % started)
    print_started_doll_builds(gun_ids)
    if quick_contracts <= 0:
        print("[*] 因快速制造契约不足，本次不执行快速完成。")
        _quick_stats["quick_contracts_used"] = _quick_used
        return started
    # ── Step 3: Quick finish + retire non-target ──────────────────────
    print("[*] 测试模式：快速制造契约可用，将自动快速完成并领取。")
    finish_payload = {"is_cost_item3": 1}
    print("[*] 正在发送 Gun/finishAllDevelop：%s" % finish_payload)
    finish_resp = client.send_request(API_GUN_FINISH_ALL_DEVELOP, finish_payload)
    if is_error(finish_resp):
        print("[!] 快速完成人形制造失败：%s" % compact_error(finish_resp))
        _quick_stats["quick_contracts_used"] = _quick_used
        return started
    _qc_step3 = finish_resp.get("gun_with_user_add_list")
    _quick_used += len(_qc_step3) if isinstance(_qc_step3, list) else 0
    index_payload = apply_finish_response_to_index_snapshot(index_payload, finish_resp, "doll", ready_slots=None, cost_quick=True) or index_payload
    print_finish_doll_result(finish_resp, protected_ids=list(protected_ids) if protected_ids else None, protect_mode=st.get("doll_protect_mode"))
    # Retire non-target dolls
    index_payload, _r = retire_non_target_dolls_for_test(client, index_payload, finish_resp, protected_ids=list(protected_ids) if protected_ids else None)
    _quick_stats["retired"] += _r
    _quick_stats["quick_contracts_used"] = _quick_used
    # Collect detail from Step 3
    for _item in (finish_resp.get("gun_with_user_add_list") or []):
        _uid = int_safe(_item.get("gun_with_user_id"), 0)
        if _uid <= 0:
            continue
        _gid = int_safe(_item.get("gun_id"), 0)
        if protected_ids and _gid in protected_ids:
            _detail_p[_uid] = _gid
        else:
            _detail_r[_uid] = _gid
    global _round_details
    _gcat = load_gun_catalog()
    _p_list = [{"uid": u, "id": gid, "name": gun_display_name(_gcat.get(gid, {}))} for u, gid in sorted(_detail_p.items())]
    _r_list = [{"uid": u, "id": gid, "name": gun_display_name(_gcat.get(gid, {}))} for u, gid in sorted(_detail_r.items())]
    _round_details.append({"built": started, "quick_used": _quick_used,
                           "protected": _p_list, "retired": _r_list})
    print("[*] 人形快速建造完成 %d 个。已尽量根据服务器返回更新本地共享 Index 缓存；本流程不会改写跟随模块制造设置。" % started)
    return started


def run_one_equip_factory_test(st, batch_count=1, force_refresh_index=False):
    print("\n================ 装备制造快速建造 ================ ")
    formula_key = str(st.get("equip_formula") or "optic")
    custom_formula = st.get("_custom_equip_formula")
    if isinstance(custom_formula, dict) and custom_formula.get("resources"):
        formula = custom_formula
        formula_key = "custom"
    elif formula_key not in EQUIP_FORMULAS:
        formula_key = "optic"
        formula = EQUIP_FORMULAS[formula_key]
    else:
        formula = EQUIP_FORMULAS[formula_key]
    print("[*] 将使用本次装备快速建造公式：%s（%s）" % (formula["name"], resource_text(formula["resources"])))
    print("[*] 自动快速建造流程：发送 Equip/developMulti（批量）；若快速制造契约足够，将自动调用 Equip/finishAllDevelop 快速完成并领取。")
    print("[!] 注意：finishAllDevelop 可能会快速完成/领取全部未完成装备制造栏位，不一定只影响刚刚测试提交的一栏。")
    protect_holo_red_dot = bool(st.get("equip_protect_holo_red_dot", False))
    if protect_holo_red_dot:
        print("[*] 全息/红点瞄具保护开关：开启。此类装备将保留。")
    else:
        print("[*] 全息/红点瞄具保护开关：关闭。所有已知星级的全息/红点瞄具默认不保护。")
    print("[*] 测试模式：不再二次确认，直接开始。")
    global _quick_stats
    _quick_stats = {"retired": 0, "protected": 0}
    _quick_used = 0
    _detail_p = {}
    _detail_r = {}
    client = make_client_for_factory_test()
    if client is None:
        _quick_stats["quick_contracts_used"] = 0
        return 0
    index_payload = request_index_for_factory_test(client, force_refresh=force_refresh_index, reason="强制刷新（上轮异常后重新获取）" if force_refresh_index else "检查资源、契约和制造栏位")
    if not isinstance(index_payload, dict):
        _quick_stats["quick_contracts_used"] = 0
        return 0
    resources = resource_snapshot(index_payload)
    missing = has_enough_resources(resources, formula)
    if missing:
        print("[!] 当前资源不足，无法测试：%s" % "；".join(missing))
        _quick_stats["quick_contracts_used"] = 0
        return 0
    contracts = item_count(index_payload, 2)
    quick_contracts = item_count(index_payload, 3)
    max_slot = int_safe((index_payload.get("user_info") or {}).get("max_equip_build_slot"), 0)
    states = build_slot_states_from_index(index_payload, "develop_equip_act_info", "equip")
    busy = set(states.keys())
    ready_slots = [slot for slot, st2 in states.items() if st2.get("is_ready")]
    building_slots = [slot for slot, st2 in states.items() if not st2.get("is_ready")]
    free_slots = [slot for slot in normal_slot_numbers(max_slot) if slot not in busy]
    print("[*] 装备制造栏位：普通 %s 个（重型 %s 个），已完成待领 %s 个，建造中 %s 个，空闲 %s 个。" % (normal_slot_count(max_slot), len(heavy_slot_numbers(max_slot)), len(ready_slots), len(building_slots), len(free_slots)))
    print_slot_states(states, "装备")
    print("[*] 装备制造契约：%s；快速制造契约：%s。" % (contracts, quick_contracts))
    if contracts <= 0:
        print("[!] 装备制造契约不足。")
        _quick_stats["quick_contracts_used"] = 0
        return 0
    # ── Step 1: Clear occupied slots ──────────────────────────────────
    if busy:
        # Step 1a: 先普通领取已完成建造（不消耗快速契约），并拆解非目标产物
        if ready_slots:
            print("[*] 检测到 %d 个栏位已完成待领取，先普通领取（不消耗快速契约）..." % len(ready_slots))
            claim_payload = {"is_cost_item3": 0}
            print("[*] 正在发送 Equip/finishAllDevelop：%s" % claim_payload)
            claim_resp = client.send_request(API_EQUIP_FINISH_ALL_DEVELOP, claim_payload)
            if is_error(claim_resp):
                print("[!] 普通领取已完成装备失败：%s" % compact_error(claim_resp))
            else:
                print_finish_equip_result(claim_resp, protect_holo_red_dot=protect_holo_red_dot)
                index_payload = apply_finish_response_to_index_snapshot(index_payload, claim_resp, "equip", ready_slots=ready_slots) or index_payload
                index_payload, _r = retire_non_five_star_finished_equips_for_test(client, index_payload, claim_resp, protect_holo_red_dot=protect_holo_red_dot)
                _quick_stats["retired"] += _r
                # Collect detail from normal claim
                _eq_catalog = load_equip_catalog()
                for _item in (claim_resp.get("equip_with_user_add_list") or []):
                    _ew = _item.get("equip_with_user") if isinstance(_item.get("equip_with_user"), dict) else {}
                    _uid = int_safe(_ew.get("id") or _item.get("equip_with_user_id") or _item.get("id"), 0)
                    if _uid <= 0:
                        continue
                    _eid = int_safe(_item.get("equip_id"), 0)
                    _is_prot, _ = equip_protect_decision(_eq_catalog, _eid, protect_holo_red_dot=protect_holo_red_dot)
                    if _is_prot:
                        _detail_p[_uid] = _eid
                    else:
                        _detail_r[_uid] = _eid
                resources = resource_snapshot(index_payload)
                contracts = item_count(index_payload, 2)
                quick_contracts = item_count(index_payload, 3)
                max_slot = int_safe((index_payload.get("user_info") or {}).get("max_equip_build_slot"), 0)
                states = build_slot_states_from_index(index_payload, "develop_equip_act_info", "equip")
                busy = set(states.keys())
                ready_slots = [slot for slot, st2 in states.items() if st2.get("is_ready")]
                building_slots = [slot for slot, st2 in states.items() if not st2.get("is_ready")]
                free_slots = [slot for slot in normal_slot_numbers(max_slot) if slot not in busy]
                print("[*] 普通领取后装备制造栏位：普通 %s 个（重型 %s 个），空闲 %s 个。" % (normal_slot_count(max_slot), len(heavy_slot_numbers(max_slot)), len(free_slots)))
        # Step 1b: 若仍有建造中的栏位，使用快速契约强制完成并拆解非目标产物
        if busy and quick_contracts > 0:
            print("[*] 仍有 %d 个栏位建造中，使用快速契约强制完成..." % len(busy))
            index_payload, force_claimed, _r = force_finish_builds_for_test(
                client, index_payload, "equip",
                protect_holo_red_dot=protect_holo_red_dot)
            _quick_stats["retired"] += _r
            _quick_used += force_claimed
            if force_claimed > 0:
                resources = resource_snapshot(index_payload)
                contracts = item_count(index_payload, 2)
                quick_contracts = item_count(index_payload, 3)
                max_slot = int_safe((index_payload.get("user_info") or {}).get("max_equip_build_slot"), 0)
                states = build_slot_states_from_index(index_payload, "develop_equip_act_info", "equip")
                busy = set(states.keys())
                ready_slots = [slot for slot, st2 in states.items() if st2.get("is_ready")]
                building_slots = [slot for slot, st2 in states.items() if not st2.get("is_ready")]
                free_slots = [slot for slot in normal_slot_numbers(max_slot) if slot not in busy]
                print("[*] 强制完成后装备制造栏位：普通 %s 个（重型 %s 个），空闲 %s 个。" % (normal_slot_count(max_slot), len(heavy_slot_numbers(max_slot)), len(free_slots)))
                print("[*] 剩余快速制造契约：%s。" % quick_contracts)
    if not free_slots:
        print("[!] 清理后仍没有装备制造空闲栏位（建造中 %d 个无法快速完成）。" % len(building_slots))
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    # Ensure equip storage has room
    index_payload, storage_ok = ensure_equip_storage_for_test(client, index_payload, protect_holo_red_dot=protect_holo_red_dot)
    if not storage_ok:
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    # 应急拆解可能已本地更新共享 Index 缓存，重新读取基础计数。
    resources = resource_snapshot(index_payload)
    contracts = item_count(index_payload, 2)
    quick_contracts = item_count(index_payload, 3)
    if quick_contracts <= 0:
        print("[!] 快速制造契约不足，仍可发送制造请求，但无法执行后续快速完成。")
    # ── Step 2: Submit new batch ───────────────────────────────────────
    batch = min(batch_count, len(free_slots), contracts)
    for _rk, _rv in formula["resources"].items():
        if int(_rv) > 0:
            batch = min(batch, resources.get(_rk, 0) // int(_rv))
    if quick_contracts > 0:
        batch = min(batch, quick_contracts)
    if batch <= 0:
        print("[!] 资源/契约/栏位不足，本批无法建造。")
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    if batch > 1:
        print("[*] 本批次计划批量建造 %d 个（空闲栏位 %d，契约 %d，请求上限 %d）。" % (batch, len(free_slots), contracts, batch_count))
    payload = dict(formula["resources"])
    payload.update({"input_level": 0, "build_quick": 0, "build_multi": int(batch), "build_heavy": 0})
    print("[*] 正在发送 Equip/developMulti（build_multi=%d）：%s" % (batch, payload))
    resp = client.send_request(API_EQUIP_DEVELOP_MULTI, payload)
    if is_error(resp):
        print("[!] 装备制造请求失败：%s" % compact_error(resp))
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    equip_ids = resp.get("equip_ids") if isinstance(resp, dict) else None
    if not equip_ids:
        print("[!] 装备制造请求返回异常：未包含 equip_ids。返回摘要：%s" % compact_error(resp))
        _quick_stats["quick_contracts_used"] = _quick_used
        return 0
    started = len(equip_ids) if isinstance(equip_ids, list) else 0
    index_payload = apply_develop_response_to_index_snapshot(index_payload, resp, "equip", formula) or index_payload
    print("[+] 装备制造请求已成功提交（%d 个）：" % started)
    print_started_equip_builds(equip_ids)
    if quick_contracts <= 0:
        print("[*] 因快速制造契约不足，本次不执行快速完成。")
        _quick_stats["quick_contracts_used"] = _quick_used
        return started
    # ── Step 3: Quick finish + retire non-target ──────────────────────
    print("[*] 测试模式：快速制造契约可用，将自动快速完成并领取。")
    finish_payload = {"is_cost_item3": 1}
    print("[*] 正在发送 Equip/finishAllDevelop：%s" % finish_payload)
    finish_resp = client.send_request(API_EQUIP_FINISH_ALL_DEVELOP, finish_payload)
    if is_error(finish_resp):
        print("[!] 快速完成装备制造失败：%s" % compact_error(finish_resp))
        _quick_stats["quick_contracts_used"] = _quick_used
        return started
    _qc_step3 = finish_resp.get("equip_with_user_add_list")
    _quick_used += len(_qc_step3) if isinstance(_qc_step3, list) else 0
    index_payload = apply_finish_response_to_index_snapshot(index_payload, finish_resp, "equip", ready_slots=None, cost_quick=True) or index_payload
    print_finish_equip_result(finish_resp, protect_holo_red_dot=protect_holo_red_dot)
    index_payload, _r = retire_non_five_star_finished_equips_for_test(client, index_payload, finish_resp, protect_holo_red_dot=protect_holo_red_dot)
    _quick_stats["retired"] += _r
    _quick_stats["quick_contracts_used"] = _quick_used
    # Collect detail from Step 3
    _eq_catalog3 = load_equip_catalog()
    for _item in (finish_resp.get("equip_with_user_add_list") or []):
        _ew = _item.get("equip_with_user") if isinstance(_item.get("equip_with_user"), dict) else {}
        _uid = int_safe(_ew.get("id") or _item.get("equip_with_user_id") or _item.get("id"), 0)
        if _uid <= 0:
            continue
        _eid = int_safe(_item.get("equip_id"), 0)
        _is_prot, _ = equip_protect_decision(_eq_catalog3, _eid, protect_holo_red_dot=protect_holo_red_dot)
        if _is_prot:
            _detail_p[_uid] = _eid
        else:
            _detail_r[_uid] = _eid
    global _round_details
    _p_list = [{"uid": u, "id": eid, "name": equip_display_name(_eq_catalog3.get(eid, {}), eid)} for u, eid in sorted(_detail_p.items())]
    _r_list = [{"uid": u, "id": eid, "name": equip_display_name(_eq_catalog3.get(eid, {}), eid)} for u, eid in sorted(_detail_r.items())]
    _round_details.append({"built": started, "quick_used": _quick_used,
                           "protected": _p_list, "retired": _r_list})
    print("[*] 装备制造完成 %d 个。已尽量根据服务器返回更新本地共享 Index 缓存；保护装备已保留，非保护测试产物已尝试自动拆解。" % started)
    return started


def quick_build_count_from_command(cmd_line, default=1, max_count=200):
    parts = str(cmd_line or "").strip().split()
    if len(parts) < 2:
        return default
    raw = parts[1]
    try:
        count = int(raw)
    except Exception:
        print("[!] 自动快速建造次数无效：%s；已按 1 次处理。" % raw)
        return default
    if count <= 0:
        print("[!] 自动快速建造次数必须大于 0；已按 1 次处理。")
        return default
    if count > max_count:
        print("[!] 自动快速建造次数 %s 过大；为避免误操作，已限制为 %s 次。" % (count, max_count))
        return max_count
    return count


def choose_doll_quick_build_state(count=1):
    """Interactive one-shot configuration for quick doll builds.

    This intentionally does not save to factory_config.json and does not affect
    the follow-module manufacturing settings shown by -show / configured by -doll.
    """
    catalog = load_gun_catalog()
    keys = list(DOLL_FORMULAS.keys())
    print("\n========== 人形自动快速建造：本次公式选择 ==========")
    for i, key in enumerate(keys, 1):
        info = DOLL_FORMULAS[key]
        rec = info.get("recommended") or {}
        rec_text = "，推荐保护：" + "、".join("%s(%s)" % (name, gid) for gid, name in rec.items()) if rec else ""
        print(" %d. %s：%s%s" % (i, info["name"], resource_text(info["resources"]), rec_text))
    print("================================================")
    ans = input("请选择本次快速建造公式编号> ").strip()
    try:
        formula_key = keys[int(ans) - 1]
    except Exception:
        print("[!] 公式选择无效，已取消本次人形自动快速建造。")
        return None
    tmp = default_state()
    tmp["doll_formula"] = formula_key
    info = DOLL_FORMULAS[formula_key]
    print("[+] 本次人形自动快速建造公式：%s；次数：%s。" % (info["name"], count))
    rec = info.get("recommended") or {}
    if rec:
        print("[*] 本公式推荐保护：%s" % "、".join("%s(%s)" % (name, gid) for gid, name in rec.items()))
    auto_ids = auto_doll_protect_ids_for_formula(formula_key, catalog)
    if auto_ids:
        print("[*] 默认保护策略：使用该公式对应枪种的所有五星人形（含推荐目标），共 %d 个 ID。" % len(auto_ids))
    ans = input("本次快速建造是否自行添加保护人形？输入 -y 手动添加，输入 -n 使用默认五星保护> ").strip().lower()
    if ans in ("-y", "y", "yes", "是"):
        tmp["doll_protect_ids"] = ask_manual_ids("人形", catalog, gun_display_name)
        tmp["doll_protect_mode"] = "manual"
        tmp["doll_target_scope"] = "protected_hits"
    else:
        tmp["doll_protect_ids"] = auto_ids
        tmp["doll_protect_mode"] = "auto_5star_by_formula"
        tmp["doll_target_scope"] = "protected_hits" if auto_ids else "total_outputs"
    tmp["doll_target_count"] = int_safe(count, 1)
    tmp["doll_enabled"] = False
    print("[*] 本次快速建造配置只在当前流程生效，不会覆盖 -show 中的跟随模块制造设置。")
    return tmp


def choose_equip_quick_build_state(count=1):
    """Interactive one-shot configuration for quick equipment builds.

    This intentionally does not save to factory_config.json and does not affect
    the follow-module manufacturing settings shown by -show / configured by -equip.
    """
    keys = list(EQUIP_FORMULAS.keys())
    print("\n========== 装备自动快速建造：本次公式选择 ==========")
    for i, key in enumerate(keys, 1):
        info = EQUIP_FORMULAS[key]
        print(" %2d. %s：%s" % (i, info["name"], resource_text(info["resources"])))
    print("================================================")
    ans = input("请选择本次快速建造装备公式编号> ").strip()
    try:
        formula_key = keys[int(ans) - 1]
    except Exception:
        print("[!] 公式选择无效，已取消本次装备自动快速建造。")
        return None
    tmp = default_state()
    tmp["equip_formula"] = formula_key
    tmp["equip_protect_mode"] = "auto_5star_outputs"
    tmp["equip_protect_ids"] = []
    tmp["equip_target_scope"] = "total_outputs"
    tmp["equip_target_count"] = int_safe(count, 1)
    tmp["equip_enabled"] = False
    info = EQUIP_FORMULAS[formula_key]
    print("[+] 本次装备自动快速建造公式：%s；次数：%s。" % (info["name"], count))
    print("[*] 本次装备保护逻辑：自动保护制造出的五星装备；普通全息/红点/ACOG 瞄具默认不保护。")
    ans = input("本次是否临时保护全息/红点/ACOG瞄具？输入 -y 保护，输入 -n 默认不保护> ").strip().lower()
    tmp["equip_protect_holo_red_dot"] = ans in ("-y", "y", "yes", "是")
    if tmp["equip_protect_holo_red_dot"]:
        print("[+] 本次快速建造将临时保护全息/红点/ACOG瞄具。")
    else:
        print("[*] 本次快速建造不保护普通全息/红点/ACOG瞄具。")
    print("[*] 本次快速建造配置只在当前流程生效，不会覆盖 -show 中的跟随模块制造设置。")
    return tmp


def run_doll_quick_build_test(st, count=1):
    count = int_safe(count, 1)
    if count <= 0:
        count = 1
    print("\n================ 人形自动快速建造 ================")
    print("[*] 该流程会单独选择本次公式与保护人形，不套用 -show / -doll 的跟随模块制造设置。")
    tmp_state = choose_doll_quick_build_state(count)
    if not isinstance(tmp_state, dict):
        return
    print("[*] 计划按本次人形公式快速建造 %s 个：根据空闲栏位批量发送制造请求 -> 自动快速完成并领取。" % count)
    print("[!] 注意：每次快速完成仍会调用 finishAllDevelop，可能领取全部已完成/未完成栏位。")
    remaining = count
    total_built = 0
    round_num = 0
    _force_refresh = True
    while remaining > 0:
        round_num += 1
        print("\n========== 人形快速建造 第 %d 轮（剩余 %d/%d）==========" % (round_num, remaining, count))
        built = run_one_doll_factory_test(tmp_state, batch_count=remaining, force_refresh_index=_force_refresh)
        _force_refresh = False
        if not built:
            print("[!] 第 %d 轮未能建造任何物品，停止。" % round_num)
            break
        remaining -= built
        total_built += built
    print("[+] 人形自动快速建造流程结束：成功 %d/%d。" % (total_built, count))


def run_equip_quick_build_test(st, count=1):
    count = int_safe(count, 1)
    if count <= 0:
        count = 1
    print("\n================ 装备自动快速建造 ================")
    print("[*] 该流程会单独选择本次公式与保护规则，不套用 -show / -equip 的跟随模块制造设置。")
    tmp_state = choose_equip_quick_build_state(count)
    if not isinstance(tmp_state, dict):
        return
    print("[*] 计划按本次装备公式快速建造 %s 个：根据空闲栏位批量发送制造请求 -> 自动快速完成并领取 -> 星级/保护判定。" % count)
    print("[!] 注意：每次快速完成仍会调用 finishAllDevelop，可能领取全部已完成/未完成栏位。")
    remaining = count
    total_built = 0
    round_num = 0
    _force_refresh = True
    while remaining > 0:
        round_num += 1
        print("\n========== 装备快速建造 第 %d 轮（剩余 %d/%d）==========" % (round_num, remaining, count))
        built = run_one_equip_factory_test(tmp_state, batch_count=remaining, force_refresh_index=_force_refresh)
        _force_refresh = False
        if not built:
            print("[!] 第 %d 轮未能建造任何物品，停止。" % round_num)
            break
        remaining -= built
        total_built += built
    print("[+] 装备自动快速建造流程结束：成功 %d/%d。" % (total_built, count))


def run_doll_quick_build_from_gui(st, count):
    """Quick doll build using pre-set config from GUI popup (no interactive prompts)."""
    count = int_safe(count, 1)
    if count <= 0:
        count = 1
    config_path = QUICK_BUILD_GUI_CONFIG_FILE
    if not config_path.exists():
        print("[!] GUI 快速建造配置文件不存在：%s" % config_path)
        return
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("[!] 读取 GUI 快速建造配置失败：%s" % exc)
        return
    if cfg.get("kind") != "doll":
        print("[!] GUI 配置类型不匹配：期望 doll，实际 %s" % cfg.get("kind"))
        return
    formula_key = str(cfg.get("formula_key") or "handgun")
    custom_resources = cfg.get("custom_resources")
    if formula_key == "custom" and isinstance(custom_resources, dict):
        # Custom formula from GUI
        res = {}
        for k in ("mp", "ammo", "mre", "part"):
            v = int_safe(custom_resources.get(k), 0)
            if v > 0:
                res[k] = v
        if not res:
            print("[!] 自定义公式资源全部为 0，已回退为手枪公式。")
            formula_key = "handgun"
            custom_resources = None
        else:
            tmp_formula = {"name": "自定义公式", "type": 0, "resources": res, "recommended": {}}
    elif formula_key not in DOLL_FORMULAS:
        print("[!] 公式不存在：%s，已回退为手枪。" % formula_key)
        formula_key = "handgun"
        custom_resources = None
    else:
        custom_resources = None
    tmp = default_state()
    tmp["doll_formula"] = formula_key
    tmp["doll_protect_mode"] = str(cfg.get("protect_mode") or "auto_5star_by_formula")
    tmp["doll_protect_ids"] = list(cfg.get("protect_ids") or [])
    tmp["doll_target_count"] = count
    tmp["doll_target_scope"] = str(cfg.get("target_scope") or "protected_hits")
    tmp["doll_enabled"] = False
    if formula_key == "custom" and custom_resources:
        tmp["_custom_doll_formula"] = tmp_formula
        info = tmp_formula
    else:
        info = DOLL_FORMULAS[formula_key]
    print("\n================ 人形自动快速建造（GUI 预设） ================")
    print("[*] 公式：%s；次数：%d。" % (info["name"], count))
    if tmp["doll_protect_ids"]:
        mode_text = "手动保护" if tmp["doll_protect_mode"] == "manual" else "默认五星保护"
        print("[*] 保护模式：%s；保护 ID 数量 %d。" % (mode_text, len(tmp["doll_protect_ids"])))
    else:
        print("[*] 未配置保护 ID。")
    print("[*] 本次快速建造配置只在当前流程生效，不会覆盖 -show 中的跟随模块制造设置。")
    # Force refresh index at the start to ensure fresh slot/resource data
    invalidate_shared_index_cache(reason="快速建造开始，强制刷新以获取最新状态")
    global _round_details
    _round_details = []
    remaining = count
    total_built = 0
    total_retired = 0
    total_quick_contracts_used = 0
    round_num = 0
    _force_refresh = True
    while remaining > 0:
        round_num += 1
        print("\n========== 人形快速建造 第 %d 轮（剩余 %d/%d）==========" % (round_num, remaining, count))
        built = run_one_doll_factory_test(tmp, batch_count=remaining, force_refresh_index=_force_refresh)
        _force_refresh = False
        total_retired += _quick_stats.get("retired", 0)
        total_quick_contracts_used += _quick_stats.get("quick_contracts_used", 0)
        if not built:
            print("[!] 第 %d 轮未能建造任何物品，停止。" % round_num)
            break
        remaining -= built
        total_built += built
    total_protected = max(0, total_built - total_retired)
    print("[+] 人形自动快速建造流程结束：成功 %d/%d。" % (total_built, count))
    # Write summary for GUI popup
    summary = {
        "kind": "doll", "formula": info["name"], "formula_key": formula_key,
        "count_requested": count, "count_completed": total_built,
        "rounds": round_num, "quick_contracts_used": total_quick_contracts_used,
        "retired": total_retired, "protected": total_protected,
        "rounds_detail": list(_round_details),
    }
    try:
        QUICK_BUILD_SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[SUMMARY] 人形快速建造统计报告已生成。")
    except Exception:
        pass


def run_equip_quick_build_from_gui(st, count):
    """Quick equipment build using pre-set config from GUI popup (no interactive prompts)."""
    count = int_safe(count, 1)
    if count <= 0:
        count = 1
    config_path = QUICK_BUILD_GUI_CONFIG_FILE
    if not config_path.exists():
        print("[!] GUI 快速建造配置文件不存在：%s" % config_path)
        return
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("[!] 读取 GUI 快速建造配置失败：%s" % exc)
        return
    if cfg.get("kind") != "equip":
        print("[!] GUI 配置类型不匹配：期望 equip，实际 %s" % cfg.get("kind"))
        return
    formula_key = str(cfg.get("formula_key") or "optic")
    custom_resources = cfg.get("custom_resources")
    if formula_key == "custom" and isinstance(custom_resources, dict):
        res = {}
        for k in ("mp", "ammo", "mre", "part"):
            v = int_safe(custom_resources.get(k), 0)
            if v > 0:
                res[k] = v
        if not res:
            print("[!] 自定义公式资源全部为 0，已回退为光学瞄具公式。")
            formula_key = "optic"
            custom_resources = None
        else:
            tmp_formula = {"name": "自定义公式", "resources": res, "recommended": {}}
    elif formula_key not in EQUIP_FORMULAS:
        print("[!] 公式不存在：%s，已回退为光学瞄具。" % formula_key)
        formula_key = "optic"
        custom_resources = None
    else:
        custom_resources = None
    tmp = default_state()
    tmp["equip_formula"] = formula_key
    tmp["equip_protect_mode"] = "auto_5star_outputs"
    tmp["equip_protect_holo_red_dot"] = bool(cfg.get("protect_holo_red_dot", False))
    tmp["equip_protect_ids"] = []
    tmp["equip_target_scope"] = "total_outputs"
    tmp["equip_target_count"] = count
    tmp["equip_enabled"] = False
    if formula_key == "custom" and custom_resources:
        tmp["_custom_equip_formula"] = tmp_formula
        info = tmp_formula
    else:
        info = EQUIP_FORMULAS[formula_key]
    print("\n================ 装备自动快速建造（GUI 预设） ================")
    print("[*] 公式：%s；次数：%d。" % (info["name"], count))
    if tmp["equip_protect_holo_red_dot"]:
        print("[*] 本次快速建造将临时保护全息/红点/ACOG瞄具。")
    else:
        print("[*] 本次快速建造不保护普通全息/红点/ACOG瞄具。")
    print("[*] 本次快速建造配置只在当前流程生效，不会覆盖 -show 中的跟随模块制造设置。")
    # Force refresh index at the start to ensure fresh slot/resource data
    invalidate_shared_index_cache(reason="快速建造开始，强制刷新以获取最新状态")
    global _round_details
    _round_details = []
    remaining = count
    total_built = 0
    total_retired = 0
    total_quick_contracts_used = 0
    round_num = 0
    _force_refresh = True
    while remaining > 0:
        round_num += 1
        print("\n========== 装备快速建造 第 %d 轮（剩余 %d/%d）==========" % (round_num, remaining, count))
        built = run_one_equip_factory_test(tmp, batch_count=remaining, force_refresh_index=_force_refresh)
        _force_refresh = False
        total_retired += _quick_stats.get("retired", 0)
        total_quick_contracts_used += _quick_stats.get("quick_contracts_used", 0)
        if not built:
            print("[!] 第 %d 轮未能建造任何物品，停止。" % round_num)
            break
        remaining -= built
        total_built += built
    total_protected = max(0, total_built - total_retired)
    print("[+] 装备自动快速建造流程结束：成功 %d/%d。" % (total_built, count))
    # Write summary for GUI popup
    summary = {
        "kind": "equip", "formula": info["name"], "formula_key": formula_key,
        "count_requested": count, "count_completed": total_built,
        "rounds": round_num, "quick_contracts_used": total_quick_contracts_used,
        "retired": total_retired, "protected": total_protected,
        "protect_holo_red_dot": bool(cfg.get("protect_holo_red_dot", False)),
        "rounds_detail": list(_round_details),
    }
    try:
        QUICK_BUILD_SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[SUMMARY] 装备快速建造统计报告已生成。")
    except Exception:
        pass


def print_ids(title, ids, catalog, name_func):
    ids = [int(x) for x in ids if str(x).strip().isdigit()]
    if not ids:
        print("  %s：未配置" % title)
        return
    print("  %s：" % title)
    for eid in ids[:80]:
        print("    %s %s" % (eid, name_func(catalog.get(eid), eid) if name_func.__name__ == "equip_display_name" else name_func(catalog.get(eid))))
    if len(ids) > 80:
        print("    ... 共 %d 个 ID" % len(ids))


def print_state(st):
    gun_catalog = load_gun_catalog()
    equip_catalog = load_equip_catalog()
    print("\n================ 制造自动化设置 ================")
    print("人形自动制造：%s" % ("开启" if st.get("doll_enabled") else "关闭"))
    f = st.get("doll_formula", "handgun")
    if f in DOLL_FORMULAS:
        print("  人形公式：%s（%s）" % (DOLL_FORMULAS[f]["name"], resource_text(DOLL_FORMULAS[f]["resources"])))
    print("  保护模式：%s" % st.get("doll_protect_mode", "-"))
    print("  目标数量：%s（%s）" % (st.get("doll_target_count", 1), "保护目标累计" if st.get("doll_target_scope") == "protected_hits" else "总制造产物"))
    print_ids("保护人形", st.get("doll_protect_ids", []), gun_catalog, gun_display_name)
    print("装备自动制造：%s" % ("开启" if st.get("equip_enabled") else "关闭"))
    ef = st.get("equip_formula", "optic")
    if ef in EQUIP_FORMULAS:
        print("  装备公式：%s（%s）" % (EQUIP_FORMULAS[ef]["name"], resource_text(EQUIP_FORMULAS[ef]["resources"])))
    equip_mode = st.get("equip_protect_mode", "-")
    if equip_mode in ("auto_5star_outputs", "protect_all_5star", "auto_5star", "protect_5star"):
        print("  保护模式：自动保护五星装备；默认排除全息/红点瞄具")
        print("  全息/红点保护：%s" % ("开启" if st.get("equip_protect_holo_red_dot") else "关闭"))
    else:
        print("  保护模式：%s" % equip_mode)
    print("  目标数量：%s（%s）" % (st.get("equip_target_count", 1), "保护目标累计" if st.get("equip_target_scope") == "protected_hits" else "总制造产物"))
    print_ids("额外保护装备", st.get("equip_protect_ids", []), equip_catalog, equip_display_name)
    print("================================================\n")


def ask_target_count(has_protected, object_name):
    if has_protected:
        prompt = "请输入目标%s保留数量（保护目标累计达到该数量后停止；输入 0 表示不设上限，回车默认 1）> " % object_name
    else:
        prompt = "请输入本次总制造数量上限（所有产物都会拆解；输入 0 表示不设上限，回车默认 1）> "
    raw = input(prompt).strip()
    if raw == "":
        return 1
    try:
        v = int(raw)
        if v < 0:
            raise ValueError()
        return v
    except Exception:
        print("[!] 数量输入无效，已按默认 1 处理。")
        return 1


def ask_manual_ids(object_name, catalog, name_func):
    while True:
        raw = input("请输入要保护的%s ID，多个 ID 可用空格/逗号分隔> " % object_name).replace(",", " ").split()
        ids = []
        bad = []
        for x in raw:
            try:
                gid = int(x)
                if gid <= 0:
                    raise ValueError()
                ids.append(gid)
            except Exception:
                bad.append(x)
        ids = sorted(set(ids))
        if bad:
            print("[!] 以下 ID 无法识别：%s" % ", ".join(bad))
        if not ids:
            print("[!] 未输入有效 ID。若希望拆解所有产物，请返回后选择 -n。")
            continue
        print("\n将加入保护的%s：" % object_name)
        for gid in ids:
            item = catalog.get(gid)
            if object_name == "装备":
                print("  %s -> %s%s" % (gid, equip_display_name(item, gid), "" if item else "（未在 equip.json/equip1.json 中找到）"))
            else:
                print("  %s -> %s%s" % (gid, gun_display_name(item), "" if item else "（未在 gun.json/gun1.json 中找到）"))
        ok = input("确认输入正确并加入保护列表吗？-y 确认 / -n 重新输入> ").strip().lower()
        if ok in ("-y", "y", "yes", "是", ""):
            return ids



def auto_doll_protect_ids_for_formula(formula_key, catalog=None):
    """Return conservative five-star T-Doll protect list for the selected formula.

    For normal formulas, type in gun.json matches the broad class: 1 HG, 2 SMG,
    3 RF, 4 AR, 5 MG.  We protect known rank 5 / rank_display 5 dolls of the
    selected class, and always include the formula's recommended fixed target.
    """
    if catalog is None:
        catalog = load_gun_catalog()
    info = DOLL_FORMULAS.get(formula_key) or {}
    gun_type = int_safe(info.get("type"), 0)
    ids = set()
    for gid, item in catalog.items():
        if not isinstance(item, dict):
            continue
        if gun_type and int_safe(item.get("type"), 0) != gun_type:
            continue
        rank = max(int_safe(item.get("rank"), 0), int_safe(item.get("rank_display"), 0))
        if rank >= 5:
            ids.add(int_safe(gid, 0))
    for gid in (info.get("recommended") or {}).keys():
        gid = int_safe(gid, 0)
        if gid > 0:
            ids.add(gid)
    return sorted(x for x in ids if x > 0)

def choose_doll_formula(st):
    catalog = load_gun_catalog()
    keys = list(DOLL_FORMULAS.keys())
    print("\n========== 人形制造公式 ==========")
    for i, key in enumerate(keys, 1):
        info = DOLL_FORMULAS[key]
        rec = info.get("recommended") or {}
        rec_text = "，推荐保护：" + "、".join("%s(%s)" % (name, gid) for gid, name in rec.items()) if rec else ""
        print(" %d. %s：%s%s" % (i, info["name"], resource_text(info["resources"]), rec_text))
    print("================================")
    ans = input("请选择公式编号> ").strip()
    try:
        formula_key = keys[int(ans) - 1]
    except Exception:
        print("[!] 公式选择无效。")
        return
    st["doll_formula"] = formula_key
    info = DOLL_FORMULAS[formula_key]
    print("[+] 已选择人形公式：%s。" % info["name"])
    rec = info.get("recommended") or {}
    if rec:
        print("[*] 本公式推荐保护：%s" % "、".join("%s(%s)" % (name, gid) for gid, name in rec.items()))
    auto_ids = auto_doll_protect_ids_for_formula(formula_key, catalog)
    if auto_ids:
        print("[*] 默认保护策略：若不手动添加，将自动保护该公式对应枪种的所有五星人形（含推荐目标），共 %d 个 ID。" % len(auto_ids))
    ans = input("是否自行添加保护人形？输入 -y 手动添加，输入 -n 使用默认五星保护> ").strip().lower()
    if ans in ("-y", "y", "yes", "是"):
        st["doll_protect_ids"] = ask_manual_ids("人形", catalog, gun_display_name)
        st["doll_protect_mode"] = "manual"
        st["doll_target_scope"] = "protected_hits"
    else:
        st["doll_protect_ids"] = auto_ids
        st["doll_protect_mode"] = "auto_5star_by_formula"
        st["doll_target_scope"] = "protected_hits" if auto_ids else "total_outputs"
        if auto_ids:
            print("[+] 已启用默认五星保护：该公式对应枪种的五星人形会保留，其余产物进入非保护拆解队列。")
        else:
            print("[!] 未能从图鉴生成默认五星保护列表；将按总产物计数并保守拆解非保护产物。")
    st["doll_target_count"] = ask_target_count(bool(st.get("doll_protect_ids")), "人形")
    st["doll_enabled"] = True
    save_state(st)
    if st.get("doll_protect_ids"):
        mode_text = "手动保护" if st.get("doll_protect_mode") == "manual" else "默认五星保护"
        print("[+] 人形自动制造已开启。模式：%s；保护列表 %s 个；保护目标累计达到 %s 后停止。" % (mode_text, len(st.get("doll_protect_ids", [])), st.get("doll_target_count")))
    else:
        print("[+] 人形自动制造已开启。当前模式：无保护列表；总制造数量达到 %s 后停止。" % st.get("doll_target_count"))
    print("[*] 后台将在进入其它功能模块时随模块一起运行。")


def choose_equip_formula(st):
    catalog = load_equip_catalog()
    keys = list(EQUIP_FORMULAS.keys())
    print("\n========== 装备制造公式 ==========")
    for i, key in enumerate(keys, 1):
        info = EQUIP_FORMULAS[key]
        rec = info.get("recommended") or {}
        rec_text = "，推荐保护：" + "、".join("%s(%s)" % (name, eid) for eid, name in rec.items()) if rec else ""
        print(" %2d. %s：%s%s" % (i, info["name"], resource_text(info["resources"]), rec_text))
    print("================================")
    ans = input("请选择装备公式编号> ").strip()
    try:
        formula_key = keys[int(ans) - 1]
    except Exception:
        print("[!] 公式选择无效。")
        return
    st["equip_formula"] = formula_key
    info = EQUIP_FORMULAS[formula_key]
    print("[+] 已选择装备公式：%s。" % info["name"])
    st["equip_protect_ids"] = []
    st["equip_protect_mode"] = "auto_5star_outputs"
    st["equip_protect_holo_red_dot"] = False
    st["equip_target_scope"] = "total_outputs"
    print("[*] 装备保护逻辑：自动保护制造出的五星装备；但全息/红点瞄具默认不保护，所有已知星级均可拆解。")
    print("[*] 如需临时保护全息/红点瞄具，可在制造菜单输入 -sighton 开启，或 -sightoff 关闭。")
    st["equip_target_count"] = ask_target_count(False, "装备")
    st["equip_enabled"] = True
    save_state(st)
    print("[+] 装备自动制造已开启。当前模式：五星自动保留（全息/红点默认不保护），非保护产物自动拆解；总制造数量达到 %s 后停止。" % st.get("equip_target_count"))
    print("[*] 后台将在进入其它功能模块时随模块一起运行。")


def set_equip_sight_protection(st, enabled):
    st["equip_protect_holo_red_dot"] = bool(enabled)
    save_state(st)
    if enabled:
        print("[+] 已开启全息/红点瞄具保护：此类装备领取后会保留。")
    else:
        print("[*] 已关闭全息/红点瞄具保护：所有已知星级的全息/红点瞄具默认不保护。")


def print_menu():
    print("\n================ 制造自动化 MENU ================")
    print(" -show       : 查看当前设置")
    print(" -doll       : 选择人形制造公式、保护目标和目标数量，并开启跟随模块运行的人形自动制造")
    print(" -dolloff    : 关闭跟随模块运行的人形自动制造")
    print(" -equip      : 选择装备制造公式、保护目标和目标数量，并开启跟随模块运行的装备自动制造")
    print(" -equipoff   : 关闭跟随模块运行的装备自动制造")
    print(" -testdoll N : 人形自动快速建造；先单独选择本次公式/保护人形，再发送 N 次并自动快速完成领取")
    print(" -testequip N: 装备自动快速建造；先单独选择本次公式/保护规则，再发送 N 次并自动快速完成领取/显示星级保护判定")
    print(" -sighton    : 开启全息/红点瞄具保护")
    print(" -sightoff   : 关闭全息/红点瞄具保护（默认）")
    print(" -E          : 返回少女全自动 GFAM 主菜单")
    print("================================================")


def main():
    st = load_state()
    while True:
        print_menu()
        cmd_line = input("GFAM-制造> ").strip()
        cmd_parts = cmd_line.split()
        cmd = (cmd_parts[0].lower() if cmd_parts else "")
        if cmd in ("-e", "e", "0", "exit", "quit"):
            print("[*] 返回 GFAM 主菜单。")
            return 0
        if cmd in ("-show", "show", "s"):
            print_state(st)
        elif cmd in ("-doll", "doll", "人形"):
            choose_doll_formula(st)
            st = load_state()
        elif cmd in ("-dolloff", "doloff", "dolloff", "关闭人形"):
            st["doll_enabled"] = False
            save_state(st)
            print("[*] 已关闭人形自动制造。")
        elif cmd in ("-equip", "equip", "装备"):
            choose_equip_formula(st)
            st = load_state()
        elif cmd in ("-equipoff", "equipoff", "关闭装备"):
            st["equip_enabled"] = False
            save_state(st)
            print("[*] 已关闭装备自动制造。")
        elif cmd in ("-sighton", "sighton", "保护瞄具", "开启瞄具保护"):
            set_equip_sight_protection(st, True)
            st = load_state()
        elif cmd in ("-sightoff", "sightoff", "不保护瞄具", "关闭瞄具保护"):
            set_equip_sight_protection(st, False)
            st = load_state()
        elif cmd in ("-testdoll", "testdoll", "dolltest", "测试人形", "人形测试", "人形自动快速建造"):
            count = quick_build_count_from_command(cmd_line)
            run_doll_quick_build_test(st, count)
            st = load_state()
        elif cmd in ("-testequip", "testequip", "equiptest", "测试装备", "装备测试", "装备自动快速建造"):
            count = quick_build_count_from_command(cmd_line)
            run_equip_quick_build_test(st, count)
            st = load_state()
        elif cmd in ("-testdollgui", "testdollgui"):
            count = quick_build_count_from_command(cmd_line)
            run_doll_quick_build_from_gui(st, count)
            st = load_state()
        elif cmd in ("-testequipgui", "testequipgui"):
            count = quick_build_count_from_command(cmd_line)
            run_equip_quick_build_from_gui(st, count)
            st = load_state()
        else:
            print("[!] 未识别命令。")


if __name__ == "__main__":
    sys.exit(main())
