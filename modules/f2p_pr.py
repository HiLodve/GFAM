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

# src/demo/farm/resource/f2p_pr.py

import sys
import time
import json
import os
import threading
import traceback
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_COMBINFO, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_ALLY_MYSIDE_MOVE,
    API_MISSION_END_TURN, API_MISSION_START_ENEMY_TURN,
    API_MISSION_END_ENEMY_TURN, API_MISSION_START_TURN,
    API_MISSION_ABORT, API_GUN_RETIRE, API_INDEX_INDEX
)

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
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "MACRO_LOOPS": 0,
    # 0 表示无固定 Macro 上限：直到手动停止，或连续失败达到上限时才停止。
    "MAX_CONSECUTIVE_FAILURES": 10,
    # 运行中 Micro 失败时，先尝试一次人形应急拆解并重试当前 Micro。
    "ENABLE_GUN_EXCEPTION_SELF_REPAIR": True,
    "MISSIONS_PER_RETIRE": 50,
    "MISSIONS_PER_RETIRE_BASE": 50,
    # 根据当前人形仓库空位自动下调 Micro 上限；按每轮战役结算 1 个人形估算。
    "DYNAMIC_MICRO_BY_STORAGE": True,
    "STORAGE_MICRO_RESERVE": 0,
    "STORAGE_MICRO_BATTLES_PER_RUN": 0,
    "STORAGE_MICRO_EXTRA_GUN_DROPS_PER_RUN": 1,
    "STORAGE_MICRO_LIMIT_BLOCKED": False,
    # 自适应间隔：默认保持原速度；连续遇到 plaintext / error:2 / error:3 / error:300 时自动放慢关键接口。
    "ADAPTIVE_TIMING_ENABLED": True,
    "ADAPTIVE_TIMING_MAX_LEVEL": 8,
    "ADAPTIVE_TIMING_TRIGGER_ERRORS": 1,
    "ADAPTIVE_TIMING_DECAY_SUCCESSES": 120,
    "ADAPTIVE_TIMING_STEP_EXTRA": 0.10,
    "ADAPTIVE_TIMING_STATE_EXTRA": 0.25,

    "RESOURCE_START_INVENTORY": {},
    "RESOURCE_END_INVENTORY": {},
    "RUN_INDEX_CACHE": None,
    "RUN_INDEX_CACHE_AT": 0,
    "SQUAD_ID": 0,
    # 重装小队移动 person_type 不同 gflzirc/服务器可能存在差异；首次移动会自动尝试这些候选。
    "SQUAD_PERSON_TYPE_CANDIDATES": [6, 5, 4, 2, 3],
    "SQUAD_PERSON_TYPE": 0,
    "BASE_URL": SERVERS["M4A1"],
    "PROXY_PORT": 12335
}

def apply_gfam_auth_from_env():
    """从 GFAM 主启动器接收已经抓取好的 UID/SIGN。"""
    try:
        uid = str(os.environ.get("GFAM_USER_UID") or "").strip()
        sign = str(os.environ.get("GFAM_SIGN_KEY") or "").strip()
        if uid and sign and sign != DEFAULT_SIGN:
            CONFIG["USER_UID"] = uid
            CONFIG["SIGN_KEY"] = sign
            CONFIG["GFAM_AUTH_READY"] = True
            if "INDEX_FETCH_READY" in CONFIG:
                CONFIG["INDEX_FETCH_READY"] = True
            print("[+] 已沿用 GFAM 主菜单获取的 UID/SIGN。")
            return True
    except Exception:
        pass
    CONFIG["GFAM_AUTH_READY"] = False
    return False


def _normalize_gfam_server_name(server):
    server = str(server or "").strip().upper().replace("_", "-")
    if server == "AR15":
        server = "AR-15"
    return server


def apply_gfam_selected_server():
    """沿用 GFAM 主菜单选择的服务器，并将 BASE_URL 切换到对应服务器。"""
    server = _normalize_gfam_server_name(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "")
    if not server:
        server = _normalize_gfam_server_name(CONFIG.get("SERVER_NAME") or "M4A1")

    aliases = [server]
    if server == "AR-15":
        aliases.append("AR15")

    for key in aliases:
        if key in SERVERS:
            CONFIG["SERVER_NAME"] = server
            CONFIG["BASE_URL"] = SERVERS[key]
            CONFIG["UNSUPPORTED_SERVER"] = False
            print("[*] 零元购使用服务器：%s" % server)
            return True

    CONFIG["SERVER_NAME"] = server or CONFIG.get("SERVER_NAME", "M4A1")
    CONFIG["UNSUPPORTED_SERVER"] = True
    print("[!] 当前 gflzirc 未找到服务器配置：%s" % CONFIG["SERVER_NAME"])
    print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
    return False

apply_gfam_selected_server()


current_worker_thread = None
worker_mode = None
proxy_instance = None

stop_macro_flag = False
stop_micro_flag = False


# === GFAM: 零元购固定状态面板 ===
F2P_DASHBOARD_STATS = {
    "running": False,
    "start_time": 0,
    "mode_name": "",
    "mission_id": 0,
    "macro": 0,
    "micro": 0,
    "micro_limit": 0,
    "total_runs": 0,
    "macro_drops": 0,
    "total_drops": 0,
    "last_drop": "无",
    "retire_total": 0,
    "retire_batches": 0,
    "consecutive_failures": 0,
    "max_failures": 0,
    "stop_reason": "",
}
F2P_LOG_BUFFER = []


def f2p_format_seconds(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    sec = seconds % 60
    if h:
        return "%d小时%d分%d秒" % (h, m, sec)
    if m:
        return "%d分%d秒" % (m, sec)
    return "%d秒" % sec


def f2p_clear_console():
    print("\033[2J\033[H", end="")


def f2p_log(message):
    line = str(message)
    F2P_LOG_BUFFER.append(line)
    if len(F2P_LOG_BUFFER) > 10:
        del F2P_LOG_BUFFER[:-10]


def f2p_start_dashboard(mode_name, mission_id):
    F2P_LOG_BUFFER.clear()
    F2P_DASHBOARD_STATS.update({
        "running": True,
        "start_time": time.time(),
        "mode_name": mode_name,
        "mission_id": mission_id,
        "macro": 0,
        "micro": 0,
        "micro_limit": int(CONFIG.get("MISSIONS_PER_RETIRE", 0) or 0),
        "total_runs": 0,
        "macro_drops": 0,
        "total_drops": 0,
        "last_drop": "无",
        "retire_total": 0,
        "retire_batches": 0,
        "consecutive_failures": 0,
        "max_failures": int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 10) or 10),
        "stop_reason": "运行中",
        "fairy_auto_start_snapshot": read_fairy_snapshot(),
    })
    f2p_log("[*] %s 自动运行已开始。" % mode_name)


