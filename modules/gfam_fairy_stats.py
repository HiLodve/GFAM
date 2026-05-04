# -*- coding: utf-8 -*-
"""GFAM 妖精自动建造/强化统计辅助。"""

import json
import os
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_FILE = os.path.join(ROOT_DIR, ".gfam_state.json")
CACHE_FILE = os.path.join(ROOT_DIR, ".gfam_fairy_auto_cache.json")

COUNTER_KEYS = (
    "build_attempts",
    "build_success",
    "finish_attempts",
    "finish_success",
    "strengthen_attempts",
    "strengthen_success",
)

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

FAIRY_ANSI = {
    "reset": "\033[0m",
    "label": "\033[97m",
    "active": "\033[96m",
    "warn": "\033[93m",
    "dim": "\033[90m",
}

READY_FLAG_KEYS = (
    "is_finish", "is_finished", "finished", "finish",
    "is_complete", "is_completed", "complete", "completed",
    "is_ready", "ready", "can_finish", "can_get", "is_get",
)
STATUS_KEYS = ("status", "state", "build_status", "develop_status")
REMAIN_KEYS = ("remain_time", "remaining_time", "left_time", "time_left")
FINISH_TIME_KEYS = ("finish_time", "end_time", "build_finish_time", "complete_time", "finished_at")


def _truthy_flag(value):
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "ready", "finish", "finished", "complete", "completed", "done", "get", "can_get"):
        return True
    if text in ("0", "false", "no", "n", "building", "running", "developing", "pending", "none", ""):
        return False
    try:
        return int(float(text)) > 0
    except Exception:
        return False


def _explicit_ready_flag(item, source_key):
    if not isinstance(item, dict):
        return False
    for key in READY_FLAG_KEYS:
        if key in item and _truthy_flag(item.get(key)):
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


def _first_present_int(item, keys, default=0):
    for key in keys:
        if isinstance(item, dict) and key in item:
            return _int(item.get(key), default)
    return default


def _c(text, key="label"):
    if os.environ.get("NO_COLOR") == "1":
        return str(text)
    return FAIRY_ANSI.get(key, "") + str(text) + FAIRY_ANSI["reset"]


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _user_info(payload):
    return payload.get("user_info", {}) if isinstance(payload, dict) else {}


def _payload_uid(payload):
    ui = _user_info(payload)
    return str(ui.get("user_id") or ui.get("id") or "").strip()


def _current_uid():
    return str(os.environ.get("GFAM_USER_UID") or os.environ.get("USER_UID") or "").strip()


def _current_server():
    return str(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "").strip()


def _cache_matches_current_identity(cache):
    if not isinstance(cache, dict):
        return False
    uid = _current_uid()
    server = _current_server()
    cache_uid = str(cache.get("cache_uid") or "").strip()
    cache_server = str(cache.get("cache_server") or "").strip()
    if uid and cache_uid and uid != cache_uid:
        return False
    if server and cache_server and server != cache_server:
        return False
    return True


def fairy_auto_enabled():
    env = str(os.environ.get("GFAM_FAIRY_AUTO_ENABLED", "")).strip()
    if env in ("1", "true", "True", "yes", "on"):
        return True
    if env in ("0", "false", "False", "no", "off"):
        return False
    state = _read_json(STATE_FILE, {})
    return state.get("fairy_auto_enabled") is True


def _iter_fairies(payload):
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


def _fairy_inventory_from_index(payload):
    fairies = list(_iter_fairies(payload))
    max_fairy = _int(_user_info(payload).get("max_fairy"), 0)
    if max_fairy <= 0:
        max_fairy = len(fairies)
    return {
        "count": len(fairies),
        "max": max_fairy,
        "free": max(0, max_fairy - len(fairies)),
    }