def f2p_render_dashboard(force=False):
    f2p_clear_console()
    print("============== 最近运行记录 ==============")
    if F2P_LOG_BUFFER:
        for line in F2P_LOG_BUFFER[-10:]:
            print(line)
    else:
        print("暂无记录")
    print("")
    now = time.time()
    elapsed = f2p_format_seconds(now - F2P_DASHBOARD_STATS.get("start_time", now))
    running_text = "运行中" if F2P_DASHBOARD_STATS.get("running") else "已停止"
    macro_limit = int(CONFIG.get("MACRO_LOOPS", 0) or 0)
    macro_limit_text = str(macro_limit) if macro_limit > 0 else "直到手动停止或进程受阻"
    max_gun = CONFIG.get("STORAGE_MAX_GUN", "-")
    used_gun = CONFIG.get("STORAGE_USED_GUN", "-")
    free_gun = CONFIG.get("STORAGE_FREE_GUN", "-")
    squad_text = CONFIG.get("SQUAD_DISPLAY", "未选择")
    print("================= 零元购运行状态 =================")
    print("状态：%s | 已运行：%s | 服务器：%s" % (running_text, elapsed, CONFIG.get("SERVER_NAME", "-")))
    print("模式：%s | 关卡：%s" % (F2P_DASHBOARD_STATS.get("mode_name") or "零元购", F2P_DASHBOARD_STATS.get("mission_id") or "-"))
    print("当前 Macro：%s / %s" % (F2P_DASHBOARD_STATS.get("macro", 0), macro_limit_text))
    print("当前 Micro：%s / %s | 累计执行：%s" % (F2P_DASHBOARD_STATS.get("micro", 0), F2P_DASHBOARD_STATS.get("micro_limit", CONFIG.get("MISSIONS_PER_RETIRE", 0)), F2P_DASHBOARD_STATS.get("total_runs", 0)))
    print("本轮掉落：%s | 累计掉落：%s | 最近掉落：%s" % (F2P_DASHBOARD_STATS.get("macro_drops", 0), F2P_DASHBOARD_STATS.get("total_drops", 0), F2P_DASHBOARD_STATS.get("last_drop", "无")))
    print("自动拆解：%s 批 / %s 只" % (F2P_DASHBOARD_STATS.get("retire_batches", 0), F2P_DASHBOARD_STATS.get("retire_total", 0)))
    print("连续失败：%s / %s" % (F2P_DASHBOARD_STATS.get("consecutive_failures", 0), F2P_DASHBOARD_STATS.get("max_failures", CONFIG.get("MAX_CONSECUTIVE_FAILURES", 10))))
    print("仓库空位：%s/%s，剩余 %s | Micro 上限按每轮结算 1 个人形估算" % (used_gun, max_gun, free_gun))
    print("作战单位：%s" % squad_text)
    fairy_auto_line = fairy_runtime_status_line()
    if fairy_auto_line:
        print(fairy_auto_line)
    print("资源统计：结束后通过 Index/index 统计四项基础资源净变化")
    print("停止：-q 当前 Macro 后停 / -Q 当前 Micro 后停 / -E 返回 GFAM 主菜单")
    print("====================================================")


# === GFAM: 根据当前仓库空位自动计算 Micro 上限 ===
def _gfam_storage_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

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
    free = max(0, max_gun - used) if max_gun > 0 else 0
    return max_gun, used, free

def gfam_request_index_for_storage(client):
    try:
        resp = client.send_request(API_INDEX_INDEX, {"time": int(time.time()), "furniture_data": False})
    except Exception as e:
        print("[仓库] 请求 Index/index 失败，无法自动计算 Micro 上限：%s" % e)
        return None
    if not isinstance(resp, dict) or "error_local" in resp or "error" in resp:
        print("[仓库] Index/index 返回异常，无法自动计算 Micro 上限：%s" % resp)
        return None
    update_fairy_cache_from_index_payload(resp, source="f2p_pr Index/index")
    return resp



# === GFAM: 零元购结束后资源统计 ===
def gfam_get_basic_resource_inventory_from_index_payload(payload):
    """从 Index/index 的 user_info 中读取四项基础资源。"""
    user_info = payload.get("user_info", {}) if isinstance(payload, dict) else {}
    if not isinstance(user_info, dict):
        user_info = {}
    return {
        "mp": _gfam_storage_int(user_info.get("mp"), 0),
        "ammo": _gfam_storage_int(user_info.get("ammo"), 0),
        "mre": _gfam_storage_int(user_info.get("mre"), 0),
        "part": _gfam_storage_int(user_info.get("part"), 0),
    }


def f2p_format_resource_inventory(inv):
    inv = inv or {}
    return "人力 %s / 弹药 %s / 口粮 %s / 零件 %s" % (
        _gfam_storage_int(inv.get("mp"), 0),
        _gfam_storage_int(inv.get("ammo"), 0),
        _gfam_storage_int(inv.get("mre"), 0),
        _gfam_storage_int(inv.get("part"), 0),
    )


def f2p_record_resource_start_from_index_payload(payload):
    inv = gfam_get_basic_resource_inventory_from_index_payload(payload)
    CONFIG["RESOURCE_START_INVENTORY"] = dict(inv)
    CONFIG["RESOURCE_END_INVENTORY"] = {}
    f2p_log("[资源] 已记录起始库存：%s" % f2p_format_resource_inventory(inv))
    print("[资源] 已记录起始库存：%s" % f2p_format_resource_inventory(inv))
    return inv


def f2p_print_resource_summary(client):
    start_inv = CONFIG.get("RESOURCE_START_INVENTORY") or {}
    if not start_inv:
        print("[资源] 未记录起始库存，跳过本次资源统计。")
        return

    payload = gfam_request_index_for_storage(client)
    if payload is None:
        print("[资源] 结束时请求 Index/index 失败，无法计算资源净变化。")
        return

    end_inv = gfam_get_basic_resource_inventory_from_index_payload(payload)
    CONFIG["RESOURCE_END_INVENTORY"] = dict(end_inv)
    diff = {
        key: _gfam_storage_int(end_inv.get(key), 0) - _gfam_storage_int(start_inv.get(key), 0)
        for key in ("mp", "ammo", "mre", "part")
    }
    elapsed = max(1, int(time.time() - F2P_DASHBOARD_STATS.get("start_time", time.time())))
    per_hour = {
        key: int(round(_gfam_storage_int(diff.get(key), 0) * 3600 / elapsed))
        for key in ("mp", "ammo", "mre", "part")
    }

    print("\n=========== %s 本次运行统计 ===========" % (F2P_DASHBOARD_STATS.get("mode_name") or "零元购"))
    print("运行总时长：%s" % f2p_format_seconds(elapsed))
    print("完成轮数：%s" % F2P_DASHBOARD_STATS.get("macro", 0))
    print("累计执行：%s" % F2P_DASHBOARD_STATS.get("total_runs", 0))
    print("累计掉落：%s" % F2P_DASHBOARD_STATS.get("total_drops", 0))
    print("自动拆解：%s 批 / %s 只" % (F2P_DASHBOARD_STATS.get("retire_batches", 0), F2P_DASHBOARD_STATS.get("retire_total", 0)))
    if F2P_DASHBOARD_STATS.get("stop_reason"):
        print("停止原因：%s" % F2P_DASHBOARD_STATS.get("stop_reason"))
    print("")
    print("四项基础资源统计：")
    print("  起始库存：%s" % f2p_format_resource_inventory(start_inv))
    print("  结束库存：%s" % f2p_format_resource_inventory(end_inv))
    print("  本次变化：%s" % f2p_format_resource_inventory(diff))
    print("  每小时效率：%s" % f2p_format_resource_inventory(per_hour))
    print_fairy_summary(F2P_DASHBOARD_STATS.get("fairy_auto_start_snapshot"))
    print("========================================\n")
# === GFAM: 零元购资源统计结束 ===

def gfam_apply_dynamic_micro_limit_from_index_payload(payload, reason="Index/index"):
    if not CONFIG.get("DYNAMIC_MICRO_BY_STORAGE", True):
        return True
    max_gun, used, free = gfam_get_gun_storage_from_index_payload(payload)
    if max_gun <= 0:
        print("[仓库] 无法从 %s 读取人形仓库容量，保留当前 Micro 上限：%s。" % (reason, CONFIG.get("MISSIONS_PER_RETIRE")))
        return True
    # 零元购没有局内战斗人形掉落；仓库只增加战役结算随机人形 1 只。
    battles = max(0, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_BATTLES_PER_RUN", 0), 0))
    extra = max(1, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_EXTRA_GUN_DROPS_PER_RUN", 1), 1))
    drops_per_run = max(1, battles + extra)
    # 人工上限使用固定基准，不使用上一次已经被仓库空位压低后的 MISSIONS_PER_RETIRE。
    # 这样仓库整理/拆解后，下一轮可以重新按当前空位计算，而不会一直停留在旧的低上限。
    env_cap = _gfam_storage_int(os.environ.get("GFAM_MICRO_CAP", "0"), 0)
    if env_cap > 0:
        base_limit = max(1, env_cap)
    else:
        base_limit = max(1, _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE_BASE", CONFIG.get("MISSIONS_PER_RETIRE", 50)), 50))
    old_limit = max(1, _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE", base_limit), base_limit))
    reserve = max(0, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_RESERVE", 0), 0))
    usable_free = max(0, free - reserve)
    # 游戏只在战役开始前检查仓库是否已满；如果剩余空位不足一轮理论掉落，仍允许再开一轮。
    auto_limit = 0 if usable_free <= 0 else max(1, (usable_free + drops_per_run - 1) // drops_per_run)
    CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = False
    if auto_limit <= 0:
        CONFIG["MISSIONS_PER_RETIRE"] = 0
        CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = True
        print("[仓库] 当前人形仓库：%s/%s，空位 %s；可安全执行的 Micro 上限为 0。" % (used, max_gun, free))
        print("[仓库] 请先整理/拆解人形仓库后再运行，避免触发应急拆解。")
        return False
    new_limit = max(1, min(base_limit, auto_limit))
    CONFIG["MISSIONS_PER_RETIRE"] = new_limit
    CONFIG["STORAGE_MAX_GUN"] = max_gun
    CONFIG["STORAGE_USED_GUN"] = used
    CONFIG["STORAGE_FREE_GUN"] = free
    print("[仓库] 当前人形仓库：%s/%s，空位 %s；按每轮战役结算 %s 个人形仓库占用估算；按本地缓存动态调整 Micro。" % (used, max_gun, free, drops_per_run))
    if new_limit != old_limit:
        print("[仓库] 已自动将本次 Micro 上限从 %s 调整为 %s。" % (old_limit, new_limit))
    else:
        print("[仓库] 当前空位足够，Micro 上限保持为 %s。" % new_limit)
    return True


def gfam_note_storage_recovered_after_retire(count):
    try:
        count = int(count or 0)
    except Exception:
        count = 0
    if count <= 0:
        return False
    max_gun = _gfam_storage_int(CONFIG.get("STORAGE_MAX_GUN", 0), 0)
    old_used = _gfam_storage_int(CONFIG.get("STORAGE_USED_GUN", 0), 0)
    old_free = _gfam_storage_int(CONFIG.get("STORAGE_FREE_GUN", 0), 0)
    used = max(0, old_used - count)
    free = old_free + count
    if max_gun > 0:
        free = max(0, min(max_gun - used, free))
    CONFIG["STORAGE_USED_GUN"] = used
    CONFIG["STORAGE_FREE_GUN"] = free
    # 正常运行时不再打印本地仓库缓存增减明细；状态面板会显示最新空位。
    return True



def gfam_note_storage_used_after_drop(count, reason="本轮掉落"):
    """零元购运行中按实际战役结算掉落更新本地人形仓库缓存。

    之前只在自动拆解成功后 used -= 拆解数量，却没有在掉落时 used += 掉落数量，
    会导致跑得越久本地缓存越低估仓库占用，例如实际 262/270 被显示成 246/270。
    游戏虽然允许战役内掉落导致仓库达到/超过上限，但下一次 startMission 前会检查仓库，
    因此每次成功结算掉落后必须先本地增加占用；当 free 变为 0 时结束当前 Macro 并拆解。
    """
    try:
        count = int(count or 0)
    except Exception:
        count = 0
    if count <= 0:
        return True
    max_gun = _gfam_storage_int(CONFIG.get("STORAGE_MAX_GUN", 0), 0)
    old_used = _gfam_storage_int(CONFIG.get("STORAGE_USED_GUN", 0), 0)
    old_free = _gfam_storage_int(CONFIG.get("STORAGE_FREE_GUN", 0), 0)
    used = old_used + count
    if max_gun > 0:
        free = max(0, max_gun - used)
    else:
        free = max(0, old_free - count)
    CONFIG["STORAGE_USED_GUN"] = used
    CONFIG["STORAGE_FREE_GUN"] = free
    # 正常运行时不再打印本地仓库缓存增减明细；状态面板会显示最新空位。
    if free <= 0:
        CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = True
        return False
    return True

def gfam_recompute_micro_limit_from_local_storage(reason="本地仓库缓存"):
    if not CONFIG.get("DYNAMIC_MICRO_BY_STORAGE", True):
        return True
    free = max(0, _gfam_storage_int(CONFIG.get("STORAGE_FREE_GUN", 0), 0))
    reserve = max(0, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_RESERVE", 0), 0))
    usable_free = max(0, free - reserve)
    battles = max(0, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_BATTLES_PER_RUN", 0), 0))
    extra = max(1, _gfam_storage_int(CONFIG.get("STORAGE_MICRO_EXTRA_GUN_DROPS_PER_RUN", 1), 1))
    drops_per_run = max(1, battles + extra)
    env_cap = _gfam_storage_int(os.environ.get("GFAM_MICRO_CAP", "0"), 0)
    if env_cap > 0:
        base_limit = max(1, env_cap)
    else:
        base_limit = max(1, _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE_BASE", CONFIG.get("MISSIONS_PER_RETIRE", 50)), 50))
    old_limit = max(1, _gfam_storage_int(CONFIG.get("MISSIONS_PER_RETIRE", base_limit), base_limit))
    auto_limit = 0 if usable_free <= 0 else max(1, (usable_free + drops_per_run - 1) // drops_per_run)
    if auto_limit <= 0:
        CONFIG["MISSIONS_PER_RETIRE"] = 0
        CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = True
        f2p_log("[仓库] %s：本地缓存可用空位为 0，下一轮将先整理/拆解，不请求 Index/index。" % reason)
        return False
    new_limit = max(1, min(base_limit, auto_limit))
    CONFIG["MISSIONS_PER_RETIRE"] = new_limit
    CONFIG["STORAGE_MICRO_LIMIT_BLOCKED"] = False
    f2p_log("[仓库] %s：已按本地缓存重新计算 Micro 上限：%s -> %s（空位 %s，每轮 %s）。" % (reason, old_limit, new_limit, usable_free, drops_per_run))
    return True

def gfam_storage_micro_blocked():
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

def gfam_gun_team_id_for_emergency(gun):
    if not isinstance(gun, dict):
        return 0
    for key in ("team_id", "team", "location"):
        if key in gun:
            return _gfam_storage_int(gun.get(key), 0)
    return 0

def gfam_gun_uid_for_emergency(gun):
    if not isinstance(gun, dict):
        return 0
    for key in ("gun_with_user_id", "id", "uid"):
        if key in gun:
            return _gfam_storage_int(gun.get(key), 0)
    return 0

def gfam_collect_emergency_retire_uids_from_index(payload):
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
        if gfam_gun_team_id_for_emergency(gun) != 0:
            continue
        uid = gfam_gun_uid_for_emergency(gun)
        if uid > 0:
            uids.append(uid)
    return uids

def gfam_try_emergency_retire_then_refresh_index(client, payload, reason="仓库空位不足"):
    uids = gfam_collect_emergency_retire_uids_from_index(payload)
    if not uids:
        print("[仓库] %s，但当前没有可用于应急拆解的未上锁、未编队人形。" % reason)
        return None
    print("[仓库] %s，正在先尝试应急拆解 %d 名未上锁、未编队人形……" % (reason, len(uids)))
    resp = client.send_request(API_GUN_RETIRE, uids)
    if not (isinstance(resp, dict) and resp.get("success")):
        print("[仓库] 应急拆解失败：%s" % str(resp))
        return None
    print("[仓库] 应急拆解成功，已按拆解数量更新本地仓库缓存，不再立即请求 Index/index。")
    gfam_note_storage_recovered_after_retire(len(uids))
    gfam_recompute_micro_limit_from_local_storage(reason="应急拆解后本地缓存")
    time.sleep(0.3)
    return payload

def gfam_apply_dynamic_micro_limit_with_emergency_retire(client, payload, reason="Index/index"):
    ok = gfam_apply_dynamic_micro_limit_from_index_payload(payload, reason=reason)
    if ok:
        return payload, True
    refreshed = gfam_try_emergency_retire_then_refresh_index(client, payload, reason="仓库空位不足，Micro 上限为 0")
    if not refreshed:
        return payload, False
    ok2 = gfam_recompute_micro_limit_from_local_storage(reason="应急拆解后本地缓存")
    if not ok2:
        print("[仓库] 应急拆解后本地缓存仍显示无可用空位，已取消本次运行。")
        return refreshed, False
    return refreshed, True

def gfam_local_storage_usable_free():
    try:
        free = _gfam_storage_int(CONFIG.get("STORAGE_FREE_GUN", 0), 0)
        reserve = _gfam_storage_int(CONFIG.get("STORAGE_MICRO_RESERVE", 0), 0)
        return max(0, free - reserve)
    except Exception:
        return 0


def gfam_try_exception_self_repair(client, reason="运行异常自修复"):
    """运行中 Micro 失败后的轻量自修复。

    优先相信本地仓库缓存：如果本地缓存仍有可用空位，说明本次失败更可能是
    状态同步/节奏问题，不请求 Index/index，也不拆解。只有本地缓存显示空位为 0
    时，才把 Index/index 作为兜底校准，用于寻找可拆对象。
    """
    if not CONFIG.get("ENABLE_GUN_EXCEPTION_SELF_REPAIR", True):
        f2p_log("[自修复] 人形异常自修复已关闭，跳过应急拆解。")
        return False
    if gfam_local_storage_usable_free() > 0:
        f2p_log("[自修复] 本地仓库缓存仍有空位 %s，本次按同步异常处理，不请求 Index/index、不触发拆解。" % gfam_local_storage_usable_free())
        return False
    payload = gfam_request_index_for_storage(client)
    if payload is None:
        f2p_log("[自修复] 无法获取 Index/index，跳过人形应急拆解。")
        return False
    refreshed = gfam_try_emergency_retire_then_refresh_index(client, payload, reason=reason)
    return refreshed is not None

# === GFAM: 仓库空位不足时的应急拆解结束 ===

# === GFAM: 动态 Micro 上限结束 ===

# === GFAM: 从 Index/index 自动选择重装小队 ===
def gfam_get_squads_from_index_payload(payload):
    """读取 Index/index 中的 squad_with_user_info，返回可部署重装小队列表。"""
    raw = payload.get("squad_with_user_info", {}) if isinstance(payload, dict) else {}
    if isinstance(raw, dict):
        items = list(raw.values())
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    squads = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uid = _gfam_storage_int(item.get("id") or item.get("squad_with_user_id") or item.get("uid"), 0)
        squad_type_id = _gfam_storage_int(item.get("squad_id"), 0)
        level = _gfam_storage_int(item.get("squad_level") or item.get("level"), 0)
        rank = _gfam_storage_int(item.get("rank"), 0)
        adv = _gfam_storage_int(item.get("advanced_level"), 0)
        life = _gfam_storage_int(item.get("life"), 0)
        ammo = _gfam_storage_int(item.get("ammo"), 0)
        mre = _gfam_storage_int(item.get("mre"), 0)
        if uid <= 0:
            continue
        squads.append({
            "uid": uid,
            "squad_id": squad_type_id,
            "level": level,
            "rank": rank,
            "advanced_level": adv,
            "life": life,
            "ammo": ammo,
            "mre": mre,
            "raw": item,
        })
    return squads


def gfam_select_squad_from_index_payload(payload, reason="Index/index"):
    """
    零元购使用的是重装小队部署，不是普通人形梯队。
    因此每次运行前从 Index/index 的 squad_with_user_info 自动选择一个可用系统梯队兼容 UID。
    """
    squads = gfam_get_squads_from_index_payload(payload)
    if not squads:
        print("[重装] 无法从 %s 读取 squad_with_user_info，已取消运行。" % reason)
        print("[重装] 请确认当前账号已解锁重装小队，并且 Index/index 返回中存在 squad_with_user_info。")
        return False

    # 允许高级用户通过环境变量指定固定重装 UID。
    env_uid = _gfam_storage_int(os.environ.get("GFAM_F2P_SQUAD_UID") or os.environ.get("GFAM_SQUAD_UID"), 0)
    if env_uid > 0:
        for sq in squads:
            if sq["uid"] == env_uid:
                CONFIG["SQUAD_ID"] = env_uid
                print("[重装] 已使用环境变量指定系统梯队兼容 UID=%s | squad_id=%s | Lv.%s | ammo=%s | mre=%s | life=%s" % (
                    sq["uid"], sq["squad_id"], sq["level"], sq["ammo"], sq["mre"], sq["life"]
                ))
                return True
        print("[重装] 环境变量指定的重装 UID=%s 不在当前仓库中，将自动选择可用重装小队。" % env_uid)

    usable = [sq for sq in squads if sq["life"] > 0]
    if not usable:
        print("[重装] 当前没有 life > 0 的可用重装小队，已取消运行。")
        for sq in squads:
            print("  UID=%s | squad_id=%s | Lv.%s | ammo=%s | mre=%s | life=%s" % (
                sq["uid"], sq["squad_id"], sq["level"], sq["ammo"], sq["mre"], sq["life"]
            ))
        return False

    # 优先选有弹粮、等级/星级/强化更高的重装小队。
    usable.sort(key=lambda sq: (
        1 if (sq["ammo"] > 0 and sq["mre"] > 0) else 0,
        sq["level"],
        sq["rank"],
        sq["advanced_level"],
        sq["life"],
        sq["ammo"] + sq["mre"],
        -sq["uid"],
    ), reverse=True)

    sq = usable[0]
    CONFIG["SQUAD_ID"] = int(sq["uid"])
    CONFIG["SQUAD_DISPLAY"] = "UID=%s | squad_id=%s | Lv.%s | 弹粮=%s/%s | life=%s" % (
        sq["uid"], sq["squad_id"], sq["level"], sq["ammo"], sq["mre"], sq["life"]
    )
    print("[重装] 已自动选择作战单位：UID=%s | squad_id=%s | Lv.%s | rank=%s | adv=%s | ammo=%s | mre=%s | life=%s" % (
        sq["uid"], sq["squad_id"], sq["level"], sq["rank"], sq["advanced_level"], sq["ammo"], sq["mre"], sq["life"]
    ))
    if sq["ammo"] <= 0 or sq["mre"] <= 0:
        print("[重装] 提示：当前选择的重装小队弹粮可能不足。如 startMission 失败，请在游戏内补给重装小队后重试。")
    return True
# === GFAM: 重装小队自动选择结束 ===

def confirm_run_start():
    if CONFIG.get("UNSUPPORTED_SERVER"):
        print("[!] 当前服务器配置不可用，请返回 GFAM 主菜单切换服务器。")
        return False
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] 尚未获取 UID/SIGN。")
        return False
    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    index_payload = gfam_request_index_for_storage(client)
    if index_payload is None:
        print("[仓库] 无法请求 Index/index，因此无法检查仓库空位，已取消运行。")
        return False
    index_payload, _storage_ok = gfam_apply_dynamic_micro_limit_with_emergency_retire(client, index_payload, reason="运行前 Index/index")
    CONFIG["SQUAD_ID"] = 0
    CONFIG["SQUAD_DISPLAY"] = "10801 系统梯队 / 友军"
    if gfam_storage_micro_blocked():
        print("[仓库] 当前可安全执行的 Micro 上限仍为 0，已取消运行。应急拆解未能释放足够仓库空位，请先手动整理人形仓库后再试。")
        return False
    print("\n=========== 零元购运行确认 ===========")
    print("服务器：%s" % CONFIG.get("SERVER_NAME", "M4A1"))
    print("作战单位：10801 系统梯队 / 友军")
    print("本次 Micro 上限：%s" % CONFIG.get("MISSIONS_PER_RETIRE"))
    print("Macro 上限：无固定上限，直到手动停止或进程受阻")
    print("说明：本模式按原始 PR 作战逻辑使用 10801 系统梯队；Index/index 仅用于仓库/资源统计。")
    print("说明：Index/index 同时用于检查仓库空位并计算 Micro 上限。")
    print("输入 -y 或 y 确认运行；其他输入取消。")
    print("====================================\n")
    try:
        ans = input("GFL-零元购(确认)> ").strip().lower()
    except Exception:
        return False
    confirmed = ans in ("-y", "y", "yes")
    if confirmed:
        CONFIG["RUN_INDEX_CACHE"] = index_payload
        CONFIG["RUN_INDEX_CACHE_AT"] = time.time()
    return confirmed

def on_traffic(event_type: str, url: str, data: dict):
    if event_type == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        print(f"\n[+] SUCCESS! Keys Auto-Configured:")
        print(f"    UID  : {CONFIG['USER_UID']}")
        print(f"    SIGN : {CONFIG['SIGN_KEY']}")
        print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
        print("[!] Then type '-r' to automatically stop proxy and begin farming.")


ADAPTIVE_TIMING_STATE = {"level": 0, "timing_errors": 0, "stable_success": 0}


def gfam_resp_text(resp) -> str:
    try:
        if isinstance(resp, dict):
            return " | ".join("%s=%s" % (k, resp.get(k)) for k in ("error_local", "error", "raw", "message", "msg") if k in resp) or str(resp)
        return str(resp)
    except Exception:
        return ""


def gfam_is_timing_sync_error(resp) -> bool:
    text = gfam_resp_text(resp).lower()
    return (
        "unexpected plaintext response" in text
        or "error:300" in text or "error=300" in text
        or "error:2" in text or "error=2" in text
        or "error:3" in text or "error=3" in text
    )


def gfam_adaptive_level() -> int:
    try:
        return max(0, int(ADAPTIVE_TIMING_STATE.get("level", 0) or 0))
    except Exception:
        return 0


def gfam_adaptive_extra(kind="step") -> float:
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True):
        return 0.0
    level = gfam_adaptive_level()
    if level <= 0:
        return 0.0
    unit = float(CONFIG.get("ADAPTIVE_TIMING_STATE_EXTRA", 0.60) if str(kind).lower() in ("sync", "abort", "start", "comb", "micro") else CONFIG.get("ADAPTIVE_TIMING_STEP_EXTRA", 0.25))
    return max(0.0, level * unit)


def gfam_adaptive_sleep(kind="step", base=0.0):
    try:
        total = max(0.0, float(base or 0.0) + gfam_adaptive_extra(kind))
    except Exception:
        total = float(base or 0.0)
    if total > 0:
        time.sleep(total)


def gfam_adaptive_note_timing_error(resp, step_name=""):
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True) or not gfam_is_timing_sync_error(resp):
        return
    max_level = max(0, int(CONFIG.get("ADAPTIVE_TIMING_MAX_LEVEL", 5) or 5))
    trigger = max(1, int(CONFIG.get("ADAPTIVE_TIMING_TRIGGER_ERRORS", 2) or 2))
    ADAPTIVE_TIMING_STATE["timing_errors"] = int(ADAPTIVE_TIMING_STATE.get("timing_errors", 0) or 0) + 1
    ADAPTIVE_TIMING_STATE["stable_success"] = 0
    count = int(ADAPTIVE_TIMING_STATE.get("timing_errors", 0) or 0)
    old = gfam_adaptive_level()
    if count % trigger == 0 and old < max_level:
        ADAPTIVE_TIMING_STATE["level"] = old + 1
        msg = "[自适应间隔] 检测到状态同步类错误 %d 次，间隔等级提升为 %d/%d。" % (count, old + 1, max_level)
        if 'f2p_log' in globals() and F2P_DASHBOARD_STATS.get("running"):
            f2p_log(msg)
        else:
            print(msg)


def gfam_adaptive_note_success():
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True) or gfam_adaptive_level() <= 0:
        return
    ADAPTIVE_TIMING_STATE["stable_success"] = int(ADAPTIVE_TIMING_STATE.get("stable_success", 0) or 0) + 1
    decay = max(1, int(CONFIG.get("ADAPTIVE_TIMING_DECAY_SUCCESSES", 80) or 80))
    if ADAPTIVE_TIMING_STATE["stable_success"] >= decay:
        ADAPTIVE_TIMING_STATE["level"] = max(0, gfam_adaptive_level() - 1)
        ADAPTIVE_TIMING_STATE["stable_success"] = 0
        ADAPTIVE_TIMING_STATE["timing_errors"] = 0
        msg = "[自适应间隔] 已连续稳定 %d 个关键接口，间隔等级降低为 %d/%d。" % (decay, gfam_adaptive_level(), int(CONFIG.get("ADAPTIVE_TIMING_MAX_LEVEL", 5) or 5))
        if 'f2p_log' in globals() and F2P_DASHBOARD_STATS.get("running"):
            f2p_log(msg)
        else:
            print(msg)

def check_step_error(resp: dict, step_name: str) -> bool:
    if not isinstance(resp, dict):
        # 零元购 f2p/f2p_pr 的 combinationInfo 可能返回 list/空 list；这不是战斗失败，也不应触发应急拆解。
        if step_name == "combinationInfo" and isinstance(resp, list):
            # 零元购没有常规局内战斗信息，combinationInfo 返回 list/[] 属于正常兼容情况。
            # 不写入最近运行记录，避免固定面板反复刷屏。
            gfam_adaptive_note_success()
            return False
        gfam_adaptive_note_timing_error(resp, step_name)
        msg = f"[-] {step_name} 返回格式异常：{type(resp).__name__}"
        if F2P_DASHBOARD_STATS.get("running"):
            f2p_log(msg)
        else:
            print(msg)
        return True
    if "error_local" in resp:
        gfam_adaptive_note_timing_error(resp, step_name)
        msg = f"[-] {step_name} 本地错误：{resp['error_local']}"
        if "raw" in resp:
            msg += f" | 原始响应：{resp.get('raw')}"
        if F2P_DASHBOARD_STATS.get("running"):
            f2p_log(msg)
        else:
            print(msg)
        return True
    if "error" in resp:
        gfam_adaptive_note_timing_error(resp, step_name)
        msg = f"[-] {step_name} 服务器错误：{resp['error']}"
        if F2P_DASHBOARD_STATS.get("running"):
            f2p_log(msg)
        else:
            print(msg)
        return True
    gfam_adaptive_note_success()
    return False

def check_drop_result(response_data: dict) -> list:
    collected_guns = []
    win_result = response_data.get("mission_win_result", {})
    if not win_result:
        return collected_guns

    reward_guns = win_result.get("reward_gun", [])
    if reward_guns:
        for gun in reward_guns:
            gun_id = gun.get("gun_id")
            gun_uid = int(gun.get("gun_with_user_id"))
            drop_text = "gun_id=%s | UID=%s" % (gun_id, gun_uid)
            F2P_DASHBOARD_STATS["last_drop"] = drop_text
            F2P_DASHBOARD_STATS["total_drops"] = int(F2P_DASHBOARD_STATS.get("total_drops", 0)) + 1
            F2P_DASHBOARD_STATS["macro_drops"] = int(F2P_DASHBOARD_STATS.get("macro_drops", 0)) + 1
            if F2P_DASHBOARD_STATS.get("running"):
                f2p_log("[掉落] %s | %s" % (drop_text, time.strftime("%H:%M:%S")))
            else:
                print("[+] Got T-Doll! Gun ID: %s | UID: %s | Time: %s" % (gun_id, gun_uid, time.strftime("%H:%M:%S")))
            collected_guns.append(gun_uid)
    return collected_guns

def farm_mission_10801(client: GFLClient, squad_id: int):
    """零元购 PR 10801 作战逻辑。

    这里必须沿用原始可运行版的“系统梯队 / 友军”部署方式：
    - startMission 使用 mission_ally_spots；
    - ally_team_id 固定为 6480101；
    - teamMove 使用 person_type=3、person_id=1；
    - Turn 1 中间需要调用 allyMySideMove。

    之前版本改成了 squad_spots + 玩家重装小队移动，会导致 startMission 返回 error:2。
    squad_id 参数仅保留用于面板显示/兼容，不参与 10801 PR 作战部署。
    """
    mission_id = 10801

    if check_step_error(client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id}), "combinationInfo"):
        return None

    start_payload = {
        "mission_id": mission_id,
        "spots": [],
        "squad_spots": [],
        "sangvis_spots": [],
        "vehicle_spots": [],
        "ally_spots": [],
        "mission_ally_spots": [
            {
                "spot_id": 64318,
                "ally_team_id": 6480101,
                "mission_myside_data": {
                    "sangvis": [],
                    "gun": {
                        "1": {
                            "position": 8
                        }
                    }
                }
            }
        ],
        "ally_id": int(time.time())
    }

    if check_step_error(client.send_request(API_MISSION_START, start_payload), "startMission"):
        return None

    gfam_adaptive_sleep("step", 0.5)

    def move_ally(from_spot: int, to_spot: int):
        payload = {
            "person_type": 3,
            "person_id": 1,
            "from_spot_id": from_spot,
            "to_spot_id": to_spot,
            "move_type": 1
        }
        return client.send_request(API_MISSION_TEAM_MOVE, payload)

    # Turn 1
    if check_step_error(move_ally(64318, 64307), "teamMove(64318->64307)"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    if check_step_error(move_ally(64307, 64308), "teamMove(64307->64308)"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    if check_step_error(client.send_request(API_MISSION_ALLY_MYSIDE_MOVE, {}), "allyMySideMove"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    if check_step_error(client.send_request(API_MISSION_END_TURN, {}), "endTurn"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    if check_step_error(client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    if check_step_error(client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    if check_step_error(client.send_request(API_MISSION_START_TURN, {}), "startTurn"):
        return None
    gfam_adaptive_sleep("step", 0.5)

    # Turn 2
    if check_step_error(move_ally(64308, 64302), "teamMove(64308->64302)"):
        return None
    gfam_adaptive_sleep("step", 0.2)

    final_resp = move_ally(64302, 64319)
    if check_step_error(final_resp, "teamMove(64302->64319)"):
        return None

    return check_drop_result(final_resp)



# v47：运行结束收尾拆解兜底。
# 只处理本次运行已经记录到的掉落 UID，不主动请求 Index/index 或扫描全仓库。
GFAM_FINAL_CLEANUP_PENDING_GUNS = []


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


def gfam_final_cleanup_mark_retired(uids):
    try:
        for uid in uids or []:
            try:
                uid = int(uid)
            except Exception:
                continue
            while uid in GFAM_FINAL_CLEANUP_PENDING_GUNS:
                GFAM_FINAL_CLEANUP_PENDING_GUNS.remove(uid)
    except Exception:
        pass


def gfam_run_final_cleanup(client, label="运行结束"):
    guns = list(dict.fromkeys(GFAM_FINAL_CLEANUP_PENDING_GUNS))
    if not guns:
        return
    f2p_log("[收尾拆解] %s：检测到本次运行仍有未处理人形掉落 %d 只，将最后拆解一次。" % (label, len(guns)))
    retire_guns(client, guns)
    if GFAM_FINAL_CLEANUP_PENDING_GUNS:
        f2p_log("[收尾拆解] 仍有 %d 只人形未确认拆解，请手动检查仓库。" % len(GFAM_FINAL_CLEANUP_PENDING_GUNS))

def retire_guns(client: GFLClient, gun_uids: list):
    if not gun_uids:
        return
    msg = "[*] 正在自动拆解 %d 只掉落人形……" % len(gun_uids)
    if F2P_DASHBOARD_STATS.get("running"):
        f2p_log(msg)
    else:
        print(msg)
    resp = client.send_request(API_GUN_RETIRE, gun_uids)
    if isinstance(resp, dict) and resp.get("success"):
        F2P_DASHBOARD_STATS["retire_batches"] = int(F2P_DASHBOARD_STATS.get("retire_batches", 0)) + 1
        F2P_DASHBOARD_STATS["retire_total"] = int(F2P_DASHBOARD_STATS.get("retire_total", 0)) + len(gun_uids)
        gfam_note_storage_recovered_after_retire(len(gun_uids))
        gfam_recompute_micro_limit_from_local_storage(reason="Macro 后人形拆解成功")
        gfam_final_cleanup_mark_retired(gun_uids)
        msg = "[+] 自动拆解成功：%d 只。" % len(gun_uids)
    else:
        msg = "[-] 自动拆解失败：%s" % resp
    if F2P_DASHBOARD_STATS.get("running"):
        f2p_log(msg)
        f2p_render_dashboard(force=True)
    else:
        print(msg)



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
            F2P_DASHBOARD_STATS["running"] = False
            F2P_DASHBOARD_STATS["stop_reason"] = "运行线程异常，已自动终止"
        except Exception:
            pass
        print("\n[异常保护] 运行线程发生未处理异常，已自动终止当前运行，避免异常进程继续执行。")
        print(traceback.format_exc())
        try:
            f2p_render_dashboard(force=True)
        except Exception:
            pass
        try:
            print_menu()
        except Exception:
            pass

def _farm_worker_impl():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread
    
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] 尚未获取 UID/SIGN。单独运行本模块时请先使用 -c；从 GFAM 主菜单进入时请先完成统一 UID/SIGN 获取。")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])

    index_payload = CONFIG.pop("RUN_INDEX_CACHE", None)
    if isinstance(index_payload, dict):
        f2p_log("[缓存] 已复用运行确认阶段的 Index/index 缓存，不重复请求。")
    else:
        index_payload = gfam_request_index_for_storage(client)
        if index_payload is None:
            print("[仓库] 无法请求 Index/index，因此无法检查仓库空位，已取消运行。")
            worker_mode, current_worker_thread = None, None
            return
        index_payload, _storage_ok = gfam_apply_dynamic_micro_limit_with_emergency_retire(client, index_payload, reason="运行前 Index/index")
    CONFIG["SQUAD_ID"] = 0
    CONFIG["SQUAD_DISPLAY"] = "10801 系统梯队 / 友军"
    if gfam_storage_micro_blocked():
        print("[仓库] 当前可安全执行的 Micro 上限仍为 0，已取消运行。应急拆解未能释放足够仓库空位，请先手动整理人形仓库后再试。")
        worker_mode, current_worker_thread = None, None
        return

    f2p_record_resource_start_from_index_payload(index_payload)

    f2p_start_dashboard("零元购 PR（额外核心）", 10801)
    f2p_render_dashboard(force=True)
    macro = 1
    consecutive_failures = 0
    max_consecutive_failures = max(1, int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 10) or 10))

    while not stop_macro_flag:
        macro_limit = int(CONFIG.get("MACRO_LOOPS", 0) or 0)
        if macro_limit > 0 and macro > macro_limit:
            break

        macro_limit_text = str(macro_limit) if macro_limit > 0 else "直到手动停止或进程受阻"
        F2P_DASHBOARD_STATS["macro"] = macro
        F2P_DASHBOARD_STATS["macro_drops"] = 0
        print(f"\n--- MACRO BATCH {macro} / {macro_limit_text} ---")

        batch_guns = []
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag:
                break
            F2P_DASHBOARD_STATS["micro"] = micro
            F2P_DASHBOARD_STATS["total_runs"] = int(F2P_DASHBOARD_STATS.get("total_runs", 0)) + 1
            f2p_log("[*] Micro %s / %s" % (micro, CONFIG.get("MISSIONS_PER_RETIRE")))
            dropped = farm_mission_10801(client, CONFIG["SQUAD_ID"])
            if dropped is None:
                consecutive_failures += 1
                try:
                    client.send_request(API_MISSION_ABORT, {"mission_id": 10801})
                except Exception:
                    pass
                F2P_DASHBOARD_STATS["consecutive_failures"] = consecutive_failures
                f2p_log(f"[!] 本次 Micro 失败，连续失败 {consecutive_failures} / {max_consecutive_failures}。")
                f2p_render_dashboard(force=True)
                failure_limit_reached = consecutive_failures >= max_consecutive_failures
                if failure_limit_reached:
                    f2p_log("[异常保护] 连续失败已达到上限，但会先执行本次自修复；若自修复成功将重新计数。")
                if CONFIG.get("ENABLE_GUN_EXCEPTION_SELF_REPAIR", True):
                    f2p_log("[自修复] 当前 Micro 失败，尝试人形应急拆解后重试当前 Micro 一次。")
                    if gfam_try_exception_self_repair(client, reason="零元购 Micro Error Before Retry"):
                        retry_drop = farm_mission_10801(client, CONFIG["SQUAD_ID"])
                        if retry_drop is not None:
                            consecutive_failures = 0
                            F2P_DASHBOARD_STATS["consecutive_failures"] = 0
                            f2p_log("[自修复] 重试成功，连续失败计数已清零，继续运行。")
                            dropped = retry_drop
                        else:
                            try:
                                client.send_request(API_MISSION_ABORT, {"mission_id": 10801})
                            except Exception:
                                pass
                            f2p_log("[自修复] 重试后仍失败，本次 Micro 跳过，继续观察后续运行。")
                            time.sleep(3)
                            continue
                    else:
                        if failure_limit_reached:
                            F2P_DASHBOARD_STATS["stop_reason"] = "连续失败达到上限且自修复未完成"
                            f2p_log("[自修复] 连续失败达到上限且本次未能完成自修复，已自动停止运行。")
                            stop_macro_flag = True
                            stop_micro_flag = True
                            break
                        f2p_log("[自修复] 人形应急拆解未完成，本次 Micro 跳过。")
                        time.sleep(3)
                        continue
                else:
                    if failure_limit_reached:
                        F2P_DASHBOARD_STATS["stop_reason"] = "连续失败达到上限，且自修复已关闭"
                        f2p_log("[!] 连续失败达到上限且自修复已关闭，已自动停止运行。")
                        stop_macro_flag = True
                        stop_micro_flag = True
                        break
                    time.sleep(3)
                    continue
            consecutive_failures = 0
            F2P_DASHBOARD_STATS["consecutive_failures"] = 0
            batch_guns.extend(dropped)
            gfam_final_cleanup_note_guns(dropped)
            storage_ok_for_next_micro = gfam_note_storage_used_after_drop(len(dropped), reason="战役结算掉落")
            if not storage_ok_for_next_micro:
                f2p_log("[仓库] 本地缓存显示人形仓库已满或超出上限，结束当前 Macro 并拆解本轮掉落。")
            f2p_render_dashboard(force=True)
            gfam_adaptive_sleep("micro", 1)
            if not storage_ok_for_next_micro:
                break

        if (stop_micro_flag or stop_macro_flag) and batch_guns:
            f2p_log("[安全停止] 已收到 -q/-Q，将先自动拆解本轮已记录掉落，再结束当前运行。")
        retire_guns(client, batch_guns)
        time.sleep(2)
        if stop_micro_flag or stop_macro_flag:
            break
        macro += 1

    F2P_DASHBOARD_STATS["running"] = False
    if not F2P_DASHBOARD_STATS.get("stop_reason"):
        if stop_micro_flag:
            F2P_DASHBOARD_STATS["stop_reason"] = "用户请求当前 Micro 后停止"
        elif stop_macro_flag:
            F2P_DASHBOARD_STATS["stop_reason"] = "用户请求当前 Macro 后停止"
        else:
            F2P_DASHBOARD_STATS["stop_reason"] = "运行结束"
    gfam_run_final_cleanup(client, label="运行结束前")
    f2p_print_resource_summary(client)
    print("\n[*] 本次运行结束。")
    worker_mode, current_worker_thread = None, None
    print_menu()

def print_menu():
    if CONFIG.get("UNSUPPORTED_SERVER"):
        print("\n================= 零元购 PR（额外核心） MENU =================")
        print("[!] 当前服务器配置不可用。")
        print("[!] 请按 -E 返回 GFAM 主菜单，输入 server 切换服务器。")
        print(" -E : 返回少女全自动 GFAM 主菜单")
        print("========================================\n")
        return
    print("\n================= 零元购 PR（额外核心） MENU =================")
    if CONFIG.get("GFAM_AUTH_READY"):
        print(" -r : 运行零元购 PR（10801 系统梯队）")
        print(" -q : 当前 Macro 结束后安全停止")
        print(" -Q : 当前 Micro 结束后安全停止")
        print(" -E : 返回少女全自动 GFAM 主菜单")
        print("----------------------------------------")
        print("提示：UID/SIGN 已由 GFAM 主菜单统一获取，本模块不再重复抓取。")
        print("提示：运行前会通过 Index/index 检查仓库空位并记录资源。")
    else:
        print(" -c : 启动代理并抓取 UID/SIGN")
        print(" -r : 运行零元购 PR（10801 系统梯队）")
        print(" -q : 当前 Macro 结束后安全停止")
        print(" -Q : 当前 Micro 结束后安全停止")
        print(" -E : 返回少女全自动 GFAM 主菜单")
        print("----------------------------------------")
        print("提示：由 GFAM 主菜单进入时，UID/SIGN 已统一获取；单独运行本模块时才需要 -c。")
    print("========================================\n")

if __name__ == '__main__':
    apply_gfam_auth_from_env()
    print_menu()
    while True:
        try:
            cmd = input("GFL-零元购PR> ").strip()
            if not cmd: continue
            cmd_prefix = cmd.split()[0]
            
            if cmd_prefix == '-c':
                if launched_from_gfam_main():
                    print("[!] 本模块由 GFAM 主菜单统一提供 UID/SIGN，不再启动代理。")
                    print("[*] 如需重新获取 UID/SIGN，请返回 GFAM 主菜单使用 auth。")
                    continue
                if proxy_instance:
                    print("[!] 代理已经在运行中。")
                    continue
                proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                proxy_instance.start()
                set_windows_proxy(True, f"127.0.0.1:{CONFIG['PROXY_PORT']}")
                worker_mode = 'c'
                print(f"[*] 代理已启动，端口 {CONFIG['PROXY_PORT']}。Windows 代理已设置。")
                
            elif cmd_prefix == '-r':
                if CONFIG.get("UNSUPPORTED_SERVER"):
                    print("[!] 当前服务器配置不可用，请按 -E 返回 GFAM 主菜单切换服务器。")
                    continue
                if not confirm_run_start():
                    print("[*] 已取消本次运行。")
                    continue
                if worker_mode == 'c' and proxy_instance:
                    print("[*] 正在停止代理并准备开始运行……")
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
                print("[*] 将在当前 Macro 结束后安全停止……")
            elif cmd_prefix == '-Q':
                stop_micro_flag = True
                print("[*] 将在当前 Micro 结束后安全停止……")
            elif cmd_prefix == '-E':
                if proxy_instance:
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    print("[*] 已安全退出，Windows 代理已恢复。")
                else:
                    print("[*] 已安全退出，未启动代理，无需恢复 Windows 代理。")
                stop_macro_flag, stop_micro_flag = True, True
                sys.exit(0)
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")