def _unlocked_fairy_build_slot_count(payload):
    """妖精建造使用装备/妖精建造栏位中的偶数栏，max_equip_build_slot=8 时为 4 栏。"""
    ui = _user_info(payload)
    raw = _int(ui.get("max_equip_build_slot", ui.get("max_build_slot", 4)), 4)
    if raw <= 0:
        return 2
    return max(1, raw // 2)


def _has_active_fairy_build_payload(item):
    """判断 develop_fairy_act_info 中某个栏位是否真的有妖精建造任务。

    某些服务器会返回空栏位占位 dict；如果只因为它来自 develop_fairy_act_info
    就判定为占用，会把空栏显示成“待领取”。因此必须要求有 start_time、
    明确完成/剩余时间、结果 fairy_id/passive_skill 或最低公式资源字段之一。
    """
    if not isinstance(item, dict) or not item:
        return False
    if _int(item.get("start_time"), 0) > 0:
        return True
    # remain_time>0 可确认正在建造；remain_time=0 单独出现时可能只是空栏位占位，
    # 不能作为待领取依据，除非同时有 fairy_id/passive_skill/完成标记等结果字段。
    if _first_present_int(item, REMAIN_KEYS, -1) > 0:
        return True
    if _first_present_int(item, FINISH_TIME_KEYS, 0) > 0:
        return True
    if _explicit_ready_flag(item, "develop_fairy_act_info"):
        return True
    # 注意：fairy_id/passive_skill 在建造中、甚至空栏位占位记录里都可能存在，
    # 不能单独作为“占用/待领取”依据。必须依赖 start_time、remain_time、finish_time、
    # 明确完成标记，或最低公式资源字段。
    if _int(item.get("input_level"), 0) == 1 and all(_int(item.get(k), 0) >= 500 for k in ("mp", "ammo", "mre", "part")):
        return True
    return False


def _looks_like_fairy_build(item, source_key):
    """只把真实妖精建造任务计入妖精栏位。

    优先使用 develop_fairy_act_info；develop_equip_act_info 默认不再参与妖精判断，
    避免把普通装备建造或空栏位误判成妖精待领取。
    """
    if not isinstance(item, dict):
        return False
    if source_key == "develop_fairy_act_info":
        return _has_active_fairy_build_payload(item)
    # 仅在老服务端没有 develop_fairy_act_info 时才可能启用 fallback；这里保持严格条件。
    if source_key == "develop_equip_act_info":
        return False
    return False


def _iter_build_records(payload):
    if not isinstance(payload, dict):
        return
    # 新字段优先；旧服务端可能把妖精建造混在 develop_equip_act_info 中。
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
            if not _looks_like_fairy_build(item, source_key):
                continue
            yield source_key, fallback_slot, item


def _active_fairy_builds_from_index(payload):
    now = int(time.time())
    result = []
    for source_key, fallback_slot, item in _iter_build_records(payload) or []:
        slot = _int(item.get("build_slot", item.get("slot", fallback_slot)), _int(fallback_slot, 0))
        explicit_ready = _explicit_ready_flag(item, source_key)
        finish_time = _first_present_int(item, FINISH_TIME_KEYS, 0)
        remain = _first_present_int(item, REMAIN_KEYS, 0)
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
            start_time = _int(item.get("start_time"), 0)
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
            "fairy_id": _int(item.get("fairy_id"), 0),
            "passive_skill": _int(item.get("passive_skill"), 0),
            "remain": remain,
            "is_ready": remain <= 0,
            "status_source": status_source,
            "expected_finish_time": expected_finish_time,
        })
    # 去重：部分服务端会同时给 develop_fairy_act_info 和 develop_equip_act_info。
    seen = set()
    unique = []
    for b in result:
        key = (b.get("slot"), b.get("expected_finish_time"), b.get("fairy_id"), b.get("passive_skill"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)
    return unique


def _recompute_builds_by_local_timer(builds):
    now = int(time.time())
    result = []
    for item in builds or []:
        if not isinstance(item, dict):
            continue
        b = dict(item)
        expected = _int(b.get("expected_finish_time"), 0)
        if expected > 0:
            remain = max(0, expected - now)
        else:
            remain = max(0, _int(b.get("remain"), 0))
            if remain > 0:
                expected = now + remain
        b["expected_finish_time"] = expected
        b["remain"] = remain
        b["is_ready"] = remain <= 0
        result.append(b)
    return result


def _local_build_counts(active):
    builds = _recompute_builds_by_local_timer(active)
    ready = sum(1 for b in builds if _int(b.get("remain"), 1) <= 0)
    building = max(0, len(builds) - ready)
    return builds, building, ready, len(builds)


def update_fairy_cache_from_index_payload(payload, source="Index/index"):
    """用主模块已经请求到的 Index/index 刷新妖精自动缓存。"""
    if not fairy_auto_enabled() or not isinstance(payload, dict):
        return False
    try:
        builds = _active_fairy_builds_from_index(payload)
        ready_count = sum(1 for b in builds if b.get("is_ready"))
        building_count = sum(1 for b in builds if not b.get("is_ready"))
        cache = _read_json(CACHE_FILE, {})
        if not _cache_matches_current_identity(cache):
            # 切换服务器/账号后丢弃上一账号的本地倒计时，避免空栏位显示成旧账号的待领取。
            cache = {k: cache.get(k, 0) for k in COUNTER_KEYS}
        payload_uid = _payload_uid(payload)
        current_server = _current_server()
        cache.update({
            "cache_uid": payload_uid or _current_uid(),
            "cache_server": current_server,
            "updated_at": int(time.time()),
            "last_index_at": int(time.time()),
            "updated_source": source,
            "fairy_inventory": _fairy_inventory_from_index(payload),
            "resources": {
                "mp": _int(_user_info(payload).get("mp"), 0),
                "ammo": _int(_user_info(payload).get("ammo"), 0),
                "mre": _int(_user_info(payload).get("mre"), 0),
                "part": _int(_user_info(payload).get("part"), 0),
            },
            "build_slots": _unlocked_fairy_build_slot_count(payload),
            "slot_numbers": [2 * i for i in range(1, _unlocked_fairy_build_slot_count(payload) + 1)],
            "active_builds": builds,
            "ready_builds": ready_count,
            "building_builds": building_count,
            "occupied_builds": len(builds),
        })
        _write_json(CACHE_FILE, cache)
        return True
    except Exception:
        return False


def read_fairy_snapshot():
    data = _read_json(CACHE_FILE, {})
    if not _cache_matches_current_identity(data):
        # 当前进程所属账号/服务器与缓存不一致时，不显示上一账号的建造倒计时。
        data = {k: _int(data.get(k), 0) for k in COUNTER_KEYS}
    snap = {k: _int(data.get(k), 0) for k in COUNTER_KEYS}
    snap["updated_at"] = _int(data.get("updated_at"), 0)
    inv = data.get("fairy_inventory") if isinstance(data.get("fairy_inventory"), dict) else {}
    snap["fairy_inventory"] = {
        "count": _int(inv.get("count"), 0),
        "max": _int(inv.get("max"), 0),
        "free": _int(inv.get("free"), 0),
    }
    active = data.get("active_builds") if isinstance(data.get("active_builds"), list) else []
    active, building_count, ready_count, occupied_count = _local_build_counts(active)
    snap["active_builds"] = active
    snap["build_slots"] = _int(data.get("build_slots"), 0)
    snap["ready_builds"] = ready_count
    snap["building_builds"] = building_count
    snap["occupied_builds"] = occupied_count
    running_remains = [_int(b.get("remain"), 0) for b in active if _int(b.get("remain"), 0) > 0]
    snap["next_finish_remaining"] = min(running_remains) if running_remains else 0
    snap["next_finish_at"] = int(time.time()) + snap["next_finish_remaining"] if snap["next_finish_remaining"] > 0 else 0
    # 保留字段用于兼容，但面板不再显示“本地计时 0秒前”这种容易误解的信息。
    snap["local_timer_updated_at"] = _int(data.get("local_timer_updated_at"), 0)
    return snap


def diff_fairy_snapshot(start=None, end=None):
    start = start or {}
    end = end or read_fairy_snapshot()
    return {k: max(0, _int(end.get(k), 0) - _int(start.get(k), 0)) for k in COUNTER_KEYS}


def _age_text(ts):
    if not ts:
        return "未更新"
    age = max(0, int(time.time()) - _int(ts, 0))
    if age < 60:
        return "%d秒前" % age
    if age < 3600:
        return "%d分钟前" % (age // 60)
    return "%d小时前" % (age // 3600)


def _duration_text(seconds):
    seconds = max(0, _int(seconds, 0))
    if seconds < 60:
        return "%d秒" % seconds
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return "%d分%d秒" % (minutes, sec)
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return "%d小时%d分" % (hours, minutes)
    days, hours = divmod(hours, 24)
    return "%d天%d小时" % (days, hours)


def _fairy_update_text(snap):
    """面板显示妖精计时状态。

    旧版把 read_fairy_snapshot() 的本地重算时间直接显示成“本地计时 0秒前”，
    因为面板每次刷新都会现场重算，所以看起来像本地计时没有正常推进。
    这里改为显示真正有意义的信息：Index 最近校准时间 + 本地倒计时状态/下次完成时间。
    """
    index_text = _age_text(snap.get("updated_at", 0))
    occupied = _int(snap.get("occupied_builds", 0), 0)
    ready = _int(snap.get("ready_builds", 0), 0)
    next_remain = _int(snap.get("next_finish_remaining", 0), 0)
    if occupied <= 0:
        return "Index %s / 本地倒计时：空闲" % index_text
    if ready > 0:
        return "Index %s / 本地倒计时：待领取 %s" % (index_text, ready)
    if next_remain > 0:
        return "Index %s / 本地倒计时：下次完成 %s后" % (index_text, _duration_text(next_remain))
    return "Index %s / 本地倒计时：运行中" % index_text


def fairy_runtime_status_line():
    if not fairy_auto_enabled():
        return ""
    snap = read_fairy_snapshot()
    inv = snap.get("fairy_inventory", {})
    label = _c("妖精自动：", "label")
    if snap.get("ready_builds", 0) > 0:
        build_part = "栏位 %s，占用 %s（建造中 %s / 待领取 %s）" % (
            snap.get("build_slots", 0), snap.get("occupied_builds", 0), snap.get("building_builds", 0), _c(snap.get("ready_builds", 0), "warn")
        )
    else:
        build_part = "栏位 %s，占用 %s（建造中 %s / 待领取 0）" % (
            snap.get("build_slots", 0), snap.get("occupied_builds", 0), snap.get("building_builds", 0)
        )
    return "%s操作 建造启动 %s/%s，领取 %s/%s，强化 %s/%s；状态 仓库 %s/%s，空位 %s；%s；更新 %s" % (
        label,
        snap.get("build_success", 0), snap.get("build_attempts", 0),
        snap.get("finish_success", 0), snap.get("finish_attempts", 0),
        snap.get("strengthen_success", 0), snap.get("strengthen_attempts", 0),
        inv.get("count", 0), inv.get("max", 0), inv.get("free", 0),
        build_part,
        _fairy_update_text(snap),
    )


def fairy_summary_lines(start_snapshot=None, end_snapshot=None):
    if not fairy_auto_enabled():
        return []
    end_snapshot = end_snapshot or read_fairy_snapshot()
    diff = diff_fairy_snapshot(start_snapshot or {}, end_snapshot)
    inv = end_snapshot.get("fairy_inventory", {})
    lines = [
        "妖精自动建造/强化统计：",
        "  妖精建造启动：%s / %s 次成功" % (diff.get("build_success", 0), diff.get("build_attempts", 0)),
        "  妖精领取：%s / %s 次成功" % (diff.get("finish_success", 0), diff.get("finish_attempts", 0)),
        "  妖精强化：%s / %s 次成功" % (diff.get("strengthen_success", 0), diff.get("strengthen_attempts", 0)),
        "  当前妖精仓库：%s / %s，空位 %s；栏位 %s，占用 %s（建造中 %s / 待领取 %s）；最近更新 %s" % (
            inv.get("count", 0), inv.get("max", 0), inv.get("free", 0),
            end_snapshot.get("build_slots", 0), end_snapshot.get("occupied_builds", 0),
            end_snapshot.get("building_builds", 0), end_snapshot.get("ready_builds", 0),
            _fairy_update_text(end_snapshot),
        ),
    ]
    if not any(diff.values()):
        lines.append("  本次模块运行期间暂无妖精建造/领取/强化动作，可能是栏位未完成、资源/仓位不足、无可用强化材料，或后台循环尚未到下一次检查。")
    return lines


def print_fairy_summary(start_snapshot=None):
    for line in fairy_summary_lines(start_snapshot):
        print(line)
